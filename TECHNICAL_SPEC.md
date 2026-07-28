# OC Profiles Manager — Specifica Tecnica Completa (v2.6.3)

> Questo documento è la **specifica di riferimento** dell'applicazione.
> Descrive architettura, ogni modulo, ogni classe/funzione, i formati file,
> gli algoritmi e le formule (in particolare quelle del **VF Editor**) con
> un livello di dettaglio sufficiente a **ricreare il programma in modo
> identico** partendo da zero.

---

## 1. Panoramica

**OC Profiles Manager** è un'applicazione desktop **Windows** (Python 3.10+,
PySide6) che gestisce profili di overclocking per **MSI Afterburner**:

- Libreria di profili (creazione, duplicazione, rinomina, eliminazione,
  import/export) salvati come cartelle di file `.cfg` di MSI Afterburner.
- **Apply** di un profilo con staging atomico, backup e rollback, seguito
  dal lancio di `MSIAfterburner.exe -Profile1`.
- **Automazione**: cambio profilo automatico in base ai processi in
  esecuzione (3 modalità di matching).
- **Telemetria GPU** in tempo reale via NVML (ctypes) con fallback simulato.
- **CFG Editor** integrato: editing grafico della **V/F Curve** (curva
  tensione/frequenza) con algoritmo di smoothing identico a quello di
  MSI Afterburner ("AB-like").
- **History** dell'uso dei profili con statistiche e export CSV.
- **Theme system** modulare: l'intera UI è fornita da un tema caricato a
  runtime (`themes/<id>/`), il core non conosce Qt widgets.

### 1.1 Stack tecnologico

| Componente | Tecnologia |
|---|---|
| Linguaggio | Python 3.10+ (testato 3.12/3.13) |
| GUI | PySide6 (Qt 6) |
| Grafico V/F | pyqtgraph |
| Monitor processi | psutil |
| Telemetria GPU | NVML via `ctypes.CDLL("nvml.dll")` |
| Suoni | `winsound.Beep` (solo Windows) |
| Autostart | Registro `HKCU\...\CurrentVersion\Run` (winreg) |
| Privilegi | UAC elevation via `ShellExecuteW(..., "runas", ...)` |

`requirements.txt`: `PySide6`, `pyqtgraph`, `psutil`.

### 1.2 Struttura del progetto

```
oc_profiles_manager/
├── main.py                      # Entry point (logging, UAC, wizard, theme launch)
├── constants.py                 # Config default, timing, suoni, validazione nomi
├── oc_core.py                   # GPUMonitor, ConfigManager, ProfileManager,
│                                #   MSIAfterburnerController, ProcessMonitorLogic
├── oc_controller.py             # ProfileController (facade core ↔ UI)
├── oc_history.py                # ProfileHistory (persistenza + statistiche)
├── oc_utils.py                  # Atomic I/O, subprocess helpers, registry, psutil
├── profile_info_extractor.py    # Estrazione dati profilo per card view (cache)
├── cfg_editor/
│   ├── cfg_model.py             # Parser/writer file .cfg di Afterburner
│   ├── vfcurve.py               # Decode/encode VFCurve + algoritmo AB-like
│   └── editor_widget.py         # VFEditorWidget (pyqtgraph, drag, undo/redo)
├── themes/
│   ├── __init__.py              # ThemeRegistry (discovery)
│   ├── base.py                  # AppContext, ThemeDescriptor, IThemeMainWindow
│   └── red_glossy/              # Tema di default
│       ├── __init__.py          # get_descriptor()
│       ├── style.py             # THEME (palette) + STYLESHEET (Qt CSS)
│       ├── widgets.py           # Gauge, card, dialog, SetupWizard
│       └── main_window.py       # OCProfilesManager (QMainWindow), thread, tray
└── widgets_common/              # Widget riusabili tra temi
```

### 1.3 Struttura su disco a runtime (accanto a MSIAfterburner.exe)

```
<dir di MSIAfterburner.exe>/
└── Profiles/                        ← cartella profili "live" letta da MSI AB
    ├── VEN_10DE&DEV_...cfg          ← file hardware caricato da Afterburner
    └── ProfilesManager/             ← radice gestita dall'app
        ├── Default/                 ← profilo di fallback (idle / nessun match)
        ├── VirginStock/             ← copia originale dei cfg, MAI modificata
        ├── <NomeProfiloUtente>/     ← un dir per profilo utente
        ├── _staging_tmp/            ← temporanea durante apply (poi rimossa)
        └── _backup_tmp/             ← backup durante apply (poi rimossa)
```

File runtime nella cartella dell'app (esclusi da git):
`oc_manager.log` (RotatingFileHandler 2 MB × 3), `oc_manager_data.json`
(config), `oc_profile_history.json` (history).

---

## 2. `constants.py`

### 2.1 Info app
```python
APP_NAME = "OCProfilesManager"
APP_VERSION = "2.6.3"
BASE_DIR = Path(__file__).parent
```

### 2.2 `DEFAULT_CONFIG`
```python
{
    "msi_path": r"C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe",
    "associations": {},            # {exe_name_lower: profile_name}
    "startup_min": False,          # avvio minimizzato in tray
    "sounds": True,
    "default_alias": "VirginStock",# profilo che "Default" replica
    "process_match_mode": "first_match",  # | "stable_no_switch" | "priority_list"
    "process_priority": [],        # ordine profili per modalità priority_list
    "profile_icons": {},           # {profile: {"key": preset, "custom": path}}
    "gpu_pause_when_hidden": True,
    "show_tray_notifications": True,
    "log_level": "INFO",
    "ui_theme": "red_glossy",      # id tema attivo (cartella in themes/)
}
```

### 2.3 `TIMING`
```python
{
    "process_check_interval": 2000,  # ms — polling monitor processi
    "gpu_update_interval": 1000,     # ms — refresh telemetria GPU
    "msi_status_interval": 5000,     # ms — check "MSI AB in esecuzione?"
    "profile_cooldown": 5,           # s  — attesa prima del ritorno a Default
    "msi_startup_delay": 3.0,        # s  — attesa avvio MSI AB
    "profile_apply_delay": 1.0,      # s  — pausa dopo swap file, prima del lancio
    "toast_duration": 4000,          # ms
    "history_save_debounce": 500,    # ms (riservato)
}
```

### 2.4 `SOUND_CONFIG` (beep winsound)
| preset | frequenza Hz | durata ms | uso |
|---|---|---|---|
| `apply` | 800 | 150 | profilo applicato |
| `default` | 400 | 250 | ritorno a Default |
| `error` | 220 | 300 | errore |
| `info` | 1000 | 80 | notifica generica |

### 2.5 Validazione nomi profilo — `sanitize_profile_name(name) -> Optional[str]`

Regole in ordine (ritorna `None` se invalido):
1. `name.strip()`; vuoto o `len > MAX_PROFILE_NAME_LENGTH (100)` → `None`.
2. Se contiene uno di `<>:"/\|?*` (regex `[<>:"/\\|?*]`) → `None`.
3. **`rstrip(". ")` PRIMA dei check riservati** (così `"CON."` non bypassa
   la blacklist); se il risultato è vuoto → `None`.
4. Se `name.upper()` ∈ nomi riservati Windows
   `{CON, PRN, AUX, NUL, COM1..COM9, LPT1..LPT9}` → `None`.
5. Se `name` ∈ nomi riservati app
   `{"Default", "VirginStock", "_staging_tmp", "_backup_tmp"}` → `None`.
6. Altrimenti ritorna il nome pulito.

### 2.6 Icone preset — `PROFILE_PRESET_ICONS`
13 preset, ognuno `{glyph, label, color}` con glifi **Segoe MDL2 Assets**
(es. `gaming`: `\uE7FC` #ff2e2e, `performance`: `\uE945` #ff6600,
`balanced`: `\uE81E`, `silent`: `\uE992`, `mining`: `\uE939`,
`streaming`: `\uE714`, `desktop`: `\uE770`, `benchmark`: `\uE9D9`,
`rendering`: `\uE8B1`, `undervolt`: `\uE83F`, ecc.).

Card view: `CARD_MIN_WIDTH=280`, `CARD_MAX_WIDTH=340`, `CARD_HEIGHT=195`.

---

## 3. `oc_utils.py` — Utility

### 3.1 Subprocess (Windows-safe)
```python
CREATE_NO_WINDOW  = 0x08000000
DETACHED_PROCESS  = 0x00000008
_IS_WINDOWS = os.name == "nt"
```
- `run_hidden(args, **kw)` → `subprocess.run` con
  `creationflags=CREATE_NO_WINDOW` (solo su Windows) e
  `capture_output=True` di default. Usato per `taskkill` ecc.
- `popen_hidden(args, **kw)` → `Popen` nascosto (avvio MSI AB in tray).
- `popen_detached(args, **kw)` → `Popen` con `DETACHED_PROCESS`
  (avvio MSI AB **con** finestra visibile).
- Su POSIX i flag NON vengono impostati (altrimenti `ValueError`).

### 3.2 File I/O atomico
- `atomic_write_json(path, data, *, indent=2, retries=3, retry_delay=0.1)`:
  scrive su `path.with_suffix(".tmp")` poi `os.replace(tmp, path)`
  (rename atomico). Su `PermissionError` ritenta fino a 3 volte con sleep.
  Ritorna `bool`.
- `safe_read_json(path, default=None)`: lettura tollerante
  (file mancante/corrotto → `default`).
- `safe_rmtree(path)`: `shutil.rmtree(..., ignore_errors=True)` con guard.

### 3.3 Formattazione tempo
- `format_duration(seconds)` → `"2h 15m"`, `"45m"`, `"30s"`.
- `format_duration_short(seconds)` → forma compatta per label.

### 3.4 Processi & registry
- `snapshot_running_exes() -> Set[str]`: set lower-case dei nomi exe da
  `psutil.process_iter(["name"])` (con try/except per processi zombie).
- `set_autostart_registry(enabled, app_name, command)` /
  `check_autostart_registry(app_name)`: chiave
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
- `open_in_explorer(path)`: apre Explorer sulla cartella.

---

## 4. `oc_core.py` — Business logic

### 4.1 Riconoscimento file cfg gestiti
```python
def is_managed_cfg(filename) -> bool:
    # True se: match regex r"^VEN_.*\.cfg$" (case-insensitive)
    #          oppure filename.lower() == "profile1.cfg"

def is_effective_cfg_path(path) -> bool:
    # True se is_managed_cfg(nome) AND dimensione file > 200 byte
    # (filtra i cfg placeholder vuoti creati da Afterburner)

def iter_managed_cfg(directory):  # yield dei path validi, ordinati
```

### 4.2 `SoundPlayer`
- `play(preset)`: `winsound.Beep(freq, dur)` dal `SOUND_CONFIG`; no-op se
  `winsound is None` (non-Windows).
- `play_async(preset)`: beep in `threading.Thread(daemon=True)`.

### 4.3 `GPUMonitor` (singleton)
- `__new__` implementa il singleton (`cls._instance`); `_init_once()` esegue
  l'inizializzazione una sola volta.
- `_try_init_nvml()`: carica NVML via ctypes provando in ordine:
  `nvml.dll` (PATH), `C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll`,
  `%SystemRoot%\System32\nvml.dll`. Poi `nvmlInit_v2()` e
  `nvmlDeviceGetHandleByIndex_v2(0)`.
- `_configure_nvml_signatures(lib)`: imposta `argtypes/restype` per le
  funzioni usate: temperatura (`nvmlDeviceGetTemperature`, sensore 0),
  utilizzo (`nvmlDeviceGetUtilizationRates` → struct `{gpu, memory}` c_uint),
  memoria (`nvmlDeviceGetMemoryInfo` → struct `{total, free, used}`
  c_ulonglong), clock, power (`nvmlDeviceGetPowerUsage`, milliwatt),
  fan speed.
- `get_stats() -> Dict`: se NVML ok → `_read_nvml_stats()`; altrimenti
  `_generate_simulated_stats()` (valori random plausibili: temp 40–75 °C,
  load 0–100 %, ecc.) così l'UI funziona anche senza GPU NVIDIA.
- `is_real_hardware` (property), `shutdown()` → `nvmlShutdown()`.

### 4.4 `ConfigManager` — thread-safe
Persistenza su `oc_manager_data.json`. **Tutte** le operazioni avvengono
sotto `threading.Lock`:

```python
_load()            # safe_read_json + merge {**DEFAULT_CONFIG, **disk}
_save_locked()     # atomic_write_json(indent=4, retries) — lock GIÀ preso
save()             # lock + _save_locked
get(key, default)  # lettura sotto lock
set(key, value)    # scrittura + save atomici
update(mapping)    # più chiavi con UN solo save (atomico)
replace_config(nc) # config = {**DEFAULT_CONFIG, **nc} + save (import config)
get_associations() # ritorna dict() COPIA DIFENSIVA
add_association(exe, profile) / remove_association(exe)
```
Regola architetturale: **nessun accesso diretto a `config.config[...]` da
fuori**; i chiamanti usano solo l'API pubblica.

### 4.5 `ProfileManager` — profili su disco con staging/backup/rollback

Costruttore: da `msi_afterburner_path` deriva
`profiles_dir = parent/"Profiles"`, `manager_root = profiles_dir/"ProfilesManager"`,
`default_dir = manager_root/"Default"`, `virgin_dir = manager_root/"VirginStock"`.

- `ensure_structure()`: crea le directory; al primo avvio copia i cfg live
  in `VirginStock/` e `Default/` (`_copy_initial_profiles`).
- `list_profiles()`: sottodirectory di `manager_root` escluse
  `EXCLUDED_FROM_LIST = {Default, VirginStock, _staging_tmp, _backup_tmp}`,
  ordinate case-insensitive.
- `create_profile(name)`: crea dir e vi copia i cfg live correnti.
- `delete_profile` / `rename_profile` / `duplicate_profile`: operazioni
  su directory con validazioni (esistenza, collisioni).
- `set_as_default(profile)`: copia i cfg del profilo in `Default/`.
- `reset_default_to_virgin()`: `Default/` ← copia di `VirginStock/`.

**`apply_profile(profile_name)` — sequenza atomica:**
1. `_staging_context()` (contextmanager): crea `_staging_tmp/`, garantisce
   cleanup nel `finally`.
2. Copia i cfg del profilo in staging.
3. `_validate_staged_files(staging, expected)`: conteggio + dimensioni > 200 B.
4. `_backup_current_profiles()`: sposta i cfg live in `_backup_tmp/`.
5. `_swap_profiles(staging)`: sposta i file staged in `Profiles/`.
6. Cleanup backup, `time.sleep(TIMING["profile_apply_delay"])` (1.0 s).
7. `_trigger_msi_profile_load()`: lancia
   `popen_hidden([msi_exe, "-Profile1"])` per far ricaricare il profilo
   dallo SLOT 1.
8. Su qualunque errore: `_restore_from_backup(backup_dir)` (rollback
   completo) e ritorna `False`.

- `save_profile_from_msi(profile_name)`: copia i cfg live correnti
  (modificati dall'utente in MSI AB) dentro la dir del profilo — usato al
  termine dell'editing.
- `validate_slot1_exists()`: verifica che il cfg live contenga `[Profile1]`.

### 4.6 `MSIAfterburnerController`
```python
PROCESS_NAME = "msiafterburner.exe"
STARTUP_TIMEOUT = 15.0  # s
```
- `is_running()`: scan psutil per nome processo (case-insensitive).
- `start(show_window=False)`: `popen_detached([exe, "-s"])` se visibile,
  altrimenti `popen_hidden([exe])`.
- `kill()`: `run_hidden(["taskkill", "/F", "/IM", PROCESS_NAME])`.
- `ensure_running(timeout)`: se non attivo → `start()` + poll fino a
  timeout (default `STARTUP_TIMEOUT`), con
  `time.sleep(TIMING["msi_startup_delay"])` iniziale.
- `wait_for_shutdown(timeout=5.0)`: poll fino a chiusura.

### 4.7 `ProcessMonitorLogic` — macchina a stati dell'automazione

Stato interno (sotto `threading.Lock`): `current_profile`,
`_pending_default: Optional[float]` (timestamp), `editing_paused: bool`,
`user_paused: bool`.

- `pause_monitoring()` / `resume_monitoring()`: flag `editing_paused`
  (usati durante l'editing cfg per non switchare profilo).
- `set_user_paused(bool)`: pausa manuale dall'UI. `is_paused()` = OR dei due.
- `check_processes() -> Optional[Tuple[new_profile, exe_name]]`:
  chiamato ogni `process_check_interval` (2 s) dal thread UI. Se in pausa
  → `None`. Altrimenti `snapshot_running_exes()` + `_evaluate_locked()`:

  1. **Nessuna associazione** configurata → `_handle_no_associations()`:
     se `current_profile != "Default"` → switch a Default (con cooldown).
  2. **Match trovato** (`_find_matching_exe`):
     - `first_match`: primo exe associato trovato nel set attivo.
     - `stable_no_switch`: come first_match, ma se il profilo corrente ha
       ancora la sua app attiva NON si cambia (evita ping-pong con due
       giochi aperti).
     - `priority_list`: tra gli exe attivi associati vince quello il cui
       profilo compare prima in `config["process_priority"]`.
     → `_handle_match_found`: annulla `_pending_default`; se il profilo
     è diverso dal corrente ritorna `(profilo, exe)`.
  3. **Nessun match** → `_handle_no_match()` con **cooldown a 2 fasi**:
     la prima volta imposta `_pending_default = time.time()`; ai check
     successivi, se sono passati `>= TIMING["profile_cooldown"]` (5 s)
     e ancora nessun match → ritorna `("Default", "")`. Se nel frattempo
     ricompare un match, il pending viene annullato.

---

## 5. `oc_controller.py` — `ProfileController` (facade)

Aggrega `ConfigManager`, `ProfileManager`, `MSIAfterburnerController`,
`ProcessMonitorLogic`, `ProfileHistory`, `SoundPlayer`. L'UI parla SOLO
con questo layer.

### 5.1 Ciclo di vita e apply
- `apply_profile_blocking(name) -> bool`: `msi.ensure_running()` →
  `profiles.apply_profile(name)` → aggiorna `current_profile`,
  `process_logic.set_current_profile(name)`,
  `history.record_switch(name, exe)`. Eseguito in un QThread dall'UI.
- `shutdown()`: `history.close_session()` + `gpu.shutdown()`.

### 5.2 CRUD profili
- `create_profile(raw)` / `duplicate_profile(src, raw)` /
  `rename_profile(old, raw)` → `Tuple[bool, str]` (nome pulito o errore);
  tutti passano da `sanitize_profile_name`.
- `delete_profile(name)`: elimina la dir, poi **un solo**
  `config.update(changes)` atomico che pulisce insieme `associations`,
  `profile_icons`, `process_priority`.
- `rename_profile`: analogo — aggiorna in un solo update atomico
  `associations`, `default_alias`, `profile_icons`; se rinomini il profilo
  attivo aggiorna anche lo stato del monitor.
- `get_display_name(name)`: `"Default"` → `f"Default ({default_alias})"`.
- Icone: `set_profile_icon(name, icon_key, custom_path)` /
  `get_profile_icon` (usa `config.set`, mai accesso diretto).

### 5.3 Workflow di editing (MSI Afterburner diretto)
- `start_editing(profile)`: `process_logic.pause_monitoring()` + apply del
  profilo + `msi.start(show_window=True)` — l'utente regola in MSI AB.
- `finish_editing(profile)`: `profiles.save_profile_from_msi(profile)`
  (salva i cfg live nella dir del profilo) + `msi.kill()`.
- `resume_after_edit()`: riavvia MSI nascosto + `resume_monitoring()`.
- `cancel_editing()`: kill MSI + resume senza salvare.

### 5.4 Accesso ai cfg per l'editor
- `get_cfg_files_for_profile(name) -> List[Path]`: cfg gestiti
  (`is_effective_cfg_path`) nella dir del profilo, ordinati.
- `get_first_cfg_for_profile` / `get_profile1_for_profile`.

### 5.5 Export / Import profilo (JSON)
```jsonc
{
  "meta": { "app": "OCProfilesManager", "version": "2.6.3",
            "exported": "<ISO datetime>", "profile_name": "<nome>" },
  "icon": { "key": "<preset>", "custom": "<path>" },
  "files": { "VEN_....cfg": "<contenuto testo completo>" }
}
```
`import_profile(src, target_name)`: sanitizza il nome, rifiuta nomi file
non-managed (`is_managed_cfg`), scrive i file e (se presente) l'icona.

### 5.6 History & suoni (delega)
`get_usage_stats(days)`, `get_daily_breakdown`, `get_summary_stats`,
`export_history_csv`; `play_sound(preset, force)` rispetta
`config["sounds"]`; `set_monitoring_paused` / `is_monitoring_paused`.

---

## 6. `oc_history.py` — History dei profili

- `ProfileHistoryEntry` (`__slots__`): `profile`, `timestamp` (ISO string),
  `exe`, `duration_sec` (0 = sessione ancora aperta).
- `ProfileHistory(path, max_days=30)` — persistenza JSON, lock interno:
  - `record_switch(profile, exe)`: chiude l'entry precedente (calcola
    `duration_sec = now - timestamp`) e appende la nuova; save atomico.
  - `close_session()`: chiude l'ultima entry all'uscita dell'app.
  - `_prune_old()`: retention 30 giorni con confronto su stringhe ISO
    (`cutoff = (now - timedelta(days=30)).isoformat()`).
  - `get_usage_last_n_days(days)` → `{profile: ore}`.
  - `get_daily_breakdown(days)` → `{"YYYY-MM-DD": {profile: ore}}`.
  - `get_summary_stats(days)` → `total_hours`, `switch_count`,
    `avg_session_minutes`, `top_profile` (+ ore).
  - `export_csv(path)`: colonne `timestamp,profile,exe,duration_sec`.

---

## 7. `profile_info_extractor.py` — Dati per le card

- `ProfileCardInfo` (dataclass): `core_clock_boost`/`mem_clock_boost` (MHz),
  `core_voltage_boost`, `power_limit`, `thermal_limit`, `fan_mode`,
  `fan_speed`, e statistiche VF: `peak_frequency`, `peak_voltage`,
  `min_voltage`, `freq_at_1000mv`, `curve_is_modified`.
- `ProfileInfoExtractor` con cache thread-safe (`RLock`):
  - chiave di invalidazione `_dir_signature(dir) = (somma mtime, count)`
    dei cfg gestiti > 200 B — se cambia, si rilegge.
  - legge SOLO il **primo** `VEN_*.cfg` ordinato del profilo.
  - Analisi VF: frequenza effettiva = `f_mhz + c_delta`;
    `curve_is_modified = any(|c_delta| > 0.1)`;
    `freq_at_1000mv` = frequenza del punto con `v_mv` più vicino a 1000.

---

## 8. `cfg_editor/` — CFG Editor e V/F Curve ⭐

### 8.1 Formato file `.cfg` di MSI Afterburner (`cfg_model.py`)

File INI (encoding UTF-8, fallback cp1252, newline `\r\n`) con sezioni
`[Startup]`, `[Profile1]`…`[Profile5]`. Parsing con
`configparser(interpolation=None)` e `optionxform=str` (chiavi
case-sensitive).

**Chiavi per profilo** (dataclass `AfterburnerProfile`):

| Chiave cfg | Campo | Unità / note |
|---|---|---|
| `CoreClkBoost` | `core_clk_boost` | **millesimi di MHz**: `225000` = +225 MHz |
| `MemClkBoost` | `mem_clk_boost` | millesimi di MHz |
| `CoreVoltageBoost` | `core_voltage_boost` | µV/percent (raw) |
| `PowerLimit` | `power_limit` | % (es. 100) |
| `ThermalLimit` | `thermal_limit` | °C |
| `ThermalPrioritize` | `thermal_prioritize` | 0/1 |
| `FanMode` | `fan_mode` | 0 = auto, 1 = manuale |
| `FanSpeed` | `fan_speed` | % |
| `VFCurve` | `vf_curve_hex` | stringa esadecimale (vedi 8.2) |

**Salvataggio (`save_profile`)** — riscrittura *structure-preserving*
riga per riga: si sostituisce solo il valore delle chiavi presenti in
`values_to_write`, **preservando lo spacing originale** (`key =value` vs
`key=value`), e si scrive con `newline="\r\n"`. Nota: `values_to_write`
NON include `ThermalLimit` (si scrive solo `ThermalPrioritize`) —
comportamento intenzionale identico ad Afterburner.

### 8.2 Formato binario della `VFCurve` (`vfcurve.py`)

La stringa hex è un array di **float32 little-endian**:

```
decode:  b = bytes.fromhex(vf_hex)
         floats = struct.unpack("<" + "f" * (len(b)//4), b)

layout:  [H0, H1, H2,                       ← header: 3 float (ignorati/preservati)
          V0, F0, C0,                       ← punto 0
          V1, F1, C1,                       ← punto 1
          ...
          V126, F126, C126]                 ← punto 126 (127 punti totali)
```

Per il punto *i* (con `base = 3`):
- `V = floats[base + i*3]`     → tensione in **mV** (es. 700.0–1250.0)
- `F = floats[base + i*3 + 1]` → frequenza **base** in MHz
- `C = floats[base + i*3 + 2]` → **delta** (offset) in MHz applicato da AB

Frequenza effettiva del punto: **`F_eff = F + C`**.

```python
@dataclass
class VFPoint:
    v_mv: float
    f_mhz: float
    c_delta: float
```

**Encode** (`encode_vfcurve(original_hex, points)`): parte dall'hex
originale (così header e ogni byte non-triplet restano identici) e
sovrascrive solo i 127×3 float da indice 3 in poi con
`struct.pack("<f", value)`. Roundtrip garantito byte-per-byte per le parti
non modificate.

### 8.3 Snap — la primitiva di quantizzazione

```python
def _snap(value: float, step: int) -> float:
    return round(value / step) * step
```
Tutte le frequenze della curva core sono quantizzate a **15 MHz**
(granularità reale dei clock NVIDIA).

### 8.4 Algoritmo di editing "AB-like" (identico a MSI Afterburner)

```python
def apply_single_point_edit_ab_like(
    base_points: List[VFPoint],   # curva base (F già consolidate, C ignorati)
    point_index: int,             # punto trascinato
    delta_mhz: float,             # spostamento richiesto (+/− MHz)
    snap_mhz: int = 15,
    left_gap_max_mhz: int = 60,
) -> List[VFPoint]:
```

Passi (le formule sono normative):

1. **Quantizza il delta**: `delta_mhz = int(_snap(delta_mhz, 15))`.
2. Crea la preview `pts` copiando `base_points` con `c_delta = 0`.
3. **Punto editato**:
   `target = _snap(base_points[k].f_mhz + delta_mhz, 15)`;
   `pts[k].f_mhz = target`.
4. **Right smoothing** (indici `i = k+1 … 126`) — curva **non decrescente**
   a destra: ogni punto viene alzato al plateau se serve, mai abbassato
   sotto la sua base:
   ```
   pts[i].f = snap( max(base[i].f, target, pts[i-1].f), 15 )
   ```
   Effetto: se alzi un punto, tutti i punti a destra più bassi vengono
   portati al livello del punto editato (plateau), quelli già più alti
   restano invariati.
5. **Left smoothing** (indici `i = k-1 … 0`, procedendo verso sinistra) —
   vincolo di **gap massimo 60 MHz** rispetto al punto alla propria destra:
   ```
   right_ref = pts[k].f
   per i da k-1 a 0:
       allowed_min = right_ref − 60
       pts[i].f = snap( max(base[i].f, allowed_min), 15 )
       right_ref = pts[i].f
   ```
   Effetto: alzando molto un punto, i punti a sinistra vengono trascinati
   su quel tanto che basta perché la salita non superi 60 MHz per step;
   se la base è già abbastanza alta resta la base.
6. Ritorna la preview (`c_delta` tutti 0 — è una curva "visuale").

### 8.5 Compilazione per il salvataggio in formato AB

```python
def compile_ab_cfg_points_for_save(base_points, preview_points,
                                   edited_index, delta_mhz) -> List[VFPoint]:
```
Convenzione di MSI Afterburner: **il punto editato mantiene la F base e
mette lo spostamento in C**; tutti gli altri punti assorbono lo smoothing
direttamente in F con C = 0:
- punto editato *k*: `B[k] = base[k].f_mhz`, `C[k] = delta_mhz`
- ogni altro punto *i*: `B[i] = preview[i].f_mhz`, `C[i] = 0`

### 8.6 `editor_widget.py` — `VFEditorWidget` (≈1400 righe)

#### Stato a 3 livelli
| Livello | Contenuto | Quando cambia |
|---|---|---|
| `original_base_points` | curva letta dal file (ghost curve, reset totale) | solo a load/reload |
| `base_points` | curva consolidata | al click **APPLICA** (consolida la preview) |
| `current_points` | preview live durante il drag | ad ogni movimento |

Al load: `current_points[i] = VFPoint(v, f_mhz + c_delta, 0)` — la curva
mostrata è quella **effettiva** (F+C).

#### Plot (pyqtgraph, `VFViewBox`)
- Limiti assoluti: `x ∈ [200, 1500]` mV, `y ∈ [0, 4500]` MHz,
  `minXRange = 50`, `minYRange = 100`.
- Vista di default: `setXRange(450, 1250)`, `setYRange(450, 3500)`.
- Griglia/tick: 25 mV in X, 100 MHz in Y.
- **Ghost curve**: `original_base_points` disegnata semi-trasparente
  sotto la curva corrente.

#### Interazione (hit-test)
- **Selezione con click** su scatter: punto più vicino con
  `|x − v_mv| ≤ 15` e `|y − f_mhz| ≤ 80`.
- **Inizio drag**: il mouse deve essere entro `|Δv| ≤ 12.5` mV **e**
  `|Δf| ≤ 80` MHz dal punto selezionato.
- **Durante il drag**: si calcola `delta = mouse_y − base_f` e si chiama
  `apply_single_point_edit_ab_like(base_points, k, delta)` in tempo reale;
  la X dei punti non cambia mai (tensioni fisse).
- **APPLICA** (o `Ctrl+Return`): `base_points = current_points` (consolida),
  registra lo stato in history.
- **Delete**: reset del punto selezionato alla base.
- **Escape**: deseleziona.

#### Slider (creati con `_make_slider_widget(label, min, max, step, unit)`)
| Slider | Range | Step |
|---|---|---|
| CORE CLOCK | −1000 … +1000 MHz | 15 |
| MEMORY CLOCK | −2000 … +2000 MHz | 25 |
| POWER LIMIT | 34 … 130 % | 1 |

Lo slider CORE applica un **offset uniforme** a tutta la curva:
`_apply_core_clock_offset` somma `snap(delta, 15)` a ogni `base_points[i]`.
Alla load lo slider viene inizializzato con
`core_mhz = round(prof.core_clk_boost / 1000)` (millesimi → MHz).

#### Undo / Redo
History a **50 stati** (`_max_history = 50`), lista di dict con:
`current_points`, `base_points`, `selected_index`, `last_edited_index`,
`last_edited_delta_mhz`, `has_pending_edit`. Un nuovo stato tronca il ramo
redo (`_history[:index+1]`); superati 50 si scarta il più vecchio.
Label `History: i/n` aggiornata a ogni operazione.

#### Salvataggio (`Ctrl+S`) — formula del delta
1. Se c'è un edit pendente viene prima auto-applicato.
2. Per ogni punto *i*:
   ```
   overall_delta = current[i].f_mhz − (original[i].f_mhz + original[i].c_delta)
   se |overall_delta| > 0.1:
       salva VFPoint(current[i].v_mv, original[i].f_mhz, overall_delta)
   altrimenti:
       salva la tripletta originale invariata
   ```
   cioè: la F scritta su file è SEMPRE quella base originale, tutto lo
   spostamento cumulativo finisce nel canale C — esattamente come fa AB.
3. `prof.core_clk_boost = core_slider.value() * 1000` (MHz → millesimi),
   idem memory; power limit diretto.
4. `encode_vfcurve(original_hex, points_to_save)` → `save_profile` →
   **reload del file da disco** per risincronizzare i 3 livelli di stato.

#### Scorciatoie (attive solo se `_is_active_page`)
`Ctrl+S` salva · `Ctrl+O` apri cfg · `Ctrl+Z`/`Ctrl+Y` undo/redo ·
`Ctrl+Return` applica · `Escape` deseleziona · `Delete` reset punto.

#### VirginStock lookup
`_find_virginstock_cfg(path)`: risale i parent fino alla dir
`ProfilesManager`, poi cerca `VirginStock/<stesso-filename>` — permette il
confronto/ripristino con la curva stock.

---

## 9. Theme system (`themes/`)

### 9.1 `themes/base.py`
- **`AppContext`** (dataclass) — bundle di dipendenze passato al tema:
  `base_dir`, `config_path`, `config_mgr`, `profile_mgr`, `msi_ctrl`,
  `gpu_monitor`, `process_logic`, `controller`, `app_name`, `app_version`,
  `start_minimized`, `log_callback`.
- **`ThemeDescriptor`**: `id`, `name`, `author`, `version`, `description`,
  `preview_image`, `factory` (callable `AppContext -> IThemeMainWindow`).
- **`IThemeMainWindow`**: interfaccia minima `show_window()` / `shutdown()`.

### 9.2 `themes/__init__.py` — `ThemeRegistry`
`register(descriptor)`, `discover()` (scan di `themes/<id>/__init__.py`
che espone `get_descriptor()`), `get(id)`, `get_or_default(id)`,
`list_descriptors()`, `list_ids()`.

### 9.3 Tema `red_glossy`
- `style.py`: dict `THEME` (palette dark glass rosso/nero) + `STYLESHEET`
  Qt CSS globale; gli stili si applicano via `objectName`.
- `widgets.py` (CRLF): gauge circolari, mini-chart, `ProfileCard`,
  dialog styled (`StyledMessageBox`), `SetupWizard` 3 step (path MSI →
  apertura MSI per salvare SLOT 1 → creazione struttura).
- `main_window.py` (LF): `OCProfilesManager(QMainWindow)` frameless con
  effetto acrilico Windows (ctypes `AccentPolicy` /
  `SetWindowCompositionAttribute`), tray icon, toast, 8 pagine in
  `QStackedWidget`:
  ```python
  PAGE_DASHBOARD=0, PAGE_PROFILES=1, PAGE_AUTOMATION=2, PAGE_HISTORY=3,
  PAGE_EDITOR=4 … PAGE_SETTINGS=7
  ```
- **Thread**:
  - `ProcessMonitorThread(QThread)`: loop con sleep
    `process_check_interval`; chiama `process_logic.check_processes()`;
    se ritorna un cambio emette `profile_changed(str profilo, str exe)`.
  - `ProfileApplyWorker(QThread)`: esegue
    `controller.apply_profile_blocking(name)` ed emette
    `finished(bool ok, str profile, bool silent)`.
- Import/export configurazione app (JSON con `config` + `profiles`):
  l'import passa da `config_mgr.replace_config(imported)` (atomico,
  preserva `msi_path` locale se quello importato non esiste su disco).

---

## 10. `main.py` — Boot sequence

1. `setup_logging()` — root logger DEBUG, `RotatingFileHandler`
   (`oc_manager.log`, 2 MB × 3, UTF-8, livello DEBUG) + console INFO.
   **Idempotente**: gli handler vengono aggiunti solo se
   `not root.handlers`.
2. `check_admin_or_relaunch()` — `IsUserAnAdmin()`; se non admin:
   `ShellExecuteW(None, "runas", sys.executable,
   subprocess.list2cmdline(sys.argv), None, 1)` (quoting corretto per
   path con spazi) e l'istanza corrente esce.
3. `QApplication` con `setQuitOnLastWindowClosed(False)` (vive in tray).
4. `_ensure_msi_configured()` — se `msi_path` mancante/invalido apre il
   `SetupWizard`; se annullato → exit.
5. `ThemeRegistry.discover()` → `get_or_default(config["ui_theme"])`.
6. `_build_app_context()` — istanzia tutti i manager e il controller.
7. `theme_desc.create_window(app_ctx)` → `show_window()` (o avvio in tray
   se `startup_min`) → `app.exec()`.
8. All'uscita: `controller.shutdown()` (chiude history + NVML).

---

## 11. Invarianti e regole di implementazione

1. **Mai** modificare i file in `VirginStock/`.
2. Ogni scrittura JSON passa da `atomic_write_json` (tmp + `os.replace`).
3. Ogni accesso alla config passa dall'API di `ConfigManager` (lock).
4. I cfg validi hanno nome `VEN_*.cfg` (o `profile1.cfg`) **e** > 200 byte.
5. Le frequenze core sono sempre multiple di 15 MHz (snap).
6. Il file cfg viene riscritto preservando struttura, spacing e `\r\n`.
7. L'apply è transazionale: staging → validate → backup → swap → launch,
   con rollback totale in caso di errore.
8. `main_window.py` usa terminatori LF, `widgets.py` CRLF — preservare i
   line ending esistenti quando si modifica.
9. Il core (oc_*) non importa mai PySide6: la UI vive solo nei temi.
