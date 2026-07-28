# OC Profiles Manager v2.4.0

Gestore di profili di overclocking per **MSI Afterburner** con interfaccia
moderna in stile *dark glass*, telemetria GPU in tempo reale, monitoraggio
automatico processi → profilo e editor avanzato della V/F Curve.

> **Versione 2.4.0** — Refactor completo: bug fix critici, performance
> migliorata, nuove feature (search, duplica, shortcut, export singolo,
> statistiche history) e test unitari.

---

## ✨ Caratteristiche principali

### Gestione profili
- **Libreria profili** con due viste: **Lista** o **Card** (con anteprima OC)
- 🔍 **Search bar** per filtrare i profili velocemente
- 📋 **Duplica** un profilo esistente per partire da una base
- 🎨 **Icone personalizzabili** (preset o PNG custom)
- 🔄 **Apply non-bloccante** con backup e rollback automatico

### Automazione
- 🤖 Cambio profilo automatico in base al **processo in primo piano**
- 3 modalità: `first_match`, `stable_no_switch`, `priority_list`
- ⏸ Pausa monitoraggio manuale dall'UI

### Editor avanzato
- 🎛️ **CFG Editor** integrato per la V/F Curve di MSI Afterburner
- Drag interattivo dei punti, ghost curve originale, undo/redo

### Telemetria
- 📊 GPU NVML: temperatura, load, fan, core clock, mem clock, power, VRAM
- Grafici live con auto-scale
- Fallback a simulazione su sistemi non NVIDIA

### Storico
- 📈 **History** con statistiche giornaliere e riassuntive
- Esportazione CSV
- Cleanup automatico (retention 30 giorni)

### Comfort
- ⌨️ **Shortcut keyboard** completi (vedi sotto)
- 🔔 Toast notification + sistema tray con menu profili rapidi
- 🎨 Acrylic glass effect su Windows

---

## ⌨️ Shortcut keyboard

| Tasto         | Azione                              |
|---------------|--------------------------------------|
| `F5`          | Aggiorna lista profili               |
| `Ctrl+N`      | Nuovo profilo                        |
| `Ctrl+D`      | Duplica profilo selezionato          |
| `F2`          | Rinomina profilo selezionato         |
| `Delete`      | Elimina profilo selezionato          |
| `Enter`       | Applica profilo selezionato          |
| `Ctrl+F`      | Focus barra di ricerca               |
| `Esc`         | Pulisci ricerca                      |
| `Ctrl+1..2`   | Vai a Dashboard / Libreria           |
| `Ctrl+L`      | Vai ai Log                           |
| `Ctrl+H`      | Vai alla History                     |
| `Ctrl+,`      | Vai alle Impostazioni                |

---

## 📦 Requisiti

- **Python 3.10+** (testato con 3.12 e 3.13)
- **Windows 10/11** (alcune feature sono Windows-specifiche)
- **MSI Afterburner installato** e avviato almeno una volta
- **GPU NVIDIA** (consigliato per telemetria via NVML; fallback simulato altrimenti)

Dipendenze Python: vedi `requirements.txt`.

---

## 🚀 Installazione

```bash
# 1. Clone / unzip del progetto
cd oc_profiles_manager

# 2. (Opzionale) Crea un virtualenv
python -m venv .venv
.venv\Scripts\activate

# 3. Installa le dipendenze
pip install -r requirements.txt

# 4. Avvia (richiede privilegi admin per gestire MSI Afterburner)
python main.py
```

Al primo avvio si aprirà un **wizard** in 3 passi per configurare il percorso
di `MSIAfterburner.exe` e creare la struttura `Profiles/ProfilesManager/`.

---

## 🗂 Struttura del progetto

```
oc_profiles_manager/
├── main.py                      # Entry point (logging, UAC, app launch)
├── constants.py                 # Theme, stylesheet, default config, validazione
├── oc_core.py                   # Business logic (NVML, profili, MSI, monitor)
├── oc_controller.py             # Layer di coordinamento tra core e UI
├── oc_history.py                # Persistenza history con statistiche
├── oc_ui.py                     # Main window, pages, threading, tray
├── oc_widgets.py                # Widget custom (gauge, chart, card, dialog)
├── oc_utils.py                  # Utility (atomic I/O, formatting, subprocess)
├── profile_info_extractor.py    # Estrazione dati profilo per card view
├── cfg_editor/
│   ├── __init__.py
│   ├── cfg_model.py             # Parser file VEN_*.cfg
│   ├── vfcurve.py               # Encode/decode V/F Curve
│   └── editor_widget.py         # Widget editor pyqtgraph
├── tests/
│   ├── test_sanitize.py
│   ├── test_history.py
│   ├── test_utils.py
│   └── test_vfcurve.py
└── requirements.txt
```

---

## 🧪 Test

```bash
python tests/test_utils.py
python tests/test_sanitize.py
python tests/test_history.py
python tests/test_vfcurve.py
```

I test core non richiedono Qt e possono essere eseguiti anche fuori da Windows.

---

## ⚠️ Note di sicurezza

- L'applicazione **richiede privilegi amministrativi** per controllare MSI
  Afterburner e modificare file in `C:\Program Files (x86)\MSI Afterburner\Profiles\`.
- I file di configurazione vengono salvati con **atomic write + retry** per
  prevenire corruzione in caso di crash o lock antivirus.
- Prima di ogni `apply_profile`, l'app crea un **backup automatico** e può fare
  **rollback** in caso di errore durante lo swap.

---

## 📝 Licenza

Progetto personale — uso a scopo educativo / personale.

---

## 🙏 Crediti

- Tema ispirato a Windows 11 Acrylic / Fluent Design
- Icone via Segoe MDL2 Assets (font di sistema Windows)
- Grafici V/F Curve tramite [pyqtgraph](https://www.pyqtgraph.org/)
