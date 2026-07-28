"""
widgets_common.theme_context — Token "tema corrente" globale a runtime.

Alcuni componenti riusabili (es. cfg_editor.editor_widget) hanno bisogno di
sapere i colori del tema senza dover essere riscritti per ogni tema.

La MainWindow del tema attivo, all'avvio, registra qui il proprio dizionario
THEME chiamando `set_current_theme(THEME)`. I componenti riusabili possono
poi chiamare `get_theme()` e leggere le chiavi che gli interessano.

È esplicitamente un GLOBAL MUTABLE STATE: serve solo come ponte di
compatibilità. Un nuovo tema può anche scegliere di non popolarlo e
fornire un editor cfg completamente custom.
"""

from __future__ import annotations

from typing import Dict, Optional

# Fallback minimale: garantisce che cfg_editor & co. abbiano sempre qualcosa
# anche se nessun tema ha ancora chiamato set_current_theme() (es. in test).
_FALLBACK_THEME: Dict[str, str] = {
    "primary":       "#ff2e2e",
    "primary_hover": "#ff4d4d",
    "primary_dark":  "#cc2525",
    "bg_dark":       "#121214",
    "bg_panel":      "#1e1e24",
    "bg_input":      "rgba(0,0,0,0.3)",
    "glass_bg":      "rgba(255, 255, 255, 0.05)",
    "glass_border":  "rgba(255, 255, 255, 0.1)",
    "text_main":     "#ffffff",
    "text_dim":      "#888899",
    "text_muted":    "#666677",
    "success":       "#00ff88",
    "warning":       "#ffaa00",
    "error":         "#ff5555",
    "info":          "#4488ff",
    "radius":        "10px",
    "radius_sm":     "6px",
}

_current: Optional[Dict[str, str]] = None


def set_current_theme(theme: Dict[str, str]) -> None:
    """
    Pubblica il dizionario THEME del tema attivo. Da chiamare in MainWindow.__init__
    PRIMA di istanziare componenti che fanno `from widgets_common.theme_context import get_theme`.
    """
    global _current
    _current = theme


def get_theme() -> Dict[str, str]:
    """Ritorna il tema corrente, o il fallback se non ancora impostato."""
    return _current if _current is not None else _FALLBACK_THEME


__all__ = ["set_current_theme", "get_theme"]
