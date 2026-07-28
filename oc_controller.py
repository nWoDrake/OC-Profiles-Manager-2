"""
OC Profiles Manager - Controller Layer.

Coordina ProfileManager, ConfigManager, MSI Controller, ProcessMonitor e History.
La UI chiama solo metodi esposti qui.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from constants import APP_NAME, APP_VERSION, BASE_DIR, sanitize_profile_name
from oc_core import (
    ConfigManager,
    MSIAfterburnerController,
    ProcessMonitorLogic,
    ProfileManager,
    SoundPlayer,
    is_managed_cfg,
    iter_managed_cfg,
)
from oc_history import ProfileHistory

logger = logging.getLogger(__name__)


class ProfileController:
    """
    Coordina ProfileManager, ConfigManager, MSI Controller e History.
    La UI chiama solo metodi di questo controller.
    """

    def __init__(
        self,
        config_mgr: ConfigManager,
        profile_mgr: ProfileManager,
        msi_ctrl: MSIAfterburnerController,
        process_logic: ProcessMonitorLogic,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.config = config_mgr
        self.profiles = profile_mgr
        self.msi = msi_ctrl
        self.process_logic = process_logic
        self._log_cb = log_callback

        # History
        self.history = ProfileHistory(BASE_DIR / "oc_profile_history.json")

        # Stato
        self.current_profile: str = "Default"
        self.sounds_enabled: bool = config_mgr.get("sounds", True)

    # ----------------------------------------------------------------
    # LOG
    # ----------------------------------------------------------------

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self._log_cb:
            try:
                self._log_cb(msg)
            except Exception:  # noqa: BLE001
                pass

    # ----------------------------------------------------------------
    # SHUTDOWN
    # ----------------------------------------------------------------

    def shutdown(self) -> None:
        """Cleanup pulito: chiude sessione history (calcola duration ultima entry)."""
        try:
            self.history.close_session()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"shutdown history error: {e}")

    # ----------------------------------------------------------------
    # PROFILE APPLICATION
    # ----------------------------------------------------------------

    def apply_profile_blocking(self, profile_name: str) -> bool:
        """
        Applica profilo (BLOCKING — chiamare da worker thread).
        Include ensure_running + apply + history.
        """
        self.msi.ensure_running()
        ok = self.profiles.apply_profile(profile_name)
        if ok:
            self.current_profile = profile_name
            self.process_logic.set_current_profile(profile_name)
            self.history.record_switch(profile_name)
            self._log(f"Profilo applicato: {profile_name}")
        else:
            self._log(f"Errore applicazione: {profile_name}")
        return ok

    def get_display_name(self, profile_name: str) -> str:
        if profile_name == "Default":
            alias = self.config.get("default_alias", "")
            return f"Default ({alias})" if alias else "Default"
        return profile_name

    # ----------------------------------------------------------------
    # PROFILE CRUD
    # ----------------------------------------------------------------

    def create_profile(self, raw_name: str) -> Tuple[bool, str]:
        clean = sanitize_profile_name(raw_name)
        if clean is None:
            return False, "Nome non valido. Evita caratteri speciali e nomi riservati."
        if self.profiles.profile_exists(clean):
            return False, f"Il profilo '{clean}' esiste già."
        if self.profiles.create_profile(clean):
            return True, clean
        return False, "Errore durante la creazione del profilo."

    def duplicate_profile(self, source: str, raw_new_name: str) -> Tuple[bool, str]:
        clean = sanitize_profile_name(raw_new_name)
        if clean is None:
            return False, "Nome non valido."
        if self.profiles.profile_exists(clean):
            return False, f"Il profilo '{clean}' esiste già."
        if not self.profiles.duplicate_profile(source, clean):
            return False, "Errore durante la duplicazione."
        # Copia icona dal sorgente, se presente
        src_key, src_custom = self.get_profile_icon(source)
        if src_key or src_custom:
            self.set_profile_icon(clean, icon_key=src_key, custom_path=src_custom)
        return True, clean

    def delete_profile(self, name: str) -> bool:
        ok = self.profiles.delete_profile(name)
        if not ok:
            return False

        # Pulisci associazioni che puntano al profilo eliminato
        assoc = self.config.get_associations()
        cleaned_assoc = {k: v for k, v in assoc.items() if v != name}
        if cleaned_assoc != assoc:
            self.config.config["associations"] = cleaned_assoc

        # Pulisci icona
        icons = dict(self.config.get("profile_icons", {}))
        icons.pop(name, None)
        self.config.config["profile_icons"] = icons

        # Pulisci priority list
        priority = self.config.get("process_priority", []) or []
        new_priority = [p for p in priority if p != name]
        if new_priority != priority:
            self.config.config["process_priority"] = new_priority

        self.config.save()
        return True

    def rename_profile(self, old: str, raw_new: str) -> Tuple[bool, str]:
        clean = sanitize_profile_name(raw_new)
        if clean is None:
            return False, "Nome non valido."
        if clean == old:
            return False, "Il nome è uguale a quello attuale."
        if self.profiles.profile_exists(clean):
            return False, f"'{clean}' esiste già."
        if not self.profiles.rename_profile(old, clean):
            return False, "Errore durante la rinomina."

        # Aggiorna associazioni
        assoc = self.config.get_associations()
        for exe, prof in list(assoc.items()):
            if prof == old:
                assoc[exe] = clean
        self.config.config["associations"] = assoc

        # Aggiorna default_alias se rinominato
        if self.config.get("default_alias") == old:
            self.config.config["default_alias"] = clean

        # Aggiorna icona profilo
        icons = dict(self.config.get("profile_icons", {}))
        if old in icons:
            icons[clean] = icons.pop(old)
            self.config.config["profile_icons"] = icons

        self.config.save()

        # Se rinomi il profilo attivo, aggiorna lo stato interno
        if self.current_profile == old:
            self.current_profile = clean
            self.process_logic.set_current_profile(clean)
        return True, clean

    def reset_default(self) -> bool:
        if self.profiles.reset_default_to_virgin():
            self.config.set("default_alias", "VirginStock")
            return True
        return False

    def set_as_default(self, profile_name: str) -> bool:
        if self.profiles.set_as_default(profile_name):
            self.config.set("default_alias", profile_name)
            self._log(f"Default impostato a: {profile_name}")
            return True
        return False

    # ----------------------------------------------------------------
    # ASSOCIATIONS
    # ----------------------------------------------------------------

    def add_association(self, exe_name: str, profile_name: str) -> bool:
        ok = self.config.add_association(exe_name, profile_name)
        if ok:
            self._log(f"Associazione: {exe_name} → {profile_name}")
        return ok

    def remove_association(self, exe_name: str) -> bool:
        ok = self.config.remove_association(exe_name)
        if ok:
            self._log(f"Associazione rimossa: {exe_name}")
        return ok

    # ----------------------------------------------------------------
    # PROFILE ICONS
    # ----------------------------------------------------------------

    def get_profile_icons(self) -> Dict[str, Dict[str, str]]:
        return self.config.get("profile_icons", {})

    def set_profile_icon(
        self,
        profile_name: str,
        icon_key: str = "",
        custom_path: str = "",
    ) -> bool:
        icons = dict(self.config.get("profile_icons", {}))
        if not icon_key and not custom_path:
            icons.pop(profile_name, None)
        else:
            icons[profile_name] = {"key": icon_key, "custom": custom_path}
        self.config.config["profile_icons"] = icons
        return self.config.save()

    def get_profile_icon(self, profile_name: str) -> Tuple[str, str]:
        icons = self.config.get("profile_icons", {})
        data = icons.get(profile_name, {})
        return data.get("key", ""), data.get("custom", "")

    # ----------------------------------------------------------------
    # EDITING (MSI Afterburner diretto)
    # ----------------------------------------------------------------

    def start_editing(self, profile_name: str) -> None:
        self.process_logic.pause_monitoring()
        self._log(f"[EDIT] Monitoraggio pausa per: {profile_name}")

    def finish_editing(self, profile_name: str) -> None:
        self.profiles.save_profile_from_msi(profile_name)
        self.msi.kill()
        self._log("[EDIT] Profilo salvato")

    def resume_after_edit(self) -> None:
        self.msi.start()
        self.process_logic.resume_monitoring()
        self._log("[EDIT] Monitoraggio ripreso")

    def cancel_editing(self) -> None:
        self.process_logic.resume_monitoring()
        self._log("[EDIT] Modifica annullata, monitoraggio ripreso")

    # ----------------------------------------------------------------
    # CFG EDITOR INTEGRATION
    # ----------------------------------------------------------------

    def get_cfg_files_for_profile(self, profile_name: str) -> List[Path]:
        """Restituisce i file VEN_*.cfg validi per un profilo (ignora stub vuoti)."""
        profile_dir = self.profiles.get_profile_dir(profile_name)
        if not profile_dir.exists():
            return []
        out: List[Path] = []
        for p in sorted(profile_dir.glob("VEN_*.cfg")):
            try:
                if p.is_file() and p.stat().st_size > 200:
                    out.append(p)
            except OSError:
                continue
        return out

    def get_profile1_for_profile(self, profile_name: str) -> Optional[Path]:
        """Restituisce Profile1.cfg se esiste ed è valido (ignora stub vuoti)."""
        profile_dir = self.profiles.get_profile_dir(profile_name)
        if not profile_dir.exists():
            return None
        p1 = profile_dir / "Profile1.cfg"
        try:
            return p1 if p1.exists() and p1.stat().st_size > 200 else None
        except OSError:
            return None

    def get_first_cfg_for_profile(self, profile_name: str) -> Optional[Path]:
        files = self.get_cfg_files_for_profile(profile_name)
        if files:
            return files[0]
        return self.get_profile1_for_profile(profile_name)

    # ----------------------------------------------------------------
    # SOUND
    # ----------------------------------------------------------------
    # SOUND
    # ----------------------------------------------------------------

    def play_sound(self, preset: str, force: bool = False) -> None:
        if force or self.sounds_enabled:
            SoundPlayer.play_async(preset)

    def set_sounds_enabled(self, enabled: bool) -> None:
        self.sounds_enabled = enabled
        self.config.set("sounds", enabled)

    # ----------------------------------------------------------------
    # HISTORY
    # ----------------------------------------------------------------

    def get_usage_stats(self, days: int = 7) -> Dict[str, float]:
        return self.history.get_usage_last_n_days(days)

    def get_daily_breakdown(self, days: int = 7) -> Dict[str, Dict[str, float]]:
        return self.history.get_daily_breakdown(days)

    def get_summary_stats(self, days: int = 7) -> Dict[str, float]:
        return self.history.get_summary_stats(days)

    def export_history_csv(self, path: Path) -> bool:
        return self.history.export_csv(path)

    # ----------------------------------------------------------------
    # MONITORING PAUSE (toggle utente)
    # ----------------------------------------------------------------

    def set_monitoring_paused(self, paused: bool) -> None:
        self.process_logic.set_user_paused(paused)

    @property
    def is_monitoring_paused(self) -> bool:
        return self.process_logic.is_paused

    # ----------------------------------------------------------------
    # IMPORT / EXPORT — Singolo profilo
    # ----------------------------------------------------------------

    def export_profile(self, profile_name: str, dest_path: Path) -> bool:
        """Esporta un singolo profilo in un file JSON."""
        try:
            dest_path = Path(dest_path)
            profile_dir = self.profiles.get_profile_dir(profile_name)
            if not profile_dir.exists():
                return False

            payload: Dict[str, Any] = {
                "meta": {
                    "app": APP_NAME,
                    "version": APP_VERSION,
                    "exported": datetime.now().isoformat(),
                    "profile_name": profile_name,
                },
                "icon": dict(self.config.get("profile_icons", {}).get(profile_name, {})),
                "files": {},
            }
            # Esporta SOLO i .cfg gestiti (VEN_*.cfg + ProfileN.cfg), ignora il resto.
            for cf in iter_managed_cfg(profile_dir):
                try:
                    payload["files"][cf.name] = cf.read_text(encoding="utf-8", errors="ignore")
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"export_profile skip {cf}: {e}")

            dest_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._log(f"Profilo esportato: {profile_name} → {dest_path}")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"export_profile error: {e}")
            return False

    def import_profile(self, src_path: Path, target_name: Optional[str] = None) -> Tuple[bool, str]:
        """
        Importa un profilo da JSON.

        Args:
            src_path: file JSON sorgente
            target_name: nome con cui salvare (se None, usa il nome dal meta)
        """
        try:
            text = Path(src_path).read_text(encoding="utf-8")
            payload = json.loads(text)
            files = payload.get("files", {}) or {}
            if not files:
                return False, "Nessun file .cfg nel JSON."

            name = target_name or payload.get("meta", {}).get("profile_name", "")
            clean = sanitize_profile_name(name)
            if clean is None:
                return False, "Nome profilo non valido."
            if self.profiles.profile_exists(clean):
                return False, f"Il profilo '{clean}' esiste già."

            dest_dir = self.profiles.manager_root / clean
            dest_dir.mkdir(parents=True, exist_ok=True)
            for fname, content in files.items():
                # Solo nomi file sicuri e .cfg gestiti.
                safe = Path(fname).name
                if not is_managed_cfg(safe):
                    continue  # ignora .cfg estranei eventualmente presenti in vecchi JSON
                (dest_dir / safe).write_text(content, encoding="utf-8", errors="ignore")

            # Importa icona se presente
            icon = payload.get("icon", {})
            if isinstance(icon, dict) and (icon.get("key") or icon.get("custom")):
                self.set_profile_icon(
                    clean,
                    icon_key=icon.get("key", ""),
                    custom_path=icon.get("custom", ""),
                )

            self._log(f"Profilo importato: {clean}")
            return True, clean
        except json.JSONDecodeError as e:
            return False, f"JSON non valido: {e}"
        except Exception as e:  # noqa: BLE001
            logger.error(f"import_profile error: {e}")
            return False, str(e)
