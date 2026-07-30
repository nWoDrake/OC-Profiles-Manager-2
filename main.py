"""
OC Profiles Manager - Entry Point.

Responsabilità di main.py:
    1. setup logging
    2. UAC elevation
    3. setup wizard (se primo avvio)
    4. costruzione AppContext (manager di dominio)
    5. caricamento del tema UI attivo (theme system)
    6. lancio MainWindow del tema

Tutta la logica di business vive in oc_controller / oc_core / oc_history.
Tutta la presentazione vive in themes/<id>/.
main.py è il punto in cui i due mondi si incontrano.
"""

from __future__ import annotations

import ctypes
import logging
import platform
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog

from constants import APP_NAME, APP_VERSION, BASE_DIR


# ============================================================================
# LOGGING
# ============================================================================

def setup_logging() -> logging.Logger:
    log_file = BASE_DIR / "oc_manager.log"
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Evita handler duplicati se main() viene richiamato (test, embed)
    if not root.handlers:
        root.addHandler(file_handler)
        root.addHandler(console_handler)

    return logging.getLogger(__name__)


def _apply_config_log_level(logger: logging.Logger) -> None:
    """
    Applica la chiave config `log_level` al logging CONSOLE.

    Il file di log resta sempre a DEBUG (diagnostica completa); la config
    regola solo il rumore in console. Letto direttamente dal JSON per non
    dover istanziare ConfigManager prima del boot.
    """
    try:
        from oc_utils import safe_read_json
        cfg = safe_read_json(BASE_DIR / "oc_manager_data.json", default={}) or {}
        level_name = str(cfg.get("log_level", "INFO")).upper()
        level = getattr(logging, level_name, None)
        if not isinstance(level, int):
            return
        for h in logging.getLogger().handlers:
            # Solo lo StreamHandler console: RotatingFileHandler è una
            # sottoclasse di StreamHandler, quindi confrontiamo il tipo esatto.
            if type(h) is logging.StreamHandler:
                h.setLevel(level)
        logger.debug(f"Log level console da config: {level_name}")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"log_level config non applicato: {e}")


def log_startup_diagnostics(logger: logging.Logger) -> None:
    logger.info("=" * 60)
    logger.info(f"{APP_NAME} v{APP_VERSION} - Avvio")
    logger.info("=" * 60)
    logger.info(f"Python: {sys.version}")
    logger.info(f"Platform: {platform.platform()}")
    logger.info(f"Architecture: {platform.architecture()[0]}")
    logger.info(f"Working Dir: {BASE_DIR}")
    logger.info(f"Executable: {sys.executable}")
    try:
        from oc_core import ConfigManager, GPUMonitor
        config = ConfigManager(BASE_DIR / "oc_manager_data.json")
        msi_path = config.get("msi_path", "Non configurato")
        msi_exists = Path(msi_path).exists() if msi_path else False
        logger.info(f"MSI Afterburner Path: {msi_path}")
        logger.info(f"MSI Afterburner Exists: {msi_exists}")
        gpu = GPUMonitor()
        logger.info(
            "GPU Monitor Mode: "
            f"{'Hardware (NVML)' if gpu.is_real_hardware else 'Simulazione'}"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Diagnostiche incomplete: {e}")
    logger.info("-" * 60)


# ============================================================================
# UAC
# ============================================================================

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def request_admin_relaunch(logger: logging.Logger) -> bool:
    """Tenta rilancio con UAC; ritorna False per indicare exit-from-this-process."""
    logger.info("Rilancio con UAC...")
    try:
        # list2cmdline: quoting corretto per argomenti con spazi
        params = subprocess.list2cmdline(sys.argv)
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1,
        )
        if result <= 32:
            logger.error(f"UAC negato (codice: {result})")
            return False
    except Exception as e:  # noqa: BLE001
        logger.error(f"Errore rilancio admin: {e}")
        return False
    return True


def check_admin_or_relaunch(logger: logging.Logger) -> bool:
    """Restituisce True se siamo admin (continua exec); False = exit silenzioso."""
    if is_admin():
        return True
    request_admin_relaunch(logger)
    return False


# ============================================================================
# APP CONTEXT BUILDER
# ============================================================================

def _build_app_context(start_minimized: bool):
    """
    Costruisce l'AppContext con tutti i manager di dominio.

    Questo è il PUNTO UNICO in cui la logica viene istanziata: il tema riceve
    poi questi oggetti già pronti via AppContext.
    """
    from oc_controller import ProfileController
    from oc_core import (
        ConfigManager, GPUMonitor, MSIAfterburnerController,
        ProcessMonitorLogic, ProfileManager,
    )
    from themes.base import AppContext

    config_path = BASE_DIR / "oc_manager_data.json"
    config_mgr = ConfigManager(config_path)
    msi_path = config_mgr.get("msi_path")

    # ProfileManager riceve un log_callback "no-op" qui: la MainWindow del tema
    # lo riaggancerà al suo add_log() una volta creata.
    profile_mgr = ProfileManager(msi_path, log_callback=None)
    msi_ctrl = MSIAfterburnerController(msi_path)
    gpu_monitor = GPUMonitor()
    process_logic = ProcessMonitorLogic(config_mgr)
    controller = ProfileController(
        config_mgr, profile_mgr, msi_ctrl, process_logic, log_callback=None,
    )

    return AppContext(
        base_dir=BASE_DIR,
        config_path=config_path,
        config_mgr=config_mgr,
        profile_mgr=profile_mgr,
        msi_ctrl=msi_ctrl,
        gpu_monitor=gpu_monitor,
        process_logic=process_logic,
        controller=controller,
        app_name=APP_NAME,
        app_version=APP_VERSION,
        start_minimized=start_minimized,
    )


# ============================================================================
# CLI HEADLESS — `--apply <profilo>` (Feature A, v2.7)
# ============================================================================

def _run_cli_apply(logger: logging.Logger, profile_name: str) -> int:
    """
    Applica un profilo da riga di comando SENZA avviare la GUI.

    Exit code:
        0 = profilo applicato
        1 = errore durante l'apply
        2 = MSI Afterburner non configurato
        3 = profilo inesistente
    """
    from oc_controller import ProfileController
    from oc_core import (
        ConfigManager, MSIAfterburnerController, ProcessMonitorLogic,
        ProfileManager,
    )

    config_mgr = ConfigManager(BASE_DIR / "oc_manager_data.json")
    msi_path = config_mgr.get("msi_path")
    if not msi_path or not Path(msi_path).exists():
        logger.error("CLI --apply: MSI Afterburner non configurato")
        print("ERRORE: MSI Afterburner non configurato. Avvia prima la GUI.")
        return 2

    profile_mgr = ProfileManager(msi_path, log_callback=None)
    msi_ctrl = MSIAfterburnerController(msi_path)
    process_logic = ProcessMonitorLogic(config_mgr)
    controller = ProfileController(
        config_mgr, profile_mgr, msi_ctrl, process_logic, log_callback=None,
    )

    try:
        available = profile_mgr.list_profiles() + ["Default"]
        if profile_name not in available:
            logger.error(f"CLI --apply: profilo '{profile_name}' inesistente")
            print(f"ERRORE: profilo '{profile_name}' inesistente.")
            print(f"Profili disponibili: {', '.join(available)}")
            return 3

        logger.info(f"CLI --apply: applico '{profile_name}'")
        ok = controller.apply_profile_blocking(profile_name)
        if ok:
            print(f"OK: profilo '{profile_name}' applicato.")
            return 0
        print(f"ERRORE: apply di '{profile_name}' fallito (vedi log).")
        return 1
    finally:
        try:
            controller.shutdown()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"CLI shutdown: {e}")


# ============================================================================
# MAIN
# ============================================================================

def main() -> int:
    logger = setup_logging()
    _apply_config_log_level(logger)

    if not check_admin_or_relaunch(logger):
        return 0

    # CLI headless: --apply <profilo> (nessuna GUI, exit code parlante)
    if "--apply" in sys.argv:
        idx = sys.argv.index("--apply")
        if idx + 1 >= len(sys.argv):
            print("Uso: python main.py --apply \"NomeProfilo\"")
            return 3
        return _run_cli_apply(logger, sys.argv[idx + 1])

    start_minimized = "--minimized" in sys.argv
    if start_minimized:
        logger.info("Modalità minimizzato")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    # Garanzia: anche se l'ultima window è hidden, l'app non si chiude
    app.setQuitOnLastWindowClosed(False)

    try:
        if not _ensure_msi_configured(logger):
            return 0

        log_startup_diagnostics(logger)

        # --- THEME SYSTEM --------------------------------------------------
        # Scopri i temi disponibili (scansiona themes/<id>/__init__.py).
        from themes import ThemeRegistry
        ThemeRegistry.discover()

        # Costruisci AppContext (logica di business pronta all'uso).
        app_ctx = _build_app_context(start_minimized=start_minimized)

        # Leggi tema attivo da config, fallback al default se non valido.
        theme_id = app_ctx.config_mgr.get("ui_theme", "red_glossy")
        theme_desc = ThemeRegistry.get_or_default(theme_id)
        logger.info(
            f"Tema UI attivo: '{theme_desc.id}' ({theme_desc.name} v{theme_desc.version})",
        )

        # Lancia la MainWindow del tema.
        window = theme_desc.create_window(app_ctx)
        if not start_minimized:
            window.show_window()

        # Mantieni reference per evitare GC
        app._main_window = window  # type: ignore[attr-defined]
        # ------------------------------------------------------------------

        exit_code = app.exec()
        logger.info(f"Terminato (exit: {exit_code})")
        return exit_code

    except Exception as e:  # noqa: BLE001
        logger.critical(f"Errore fatale: {e}", exc_info=True)
        return 1


def _ensure_msi_configured(logger: logging.Logger) -> bool:
    """
    Avvia il wizard se MSI Afterburner non è configurato.
    Returns: True se ok per proseguire, False se l'utente ha annullato.
    """
    config_path = BASE_DIR / "oc_manager_data.json"
    needs_setup = False

    if not config_path.exists():
        needs_setup = True
        logger.info("Config non trovato")
    else:
        from oc_core import ConfigManager
        tmp = ConfigManager(config_path)
        msi = tmp.get("msi_path")
        if not msi or not Path(msi).exists():
            needs_setup = True
            logger.info(f"MSI non trovato: {msi}")

    if not needs_setup:
        return True

    logger.info("Avvio wizard")
    # Il wizard è un widget del tema "red_glossy": lo importiamo da lì
    # perché è l'unico tema disponibile alla prima esecuzione (theme attivo non
    # ancora scelto). Un tema futuro può fornire il proprio wizard se desidera.
    from themes.red_glossy.widgets import SetupWizard
    from oc_core import ConfigManager, ProfileManager

    wizard = SetupWizard()
    if wizard.exec() != QDialog.Accepted or not wizard.msi_path:
        logger.info("Wizard annullato")
        return False

    cfg = ConfigManager(config_path)
    cfg.set("msi_path", wizard.msi_path)
    logger.info(f"Config salvata: {wizard.msi_path}")

    pm = ProfileManager(wizard.msi_path)
    if pm.ensure_structure():
        logger.info("Struttura creata")
    else:
        logger.error("Errore struttura")
    return True


if __name__ == "__main__":
    sys.exit(main())
