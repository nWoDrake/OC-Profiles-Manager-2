"""
OC Profiles Manager - Core Business Logic.

Layer di logica applicativa (no Qt). Comprende:
- SoundPlayer       : beep semplice tramite winsound
- GPUMonitor        : telemetria GPU tramite NVML (con simulazione fallback)
- ConfigManager     : persistenza JSON thread-safe
- ProfileManager    : staging atomico, backup/rollback, swap profilo
- MSIAfterburnerController : avvio/kill/polling MSI Afterburner
- ProcessMonitorLogic     : state machine match processi → profilo
"""

from __future__ import annotations

import ctypes
import logging
import random
import re
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import psutil

try:  # winsound non disponibile fuori da Windows
    import winsound  # type: ignore[import]
except ImportError:  # pragma: no cover
    winsound = None  # type: ignore[assignment]

from constants import DEFAULT_CONFIG, SOUND_CONFIG, TIMING
from oc_utils import (
    atomic_write_json,
    popen_detached,
    popen_hidden,
    run_hidden,
    safe_read_json,
    safe_rmtree,
    snapshot_running_exes,
)

logger = logging.getLogger(__name__)

# Pattern precompilati (usati nel hot path)
_PROFILE_NAME_RE = re.compile(r"Profile\s*(\d+)")
_VEN_FILE_RE = re.compile(r"^VEN_.*\.cfg$", re.IGNORECASE)
_MIN_EFFECTIVE_CFG_BYTES = 200


def is_managed_cfg(filename: str) -> bool:
    """
    True se il file .cfg deve essere gestito dal programma.

    Politica (v2.6.1): consideriamo SOLO due tipi di file .cfg:
        - VEN_*.cfg
        - Profile1.cfg

    Tutti gli altri .cfg vengono ignorati.
    """
    name = filename.strip()
    return bool(_VEN_FILE_RE.match(name) or name.lower() == "profile1.cfg")


def is_effective_cfg_path(path: "Path") -> bool:
    """True se il file è gestito ed è abbastanza grande da non essere uno stub vuoto."""
    try:
        return path.is_file() and is_managed_cfg(path.name) and path.stat().st_size > _MIN_EFFECTIVE_CFG_BYTES
    except OSError:
        return False


def iter_managed_cfg(directory: "Path"):
    """Generatore: itera SOLO i file .cfg gestiti ed effettivi (no stub vuoti)."""
    if not directory.exists():
        return
    for f in directory.iterdir():
        if is_effective_cfg_path(f):
            yield f


# ============================================================================
# SOUND

# ============================================================================
# SOUND — winsound.Beep
# ============================================================================

class SoundPlayer:
    """Riproduzione suoni leggera tramite winsound.Beep."""

    @staticmethod
    def play(preset_name: str) -> None:
        if winsound is None:
            return
        cfg = SOUND_CONFIG.get(preset_name)
        if not cfg:
            return
        try:
            winsound.Beep(cfg["frequency"], cfg["duration_ms"])
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Beep fallito: {e}")

    @staticmethod
    def play_async(preset_name: str) -> None:
        """Esegue il beep in un thread daemon (non blocca la UI)."""
        if winsound is None:
            return
        t = threading.Thread(
            target=SoundPlayer.play,
            args=(preset_name,),
            daemon=True,
            name=f"SoundPlayer-{preset_name}",
        )
        t.start()


# ============================================================================
# GPU MONITOR — Singleton con NVML correttamente tipizzato
# ============================================================================

class GPUMonitor:
    """
    Monitor GPU singleton, lettura tramite NVML (NVIDIA).
    Fallback a simulazione se NVML non disponibile.
    Thread-safe (lock su letture NVML).
    """

    _instance: Optional["GPUMonitor"] = None
    _instance_lock: threading.Lock = threading.Lock()

    # Costanti NVML
    NVML_CLOCK_GRAPHICS = 0
    NVML_CLOCK_MEM = 2
    NVML_TEMPERATURE_GPU = 0

    class NvmlUtilization(ctypes.Structure):
        _fields_ = [
            ("gpu", ctypes.c_uint),
            ("memory", ctypes.c_uint),
        ]

    class NvmlMemory(ctypes.Structure):
        _fields_ = [
            ("total", ctypes.c_ulonglong),
            ("free", ctypes.c_ulonglong),
            ("used", ctypes.c_ulonglong),
        ]

    def __new__(cls) -> "GPUMonitor":
        with cls._instance_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._init_once()
                cls._instance = inst
        return cls._instance

    def _init_once(self) -> None:
        self._nvml_lib: Optional[ctypes.CDLL] = None
        self._device_handle: Optional[ctypes.c_void_p] = None
        self._initialized: bool = False
        self._simulating: bool = False
        self._read_lock = threading.Lock()
        self._try_init_nvml()

    # ----------------- NVML init / typing -----------------

    def _try_init_nvml(self) -> bool:
        """Tenta init NVML; restituisce True se hardware disponibile."""
        candidate_paths = [
            "nvml.dll",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll",
            r"C:\Windows\System32\nvml.dll",
        ]
        for path in candidate_paths:
            try:
                lib = ctypes.CDLL(path)
            except OSError:
                continue
            except Exception as e:  # noqa: BLE001
                logger.debug(f"NVML load error {path}: {e}")
                continue

            try:
                self._configure_nvml_signatures(lib)
                if lib.nvmlInit_v2() != 0:
                    continue
                handle = ctypes.c_void_p()
                if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
                    continue
                self._nvml_lib = lib
                self._device_handle = handle
                self._initialized = True
                logger.info(f"NVML inizializzato da: {path}")
                return True
            except Exception as e:  # noqa: BLE001
                logger.debug(f"NVML init error {path}: {e}")
                continue

        self._simulating = True
        logger.warning("NVML non disponibile — modalità simulazione attiva")
        return False

    @staticmethod
    def _configure_nvml_signatures(lib: ctypes.CDLL) -> None:
        """Imposta argtypes/restype per chiamate NVML (sicurezza 64-bit)."""
        c_uint_p = ctypes.POINTER(ctypes.c_uint)
        void_p = ctypes.c_void_p

        # init
        lib.nvmlInit_v2.restype = ctypes.c_int
        lib.nvmlInit_v2.argtypes = []
        lib.nvmlShutdown.restype = ctypes.c_int
        lib.nvmlShutdown.argtypes = []

        # device
        lib.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
        lib.nvmlDeviceGetHandleByIndex_v2.argtypes = [
            ctypes.c_uint, ctypes.POINTER(void_p),
        ]
        lib.nvmlDeviceGetTemperature.restype = ctypes.c_int
        lib.nvmlDeviceGetTemperature.argtypes = [void_p, ctypes.c_int, c_uint_p]
        lib.nvmlDeviceGetUtilizationRates.restype = ctypes.c_int
        lib.nvmlDeviceGetUtilizationRates.argtypes = [
            void_p, ctypes.POINTER(GPUMonitor.NvmlUtilization),
        ]
        lib.nvmlDeviceGetFanSpeed.restype = ctypes.c_int
        lib.nvmlDeviceGetFanSpeed.argtypes = [void_p, c_uint_p]
        lib.nvmlDeviceGetClockInfo.restype = ctypes.c_int
        lib.nvmlDeviceGetClockInfo.argtypes = [void_p, ctypes.c_int, c_uint_p]
        lib.nvmlDeviceGetPowerUsage.restype = ctypes.c_int
        lib.nvmlDeviceGetPowerUsage.argtypes = [void_p, c_uint_p]
        lib.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int
        lib.nvmlDeviceGetMemoryInfo.argtypes = [
            void_p, ctypes.POINTER(GPUMonitor.NvmlMemory),
        ]

    # ----------------- Public API -----------------

    @property
    def is_real_hardware(self) -> bool:
        return self._initialized and not self._simulating

    def get_stats(self) -> Dict[str, Any]:
        """Lettura thread-safe delle statistiche GPU."""
        with self._read_lock:
            if self._initialized and self._nvml_lib is not None:
                try:
                    return self._read_nvml_stats()
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Errore lettura NVML: {e}")
            return self._generate_simulated_stats()

    def shutdown(self) -> None:
        """Chiude NVML correttamente per evitare handle leak."""
        with self._read_lock:
            if self._initialized and self._nvml_lib is not None:
                try:
                    self._nvml_lib.nvmlShutdown()
                    logger.info("NVML shutdown completato")
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"NVML shutdown error: {e}")
                finally:
                    self._initialized = False

    # ----------------- Read helpers -----------------

    def _read_nvml_stats(self) -> Dict[str, Any]:
        lib = self._nvml_lib
        h = self._device_handle
        assert lib is not None and h is not None

        temp = ctypes.c_uint()
        lib.nvmlDeviceGetTemperature(h, self.NVML_TEMPERATURE_GPU, ctypes.byref(temp))
        util = self.NvmlUtilization()
        lib.nvmlDeviceGetUtilizationRates(h, ctypes.byref(util))
        fan = ctypes.c_uint()
        lib.nvmlDeviceGetFanSpeed(h, ctypes.byref(fan))
        core = ctypes.c_uint()
        lib.nvmlDeviceGetClockInfo(h, self.NVML_CLOCK_GRAPHICS, ctypes.byref(core))
        mem = ctypes.c_uint()
        lib.nvmlDeviceGetClockInfo(h, self.NVML_CLOCK_MEM, ctypes.byref(mem))
        pwr = ctypes.c_uint()
        lib.nvmlDeviceGetPowerUsage(h, ctypes.byref(pwr))
        mi = self.NvmlMemory()
        lib.nvmlDeviceGetMemoryInfo(h, ctypes.byref(mi))

        return {
            "temp": temp.value,
            "load": util.gpu,
            "fan": fan.value,
            "core_clk": core.value,
            "mem_clk": mem.value,
            "power": int(pwr.value / 1000),
            "vram": round(mi.used / (1024 ** 3), 1),
        }

    @staticmethod
    def _generate_simulated_stats() -> Dict[str, Any]:
        return {
            "temp": random.randint(30, 60),
            "load": random.randint(0, 5),
            "fan": random.randint(30, 40),
            "core_clk": random.randint(210, 1800),
            "mem_clk": 810,
            "power": random.randint(10, 50),
            "vram": 0.5,
        }


# ============================================================================
# CONFIG MANAGER
# ============================================================================

class ConfigManager:
    """Gestisce config JSON con merge default + retry su save."""

    def __init__(self, config_path: Path):
        self.config_path: Path = Path(config_path)
        self._lock = threading.Lock()
        self.config: Dict[str, Any] = self._load()

    # --- IO ---

    def _load(self) -> Dict[str, Any]:
        data = safe_read_json(self.config_path, default=None)
        if isinstance(data, dict):
            # Merge: default ⊕ disk (disk wins per chiavi presenti)
            return {**DEFAULT_CONFIG, **data}
        return DEFAULT_CONFIG.copy()

    def _save_locked(self, retries: int = 3) -> bool:
        """Scrive su disco. Da chiamare SOLO con self._lock già acquisito."""
        return atomic_write_json(
            self.config_path, self.config, indent=4, retries=retries
        )

    def save(self, retries: int = 3) -> bool:
        with self._lock:
            return self._save_locked(retries)

    # --- Access (tutte le operazioni sotto lock) ---

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.config.get(key, default)

    def set(self, key: str, value: Any) -> bool:
        with self._lock:
            self.config[key] = value
            return self._save_locked()

    def update(self, mapping: Dict[str, Any]) -> bool:
        """Aggiorna più chiavi insieme con un solo save (atomico)."""
        with self._lock:
            self.config.update(mapping)
            return self._save_locked()

    def replace_config(self, new_config: Dict[str, Any]) -> bool:
        """Sostituisce l'intera config (merge con DEFAULT_CONFIG) in modo atomico."""
        with self._lock:
            self.config = {**DEFAULT_CONFIG, **new_config}
            return self._save_locked()

    # --- Associations ---

    def get_associations(self) -> Dict[str, str]:
        with self._lock:
            # Copia difensiva: il chiamante non può mutare lo stato interno
            return dict(self.config.get("associations", {}))

    def add_association(self, exe_name: str, profile_name: str) -> bool:
        with self._lock:
            assoc = dict(self.config.get("associations", {}))
            assoc[exe_name] = profile_name
            self.config["associations"] = assoc
            return self._save_locked()

    def remove_association(self, exe_name: str) -> bool:
        with self._lock:
            assoc = dict(self.config.get("associations", {}))
            if exe_name in assoc:
                del assoc[exe_name]
                self.config["associations"] = assoc
                return self._save_locked()
        return False


# ============================================================================
# PROFILE MANAGER
# ============================================================================

class ProfileManager:
    """
    Gestione directory profili con staging atomico e backup/rollback.

    Struttura:
        <msi_dir>/Profiles/
            VEN_*.cfg              ← profilo "live" caricato da MSI
            ProfilesManager/
                Default/           ← profilo di fallback (idle)
                VirginStock/       ← profili originali (mai modificati)
                <NomeUtente>/      ← profili creati dall'utente
    """

    EXCLUDED_FROM_LIST = frozenset({"Default", "VirginStock", "_staging_tmp", "_backup_tmp"})

    def __init__(
        self,
        msi_afterburner_path: str,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.msi_path = Path(msi_afterburner_path)
        self.profiles_dir = self.msi_path.parent / "Profiles"
        self.manager_root = self.profiles_dir / "ProfilesManager"
        self.default_dir = self.manager_root / "Default"
        self.virgin_dir = self.manager_root / "VirginStock"
        self._log_callback = log_callback

    # --- Log ---

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self._log_callback:
            try:
                self._log_callback(msg)
            except Exception:  # noqa: BLE001
                pass  # callback UI non deve bloccare core

    # --- Struttura ---

    def ensure_structure(self) -> bool:
        try:
            self.manager_root.mkdir(parents=True, exist_ok=True)
            self.virgin_dir.mkdir(parents=True, exist_ok=True)
            self.default_dir.mkdir(parents=True, exist_ok=True)

            if not any(self.virgin_dir.iterdir()):
                copied = self._copy_initial_profiles(self.virgin_dir)
                if copied:
                    self._log(f"VirginStock inizializzato: {copied} file")
                else:
                    self._log("ATTENZIONE: nessun .cfg trovato in Profiles")

            if not any(self.default_dir.iterdir()):
                for f in iter_managed_cfg(self.virgin_dir):
                    shutil.copy2(f, self.default_dir)
                self._log("Default inizializzato da VirginStock")

            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore struttura: {e}")
            return False

    def _copy_initial_profiles(self, target: Path) -> int:
        """Copia VEN_*.cfg + Profile1.cfg dalla cartella Profiles/ a target/.

        Politica v2.6.2: Profile1.cfg viene esplicitamente incluso perché segna
        la presenza di un profilo salvato nello slot 1 di MSI Afterburner.
        """
        if not self.profiles_dir.exists():
            return 0
        copied = 0
        has_profile1 = False
        for f in iter_managed_cfg(self.profiles_dir):
            try:
                shutil.copy2(f, target)
                copied += 1
                if f.name.lower() == "profile1.cfg":
                    has_profile1 = True
            except Exception as e:  # noqa: BLE001
                logger.debug(f"copy initial fail {f}: {e}")
        if has_profile1:
            self._log(f"Profile1.cfg incluso nel setup ({target.name})")
        return copied

    # --- Listing ---

    def list_profiles(self) -> List[str]:
        if not self.manager_root.exists():
            return []
        return sorted(
            d.name for d in self.manager_root.iterdir()
            if d.is_dir() and d.name not in self.EXCLUDED_FROM_LIST
        )

    def get_next_profile_number(self) -> int:
        nums = []
        for name in self.list_profiles():
            m = _PROFILE_NAME_RE.match(name)
            if m:
                nums.append(int(m.group(1)))
        return (max(nums) + 1) if nums else 1

    def profile_exists(self, name: str) -> bool:
        return (self.manager_root / name).exists()

    # --- CRUD ---

    def create_profile(self, name: str) -> bool:
        try:
            p = self.manager_root / name
            p.mkdir(parents=True, exist_ok=True)
            # v2.6.2: copia da VirginStock TUTTI i file gestiti (VEN_*.cfg + Profile1.cfg).
            # Profile1.cfg segna che lo slot 1 di MSI ha un profilo salvato.
            had_profile1 = False
            had_ven = 0
            for f in iter_managed_cfg(self.virgin_dir):
                shutil.copy2(f, p)
                if f.name.lower() == "profile1.cfg":
                    had_profile1 = True
                else:
                    had_ven += 1
            extras = " + Profile1.cfg" if had_profile1 else ""
            self._log(f"Profilo creato: {name} ({had_ven} VEN_*.cfg{extras})")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore creazione profilo {name}: {e}")
            return False

    def delete_profile(self, name: str) -> bool:
        try:
            p = self.manager_root / name
            if p.exists():
                shutil.rmtree(p)
                self._log(f"Profilo eliminato: {name}")
                return True
            return False
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore eliminazione profilo {name}: {e}")
            return False

    def rename_profile(self, old: str, new: str) -> bool:
        try:
            op, np = self.manager_root / old, self.manager_root / new
            if op.exists() and not np.exists():
                op.rename(np)
                self._log(f"Profilo rinominato: {old} → {new}")
                return True
            return False
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore rinomina: {e}")
            return False

    def duplicate_profile(self, source: str, dest: str) -> bool:
        """Copia SOLO i .cfg gestiti (VEN_*.cfg + ProfileN.cfg) da source a dest."""
        try:
            src_dir = self.get_profile_dir(source)
            dst_dir = self.manager_root / dest
            if not src_dir.exists():
                self._log(f"Sorgente non esistente: {source}")
                return False
            if dst_dir.exists():
                self._log(f"Destinazione esistente: {dest}")
                return False
            dst_dir.mkdir(parents=True, exist_ok=True)
            for f in iter_managed_cfg(src_dir):
                shutil.copy2(f, dst_dir)
            self._log(f"Profilo duplicato: {source} → {dest}")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore duplicazione profilo: {e}")
            return False

    def set_as_default(self, profile_name: str) -> bool:
        src = self.manager_root / profile_name
        if not src.exists():
            return False
        try:
            for f in iter_managed_cfg(self.default_dir):
                f.unlink()
            for f in iter_managed_cfg(src):
                shutil.copy2(f, self.default_dir)
            self._log(f"Default aggiornato a: {profile_name}")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore set default: {e}")
            return False

    def reset_default_to_virgin(self) -> bool:
        try:
            for f in iter_managed_cfg(self.default_dir):
                f.unlink()
            for f in iter_managed_cfg(self.virgin_dir):
                shutil.copy2(f, self.default_dir)
            self._log("Default ripristinato a VirginStock")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore reset default: {e}")
            return False

    # --- Apply: staging + backup + rollback ---

    @contextmanager
    def _staging_context(self):
        """Context manager per staging dir; cleanup garantito."""
        staging = self.profiles_dir / "_staging_tmp"
        safe_rmtree(staging)
        try:
            staging.mkdir(parents=True)
            yield staging
        finally:
            safe_rmtree(staging)

    def _backup_current_profiles(self) -> Optional[Path]:
        """Crea backup dei .cfg gestiti (VEN_*.cfg + ProfileN.cfg) presenti in Profiles/."""
        backup_dir = self.profiles_dir / "_backup_tmp"
        safe_rmtree(backup_dir)
        try:
            backup_dir.mkdir(parents=True)
            for f in iter_managed_cfg(self.profiles_dir):
                shutil.copy2(f, backup_dir)
            return backup_dir
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore creazione backup: {e}")
            safe_rmtree(backup_dir)
            return None

    def _restore_from_backup(self, backup_dir: Path) -> bool:
        try:
            if not backup_dir or not backup_dir.exists():
                return False
            for f in iter_managed_cfg(self.profiles_dir):
                try:
                    f.unlink()
                except Exception:  # noqa: BLE001
                    pass
            for f in iter_managed_cfg(backup_dir):
                shutil.copy2(f, self.profiles_dir)
            self._log("Rollback completato: profili ripristinati dal backup")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"CRITICO: rollback fallito: {e}")
            return False

    def _validate_staged_files(self, staging: Path, expected: int) -> bool:
        staged = list(iter_managed_cfg(staging))
        if len(staged) != expected:
            self._log(f"Validazione fallita: attesi {expected}, trovati {len(staged)}")
            return False
        for f in staged:
            try:
                if f.stat().st_size == 0:
                    self._log(f"Validazione fallita: {f.name} è vuoto")
                    return False
            except OSError:
                self._log(f"Validazione fallita: stat fallito su {f.name}")
                return False
        return True

    def _swap_profiles(self, staging: Path) -> None:
        """Sostituisce SOLO i .cfg gestiti in Profiles/ con quelli dallo staging."""
        for f in iter_managed_cfg(self.profiles_dir):
            f.unlink()
        for f in iter_managed_cfg(staging):
            shutil.move(str(f), str(self.profiles_dir / f.name))

    def _trigger_msi_profile_load(self) -> bool:
        """Avvia MSI Afterburner con flag -Profile1 per caricare il profilo."""
        if not self.msi_path.exists():
            return False
        try:
            popen_hidden(
                [str(self.msi_path), "-Profile1"],
                cwd=str(self.msi_path.parent),
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore lancio MSI: {e}")
            return False

    def apply_profile(self, profile_name: str) -> bool:
        """
        Applica un profilo con flow:
        1. Copia file sorgente in staging
        2. Valida staging (count + size > 0)
        3. Backup profili correnti
        4. Swap atomico
        5. Cleanup backup
        6. Lancia MSI Afterburner per caricare Profile1
        7. Rollback su errore.
        """
        src = self.default_dir if profile_name == "Default" else self.manager_root / profile_name
        if not src.exists():
            self._log(f"Profilo non trovato: {profile_name}")
            return False

        backup_dir: Optional[Path] = None
        try:
            with self._staging_context() as staging:
                src_files = list(iter_managed_cfg(src))
                if not src_files:
                    self._log(f"Nessun .cfg gestito in: {profile_name}")
                    return False

                for f in src_files:
                    shutil.copy2(f, staging)

                if not self._validate_staged_files(staging, len(src_files)):
                    return False

                backup_dir = self._backup_current_profiles()
                if backup_dir is None:
                    self._log("Impossibile creare backup, apply annullato")
                    return False

                try:
                    self._swap_profiles(staging)
                except Exception as swap_err:  # noqa: BLE001
                    logger.error(f"Errore durante swap: {swap_err}")
                    self._restore_from_backup(backup_dir)
                    return False

            # Cleanup backup su successo
            safe_rmtree(backup_dir)
            backup_dir = None

            time.sleep(TIMING["profile_apply_delay"])

            if self._trigger_msi_profile_load():
                self._log(f"Profilo applicato: {profile_name}")
                return True

            self._log("MSI Afterburner non trovato, profilo copiato ma non caricato")
            return False

        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore apply profilo: {e}")
            if backup_dir:
                self._restore_from_backup(backup_dir)
                safe_rmtree(backup_dir)
            return False

    # --- Save da MSI / utility ---

    def save_profile_from_msi(self, profile_name: str) -> bool:
        try:
            dest = self.manager_root / profile_name
            dest.mkdir(parents=True, exist_ok=True)
            for f in iter_managed_cfg(self.profiles_dir):
                shutil.copy2(f, dest)
            self._log(f"Profilo salvato: {profile_name}")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore salvataggio profilo: {e}")
            return False

    def validate_slot1_exists(self) -> bool:
        p = self.profiles_dir / "Profile1.cfg"
        try:
            return p.exists() and p.stat().st_size > 0
        except OSError:
            return False

    def get_profile_dir(self, name: str) -> Path:
        if name == "Default":
            return self.default_dir
        if name == "VirginStock":
            return self.virgin_dir
        return self.manager_root / name


# ============================================================================
# MSI AFTERBURNER CONTROLLER
# ============================================================================

class MSIAfterburnerController:
    """Wrapper per ciclo di vita MSI Afterburner."""

    STARTUP_TIMEOUT: float = 15.0
    POLL_INTERVAL: float = 0.5
    PROCESS_NAME: str = "msiafterburner.exe"

    def __init__(self, msi_path: str):
        self.msi_path = Path(msi_path)

    def is_running(self) -> bool:
        # Riusa lo snapshot TTL condiviso: zero scan psutil aggiuntivi
        # quando il monitor processi ha già scansionato in questo secondo.
        try:
            return self.PROCESS_NAME in snapshot_running_exes()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"is_running error: {e}")
            return False

    def start(self, show_window: bool = False) -> bool:
        if not self.msi_path.exists():
            return False
        try:
            args = [str(self.msi_path)]
            if show_window:
                args.append("-s")
                # DETACHED_PROCESS: MSI mostra la sua finestra
                popen_detached(args)
            else:
                popen_hidden(args)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore avvio MSI: {e}")
            return False

    def kill(self) -> bool:
        try:
            r = run_hidden(["taskkill", "/F", "/IM", "MSIAfterburner.exe"])
            return r.returncode == 0
        except Exception as e:  # noqa: BLE001
            logger.debug(f"kill error: {e}")
            return False

    def ensure_running(self, timeout: Optional[float] = None) -> bool:
        """Assicura MSI in esecuzione; ritorna True quando il processo è up."""
        if timeout is None:
            timeout = self.STARTUP_TIMEOUT
        if self.is_running():
            return True
        if not self.start():
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(self.POLL_INTERVAL)
            if self.is_running():
                return True
        return False

    def wait_for_shutdown(self, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_running():
                return True
            time.sleep(0.25)
        return not self.is_running()


# ============================================================================
# PROCESS MONITOR LOGIC — state machine thread-safe
# ============================================================================

class ProcessMonitorLogic:
    """
    State machine che mappa processi attivi → profilo da applicare.

    Modalità (config['process_match_mode']):
    - first_match       : primo exe associato trovato
    - stable_no_switch  : non cambia profilo se l'ultimo matched è ancora attivo
    - priority_list     : usa l'ordine in config['process_priority']
    """

    MODE_FIRST_MATCH = "first_match"
    MODE_STABLE_NO_SWITCH = "stable_no_switch"
    MODE_PRIORITY_LIST = "priority_list"

    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self._lock = threading.Lock()
        self.current_profile: str = "Default"
        self._pending_default: bool = False
        self._cooldown_start: float = 0.0
        self._last_matched_exe: str = ""
        self._had_active_app: bool = False
        self._editing_paused: bool = False
        self._user_paused: bool = False  # pausa esplicita dall'utente
        # Config prefetch (aggiornati una volta per tick in check_processes)
        self._cfg_mode: str = self.MODE_FIRST_MATCH
        self._cfg_priority: List[str] = []

    # --- Pause control ---

    def pause_monitoring(self) -> None:
        """Pausa interna usata durante editing."""
        with self._lock:
            self._editing_paused = True
            self._pending_default = False
        logger.info("[MONITOR] Pausa (edit)")

    def resume_monitoring(self) -> None:
        with self._lock:
            self._editing_paused = False
            self._pending_default = False
            self._cooldown_start = time.time()
        logger.info("[MONITOR] Ripreso")

    def set_user_paused(self, paused: bool) -> None:
        """Pausa esplicita dell'utente (toggle da UI)."""
        with self._lock:
            self._user_paused = paused
            if paused:
                self._pending_default = False
        logger.info(f"[MONITOR] User-paused={paused}")

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._editing_paused or self._user_paused

    # --- State management ---

    def set_current_profile(self, profile_name: str) -> None:
        with self._lock:
            self.current_profile = profile_name
            if profile_name != "Default":
                self._had_active_app = True

    def is_associated_app_running(self) -> bool:
        """
        Verifica in tempo reale se almeno un processo associato è attivo.
        Snapshot fatto SENZA tenere il lock (psutil può essere lento).
        """
        associations = self.config.get_associations()
        if not associations:
            return False
        try:
            active = snapshot_running_exes()
            return any(exe.lower() in active for exe in associations)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Errore check associazione attiva: {e}")
            return False

    # --- Main check ---

    def check_processes(self) -> Optional[Tuple[str, str]]:
        """
        Esegue un passaggio della state machine.

        Returns:
            (profile_to_apply, exe_matched) se serve un cambio,
            None altrimenti.
        """
        # Read snapshot OUT of the lock (potential I/O)
        if self.is_paused:
            return None

        associations = self.config.get_associations()
        active_exes: Set[str] = snapshot_running_exes() if associations else set()

        # Prefetch config una volta per tick (evita get() ripetuti sotto lock)
        self._cfg_mode = self.config.get(
            "process_match_mode", self.MODE_FIRST_MATCH)
        self._cfg_priority = self.config.get("process_priority", []) or []

        # Mutate state UNDER lock
        with self._lock:
            if self._editing_paused or self._user_paused:
                return None
            try:
                return self._evaluate_locked(associations, active_exes)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Check processi: {e}")
                return None

    def _evaluate_locked(
        self,
        associations: Dict[str, str],
        active: Set[str],
    ) -> Optional[Tuple[str, str]]:
        if not associations:
            return self._handle_no_associations()

        found = self._find_matching_exe(associations, active)
        if found:
            return self._handle_match_found(found, associations)
        return self._handle_no_match()

    def _handle_no_associations(self) -> Optional[Tuple[str, str]]:
        if self._had_active_app and self.current_profile != "Default":
            self._had_active_app = False
            self.current_profile = "Default"
            return ("Default", "")
        return None

    def _handle_match_found(
        self, found_exe: str, assoc: Dict[str, str]
    ) -> Optional[Tuple[str, str]]:
        self._pending_default = False
        self._had_active_app = True
        target = assoc.get(found_exe, "Default")
        if self.current_profile != target:
            self.current_profile = target
            self._last_matched_exe = found_exe
            return (target, found_exe)
        # nessun cambio ma teniamo memoria dell'exe (utile per stable mode)
        self._last_matched_exe = found_exe
        return None

    def _handle_no_match(self) -> Optional[Tuple[str, str]]:
        if not (self._had_active_app or self.current_profile != "Default"):
            return None
        if not self._pending_default:
            self._pending_default = True
            self._cooldown_start = time.time()
            return None
        elapsed = time.time() - self._cooldown_start
        if elapsed > TIMING["profile_cooldown"]:
            self._pending_default = False
            self._had_active_app = False
            self._last_matched_exe = ""
            self.current_profile = "Default"
            return ("Default", "")
        return None

    def _find_matching_exe(self, assoc: Dict[str, str], active: Set[str]) -> str:
        mode = self._cfg_mode
        priority: List[str] = self._cfg_priority
        matched = [exe for exe in assoc if exe.lower() in active]
        if not matched:
            return ""

        if mode == self.MODE_STABLE_NO_SWITCH:
            if (
                self._last_matched_exe
                and self._last_matched_exe.lower() in active
                and self._last_matched_exe in assoc
            ):
                return self._last_matched_exe
            return matched[0]

        if mode == self.MODE_PRIORITY_LIST and priority:
            for pe in priority:
                if pe in matched:
                    return pe
            return matched[0]

        return matched[0]
