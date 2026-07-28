"""
themes.red_glossy.style — Definizione colori + stylesheet del tema "Red Glossy".

Era precedentemente in constants.py (THEME + build_stylesheet + STYLESHEET).
Spostato qui per isolare il look del tema dal core dell'applicazione.

Qualunque nuovo tema può definire la propria coppia THEME/STYLESHEET in modo
analogo. Il core non importa più nulla di questo file: solo la MainWindow del
tema lo usa.
"""

from __future__ import annotations

from typing import Optional

# ============================================================================
# PALETTE / TOKEN DEL TEMA
# ============================================================================

THEME = {
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
    "window_radius": "12px",
    # Versioni semitrasparenti per il glass blur di Windows (acrilico passa dietro)
    "bg_dark_glass":  "rgba(18, 18, 20, 0.72)",
    "bg_panel_glass": "rgba(30, 30, 36, 0.68)",
}


def build_stylesheet(theme: Optional[dict] = None) -> str:
    """Costruisce la stringa StyleSheet globale (Qt) basandosi sul tema."""
    t = theme or THEME
    return f"""
/* La finestra principale ha sfondo trasparente: il vero rendering avviene
   in paintEvent() per ottenere i bordi arrotondati. Lo stylesheet del
   QMainWindow resta minimale per non sovrascriverne il painting. */
QMainWindow {{
    background: transparent;
}}
QWidget#RootContainer {{
    background: {t['bg_dark_glass']};
    border-radius: {t['window_radius']};
}}
QFrame#Sidebar {{
    background: {t['bg_panel_glass']};
    border-top-left-radius: {t['window_radius']};
    border-bottom-left-radius: {t['window_radius']};
    border-right: 1px solid {t['glass_border']};
}}
QWidget#OCBrandLogo {{
    background: transparent;
}}
QWidget#OCBrandLogoCollapsed {{
    background: transparent;
}}
QPushButton[class="NavBtn"] {{
    background: transparent;
    border: none;
    color: {t['text_dim']};
    text-align: left;
    padding: 12px 25px;
    font-family: "Segoe UI";
    font-size: 14px;
    font-weight: 500;
    margin: 2px 10px;
    border-radius: {t['radius_sm']};
}}
QPushButton[class="NavBtn"]:hover {{
    background: rgba(255, 46, 46, 0.1);
    color: white;
}}
QPushButton[class="NavBtn"][active="true"] {{
    background: rgba(255, 46, 46, 0.15);
    color: {t['primary']};
    border-left: 3px solid {t['primary']};
    font-weight: 700;
}}
QPushButton[class="NavBtn"][dirty="true"] {{
    color: {t['warning']};
}}
/* Sidebar collapsed: bottoni compatti e centrati (solo icona). */
QPushButton[class="NavBtn"][collapsed="true"] {{
    padding: 12px 0px;
    margin: 2px 8px;
    text-align: center;
}}
/* SpinBox/DoubleSpinBox con frecce ben visibili (CFG Editor & co). */
QSpinBox, QDoubleSpinBox {{
    background: {t['bg_input']};
    border: 1px solid #444;
    color: white;
    padding: 4px 6px;
    border-radius: 4px;
    min-height: 24px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {t['primary']};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid #555;
    border-top-right-radius: 4px;
    background: rgba(255,255,255,0.05);
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border-left: 1px solid #555;
    border-bottom-right-radius: 4px;
    background: rgba(255,255,255,0.05);
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {t['primary']};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    width: 0px;
    height: 0px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid white;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    width: 0px;
    height: 0px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid white;
}}
/* Pulsante toggle (es. ORIGINALE in CFG Editor): bordo evidenziato quando attivo. */
QPushButton[class="ToggleBtn"] {{
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid {t['glass_border']};
    color: white;
    padding: 8px 15px;
    border-radius: {t['radius_sm']};
    font-weight: 600;
}}
QPushButton[class="ToggleBtn"]:hover {{
    background: rgba(255, 255, 255, 0.15);
}}
QPushButton[class="ToggleBtn"][active="true"] {{
    background: rgba(255, 46, 46, 0.18);
    border: 2px solid {t['primary']};
    color: {t['primary']};
}}
/* Tab bar per VEN / Profile1 nel CFG Editor */
QTabWidget::pane {{
    border: 1px solid {t['glass_border']};
    border-radius: {t['radius_sm']};
    background: transparent;
    top: -1px;
}}
QTabBar::tab {{
    background: rgba(255,255,255,0.04);
    color: {t['text_dim']};
    padding: 7px 18px;
    border: 1px solid {t['glass_border']};
    border-bottom: none;
    border-top-left-radius: {t['radius_sm']};
    border-top-right-radius: {t['radius_sm']};
    margin-right: 3px;
    font-size: 12px;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    background: rgba(255,255,255,0.10);
    color: white;
}}
QTabBar::tab:selected {{
    background: rgba(255, 46, 46, 0.15);
    color: {t['primary']};
    border: 1px solid {t['primary']};
    border-bottom: 2px solid {t['primary']};
}}
QFrame#Card {{
    background: {t['glass_bg']};
    border: 1px solid {t['glass_border']};
    border-radius: {t['radius']};
}}
QFrame#NotifyCard {{
    background: #1a1a1e;
    border: 1px solid {t['glass_border']};
    border-left: 4px solid {t['primary']};
    border-radius: 8px;
}}
QPushButton#ActionBtn {{
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid {t['glass_border']};
    color: white;
    padding: 8px 15px;
    border-radius: {t['radius_sm']};
    font-weight: 600;
}}
QPushButton#ActionBtn:hover {{
    background: rgba(255, 255, 255, 0.15);
    border: 1px solid white;
}}
QPushButton#ActionBtn:disabled {{
    background: rgba(255, 255, 255, 0.03);
    color: #555;
    border: 1px solid #333;
}}
QPushButton#ApplyBtn {{
    background: {t['primary']};
    color: white;
    border: none;
    padding: 8px 20px;
    border-radius: {t['radius_sm']};
    font-weight: bold;
}}
QPushButton#ApplyBtn:hover {{
    background: {t['primary_hover']};
}}
QPushButton#ApplyBtn:disabled {{
    background: #555;
    color: #888;
}}
QPushButton#WinBtn {{
    background: transparent;
    border: none;
    color: {t['text_dim']};
    font-size: 14px;
    border-radius: 4px;
}}
QPushButton#WinBtn:hover {{
    background: rgba(255,255,255,0.1);
    color: white;
}}
QListWidget {{
    background: {t['glass_bg']};
    border: 1px solid {t['glass_border']};
    border-radius: {t['radius']};
    outline: none;
    padding: 5px;
}}
QListWidget::item {{
    padding: 10px;
    border-radius: {t['radius_sm']};
    margin-bottom: 2px;
    color: {t['text_dim']};
}}
QListWidget::item:hover {{
    background: rgba(255, 255, 255, 0.05);
    color: white;
}}
QListWidget::item:selected {{
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255,255,255,0.2);
    color: white;
}}
QTableWidget {{
    background: {t['glass_bg']};
    border: 1px solid {t['glass_border']};
    gridline-color: #333;
    color: white;
    border-radius: 8px;
}}
QHeaderView::section {{
    background: {t['bg_panel']};
    color: #aaa;
    border: none;
    padding: 6px;
    font-weight: bold;
}}
QFrame#TelemBox {{
    background: rgba(0,0,0,0.2);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: {t['radius_sm']};
}}
QLabel#TelemVal {{
    font-size: 16px;
    font-weight: bold;
    color: white;
}}
QLabel#TelemLbl {{
    font-size: 11px;
    color: #888;
    text-transform: uppercase;
    font-weight: 600;
}}
QLabel#ActiveProfileLabel {{
    font-size: 22px;
    font-weight: 700;
    color: white;
}}
QLabel#ActiveAppLabel {{
    color: {t['text_dim']};
    font-size: 14px;
    margin-top: 5px;
}}
QLabel#DefaultStatusLabel {{
    font-size: 15px;
    font-weight: 600;
    color: {t['primary']};
}}
QLabel#DefaultSubLabel {{
    color: {t['text_dim']};
    font-size: 12px;
}}
QLabel#PageTitle {{
    font-size: 20px;
    font-weight: 700;
    color: white;
}}
QLabel#SectionTitle {{
    font-size: 20px;
    font-weight: bold;
    color: {t['primary']};
    margin-bottom: 10px;
}}
QLabel#SectionTitleMargin {{
    font-size: 20px;
    font-weight: bold;
    color: {t['primary']};
    margin-bottom: 20px;
}}
QLabel#MsiStatusRunning {{
    color: {t['success']};
    font-size: 12px;
    margin-top: 5px;
}}
QLabel#MsiStatusStopped {{
    color: {t['warning']};
    font-size: 12px;
    margin-top: 5px;
}}
QLabel#CompareSectionTitle {{
    font-size: 16px;
    font-weight: bold;
    color: {t['primary']};
}}
QLabel#HistoryComboLabel {{
    color: white;
    font-size: 14px;
}}
QLabel#StatPill {{
    background: rgba(255,255,255,0.05);
    border: 1px solid {t['glass_border']};
    border-radius: 6px;
    padding: 6px 10px;
    color: white;
    font-size: 12px;
}}
QCheckBox {{
    color: #ccc;
    spacing: 8px;
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #555;
    background: #222;
}}
QCheckBox::indicator:checked {{
    background: {t['primary']};
    border-color: {t['primary']};
}}
QLineEdit {{
    background: {t['bg_input']};
    border: 1px solid #444;
    color: white;
    padding: 5px;
    border-radius: 4px;
}}
QLineEdit:focus {{
    border-color: {t['primary']};
}}
QLineEdit#SearchBox {{
    background: {t['bg_input']};
    border: 1px solid {t['glass_border']};
    color: white;
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 13px;
}}
QLineEdit#SearchBox:focus {{
    border-color: {t['primary']};
}}
QTextEdit {{
    background: {t['bg_panel']};
    color: #aaa;
    border: 1px solid #333;
    border-radius: 8px;
    font-family: Consolas;
}}
QMenu {{
    background: {t['bg_panel']};
    color: white;
    border: 1px solid {t['glass_border']};
    border-radius: {t['radius_sm']};
    padding: 5px;
}}
QMenu::item {{
    padding: 8px 25px 8px 15px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {t['primary']};
}}
QMenu::separator {{
    height: 1px;
    background: {t['glass_border']};
    margin: 5px 10px;
}}
QComboBox {{
    background: {t['bg_input']};
    border: 1px solid #444;
    color: white;
    padding: 5px 10px;
    border-radius: 4px;
    min-width: 80px;
}}
QComboBox:hover {{
    border-color: {t['primary']};
}}
QComboBox QAbstractItemView {{
    background: {t['bg_panel']};
    color: white;
    selection-background-color: {t['primary']};
    border: 1px solid {t['glass_border']};
}}
"""


STYLESHEET: str = build_stylesheet(THEME)
