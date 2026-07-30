"""
OC Profiles Manager - Utility comuni.

Contiene helper funzioni riusabili attraverso il progetto:
- Operazioni file thread-safe (atomic write)
- Formattazione tempo human-readable
- Wrapper subprocess sicuri per Windows (no console flash)
- Helper psutil (snapshot leggero dei processi)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

import psutil

logger = logging.getLogger(__name__)


# ============================================================================
# WINDOWS — Subprocess senza finestra
# ============================================================================

# Flag per nascondere console e creare gruppo separato (Win32 specifico).
# Su Linux/macOS valore ignorato.
CREATE_NO_WINDOW: int = 0x08000000
DETACHED_PROCESS: int = 0x00000008

_IS_WINDOWS = os.name == "nt"


def run_hidden(args: list, **kwargs) -> subprocess.CompletedProcess:
    """Esegue subprocess.run nascondendo la console su Windows."""
    if _IS_WINDOWS:
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    kwargs.setdefault("capture_output", True)
    return subprocess.run(args, **kwargs)


def popen_hidden(args: list, **kwargs) -> subprocess.Popen:
    """Avvia Popen nascondendo la console su Windows."""
    if _IS_WINDOWS:
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.Popen(args, **kwargs)


def popen_detached(args: list, **kwargs) -> subprocess.Popen:
    """Avvia Popen come processo detached su Windows (mostra la sua finestra)."""
    if _IS_WINDOWS:
        kwargs.setdefault("creationflags", DETACHED_PROCESS)
    return subprocess.Popen(args, **kwargs)


# ============================================================================
# FILE I/O — Atomic write JSON con retry
# ============================================================================

def atomic_write_json(
    path: Path,
    data: Any,
    *,
    indent: int = 2,
    retries: int = 3,
    retry_delay: float = 0.1,
) -> bool:
    """
    Scrive un file JSON atomicamente (tmp + rename) con retry.

    Args:
        path: percorso di destinazione
        data: dati JSON-serializzabili
        indent: indentazione JSON (default 2)
        retries: numero massimo di tentativi in caso di PermissionError
        retry_delay: pausa base tra retry (incrementale)

    Returns:
        True se il salvataggio è riuscito.
    """
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, indent=indent, ensure_ascii=False)

    for attempt in range(retries):
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
            return True
        except PermissionError:
            if attempt < retries - 1:
                time.sleep(retry_delay * (attempt + 1))
                continue
            logger.error(f"atomic_write_json: PermissionError persistente su {path}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"atomic_write_json error: {e}")
            break
    return False


def safe_read_json(path: Path, default: Any = None) -> Any:
    """Legge un JSON; ritorna `default` in caso di errore o file mancante."""
    try:
        if not path.exists():
            return default
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return default
        return json.loads(text)
    except Exception as e:  # noqa: BLE001
        logger.error(f"safe_read_json error {path}: {e}")
        return default


def safe_rmtree(path: Optional[Path]) -> None:
    """Rimuove ricorsivamente una directory ignorando errori."""
    try:
        if path and Path(path).exists():
            shutil.rmtree(path)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"safe_rmtree({path}) ignored: {e}")


# ============================================================================
# FORMATTING — durata human-readable
# ============================================================================

def format_duration(seconds: float) -> str:
    """
    Formatta una durata in stringa human-readable.

    Esempi:
        45  -> '45s'
        90  -> '1.5 min'
        3700 -> '1.0 h'
        90000 -> '1.0 d'
    """
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f} min"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f} h"
    days = hours / 24
    return f"{days:.1f} d"


def format_duration_short(seconds: float) -> str:
    """Versione breve con unità intera adatta (m/h/d)."""
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}m"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f}h"
    days = hours / 24
    return f"{days:.1f}d"


# ============================================================================
# PSUTIL — snapshot processi
# ============================================================================

# Cache TTL condivisa: un solo scan psutil al secondo serve tutti i chiamanti
# (monitor processi, check MSI Afterburner, ecc.). Thread-safe.
_SNAPSHOT_TTL_S: float = 1.0
_snapshot_lock = threading.Lock()
_snapshot_cache: Set[str] = set()
_snapshot_time: float = 0.0


def snapshot_running_exes(*, max_age_s: float = _SNAPSHOT_TTL_S) -> Set[str]:
    """
    Restituisce un set di nomi eseguibili (lowercased) attualmente in esecuzione.
    Robusto contro processi che scompaiono mid-iterazione.

    Il risultato è cachato per `max_age_s` secondi (default 1.0) e condiviso
    tra tutti i chiamanti: passare max_age_s=0 forza uno scan fresco.

    Nota: l'iterazione è veloce ma fatta SENZA tenere lock applicativi
    (chi chiama deve evitare di tenere lock pesanti durante la chiamata).
    """
    global _snapshot_cache, _snapshot_time
    now = time.monotonic()
    with _snapshot_lock:
        if max_age_s > 0 and (now - _snapshot_time) < max_age_s and _snapshot_cache:
            return set(_snapshot_cache)  # copia difensiva

    active: Set[str] = set()
    try:
        for p in psutil.process_iter(["name"]):
            try:
                name = p.info.get("name") if hasattr(p, "info") else None
                if name:
                    active.add(name.lower())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:  # noqa: BLE001
                continue
    except Exception as e:  # noqa: BLE001
        logger.debug(f"snapshot_running_exes error: {e}")

    with _snapshot_lock:
        _snapshot_cache = active
        _snapshot_time = time.monotonic()
    return set(active)


def any_exe_running(exe_names: Iterable[str]) -> bool:
    """Verifica se almeno uno degli exe (case-insensitive) è attivo."""
    needles = {e.lower() for e in exe_names if e}
    if not needles:
        return False
    return bool(snapshot_running_exes() & needles)


# ============================================================================
# WINDOWS — autostart registry helper
# ============================================================================

def set_autostart_registry(app_name: str, command: str, enabled: bool) -> bool:
    """
    Abilita/disabilita l'autostart Windows tramite registro.

    Args:
        app_name: chiave nel registry (Run)
        command: comando completo da eseguire
        enabled: True per abilitare, False per rimuovere

    Returns:
        True se l'operazione è riuscita.
    """
    try:
        import winreg  # type: ignore[import]
    except ImportError:
        logger.warning("winreg non disponibile (non Windows)")
        return False

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_ALL_ACCESS,
        )
        try:
            if enabled:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            return True
        finally:
            winreg.CloseKey(key)
    except Exception as e:  # noqa: BLE001
        logger.error(f"set_autostart_registry: {e}")
        return False


def check_autostart_registry(app_name: str) -> bool:
    """Controlla se l'autostart è già impostato nel registry."""
    try:
        import winreg  # type: ignore[import]
    except ImportError:
        return False

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, app_name)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:  # noqa: BLE001
        return False


# ============================================================================
# MISC
# ============================================================================

def open_in_explorer(path: Path) -> bool:
    """Apre una cartella in Esplora Risorse di Windows."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        if os.name == "nt":
            popen_hidden(["explorer", str(path)])
        else:
            popen_hidden(["xdg-open", str(path)])
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"open_in_explorer error: {e}")
        return False
