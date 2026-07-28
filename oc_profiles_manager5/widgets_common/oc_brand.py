"""widgets_common.oc_brand — Widget logo "OC" per la sidebar.

Espone due QWidget:
  * OCBrandLogo          : versione estesa (monogramma "OC" glossy + testo).
  * OCBrandLogoCollapsed : versione compatta animata (chip/GPU con linee di
                           corrente pulsanti). Animazione automatica in loop
                           ogni ~2.5 s, intensificata su hover del mouse.

Entrambi i widget leggono i colori dal theme_context, quindi si adattano in
automatico al tema attivo. Per usare un altro stile in un nuovo tema basta
scrivere widget alternativi nel pacchetto del tema.
"""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from widgets_common.theme_context import get_theme


# ===========================================================================
# Util colori
# ===========================================================================

def _qcolor(value, alpha: Optional[int] = None) -> QColor:
    """Costruisce un QColor da hex/rgba con alpha opzionale override."""
    if isinstance(value, QColor):
        c = QColor(value)
    else:
        c = QColor(str(value))
    if not c.isValid():
        c = QColor("#ff2e2e")
    if alpha is not None:
        c.setAlpha(max(0, min(255, int(alpha))))
    return c


# ===========================================================================
# Logo espanso: monogramma "OC" in cerchio glossy + testo "Profiles Manager"
# ===========================================================================

class OCBrandLogo(QWidget):
    """Logo header per la sidebar quando è espansa."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("OCBrandLogo")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedHeight(64)
        self.setMinimumWidth(180)

    def sizeHint(self) -> QSize:  # noqa: D401
        return QSize(220, 64)

    def paintEvent(self, event) -> None:  # noqa: N802
        theme = get_theme()
        primary = _qcolor(theme.get("primary", "#ff2e2e"))
        primary_hover = _qcolor(theme.get("primary_hover", "#ff4d4d"))
        primary_dark = _qcolor(theme.get("primary_dark", "#cc2525"))
        text_main = _qcolor(theme.get("text_main", "#ffffff"))
        text_dim = _qcolor(theme.get("text_dim", "#888899"))

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # --- Monogramma in cerchio glossy -----------------------------------
        diameter = 40
        margin_left = 18
        cx = margin_left + diameter / 2
        cy = self.height() / 2

        # Glow esterno
        glow = QRadialGradient(QPointF(cx, cy), diameter / 2 + 6)
        glow_color = QColor(primary)
        glow_color.setAlpha(80)
        glow.setColorAt(0.55, glow_color)
        glow_color.setAlpha(0)
        glow.setColorAt(1.0, glow_color)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), diameter / 2 + 6, diameter / 2 + 6)

        # Cerchio rosso con gradiente verticale (glossy)
        grad = QLinearGradient(QPointF(cx, cy - diameter / 2), QPointF(cx, cy + diameter / 2))
        grad.setColorAt(0.0, primary_hover)
        grad.setColorAt(0.55, primary)
        grad.setColorAt(1.0, primary_dark)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawEllipse(QPointF(cx, cy), diameter / 2, diameter / 2)

        # Highlight glossy (mezzaluna superiore semitrasparente)
        highlight_path = QPainterPath()
        highlight_rect = QRectF(cx - diameter / 2 + 4, cy - diameter / 2 + 3,
                                diameter - 8, diameter / 2 - 2)
        highlight_path.addEllipse(highlight_rect)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 55))
        p.drawPath(highlight_path)

        # Lettere "OC"
        oc_font = QFont("Segoe UI", 12, QFont.Black)
        oc_font.setLetterSpacing(QFont.AbsoluteSpacing, -0.5)
        p.setFont(oc_font)
        p.setPen(QColor(255, 255, 255, 235))
        oc_rect = QRectF(cx - diameter / 2, cy - diameter / 2, diameter, diameter)
        p.drawText(oc_rect, Qt.AlignCenter, "OC")

        # --- Testo "Profiles Manager" --------------------------------------
        text_x = margin_left + diameter + 12
        text_w = max(0, self.width() - text_x - 8)

        # Riga 1: "PROFILES" in bianco bold
        title_font = QFont("Segoe UI", 11, QFont.Black)
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(title_font)
        p.setPen(text_main)
        rect_top = QRectF(text_x, cy - 16, text_w, 18)
        p.drawText(rect_top, Qt.AlignLeft | Qt.AlignVCenter, "PROFILES")

        # Riga 2: "MANAGER" in grigio
        sub_font = QFont("Segoe UI", 9, QFont.DemiBold)
        sub_font.setLetterSpacing(QFont.AbsoluteSpacing, 2.2)
        p.setFont(sub_font)
        p.setPen(text_dim)
        rect_bottom = QRectF(text_x, cy + 2, text_w, 14)
        p.drawText(rect_bottom, Qt.AlignLeft | Qt.AlignVCenter, "MANAGER")

        p.end()


# ===========================================================================
# Logo collassato: chip/GPU stilizzata con linee di corrente animate
# ===========================================================================

class OCBrandLogoCollapsed(QWidget):
    """Logo compatto animato per la sidebar collassata.

    Animazione: una "onda" di luminosità scorre lungo le linee di corrente
    che escono dal chip. In stato idle gira lentamente; al passaggio del
    mouse l'animazione accelera e il chip brilla più intenso.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("OCBrandLogoCollapsed")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(60, 60)
        self.setToolTip("OC Profiles Manager")

        self._hover = False
        self._phase = 0.0  # 0.0 → 1.0 ciclo onda
        self._intensity = 0.5  # 0.0 idle → 1.0 hover (animato)

        # Animazione idle (loop continuo, ~2.5s per ciclo, ease inout)
        self._idle_anim = QVariantAnimation(self)
        self._idle_anim.setStartValue(0.0)
        self._idle_anim.setEndValue(1.0)
        self._idle_anim.setDuration(2500)
        self._idle_anim.setLoopCount(-1)
        self._idle_anim.setEasingCurve(QEasingCurve.Linear)
        self._idle_anim.valueChanged.connect(self._on_phase_changed)
        self._idle_anim.start()

        # Animazione intensità (transizione idle <-> hover)
        self._intensity_anim = QVariantAnimation(self)
        self._intensity_anim.setDuration(280)
        self._intensity_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._intensity_anim.valueChanged.connect(self._on_intensity_changed)

    # --- API animazione -----------------------------------------------------

    def _on_phase_changed(self, value: float) -> None:
        self._phase = float(value)
        self.update()

    def _on_intensity_changed(self, value: float) -> None:
        self._intensity = float(value)
        self.update()

    def _animate_intensity_to(self, target: float) -> None:
        self._intensity_anim.stop()
        self._intensity_anim.setStartValue(self._intensity)
        self._intensity_anim.setEndValue(float(target))
        self._intensity_anim.start()

    # --- Hover handling -----------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self._animate_intensity_to(1.0)
        # Accelera il loop principale su hover (ciclo più corto)
        self._idle_anim.setDuration(1200)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._animate_intensity_to(0.5)
        self._idle_anim.setDuration(2500)
        super().leaveEvent(event)

    # --- Painting -----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        theme = get_theme()
        primary = _qcolor(theme.get("primary", "#ff2e2e"))

        # Opacità base ~50% in idle, ~85% in hover (mix con intensity)
        base_alpha = int(110 + 110 * self._intensity)  # 110..220

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        chip_size = 24
        chip_rect = QRectF(cx - chip_size / 2, cy - chip_size / 2, chip_size, chip_size)

        # --- Glow esterno (radiale, varia con intensity) -------------------
        glow_radius = chip_size * 0.95 + 8 * self._intensity
        glow = QRadialGradient(QPointF(cx, cy), glow_radius)
        glow_color = QColor(primary)
        glow_color.setAlpha(int(45 + 60 * self._intensity))
        glow.setColorAt(0.0, glow_color)
        glow_end = QColor(primary)
        glow_end.setAlpha(0)
        glow.setColorAt(1.0, glow_end)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), glow_radius, glow_radius)

        # --- Linee di corrente (4 lati, ognuno con 2 pin) ------------------
        pin_color_idle = QColor(primary)
        pin_color_idle.setAlpha(int(base_alpha * 0.6))
        pen_idle = QPen(pin_color_idle)
        pen_idle.setWidthF(1.6)
        pen_idle.setCapStyle(Qt.RoundCap)

        # ogni "pin" è un piccolo segmento che esce dal bordo del chip
        pin_len_base = 7
        pin_len_hover_bonus = 3  # +3 px quando hover

        # 4 lati, 2 pin per lato → 8 pin totali
        # Ogni pin ha un offset di fase per far scorrere l'onda
        pins = []
        # Top
        pins += [
            (chip_rect.left() + chip_size * 0.30, chip_rect.top(), 0, -1, 0.00),
            (chip_rect.left() + chip_size * 0.70, chip_rect.top(), 0, -1, 0.12),
        ]
        # Right
        pins += [
            (chip_rect.right(), chip_rect.top() + chip_size * 0.30, 1, 0, 0.25),
            (chip_rect.right(), chip_rect.top() + chip_size * 0.70, 1, 0, 0.37),
        ]
        # Bottom
        pins += [
            (chip_rect.left() + chip_size * 0.70, chip_rect.bottom(), 0, 1, 0.50),
            (chip_rect.left() + chip_size * 0.30, chip_rect.bottom(), 0, 1, 0.62),
        ]
        # Left
        pins += [
            (chip_rect.left(), chip_rect.top() + chip_size * 0.70, -1, 0, 0.75),
            (chip_rect.left(), chip_rect.top() + chip_size * 0.30, -1, 0, 0.87),
        ]

        pin_len = pin_len_base + pin_len_hover_bonus * self._intensity
        for (px, py, dx, dy, phase_off) in pins:
            # Onda: distanza in fase rispetto a self._phase
            d = (self._phase - phase_off) % 1.0
            # Bump centrato attorno a d=0.0 con larghezza 0.25
            if d > 0.5:
                d = d - 1.0
            bump = max(0.0, 1.0 - (abs(d) / 0.18))  # 0..1
            # Boost luminosità in base a intensità globale
            local_alpha = int(base_alpha * 0.55 + 110 * bump * (0.5 + 0.5 * self._intensity))
            local_alpha = max(0, min(255, local_alpha))

            col = QColor(primary)
            col.setAlpha(local_alpha)
            pen = QPen(col)
            pen.setWidthF(1.8 + 0.6 * bump)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)

            x2 = px + dx * pin_len
            y2 = py + dy * pin_len
            p.drawLine(QPointF(px, py), QPointF(x2, y2))

            # Pallino luminoso sulla cresta (visibile solo quando bump > 0.4)
            if bump > 0.35:
                dot_col = QColor(primary)
                dot_col.setAlpha(min(255, int(160 * bump + 60 * self._intensity)))
                p.setPen(Qt.NoPen)
                p.setBrush(dot_col)
                dot_r = 1.4 + 1.2 * bump
                p.drawEllipse(QPointF(x2, y2), dot_r, dot_r)

        # --- Chip body (rounded square) -----------------------------------
        body_color = QColor(primary)
        body_color.setAlpha(base_alpha)
        body_pen = QPen(body_color)
        body_pen.setWidthF(1.6)
        p.setPen(body_pen)

        body_fill = QColor(primary)
        body_fill.setAlpha(int(35 + 35 * self._intensity))
        p.setBrush(body_fill)
        p.drawRoundedRect(chip_rect, 5, 5)

        # Inner square (die)
        inner_inset = 5
        die_rect = QRectF(
            chip_rect.left() + inner_inset, chip_rect.top() + inner_inset,
            chip_rect.width() - 2 * inner_inset, chip_rect.height() - 2 * inner_inset,
        )
        die_pen = QPen(body_color)
        die_pen.setWidthF(1.0)
        p.setPen(die_pen)
        die_fill = QColor(primary)
        die_fill.setAlpha(int(60 + 60 * self._intensity))
        p.setBrush(die_fill)
        p.drawRoundedRect(die_rect, 2, 2)

        # "OC" microscopico al centro del die (visibile soprattutto in hover)
        oc_alpha = int(80 + 140 * self._intensity)
        oc_color = QColor(255, 255, 255, max(0, min(255, oc_alpha)))
        oc_font = QFont("Segoe UI", 7, QFont.Black)
        oc_font.setLetterSpacing(QFont.AbsoluteSpacing, -0.3)
        p.setFont(oc_font)
        p.setPen(oc_color)
        p.drawText(die_rect, Qt.AlignCenter, "OC")

        # Pulse leggero sulla die (alone interno che pulsa col phase)
        pulse = 0.5 + 0.5 * math.sin(self._phase * math.pi * 2)
        if self._intensity > 0.2:
            pulse_alpha = int(40 * pulse * self._intensity)
            pulse_color = QColor(255, 255, 255, pulse_alpha)
            p.setPen(Qt.NoPen)
            p.setBrush(pulse_color)
            inset = 1.5
            p.drawRoundedRect(
                die_rect.adjusted(inset, inset, -inset, -inset), 2, 2
            )

        p.end()


__all__ = ["OCBrandLogo", "OCBrandLogoCollapsed"]
