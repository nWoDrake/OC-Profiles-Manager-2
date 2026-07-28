"""
Parser file .cfg di MSI Afterburner.

Gestisce file VEN_*.cfg con sezioni [Startup], [Profile1]-[Profile5].
Il salvataggio preserva l'ordine delle chiavi nel file originale.
"""

from __future__ import annotations

import configparser
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

logger = logging.getLogger(__name__)


# ============================================================================
# AFTERBURNER PROFILE
# ============================================================================

@dataclass
class AfterburnerProfile:
    """Dati di un singolo profilo estratto da un file .cfg."""

    section: str
    core_clk_boost: int = 0       # 225000 = +225 MHz
    mem_clk_boost: int = 0        # 494000 = +494 MHz
    core_voltage_boost: int = 0
    power_limit: int = 0          # %
    thermal_limit: int = 0
    thermal_prioritize: int = 0
    fan_mode: int = 0             # 0=auto, 1=manuale
    fan_speed: int = 0            # % (se manuale)
    vfcurve_hex: str = ""         # VFCurve hex string

    @staticmethod
    def from_config(cfg: configparser.ConfigParser, section: str) -> "AfterburnerProfile":
        if section not in cfg:
            raise KeyError(f"Missing section [{section}]")
        s = cfg[section]

        def _as_int(key: str) -> int:
            raw = (s.get(key, "0") or "0").strip()
            try:
                return int(raw)
            except ValueError:
                logger.debug(f"from_config: {key}={raw!r} non int, fallback 0")
                return 0

        return AfterburnerProfile(
            section=section,
            core_clk_boost=_as_int("CoreClkBoost"),
            mem_clk_boost=_as_int("MemClkBoost"),
            core_voltage_boost=_as_int("CoreVoltageBoost"),
            power_limit=_as_int("PowerLimit"),
            thermal_limit=_as_int("ThermalLimit"),
            thermal_prioritize=_as_int("ThermalPrioritize"),
            fan_mode=_as_int("FanMode"),
            fan_speed=_as_int("FanSpeed"),
            vfcurve_hex=(s.get("VFCurve", "") or "").strip(),
        )

    def apply_to_config(self, cfg: configparser.ConfigParser) -> None:
        if self.section not in cfg:
            cfg[self.section] = {}
        s = cfg[self.section]
        s["CoreClkBoost"] = str(int(self.core_clk_boost))
        s["MemClkBoost"] = str(int(self.mem_clk_boost))
        s["CoreVoltageBoost"] = str(int(self.core_voltage_boost))
        s["PowerLimit"] = str(int(self.power_limit))
        s["ThermalPrioritize"] = str(int(self.thermal_prioritize))
        s["FanMode"] = str(int(self.fan_mode))
        s["FanSpeed"] = str(int(self.fan_speed))
        s["VFCurve"] = self.vfcurve_hex

    @property
    def core_clock_mhz(self) -> float:
        return self.core_clk_boost / 1000.0

    @property
    def mem_clock_mhz(self) -> float:
        return self.mem_clk_boost / 1000.0

    def to_display_dict(self) -> dict:
        return {
            "Core Clock Boost": f"{self.core_clock_mhz:+.0f} MHz",
            "Memory Clock Boost": f"{self.mem_clock_mhz:+.0f} MHz",
            "Power Limit": f"{self.power_limit}%",
            "Core Voltage Boost": f"{self.core_voltage_boost} mV",
            "Fan Mode": "Manuale" if self.fan_mode == 1 else "Auto",
            "Fan Speed": f"{self.fan_speed}%" if self.fan_mode == 1 else "Auto",
            "VF Curve": "Presente" if self.vfcurve_hex else "Assente",
        }


# ============================================================================
# AFTERBURNER CFG FILE
# ============================================================================

class AfterburnerCfgFile:
    """
    Gestisce un file .cfg di MSI Afterburner (VEN_*.cfg).
    Preserva la struttura originale durante il salvataggio.
    """

    def __init__(
        self,
        path: Path,
        cfg: configparser.ConfigParser,
        raw_text: str = "",
    ):
        self.path: Path = path
        self.cfg: configparser.ConfigParser = cfg
        self._raw_text: str = raw_text

    # --- IO ---

    @staticmethod
    def load(path: Union[str, Path]) -> "AfterburnerCfgFile":
        p = Path(path)
        cp = configparser.ConfigParser(interpolation=None)
        cp.optionxform = str  # preserva case delle chiavi

        raw = p.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="ignore")

        cp.read_file(io.StringIO(text))
        return AfterburnerCfgFile(path=p, cfg=cp, raw_text=text)

    # --- Inspection ---

    def get_profile(self, section: str = "Profile1") -> AfterburnerProfile:
        return AfterburnerProfile.from_config(self.cfg, section)

    def get_available_profiles(self) -> List[str]:
        """Restituisce le sezioni Profile* presenti nel file."""
        return [s for s in self.cfg.sections() if s.startswith("Profile")]

    def has_profile(self, section: str) -> bool:
        return section in self.cfg

    # --- Save ---

    def save_profile(
        self,
        profile: AfterburnerProfile,
        out_path: Optional[Union[str, Path]] = None,
    ) -> None:
        """
        Salva il profilo preservando il più possibile la struttura originale.
        Usa line-by-line replacement per evitare il riordino chiavi di configparser.
        """
        profile.apply_to_config(self.cfg)
        target = Path(out_path) if out_path else self.path

        if self._raw_text and target == self.path:
            new_text = self._rebuild_preserving_structure(profile)
            if new_text is not None:
                target.write_text(new_text, encoding="utf-8", newline="\r\n")
                logger.info(
                    f"Profilo {profile.section} salvato (preservando struttura) in {target}"
                )
                return

        # Fallback: configparser standard
        with target.open("w", encoding="utf-8", newline="\r\n") as f:
            self.cfg.write(f)
        logger.info(f"Profilo {profile.section} salvato in {target}")

    def _rebuild_preserving_structure(
        self, profile: AfterburnerProfile
    ) -> Optional[str]:
        """
        Ricostruisce il file sostituendo i valori nella sezione del profilo
        senza alterare ordine chiavi, formattazione o altre sezioni.
        """
        try:
            lines = self._raw_text.splitlines(keepends=True)
            result: List[str] = []
            in_target_section = False
            target_section = f"[{profile.section}]"

            values_to_write = {
                "CoreClkBoost":      str(int(profile.core_clk_boost)),
                "MemClkBoost":       str(int(profile.mem_clk_boost)),
                "CoreVoltageBoost":  str(int(profile.core_voltage_boost)),
                "PowerLimit":        str(int(profile.power_limit)),
                "ThermalPrioritize": str(int(profile.thermal_prioritize)),
                "FanMode":           str(int(profile.fan_mode)),
                "FanSpeed":          str(int(profile.fan_speed)),
                "VFCurve":           profile.vfcurve_hex,
            }

            for line in lines:
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    in_target_section = (stripped == target_section)
                    result.append(line)
                    continue

                if in_target_section and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in values_to_write:
                        # Preserva spazio attorno all'=
                        if " =" in line or "= " in line:
                            result.append(f"{key} ={values_to_write[key]}\n")
                        else:
                            result.append(f"{key}={values_to_write[key]}\n")
                        continue

                result.append(line)

            new_text = "".join(result)
            self._raw_text = new_text
            return new_text
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Rebuild preservando struttura fallito: {e}")
            return None
