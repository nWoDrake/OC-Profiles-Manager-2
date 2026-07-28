"""
widgets_common.lucide_icons — Icon factory con icone in stile Lucide/Material.

Implementa un set di icone moderne disegnate vettorialmente con QPainter (path
SVG semplici, no dipendenze esterne). Pensata principalmente per le icone
"preset" mostrate nella lista profili (gaming, performance, balanced, ecc.).

Caratteristiche:
- Stile Lucide: linee 2px, stroke-only, round caps, round joins.
- Badge colorato: cerchio pieno dietro l'icona, con icona bianca/scura sopra.
- Cache per evitare di ridisegnare la stessa icona N volte.

Uso:
    from widgets_common.lucide_icons import LucideIcons
    qicon = LucideIcons.badge_icon("gaming", size=32, badge_color="#ff2e2e")

Estensione: per aggiungere una nuova icona, aggiungere una entry in
_DRAWERS (key -> funzione drawer che riceve QPainter).
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)


def _setup_stroke_pen(p: QPainter, color: str, width: float = 2.0) -> None:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)


def _draw_gaming(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(2, 9, 20, 11), 5, 5)
    p.drawLine(QPointF(7, 14.5), QPointF(10, 14.5))
    p.drawLine(QPointF(8.5, 13), QPointF(8.5, 16))
    p.drawEllipse(QPointF(15.5, 13.0), 1.0, 1.0)
    p.drawEllipse(QPointF(17.5, 15.0), 1.0, 1.0)


def _draw_performance(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(13, 3)
    path.lineTo(5, 13.5)
    path.lineTo(11, 13.5)
    path.lineTo(10, 21)
    path.lineTo(19, 9.5)
    path.lineTo(13, 9.5)
    path.closeSubpath()
    p.drawPath(path)


def _draw_balanced(p: QPainter) -> None:
    p.drawLine(QPointF(12, 4), QPointF(12, 20))
    p.drawLine(QPointF(5, 7), QPointF(19, 7))
    p.drawArc(QRectF(2, 8, 8, 6), 0 * 16, -180 * 16)
    p.drawArc(QRectF(14, 8, 8, 6), 0 * 16, -180 * 16)
    p.drawLine(QPointF(8, 20), QPointF(16, 20))


def _draw_silent(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(4, 9)
    path.lineTo(8, 9)
    path.lineTo(12, 5)
    path.lineTo(12, 19)
    path.lineTo(8, 15)
    path.lineTo(4, 15)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(16, 9), QPointF(20, 13))
    p.drawLine(QPointF(20, 9), QPointF(16, 13))


def _draw_mining(p: QPainter) -> None:
    p.drawLine(QPointF(2, 22), QPointF(13, 11))
    p.drawLine(QPointF(11, 4), QPointF(20, 13))
    p.drawLine(QPointF(13, 2), QPointF(22, 11))
    p.drawLine(QPointF(11, 4), QPointF(13, 2))
    p.drawLine(QPointF(20, 13), QPointF(22, 11))


def _draw_streaming(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(2, 7, 14, 10), 2, 2)
    p.drawEllipse(QPointF(9, 12), 2.5, 2.5)
    path = QPainterPath()
    path.moveTo(18, 9)
    path.lineTo(22, 7)
    path.lineTo(22, 17)
    path.lineTo(18, 15)
    path.closeSubpath()
    p.drawPath(path)


def _draw_desktop(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(2, 4, 20, 13), 2, 2)
    p.drawLine(QPointF(8, 21), QPointF(16, 21))
    p.drawLine(QPointF(12, 17), QPointF(12, 21))


def _draw_benchmark(p: QPainter) -> None:
    p.drawArc(QRectF(3, 5, 18, 18), 30 * 16, 120 * 16)
    p.drawLine(QPointF(12, 14), QPointF(16, 9))
    p.drawEllipse(QPointF(12, 14), 1.2, 1.2)


def _draw_rendering(p: QPainter) -> None:
    p.drawLine(QPointF(12, 3), QPointF(21, 8))
    p.drawLine(QPointF(21, 8), QPointF(21, 17))
    p.drawLine(QPointF(21, 17), QPointF(12, 22))
    p.drawLine(QPointF(12, 22), QPointF(3, 17))
    p.drawLine(QPointF(3, 17), QPointF(3, 8))
    p.drawLine(QPointF(3, 8), QPointF(12, 3))
    p.drawLine(QPointF(12, 3), QPointF(12, 12))
    p.drawLine(QPointF(3, 8), QPointF(12, 12))
    p.drawLine(QPointF(21, 8), QPointF(12, 12))


def _draw_undervolt(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(4, 19)
    path.cubicTo(4, 11, 11, 4, 20, 4)
    path.cubicTo(20, 13, 13, 20, 4, 19)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(5, 19), QPointF(14, 10))


def _draw_overclock(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(11, 3)
    path.lineTo(5, 13)
    path.lineTo(10, 13)
    path.lineTo(8, 21)
    path.lineTo(15, 11)
    path.lineTo(10, 11)
    path.lineTo(11, 3)
    p.drawPath(path)
    path2 = QPainterPath()
    path2.moveTo(17, 7)
    path2.lineTo(13, 14)
    path2.lineTo(16, 14)
    path2.lineTo(15, 19)
    path2.lineTo(20, 12)
    path2.lineTo(17, 12)
    path2.lineTo(17, 7)
    p.drawPath(path2)


def _draw_stock(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(4, 11, 16, 10), 2, 2)
    p.drawArc(QRectF(7, 4, 10, 12), 0 * 16, 180 * 16)
    p.drawEllipse(QPointF(12, 16), 1.0, 1.0)


def _draw_custom(p: QPainter) -> None:
    p.drawLine(QPointF(5, 4), QPointF(5, 20))
    p.drawLine(QPointF(12, 4), QPointF(12, 20))
    p.drawLine(QPointF(19, 4), QPointF(19, 20))
    p.drawEllipse(QPointF(5, 9), 2.0, 2.0)
    p.drawEllipse(QPointF(12, 16), 2.0, 2.0)
    p.drawEllipse(QPointF(19, 11), 2.0, 2.0)


def _draw_folder(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(3, 7)
    path.lineTo(10, 7)
    path.lineTo(12, 5)
    path.lineTo(21, 5)
    path.lineTo(21, 19)
    path.lineTo(3, 19)
    path.closeSubpath()
    p.drawPath(path)


def _draw_play(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(7, 4)
    path.lineTo(20, 12)
    path.lineTo(7, 20)
    path.closeSubpath()
    p.fillPath(path, p.pen().color())


_DRAWERS: Dict[str, Callable[[QPainter], None]] = {
    "gaming": _draw_gaming, "performance": _draw_performance,
    "balanced": _draw_balanced, "silent": _draw_silent,
    "mining": _draw_mining, "streaming": _draw_streaming,
    "desktop": _draw_desktop, "benchmark": _draw_benchmark,
    "rendering": _draw_rendering, "undervolt": _draw_undervolt,
    "overclock": _draw_overclock, "stock": _draw_stock,
    "custom": _draw_custom, "folder": _draw_folder,
    "play": _draw_play,
}


class LucideIcons:
    """Factory di QIcon Lucide-like con badge colorato opzionale."""

    _cache: Dict[str, QIcon] = {}

    @classmethod
    def has(cls, key: str) -> bool:
        return key in _DRAWERS

    @classmethod
    def icon(cls, key: str, size: int = 32, color: str = "#ffffff") -> QIcon:
        cache_key = f"plain_{key}_{size}_{color}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(size / 24.0, size / 24.0)
        _setup_stroke_pen(p, color, 2.0)
        drawer = _DRAWERS.get(key, _draw_folder)
        drawer(p)
        p.end()
        icon = QIcon(pix)
        cls._cache[cache_key] = icon
        return icon

    @classmethod
    def badge_icon(
        cls, key: str, size: int = 32,
        badge_color: str = "#ff2e2e",
        glyph_color: str = "#ffffff",
        ring_color: Optional[str] = None,
    ) -> QIcon:
        """Icona con badge circolare colorato dietro al glifo."""
        cache_key = f"badge_{key}_{size}_{badge_color}_{glyph_color}_{ring_color or ''}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)

        diam = size - 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(badge_color)))
        p.drawEllipse(QPointF(size / 2, size / 2), diam / 2, diam / 2)

        if ring_color:
            ring_pen = QPen(QColor(ring_color))
            ring_pen.setWidthF(max(1.5, size * 0.08))
            p.setPen(ring_pen)
            p.setBrush(Qt.NoBrush)
            inset = ring_pen.widthF() / 2
            p.drawEllipse(QPointF(size / 2, size / 2),
                          diam / 2 - inset, diam / 2 - inset)

        glyph_size = diam * 0.60
        p.save()
        p.translate(size / 2 - glyph_size / 2, size / 2 - glyph_size / 2)
        p.scale(glyph_size / 24.0, glyph_size / 24.0)
        _setup_stroke_pen(p, glyph_color, 2.2)
        drawer = _DRAWERS.get(key, _draw_folder)
        drawer(p)
        p.restore()

        p.end()
        icon = QIcon(pix)
        cls._cache[cache_key] = icon
        return icon


__all__ = ["LucideIcons"]
