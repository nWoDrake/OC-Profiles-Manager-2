# Changelog

Tutti i cambiamenti significativi del progetto sono documentati qui.

## [2.7.0] — 2026-07-30

### ✨ Nuove funzioni

- **CLI headless `--apply <profilo>`** (`main.py`) — applica un profilo da
  riga di comando senza avviare la GUI. Exit code: `0` ok, `1` errore,
  `2` MSI AB non configurato, `3` profilo inesistente. Ideale per script,
  Task Scheduler e integrazioni esterne.
- **Backup automatico profili** (`oc_services.BackupManager`) — zip di tutta
  la cartella profili in `ProfilesManager_Backups/` all'avvio (opzionale),
  con retention configurabile (default 10), pulsanti "BACKUP ORA" e "APRI
  CARTELLA BACKUP" nelle impostazioni e `restore_backup()` con protezione
  zip-slip.
- **Confronto curve V/F nel CFG Editor** — nuovo pulsante **CONFRONTA**:
  sovrappone la curva di un altro profilo (tratteggiata, ciano) a quella in
  editing, per confrontare a colpo d'occhio due tuning.
- **Scheduler orario profili** (`oc_services.ProfileScheduler`) — regole
  a fasce orarie (`{start, end, profile, enabled}`) con supporto fasce che
  attraversano la mezzanotte (es. 22:00 → 07:00), editor dedicato nelle
  impostazioni (dialog "REGOLE ORARIE..."), applicazione edge-triggered
  (mai ri-applica ogni tick) e priorità al monitor processi.
- **Hotkey globali Ctrl+Alt+1..9** (`oc_services.GlobalHotkeyListener`) —
  applicano l'N-esimo profilo (ordine alfabetico) da qualunque app, anche
  a schermo intero. RegisterHotKey nativo Win32 in thread dedicato.
- **Watchdog temperatura GPU** (`oc_services.TempWatchdog`) — se la GPU
  resta sopra la soglia (default 90 °C) per N secondi (default 10), applica
  automaticamente un profilo "safe" con notifica e suono. Isteresi di 5 °C
  per il ri-arm.
- **Check aggiornamenti GitHub** (`oc_services.UpdateChecker`) — all'avvio
  (opzionale) interroga l'ultima release del repo e notifica se esiste una
  versione più recente.

### 🎨 Nuovo tema "Liquid Glass"

- **`themes/liquid_glass/`** — seconda UI completa selezionabile da
  Impostazioni → Aspetto: superfici traslucide ad alta trasparenza, bordi
  luminosi, accento ciano, raggi ampi e micro-animazioni (fade-in della
  finestra, transizioni di pagina con dissolvenza, acrylic Windows con
  tinta blu, bordo con glow ciano). Implementato riusando la MainWindow di
  red_glossy re-skinnata (zero duplicazione di logica).

### ⚡ Ottimizzazioni

- **Cache TTL snapshot processi** (`oc_utils.snapshot_running_exes`) — un
  solo scan psutil al secondo condiviso tra monitor processi e check MSI AB
  (prima: 2+ scan/tick).
- **Telemetria GPU fuori dal thread UI** (`GpuStatsThread`) — le letture
  NVML girano in un QThread dedicato con `Signal(dict)`; la UI non si
  blocca mai su driver lenti. In tray il thread va in pausa.
- **`log_level` di config finalmente applicato** — la chiave esistente ora
  regola il livello del logging console (il file resta a DEBUG).
- **Vista card: 1 sola lettura icone** — `get_profile_icons()` chiamata una
  volta per refresh invece che per ogni card.
- **Config prefetch nel monitor processi** — `process_match_mode` e
  `process_priority` letti una volta per tick, non per ogni exe.
- **Reflow griglia card skippato** se colonne e ordine non cambiano.

### ⚙️ Nuove chiavi config

`auto_backup_enabled`, `auto_backup_retention`, `scheduler_enabled`,
`schedule_rules`, `global_hotkeys_enabled`, `temp_watchdog_enabled`,
`temp_watchdog_threshold`, `temp_watchdog_duration_s`,
`temp_watchdog_profile`, `check_updates`.

## [2.5.0] — 2026-05-25

### ✨ Theme System — UI multiple intercambiabili

Refactor architetturale: la UI è ora completamente disaccoppiata dalla logica
di business. È possibile avere più "temi" (GUI complete, non solo skin di
colori) selezionabili da **Impostazioni → Aspetto**.

#### Nuova struttura

- **`themes/`** — package dei temi UI. Ogni sottocartella è un tema autonomo.
  - **`themes/base.py`** — `AppContext` (bundle controller di dominio) e
    `ThemeDescriptor` (metadata di un tema).
  - **`themes/__init__.py`** — `ThemeRegistry` con discovery automatica dei
    temi presenti nella cartella.
  - **`themes/red_glossy/`** — il tema originale dell'applicazione, isolato.
    Contiene `style.py` (palette + stylesheet), `widgets.py` (widget custom),
    `main_window.py` (`OCProfilesManager`).
- **`widgets_common/`** — utility realmente generiche condivise tra temi:
  - **`icon_factory.py`** — `IconFactory` basata su Segoe MDL2.
  - **`theme_context.py`** — token globale `THEME` per componenti riusabili
    (es. `cfg_editor`) che hanno bisogno dei colori del tema attivo senza
    accoppiarsi a uno specifico.

#### File spostati / rimossi dalla root

- `oc_ui.py` → **`themes/red_glossy/main_window.py`**
- `oc_widgets.py` → **`themes/red_glossy/widgets.py`**
- `THEME`, `STYLESHEET`, `build_stylesheet()` rimossi da `constants.py`
  → spostati in **`themes/red_glossy/style.py`**

#### Nuova configurazione

- `DEFAULT_CONFIG["ui_theme"] = "red_glossy"` — id del tema UI attivo.

#### Comportamento

- All'avvio, `main.py` legge `ui_theme` da config, scopre i temi disponibili
  e istanzia la `QMainWindow` del tema corrispondente.
- Nelle **Impostazioni** è disponibile una nuova sezione **"Aspetto"** con
  un selettore di tema; cambiandolo viene proposto un riavvio.
- Aggiungere un nuovo tema = creare una nuova cartella sotto `themes/`
  (vedi `themes/README.md`).

#### Nessun cambio alla logica

`oc_controller.py`, `oc_core.py`, `oc_history.py`, `oc_utils.py`,
`profile_info_extractor.py`, `cfg_editor/cfg_model.py`, `cfg_editor/vfcurve.py`
sono **invariati**. Solo `cfg_editor/editor_widget.py` ha avuto una piccola
modifica per leggere il `THEME` dal `theme_context` invece che da `constants`.

---

## [2.4.0] — 2026-05-24

### 🐛 Bug fix critici

- **`oc_ui.py`**: rimossa **duplicazione** di `_setup_cfg_editor()` e
  `_open_cfg_editor_for_selected()` (la seconda definizione sovrascriveva
  silenziosamente la prima → codice morto e comportamento inconsistente).
- **`oc_ui.py`**: rimosso import duplicato di `oc_widgets`.
- **`oc_core.py` (GPUMonitor)**: aggiunti `restype` e `argtypes` corretti a
  tutte le chiamate **NVML via ctypes**. Senza questi, su sistemi 64-bit i
  pointer venivano troncati a 32-bit causando potenziali crash o letture
  garbled.
- **`oc_history.py`**: aggiunto `close_session()` chiamato in cleanup.
  Senza di esso, l'ultima entry restava con `duration_sec=0` perdendo
  l'informazione sul tempo dell'ultima sessione.
- **`oc_core.py` (ProcessMonitorLogic)**: lo snapshot dei processi via
  `psutil.process_iter` veniva fatto **mentre si teneva il lock interno**.
  Su sistemi con tanti processi questo poteva bloccare l'UI per centinaia di
  ms. Ora lo snapshot viene fatto **fuori dal lock** e il lock copre solo
  la mutazione dello stato.
- **`cfg_editor/cfg_model.py`**: aggiunto import mancante di `Optional` —
  `_rebuild_preserving_structure` ritorna `Optional[str]` ma `Optional` non
  era importato (errore di name resolution latente).

### ⚡ Performance

- Pausa automatica del **timer GPU** quando la finestra è minimizzata in tray
  (risparmio CPU non trascurabile su laptop / mining rig).
- **Caching tray menu**: ricostruito solo quando i profili cambiano.
- Regex `Profile\d\.cfg` **precompilata** a livello modulo.
- `ProfileInfoExtractor` ora usa **(sum_mtime, count)** come signature di
  cache: più robusto che il solo max(mtime) quando un file viene aggiunto
  o rimosso senza che gli altri cambino.

### 🔒 Robustezza

- `ProfileInfoExtractor` ora ha **lock interno** (RLock) per safety in
  scenari multi-thread (es. card view rinfrescata in background).
- Atomic JSON write centralizzato in `oc_utils.atomic_write_json`,
  consolidato il pattern retry+rename.
- Tutti i `Popen`/`run` su Windows passano per `oc_utils.popen_hidden` /
  `run_hidden` (no console flash).
- `ConfigManager.config` viene merged con `DEFAULT_CONFIG` al load (nuove
  chiavi di default vengono ereditate da config esistenti senza richiedere
  reset utente).
- `_apply_buttons` ora ignora silenziosamente bottoni distrutti dal layout
  (es. dopo rinomina).

### ✨ Nuove feature

- **🔍 Search bar** nella libreria profili (filtra sia lista che card view).
- **📋 Duplica profilo** (button + context menu + shortcut `Ctrl+D`).
- **⌨️ Shortcut keyboard** completi:
  `F5` refresh, `Ctrl+N` nuovo, `Ctrl+D` duplica, `F2` rinomina, `Del`
  elimina, `Enter` applica, `Ctrl+F` search, `Ctrl+1..2/L/H/,` navigazione.
- **📤 Export singolo profilo** in JSON (con icona e VEN files).
- **📥 Import profilo** da JSON singolo (`ProfileController.import_profile`).
- **📊 Statistiche history arricchite** sulla pagina History:
  ore totali, numero cambi, sessione media, profilo più usato.
- **📈 Export CSV** della history.
- **⏸ Pausa monitoraggio automatico** dall'UI Impostazioni.
- **💾 Risparmio CPU**: pausa monitor GPU quando in tray (toggle nelle
  impostazioni).
- **🔔 Toggle notifiche tray**.
- **🚨 Sidebar dirty indicator**: il CFG Editor mostra `*` se ci sono
  modifiche non salvate.
- **🔄 Refresh tray menu** quando si creano/eliminano profili.

### 🏗 Architettura / refactor

- Nuovo modulo **`oc_utils.py`** con utility riusabili:
  `atomic_write_json`, `safe_read_json`, `safe_rmtree`,
  `snapshot_running_exes`, `format_duration`, `popen_hidden`, `run_hidden`,
  `set_autostart_registry`, `check_autostart_registry`, `open_in_explorer`.
- `ProfileController` arricchito con: `shutdown()`, `duplicate_profile()`,
  `export_profile()`, `import_profile()`, `set_monitoring_paused()`,
  `is_monitoring_paused`, `export_history_csv()`, `get_summary_stats()`.
- **Indici pagine** estratti come costanti modulo (`PAGE_DASHBOARD`,
  `PAGE_PROFILES`, …) — niente più magic numbers nel codice UI.
- `cfg_editor/` rimane il package per il CFG Editor (struttura immutata,
  retrocompatibilità API garantita).
- Cleanup di `delete_profile` / `rename_profile` nel controller: aggiornano
  anche `process_priority` (lista) e `profile_icons`.

### 📚 Documentazione

- README completo con shortcut, struttura progetto, installazione
- `requirements.txt` con dipendenze esplicite
- Docstring estesi su tutte le funzioni pubbliche

---

## [2.3.0] — precedente

- Vista Card + Lista per la libreria profili
- Sistema icone profilo (preset + custom PNG)
- CFG Editor integrato per la V/F Curve
- History strutturata con grafico orizzontale
- Backup/rollback su apply
