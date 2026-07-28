"""
OC Profiles Manager - Profile Info Extractor.

Legge i file .cfg di un profilo e ne estrae informazioni strutturate
per la visualizzazione nella vista Card.

Caching basato su mtime + size dei file .cfg.
Thread-safe (lock interno).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cfg_editor.cfg_model import AfterburnerCfgFile, AfterburnerProfile
from cfg_editor.vfcurve import VFPoint, decode_vfcurve

logger = logging.getLogger(__name__)


# ============================================================================
# DATA CLASS
# ============================================================================

@dataclass
class ProfileCardInfo:
    """Tutte le informazioni estratte da un profilo per la vista Card."""

    profile_name: str = ""
    cfg_file_count: int = 0

    # Valori dal profilo (Profile1 di default)
    core_clock_boost_mhz: float = 0.0
    mem_clock_boost_mhz: float = 0.0
    core_voltage_boost_mv: int = 0
    power_limit_pct: int = 0
    thermal_limit: int = 0
    fan_mode: str = "Auto"
    fan_speed_pct: int = 0

    # VF Curve stats
    has_vf_curve: bool = False
    vf_point_count: int = 0
    peak_frequency_mhz: float = 0.0
    peak_voltage_mv: float = 0.0
    min_voltage_mv: float = 0.0
    freq_at_1000mv: float = 0.0
    curve_is_modified: bool = False

    # Meta
    is_active: bool = False
    is_default: bool = False
    icon_key: str = ""
    icon_custom_path: str = ""

    # Errore
    load_error: str = ""

    @property
    def has_custom_icon(self) -> bool:
        return bool(self.icon_custom_path) and Path(self.icon_custom_path).exists()

    @property
    def effective_peak_freq(self) -> float:
        return self.peak_frequency_mhz

    @property
    def summary_text(self) -> str:
        parts: List[str] = []
        if self.core_clock_boost_mhz != 0:
            parts.append(f"Core: {self.core_clock_boost_mhz:+.0f} MHz")
        if self.mem_clock_boost_mhz != 0:
            parts.append(f"Mem: {self.mem_clock_boost_mhz:+.0f} MHz")
        if self.power_limit_pct and self.power_limit_pct != 100:
            parts.append(f"Power: {self.power_limit_pct}%")
        if self.peak_frequency_mhz > 0:
            parts.append(f"Peak: {self.peak_frequency_mhz:.0f} MHz @ {self.peak_voltage_mv:.0f} mV")
        return " | ".join(parts) if parts else "Profilo base"


# ============================================================================
# EXTRACTOR
# ============================================================================

class ProfileInfoExtractor:
    """
    Estrae informazioni strutturate dai file .cfg di un profilo.
    Cache: invalidata quando la *signature* (mtime+size somma) cambia.
    Thread-safe via lock interno.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, ProfileCardInfo] = {}
        self._cache_signatures: Dict[str, Tuple[float, int]] = {}
        self._lock = threading.RLock()

    # --- Cache control ---

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
            self._cache_signatures.clear()

    def invalidate(self, profile_name: str) -> None:
        with self._lock:
            # Rimuove tutte le entry che iniziano per "profile_name:"
            keys = [k for k in self._cache if k.startswith(f"{profile_name}:")]
            for k in keys:
                self._cache.pop(k, None)
                self._cache_signatures.pop(k, None)

    # --- Public API ---

    def extract(
        self,
        profile_name: str,
        profile_dir: Path,
        profile_section: str = "Profile1",
        is_active: bool = False,
        is_default: bool = False,
        icon_key: str = "",
        icon_custom_path: str = "",
    ) -> ProfileCardInfo:
        """Estrae info da un profilo (con caching)."""
        cache_key = f"{profile_name}:{profile_section}"
        sig = self._dir_signature(profile_dir)

        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None and self._cache_signatures.get(cache_key) == sig:
                # Cache valida: aggiorna solo metadati dinamici
                cached.is_active = is_active
                cached.is_default = is_default
                cached.icon_key = icon_key
                cached.icon_custom_path = icon_custom_path
                return cached

        # Cache miss: estrai senza tenere il lock
        info = self._extract_fresh(
            profile_name, profile_dir, profile_section,
            is_active, is_default, icon_key, icon_custom_path,
        )
        with self._lock:
            self._cache[cache_key] = info
            self._cache_signatures[cache_key] = sig
        return info

    # --- Internal helpers ---

    def _extract_fresh(
        self,
        profile_name: str,
        profile_dir: Path,
        profile_section: str,
        is_active: bool,
        is_default: bool,
        icon_key: str,
        icon_custom_path: str,
    ) -> ProfileCardInfo:
        info = ProfileCardInfo(
            profile_name=profile_name,
            is_active=is_active,
            is_default=is_default,
            icon_key=icon_key,
            icon_custom_path=icon_custom_path,
        )

        if not profile_dir.exists():
            info.load_error = "Directory non trovata"
            return info

        # Politica v2.6+: leggiamo SOLO i file VEN_*.cfg (i ProfileN.cfg sono
        # gestiti separatamente come 'global profile' di MSI Afterburner).
        ven_files = []
        for p in sorted(profile_dir.glob("VEN_*.cfg")):
            try:
                if p.is_file() and p.stat().st_size > 200:
                    ven_files.append(p)
            except OSError:
                continue
        info.cfg_file_count = len(ven_files)

        if not ven_files:
            info.load_error = "Nessun file VEN_*.cfg"
            return info

        try:
            cfg_file = AfterburnerCfgFile.load(ven_files[0])
            if not cfg_file.has_profile(profile_section):
                available = cfg_file.get_available_profiles()
                if available:
                    profile_section = available[0]
                else:
                    info.load_error = "Nessun profilo nel file"
                    return info
            prof = cfg_file.get_profile(profile_section)
            self._fill_from_profile(info, prof)
        except Exception as e:  # noqa: BLE001
            info.load_error = str(e)
            logger.debug(f"Errore estrazione {profile_name}: {e}")

        return info

    @staticmethod
    def _fill_from_profile(info: ProfileCardInfo, prof: AfterburnerProfile) -> None:
        info.core_clock_boost_mhz = prof.core_clock_mhz
        info.mem_clock_boost_mhz = prof.mem_clock_mhz
        info.core_voltage_boost_mv = prof.core_voltage_boost
        info.power_limit_pct = prof.power_limit if prof.power_limit else 100
        info.thermal_limit = prof.thermal_limit
        info.fan_mode = "Manuale" if prof.fan_mode == 1 else "Auto"
        info.fan_speed_pct = prof.fan_speed if prof.fan_mode == 1 else 0

        if prof.vfcurve_hex:
            try:
                points = decode_vfcurve(prof.vfcurve_hex)
                info.has_vf_curve = True
                info.vf_point_count = len(points)
                ProfileInfoExtractor._analyze_vf_curve(info, points)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Errore decode VF curve: {e}")

    @staticmethod
    def _analyze_vf_curve(info: ProfileCardInfo, points: List[VFPoint]) -> None:
        if not points:
            return
        # Frequenze effettive (base + delta)
        effective: List[Tuple[float, float]] = [
            (p.v_mv, p.f_mhz + p.c_delta) for p in points
        ]
        valid = [(v, f) for v, f in effective if f > 0]
        if not valid:
            return

        peak_v, peak_f = max(valid, key=lambda x: x[1])
        info.peak_frequency_mhz = peak_f
        info.peak_voltage_mv = peak_v
        info.min_voltage_mv = min(v for v, _ in valid)

        closest_1000 = min(valid, key=lambda x: abs(x[0] - 1000))
        info.freq_at_1000mv = closest_1000[1]

        info.curve_is_modified = any(abs(p.c_delta) > 0.1 for p in points)

    @staticmethod
    def _dir_signature(directory: Path) -> Tuple[float, int]:
        """Signature stabile: somma mtime + count .cfg files."""
        try:
            mtimes: List[float] = []
            count = 0
            # Signature stabile: solo .cfg gestiti (VEN_*.cfg + ProfileN.cfg)
            from oc_core import is_managed_cfg as _is_mgd
            for f in directory.iterdir():
                if not (f.is_file() and _is_mgd(f.name)):
                    continue
                try:
                    if f.stat().st_size <= 200:
                        continue
                    mtimes.append(f.stat().st_mtime)
                    count += 1
                except OSError:
                    continue
            return (sum(mtimes), count)
        except Exception:  # noqa: BLE001
            return (0.0, 0)
