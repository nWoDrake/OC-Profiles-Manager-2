"""
OC Profiles Manager - Costanti e Configurazione

Centralizza:
- Informazioni applicazione (nome, versione, paths)
- Configurazione default
- Timing
- Validazione nomi profilo
- Mapping icone preset

NOTA: la PALETTE colori e lo STYLESHEET (Qt CSS) NON sono più in questo file.
Sono stati spostati dentro ogni tema (vedi themes/<id>/style.py) perché ogni
tema può avere il proprio look completamente diverso. Il core dell'app non
importa più alcuno stile: è il tema attivo a fornirlo alla sua MainWindow.
"""

from __future__ import annotations

import re as _re
from pathlib import Path
from typing import Optional

# ============================================================================
# INFORMAZIONI APP
# ============================================================================

APP_NAME: str = "OCProfilesManager"
APP_VERSION: str = "2.6.3"
APP_AUTHOR: str = "OC Profiles Team"
BASE_DIR: Path = Path(__file__).parent

# ============================================================================
# (RIMOSSO) TEMA COLORI — vedi themes/<id>/style.py
# ============================================================================

# ============================================================================
# CONFIGURAZIONE DEFAULT
# ============================================================================

DEFAULT_CONFIG = {
    "msi_path": r"C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe",
    "associations": {},
    "startup_min": False,
    "sounds": True,
    "default_alias": "VirginStock",
    "process_match_mode": "first_match",
    "process_priority": [],
    "profile_icons": {},
    # Nuove preferenze (introdotte in v2.4)
    "gpu_pause_when_hidden": True,   # Risparmio CPU se in tray
    "show_tray_notifications": True,
    "log_level": "INFO",             # DEBUG/INFO/WARNING/ERROR
    # Theme system (v2.5+)
    "ui_theme": "red_glossy",        # id del tema UI attivo (cartella in themes/)
}

# ============================================================================
# TIMING (millisecondi salvo dove indicato)
# ============================================================================

TIMING = {
    "process_check_interval": 2000,   # ms
    "gpu_update_interval": 1000,      # ms
    "msi_status_interval": 5000,      # ms
    "profile_cooldown": 5,            # secondi (timer interno logico)
    "msi_startup_delay": 3.0,         # secondi
    "profile_apply_delay": 1.0,       # secondi
    "toast_duration": 4000,           # ms
    "history_save_debounce": 500,     # ms (futuro)
}

# ============================================================================
# SOUND
# ============================================================================

SOUND_CONFIG = {
    "apply":   {"frequency": 800, "duration_ms": 150},
    "default": {"frequency": 400, "duration_ms": 250},
    "error":   {"frequency": 220, "duration_ms": 300},
    "info":    {"frequency": 1000, "duration_ms": 80},
}

# ============================================================================
# PROFILE NAME VALIDATION
# ============================================================================

_INVALID_CHARS_RE = _re.compile(r'[<>:"/\\|?*]')
_RESERVED_WINDOWS_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
# Riservati dalla logica applicativa: non usabili come nome profilo utente.
_RESERVED_APP_NAMES = frozenset({"Default", "VirginStock", "_staging_tmp", "_backup_tmp"})

MAX_PROFILE_NAME_LENGTH: int = 100


def sanitize_profile_name(name: str) -> Optional[str]:
    """
    Valida e pulisce un nome profilo.

    Regole:
    - Vuoto o > 100 caratteri  → None
    - Contiene <>:"/\\|?*       → None
    - Riservato Windows         → None
    - Riservato app             → None
    - Trailing dots/spaces      → strippati
    """
    if not name:
        return None
    name = name.strip()
    if not name or len(name) > MAX_PROFILE_NAME_LENGTH:
        return None
    if _INVALID_CHARS_RE.search(name):
        return None
    if name.upper() in _RESERVED_WINDOWS_NAMES:
        return None
    if name in _RESERVED_APP_NAMES:
        return None
    name = name.rstrip(". ")
    return name or None


# ============================================================================
# PROFILE CARD SETTINGS
# ============================================================================

PROFILE_PRESET_ICONS = {
    "gaming":       {"glyph": "\uE7FC", "label": "Gaming",        "color": "#ff2e2e"},
    "performance":  {"glyph": "\uE945", "label": "Performance",   "color": "#ff6600"},
    "balanced":     {"glyph": "\uE81E", "label": "Bilanciato",    "color": "#ffaa00"},
    "silent":       {"glyph": "\uE992", "label": "Silenzioso",    "color": "#00aaff"},
    "mining":       {"glyph": "\uE939", "label": "Mining",        "color": "#00ff88"},
    "streaming":    {"glyph": "\uE714", "label": "Streaming",     "color": "#aa44ff"},
    "desktop":      {"glyph": "\uE770", "label": "Desktop",       "color": "#888899"},
    "benchmark":    {"glyph": "\uE9D9", "label": "Benchmark",     "color": "#ff4488"},
    "rendering":    {"glyph": "\uE8B1", "label": "Rendering",     "color": "#44aaff"},
    "undervolt":    {"glyph": "\uE83F", "label": "Undervolt",     "color": "#00ddaa"},
    "overclock":    {"glyph": "\uE945", "label": "Overclock",     "color": "#ff2e2e"},
    "stock":        {"glyph": "\uE74E", "label": "Stock",         "color": "#666677"},
    "custom":       {"glyph": "\uE771", "label": "Custom",        "color": "#ffffff"},
}

# Dimensioni card (usate da ProfileCardView per calcolo colonne)
CARD_MIN_WIDTH: int = 280
CARD_MAX_WIDTH: int = 340
CARD_HEIGHT: int = 195
