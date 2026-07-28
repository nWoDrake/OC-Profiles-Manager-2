# Theme System — Guida per creare un nuovo tema

Questo documento spiega come aggiungere una nuova GUI all'applicazione senza
toccare la logica di business.

## Architettura

```
oc_profiles_manager/
├── main.py                       ← carica il tema scelto in config
├── oc_controller.py              ← logica (NON toccare per fare un tema)
├── oc_core.py                    ← logica
├── widgets_common/               ← utility riusabili (icone, theme_context)
└── themes/
    ├── __init__.py               ← ThemeRegistry
    ├── base.py                   ← AppContext + ThemeDescriptor
    ├── red_glossy/               ← tema originale (riferimento)
    └── <tuo_nuovo_tema>/         ← la tua nuova GUI
```

## Struttura di un tema

Un tema è una sottocartella di `themes/` con almeno un file `__init__.py` che
registra il tema. Tutto il resto è libero: ogni tema può scegliere come
strutturarsi.

Struttura consigliata (uguale a `red_glossy`):

```
themes/<id>/
├── __init__.py        ← metadata + registrazione (OBBLIGATORIO)
├── style.py           ← palette + stylesheet Qt (opzionale)
├── widgets.py         ← widget custom del tema (opzionale)
└── main_window.py     ← QMainWindow del tema (necessario, ma può
                         stare anche nel __init__.py se piccolo)
```

## Esempio minimo

Vuoi creare un tema chiamato `cyber_minimal`?

### 1. Crea la cartella e `__init__.py`

```python
# themes/cyber_minimal/__init__.py
from themes import ThemeRegistry
from themes.base import AppContext, ThemeDescriptor


def _factory(ctx: AppContext):
    from .main_window import CyberMinimalWindow
    return CyberMinimalWindow(ctx)


ThemeRegistry.register(
    ThemeDescriptor(
        id="cyber_minimal",
        name="Cyber Minimal",
        author="Tu",
        version="1.0.0",
        description="Tema essenziale con accent verde e tipografia mono.",
        factory=_factory,
    )
)
```

### 2. Crea la tua MainWindow

```python
# themes/cyber_minimal/main_window.py
from PySide6.QtWidgets import QMainWindow, QLabel, QVBoxLayout, QWidget

from themes.base import AppContext


class CyberMinimalWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.ctrl = ctx.controller   # ← la logica è pronta all'uso
        self.setWindowTitle("Cyber Minimal")

        # Qui costruisci la TUA GUI con la struttura che preferisci.
        # Puoi usare QStackedWidget, QTabWidget, una single-page, qualunque cosa.
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel("La mia nuova UI!"))
        self.setCentralWidget(central)

    # ── API richiesta dal theme system ──────────────────────────────────
    def show_window(self):
        self.show()

    def shutdown(self):
        # Cleanup: stop timer, thread, chiusura sessioni, ecc.
        self.ctx.controller.shutdown()
```

### 3. Riavvia l'applicazione

Il tema verrà scoperto automaticamente e apparirà nel selettore in
**Impostazioni → Aspetto → Tema interfaccia**.

## Cosa NON deve fare un tema

- ❌ Istanziare `ConfigManager`, `ProfileManager`, ecc. — usa `ctx`
- ❌ Modificare file in `oc_controller.py`, `oc_core.py`, `oc_history.py`
- ❌ Importare `THEME` o `STYLESHEET` da `constants.py` (non esistono più lì)

## Cosa PUÒ fare un tema

- ✅ Avere widget completamente diversi (non solo cambiare colori)
- ✅ Riorganizzare le pagine come vuole (es. tab invece di sidebar)
- ✅ Avere una propria `style.py` con palette/stylesheet propria
- ✅ Importare `IconFactory` da `widgets_common.icon_factory` (oppure no)
- ✅ Riusare widget del tema `red_glossy` se vuole partire da una base
- ✅ Pubblicare il proprio `THEME` dict via `widgets_common.theme_context.set_current_theme()`
  così che `cfg_editor` legga i colori corretti

## API di AppContext (ciò che un tema riceve)

```python
ctx.config_mgr      # ConfigManager (read/write user settings)
ctx.profile_mgr     # ProfileManager (CRUD profili)
ctx.msi_ctrl        # MSIAfterburnerController (start/stop MSI)
ctx.gpu_monitor     # GPUMonitor (telemetria GPU)
ctx.process_logic   # ProcessMonitorLogic
ctx.controller      # ProfileController (API principale: apply, create, delete...)
ctx.base_dir        # Path del progetto
ctx.config_path     # Path al JSON di config
ctx.app_name        # "OCProfilesManager"
ctx.app_version     # "2.5.0"
ctx.start_minimized # True se lanciato con --minimized
```

Tutto quello che il vecchio `OCProfilesManager` faceva, il tuo nuovo tema lo
può fare chiamando metodi su `ctx.controller`. Esempio:

```python
ctx.controller.create_profile("MyProfile")
ctx.controller.apply_profile_blocking("MyProfile")
ctx.controller.history.get_recent_entries(50)
```
