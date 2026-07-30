"""
themes.liquid_glass.main_window — MainWindow del tema "Liquid Glass".

Strategia: NON duplichiamo le ~2400 righe della MainWindow di red_glossy.
Il tema:
    1. inietta la palette liquid nel THEME condiviso di red_glossy
       (mutazione in-place: tutti i lookup runtime `THEME[...]` la vedono);
    2. rigenera lo stylesheet base con i nuovi token e lo arricchisce
       con il layer QSS liquid (gradienti, glow, raggi ampi);
    3. SOLO DOPO importa la MainWindow di red_glossy (che a quel punto
       "nasce" già liquida) e la estende con le animazioni:
         - fade-in della finestra alla comparsa;
         - transizioni di pagina con dissolvenza (QGraphicsOpacityEffect);
         - acrylic Windows con tinta blu profonda;
         - bordo dipinto con glow ciano.

Nota: il cambio tema a runtime richiede comunque il riavvio dell'app
(come già previsto dal selettore temi), quindi la mutazione in-place del
THEME condiviso è sicura: in un processo vive un solo tema.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, QRectF, Qt,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsOpacityEffect

# ── STEP 1: re-skin del modulo style di red_glossy PRIMA di ogni import UI ──
from themes.red_glossy import style as _rg_style
from .style import LIQUID_THEME, build_liquid_stylesheet

_rg_style.THEME.update(LIQUID_THEME)              # mutazione in-place
_rg_style.STYLESHEET = build_liquid_stylesheet(_rg_style.THEME)

# Pubblica il tema liquido ai componenti riusabili (cfg_editor, ecc.)
from widgets_common.theme_context import set_current_theme
set_current_theme(_rg_style.THEME)

# ── STEP 2: ora (e solo ora) importiamo la MainWindow di red_glossy ────────
from themes.red_glossy.main_window import OCProfilesManager  # noqa: E402
from themes.base import AppContext  # noqa: E402,F401

logger = logging.getLogger(__name__)

_FADE_MS = 320          # fade-in finestra
_PAGE_FADE_MS = 220     # dissolvenza cambio pagina


class LiquidGlassManager(OCProfilesManager):
    """MainWindow Liquid Glass: skin + animazioni sopra la UI red_glossy."""

    def __init__(self, ctx: "AppContext"):
        super().__init__(ctx)
        # Riafferma lo stylesheet liquid (difensivo: se la superclass
        # avesse cache-ato la vecchia stringa non succede nulla di male).
        self.setStyleSheet(_rg_style.STYLESHEET)
        self._win_fade: QPropertyAnimation | None = None
        self._page_fade: QPropertyAnimation | None = None
        logger.info("Tema Liquid Glass attivo")

    # ================================================================
    # ANIMAZIONE 1 — Fade-in della finestra
    # ================================================================

    def show_window(self) -> None:  # override
        self.setWindowOpacity(0.0)
        super().show_window()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(_FADE_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._win_fade = anim

    # ================================================================
    # ANIMAZIONE 2 — Transizione di pagina con dissolvenza
    # ================================================================

    def _switch_page(self, idx: int) -> None:  # override
        prev_idx = self.pages.currentIndex() if hasattr(self, "pages") else -1
        super()._switch_page(idx)
        # Se la superclass ha bloccato il cambio (modifiche non salvate)
        # o la pagina non è cambiata, niente animazione.
        if not hasattr(self, "pages") or self.pages.currentIndex() == prev_idx:
            return
        page = self.pages.currentWidget()
        if page is None:
            return
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", page)
        anim.setDuration(_PAGE_FADE_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        # A fine animazione rimuovi l'effect: alcuni widget (pyqtgraph)
        # renderizzano meglio senza un QGraphicsEffect permanente.
        anim.finished.connect(lambda p=page: p.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._page_fade = anim

    # ================================================================
    # ANIMAZIONE 3 — Acrylic Windows con tinta blu profonda
    # ================================================================

    def _apply_glass_effect(self) -> None:  # override
        import os
        if os.name != "nt":
            return
        try:
            import ctypes

            class AccentPolicy(ctypes.Structure):
                _fields_ = [
                    ("state", ctypes.c_int), ("flags", ctypes.c_int),
                    ("color", ctypes.c_int), ("anim", ctypes.c_int),
                ]

            class WinCompData(ctypes.Structure):
                _fields_ = [
                    ("attrib", ctypes.c_int),
                    ("data", ctypes.POINTER(AccentPolicy)),
                    ("size", ctypes.c_int),
                ]

            # state=4 = ACCENT_ENABLE_ACRYLICBLURBEHIND (fallback: 3 blur)
            # color ABGR: tinta blu notte molto leggera
            for state in (4, 3):
                accent = AccentPolicy(
                    state=state, flags=2, color=0x33261407, anim=0)
                data = WinCompData(
                    attrib=19,
                    data=ctypes.pointer(accent),
                    size=ctypes.sizeof(accent),
                )
                res = ctypes.windll.user32.SetWindowCompositionAttribute(
                    int(self.winId()), ctypes.pointer(data),
                )
                if res:
                    break
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Liquid glass effect: {e}")

    # ================================================================
    # Bordo dipinto: glow ciano sui bordi arrotondati
    # ================================================================

    def paintEvent(self, event) -> None:  # override
        radius_str = str(
            _rg_style.THEME.get("window_radius", "18px"),
        ).replace("px", "").strip()
        try:
            radius = float(radius_str)
        except Exception:  # noqa: BLE001
            radius = 18.0
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Velo quasi invisibile: lascia passare l'acrylic ma clippa gli angoli
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 1))
        p.drawRoundedRect(rect, radius, radius)
        # Doppio bordo: glow ciano esterno + linea di rifrazione bianca
        glow = QPen(QColor(77, 214, 255, 46))
        glow.setWidthF(2.0)
        p.setPen(glow)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        edge = QPen(QColor(255, 255, 255, 34))
        edge.setWidthF(1.0)
        p.setPen(edge)
        p.drawRoundedRect(rect, radius, radius)
        p.end()
