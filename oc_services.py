"""
OC Profiles Manager - Servizi accessori (v2.7).

Contiene la logica core (NO Qt) dei nuovi servizi:
- BackupManager        → backup zip automatico dei profili con retention
- ProfileScheduler     → regole orarie profilo (es. "Silent" 22:00-07:00)
- TempWatchdog         → protezione temperatura GPU
- UpdateChecker        → check nuove release da GitHub
- GlobalHotkeyListener → hotkey globali Windows (Ctrl+Alt+1..9)

Tutte le classi sono testabili senza UI; l'integrazione Qt vive nei temi.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import threading
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from constants import APP_VERSION

logger = logging.getLogger(__name__)

_IS_WINDOWS = os.name == "nt"


# ============================================================================
# B — BACKUP AUTOMATICO PROFILI
# ============================================================================

class BackupManager:
    """
    Backup zip di ProfilesManager/ con retention.

    Struttura: <manager_root>/../ProfilesManager_Backups/
        profiles_backup_2026-07-29_143000.zip
    I backup escludono le directory temporanee (_staging_tmp, _backup_tmp).
    """

    EXCLUDED_DIRS = frozenset({"_staging_tmp", "_backup_tmp"})
    PREFIX = "profiles_backup_"

    def __init__(self, manager_root: Path):
        self.manager_root = Path(manager_root)
        self.backup_dir = self.manager_root.parent / "ProfilesManager_Backups"

    def list_backups(self) -> List[Path]:
        """Backup esistenti, dal più recente al più vecchio."""
        if not self.backup_dir.exists():
            return []
        zips = sorted(
            self.backup_dir.glob(f"{self.PREFIX}*.zip"),
            key=lambda p: p.name,
            reverse=True,
        )
        return zips

    def create_backup(self) -> Optional[Path]:
        """Crea un backup zip datato. Ritorna il path o None su errore."""
        if not self.manager_root.exists():
            logger.warning("BackupManager: manager_root inesistente")
            return None
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            dest = self.backup_dir / f"{self.PREFIX}{stamp}.zip"
            # Evita collisioni se due backup nascono nello stesso secondo
            seq = 1
            while dest.exists():
                dest = self.backup_dir / f"{self.PREFIX}{stamp}_{seq}.zip"
                seq += 1
            tmp = dest.with_suffix(".tmp")
            n_files = 0
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(self.manager_root):
                    # non scendere nelle dir temporanee
                    dirs[:] = [d for d in dirs if d not in self.EXCLUDED_DIRS]
                    for fname in files:
                        fpath = Path(root) / fname
                        arcname = fpath.relative_to(self.manager_root)
                        zf.write(fpath, arcname)
                        n_files += 1
            os.replace(tmp, dest)  # atomico
            logger.info(f"Backup creato: {dest.name} ({n_files} file)")
            return dest
        except Exception as e:  # noqa: BLE001
            logger.error(f"Backup fallito: {e}")
            try:
                tmp.unlink(missing_ok=True)  # type: ignore[possibly-undefined]
            except Exception:  # noqa: BLE001
                pass
            return None

    def prune_old(self, keep: int = 10) -> int:
        """Elimina i backup oltre la retention. Ritorna quanti rimossi."""
        removed = 0
        for old in self.list_backups()[max(keep, 1):]:
            try:
                old.unlink()
                removed += 1
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Prune backup {old.name}: {e}")
        if removed:
            logger.info(f"Backup pruning: rimossi {removed} zip vecchi")
        return removed

    def auto_backup(self, retention: int = 10) -> Optional[Path]:
        """Backup + pruning in un colpo (chiamato all'avvio, in thread)."""
        path = self.create_backup()
        if path is not None:
            self.prune_old(retention)
        return path

    def restore_backup(self, zip_path: Path) -> bool:
        """
        Ripristina un backup DENTRO manager_root (sovrascrive i profili).
        Non tocca i cfg live in Profiles/: dopo il restore serve un apply.
        """
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # Zip-slip guard
                root = self.manager_root.resolve()
                for member in zf.namelist():
                    target = (root / member).resolve()
                    if not str(target).startswith(str(root)):
                        logger.error(f"Restore rifiutato, path sospetto: {member}")
                        return False
                zf.extractall(self.manager_root)
            logger.info(f"Backup ripristinato: {zip_path.name}")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Restore fallito: {e}")
            return False


# ============================================================================
# E — SCHEDULER ORARIO PROFILI
# ============================================================================

class ProfileScheduler:
    """
    Valuta regole orarie → profilo.

    Regola: {"start": "22:00", "end": "07:00", "profile": "Silent",
             "enabled": True}
    - Intervallo che scavalca la mezzanotte supportato (start > end).
    - La PRIMA regola attiva che matcha l'ora corrente vince.
    - Lo scheduler NON applica da solo: espone check() e il chiamante
      (UI timer) decide; il monitor processi ha priorità (se c'è un
      match di processo attivo, lo scheduler non interviene).
    """

    def __init__(self, config_manager):
        self.config = config_manager
        self._last_applied_rule: Optional[str] = None  # firma regola applicata

    def reset(self) -> None:
        """Azzera la memoria edge-trigger (dopo modifica regole)."""
        self._last_applied_rule = None

    @staticmethod
    def _parse_hhmm(s: str) -> Optional[int]:
        """'22:30' → minuti dalla mezzanotte (1350). None se invalida."""
        try:
            hh, mm = s.strip().split(":")
            h, m = int(hh), int(mm)
            if 0 <= h <= 23 and 0 <= m <= 59:
                return h * 60 + m
        except Exception:  # noqa: BLE001
            pass
        return None

    @classmethod
    def rule_matches_now(cls, rule: Dict, now_minutes: Optional[int] = None) -> bool:
        """True se l'ora corrente cade nell'intervallo della regola."""
        if not rule.get("enabled", True):
            return False
        start = cls._parse_hhmm(str(rule.get("start", "")))
        end = cls._parse_hhmm(str(rule.get("end", "")))
        if start is None or end is None or start == end:
            return False
        if now_minutes is None:
            t = datetime.now()
            now_minutes = t.hour * 60 + t.minute
        if start < end:
            return start <= now_minutes < end
        # Scavalca mezzanotte: es. 22:00 → 07:00
        return now_minutes >= start or now_minutes < end

    def check(self) -> Optional[str]:
        """
        Ritorna il profilo da applicare ORA secondo le regole, oppure None.
        Ritorna un profilo solo al CAMBIO di regola attiva (edge-triggered),
        così non ri-applica lo stesso profilo ogni minuto.
        """
        if not self.config.get("scheduler_enabled", False):
            self._last_applied_rule = None
            return None
        rules: List[Dict] = self.config.get("schedule_rules", []) or []
        active_rule = None
        for rule in rules:
            if self.rule_matches_now(rule):
                active_rule = rule
                break
        if active_rule is None:
            self._last_applied_rule = None
            return None
        signature = f"{active_rule.get('start')}-{active_rule.get('end')}-{active_rule.get('profile')}"
        if signature == self._last_applied_rule:
            return None  # già applicata
        self._last_applied_rule = signature
        profile = str(active_rule.get("profile", "")).strip()
        return profile or None


# ============================================================================
# G — WATCHDOG TEMPERATURA GPU
# ============================================================================

class TempWatchdog:
    """
    Se la temperatura GPU resta sopra soglia per N secondi consecutivi,
    segnala che va applicato il profilo safe (una sola volta per episodio).

    Uso: chiamare feed(temp) a ogni tick di telemetria (1 s);
    ritorna il nome del profilo safe quando scatta, altrimenti None.
    """

    def __init__(self, config_manager):
        self.config = config_manager
        self._over_since: Optional[float] = None
        self._triggered: bool = False

    def reset(self) -> None:
        self._over_since = None
        self._triggered = False

    def feed(self, temp_c: float) -> Optional[str]:
        if not self.config.get("temp_watchdog_enabled", False):
            self.reset()
            return None
        threshold = float(self.config.get("temp_watchdog_threshold", 90))
        duration = float(self.config.get("temp_watchdog_duration_s", 10))

        if temp_c < threshold:
            # Rientro sotto soglia con isteresi di 5 °C: riarma il watchdog
            if temp_c < threshold - 5:
                self.reset()
            else:
                self._over_since = None
            return None

        now = time.monotonic()
        if self._over_since is None:
            self._over_since = now
            return None
        if self._triggered:
            return None  # già scattato per questo episodio
        if (now - self._over_since) >= duration:
            self._triggered = True
            profile = str(self.config.get("temp_watchdog_profile", "Default"))
            logger.warning(
                f"TempWatchdog: {temp_c:.0f}°C ≥ {threshold:.0f}°C per "
                f"{duration:.0f}s → applico profilo safe '{profile}'"
            )
            return profile
        return None


# ============================================================================
# H — CHECK AGGIORNAMENTI (GitHub Releases)
# ============================================================================

class UpdateChecker:
    """
    Confronta APP_VERSION con l'ultima release GitHub.
    check() è bloccante (rete) → chiamare in thread.
    """

    API_URL = "https://api.github.com/repos/nWoDrake/OC-Profiles-Manager-2/releases/latest"
    TIMEOUT_S = 6.0

    @staticmethod
    def _parse_version(v: str) -> Tuple[int, ...]:
        v = v.strip().lstrip("vV")
        parts = []
        for chunk in v.split("."):
            digits = "".join(ch for ch in chunk if ch.isdigit())
            parts.append(int(digits) if digits else 0)
        return tuple(parts) or (0,)

    @classmethod
    def is_newer(cls, remote: str, local: str = APP_VERSION) -> bool:
        return cls._parse_version(remote) > cls._parse_version(local)

    @classmethod
    def check(cls) -> Optional[Dict[str, str]]:
        """
        Ritorna {"version": "...", "url": "...", "name": "..."} se esiste
        una versione più nuova, None altrimenti (o su errore rete).
        """
        try:
            req = urllib.request.Request(
                cls.API_URL,
                headers={"Accept": "application/vnd.github+json",
                         "User-Agent": f"OCProfilesManager/{APP_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=cls.TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            tag = str(data.get("tag_name", ""))
            if tag and cls.is_newer(tag):
                return {
                    "version": tag,
                    "url": str(data.get("html_url", "")),
                    "name": str(data.get("name", tag)),
                }
        except Exception as e:  # noqa: BLE001
            logger.debug(f"UpdateChecker: {e}")
        return None


# ============================================================================
# F — HOTKEY GLOBALI (Windows RegisterHotKey)
# ============================================================================

class GlobalHotkeyListener(threading.Thread):
    """
    Registra Ctrl+Alt+1..9 come hotkey GLOBALI Windows.
    Alla pressione di Ctrl+Alt+N chiama callback(N) (N = 1..9).

    Il thread possiede un message loop Win32 (GetMessageW); su sistemi
    non-Windows è un no-op silenzioso. stop() è thread-safe.
    """

    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    # Virtual-Key '1'..'9' = 0x31..0x39
    VK_1 = 0x31

    def __init__(self, callback: Callable[[int], None]):
        super().__init__(daemon=True, name="GlobalHotkeys")
        self._callback = callback
        self._thread_id: Optional[int] = None
        self._registered: List[int] = []
        self._stop_requested = False

    def run(self) -> None:  # pragma: no cover (solo Windows)
        if not _IS_WINDOWS:
            logger.debug("GlobalHotkeyListener: non-Windows, no-op")
            return
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()

        for n in range(1, 10):
            hotkey_id = 100 + n
            vk = self.VK_1 + (n - 1)
            if user32.RegisterHotKey(None, hotkey_id,
                                     self.MOD_CONTROL | self.MOD_ALT, vk):
                self._registered.append(hotkey_id)
            else:
                logger.debug(f"RegisterHotKey Ctrl+Alt+{n} fallita (in uso?)")

        if not self._registered:
            logger.warning("Nessuna hotkey globale registrata")
            return
        logger.info(f"Hotkey globali attive: Ctrl+Alt+1..{len(self._registered)}")

        msg = ctypes.wintypes.MSG() if hasattr(ctypes, "wintypes") else None
        import ctypes.wintypes as wt
        msg = wt.MSG()
        try:
            while not self._stop_requested:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret in (0, -1):  # WM_QUIT o errore
                    break
                if msg.message == self.WM_HOTKEY:
                    n = int(msg.wParam) - 100
                    if 1 <= n <= 9:
                        try:
                            self._callback(n)
                        except Exception as e:  # noqa: BLE001
                            logger.error(f"Hotkey callback: {e}")
        finally:
            for hotkey_id in self._registered:
                user32.UnregisterHotKey(None, hotkey_id)
            self._registered.clear()

    def stop(self) -> None:
        """Ferma il message loop (thread-safe)."""
        self._stop_requested = True
        if _IS_WINDOWS and self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, self.WM_QUIT, 0, 0
                )
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Hotkey stop: {e}")
