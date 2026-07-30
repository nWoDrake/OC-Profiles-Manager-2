"""
themes.liquid_glass.style — Palette e stylesheet del tema "Liquid Glass".

Filosofia del tema:
- superfici quasi liquide: trasparenze alte, l'acrylic di Windows traspare
  molto più che in Red Glossy;
- bordi luminosi sottili (rgba bianco ~0.16) che simulano la rifrazione
  del vetro;
- raggi ampi (16 px) e accento ciano freddo (#4dd6ff);
- highlight superiore con gradiente verticale, come luce che scivola
  sul vetro.

Il tema NON ridefinisce i widget: riusa quelli di red_glossy re-skinnati.
`LIQUID_THEME` sovrascrive i token del THEME condiviso; lo stylesheet viene
rigenerato con `build_stylesheet()` di red_glossy e poi arricchito con il
layer QSS `EXTRA_QSS` (tocchi liquid: gradienti, glow, raggi).
"""

from __future__ import annotations

# ============================================================================
# TOKEN DEL TEMA — sovrascrivono quelli di red_glossy (stesse chiavi)
# ============================================================================

LIQUID_THEME = {
    "primary":       "#4dd6ff",
    "primary_hover": "#7ce2ff",
    "primary_dark":  "#2aa8d0",
    "bg_dark":       "#0b1016",
    "bg_panel":      "#121a24",
    "bg_input":      "rgba(8, 14, 22, 0.42)",
    "glass_bg":      "rgba(255, 255, 255, 0.07)",
    "glass_border":  "rgba(255, 255, 255, 0.16)",
    "text_main":     "#f2f7fb",
    "text_dim":      "#8fa3b8",
    "text_muted":    "#5d7186",
    "success":       "#39e6a3",
    "warning":       "#ffc14d",
    "error":         "#ff5f7a",
    "info":          "#4dd6ff",
    "radius":        "16px",
    "radius_sm":     "10px",
    "window_radius": "18px",
    # Molto più trasparenti di red_glossy: il blur acrylic domina.
    "bg_dark_glass":  "rgba(10, 16, 24, 0.52)",
    "bg_panel_glass": "rgba(16, 24, 34, 0.46)",
}


# ============================================================================
# LAYER QSS AGGIUNTIVO — tocchi "liquid" sopra lo stylesheet base
# ============================================================================

def build_extra_qss(t: dict) -> str:
    """QSS supplementare applicato DOPO lo stylesheet base rigenerato."""
    return f"""
/* ── Liquid Glass overlay ────────────────────────────────────────────── */

/* Superficie principale: gradiente verticale = luce che scivola sul vetro */
QWidget#RootContainer {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(38, 58, 82, 0.40),
        stop:0.12 rgba(14, 22, 33, 0.52),
        stop:1 rgba(8, 13, 20, 0.58));
    border-radius: {t['window_radius']};
    border: 1px solid rgba(255, 255, 255, 0.10);
}}

QFrame#Sidebar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(20, 30, 44, 0.55),
        stop:1 rgba(12, 19, 29, 0.35));
    border-right: 1px solid rgba(255, 255, 255, 0.10);
}}

/* Navigazione: pillole di vetro con glow ciano quando attive */
QPushButton[class="NavBtn"] {{
    border-radius: 12px;
    margin: 3px 12px;
}}
QPushButton[class="NavBtn"]:hover {{
    background: rgba(125, 216, 255, 0.10);
    color: {t['text_main']};
}}
QPushButton[class="NavBtn"][active="true"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(77, 214, 255, 0.26),
        stop:1 rgba(77, 214, 255, 0.10));
    border: 1px solid rgba(125, 216, 255, 0.40);
    color: {t['primary_hover']};
}}

/* Card e pannelli: vetro spesso con bordo rifrangente */
QFrame#GlassCard, QFrame#TelemetryCard, QFrame#NotifyCard {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 255, 255, 0.10),
        stop:0.5 rgba(255, 255, 255, 0.05),
        stop:1 rgba(255, 255, 255, 0.03));
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: {t['radius']};
}}

/* Bottoni azione: capsule di vetro */
QPushButton#ActionBtn {{
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 11px;
}}
QPushButton#ActionBtn:hover {{
    background: rgba(125, 216, 255, 0.14);
    border: 1px solid rgba(125, 216, 255, 0.45);
}}
QPushButton#ApplyBtn {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(77, 214, 255, 0.85),
        stop:1 rgba(42, 168, 208, 0.85));
    color: #06222e;
    border: 1px solid rgba(190, 236, 255, 0.55);
    border-radius: 11px;
    font-weight: 700;
}}
QPushButton#ApplyBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(124, 226, 255, 0.95),
        stop:1 rgba(77, 214, 255, 0.90));
}}

/* Input: incavi di vetro scuro */
QLineEdit, QComboBox, QSpinBox, QTextEdit {{
    background: rgba(6, 12, 19, 0.45);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    selection-background-color: rgba(77, 214, 255, 0.45);
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid rgba(125, 216, 255, 0.55);
}}

/* Tabelle e liste: righe fluide */
QTableWidget, QListWidget {{
    background: rgba(6, 12, 19, 0.32);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: {t['radius_sm']};
    alternate-background-color: rgba(255, 255, 255, 0.03);
}}
QTableWidget::item:selected, QListWidget::item:selected {{
    background: rgba(77, 214, 255, 0.22);
    color: {t['text_main']};
}}

/* Scrollbar minimal a goccia */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(160, 210, 240, 0.28);
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(125, 216, 255, 0.50);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* Checkbox: indicatore liquid */
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border-radius: 6px;
    border: 1px solid rgba(255, 255, 255, 0.22);
    background: rgba(6, 12, 19, 0.45);
}}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {t['primary_hover']}, stop:1 {t['primary_dark']});
    border: 1px solid rgba(190, 236, 255, 0.6);
}}

/* Tooltip di vetro */
QToolTip {{
    background: rgba(14, 22, 33, 0.92);
    color: {t['text_main']};
    border: 1px solid rgba(125, 216, 255, 0.35);
    border-radius: 8px;
    padding: 6px 10px;
}}
"""


def build_liquid_stylesheet(theme: dict) -> str:
    """Stylesheet completo: base di red_glossy rigenerata + layer liquid."""
    from themes.red_glossy.style import build_stylesheet
    return build_stylesheet(theme) + build_extra_qss(theme)
