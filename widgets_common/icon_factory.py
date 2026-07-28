"""
widgets_common.icon_factory — IconFactory condivisa basata su Segoe MDL2 Assets.

Estratta da oc_widgets.py originale per essere riusabile da qualunque tema.
NON dipende dal tema (il colore è passato per parametro): i temi possono
usarla così com'è o estenderla.

Esempio d'uso in un tema:
    from widgets_common.icon_factory import IconFactory
    btn.setIcon(IconFactory.get_icon("play", "#ff2e2e"))
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


class IconFactory:
    """Factory di QIcon basata su glyph Segoe MDL2 Assets, con cache."""

    _GLYPH_MAP: dict = {
        "dashboard": "\uE80F", "folder": "\uE8B7", "link": "\uE71B",
        "list":      "\uE8FD", "chart":  "\uE9D9", "settings": "\uE713",
        "play":      "\uE768", "play_circle": "\uE768", "plus": "\uE710",
        "gear":      "\uE713", "edit":   "\uE70F", "save":   "\uE74E",
        "trash":     "\uE74D", "power":  "\uE7E8", "reset":  "\uE72C",
        "volume":    "\uE767", "backup": "\uE896", "maximize": "\uE740",
        "restore":   "\uE73F", "compare": "\uE8F1", "history": "\uE81C",
        "minimize":  "\uE949", "close":  "\uE8BB",
        "palette":   "\uE790",  # icona per il selettore tema
    }
    _cache: dict = {}

    @classmethod
    def get_icon(cls, name: str, color: str = "#888899") -> QIcon:
        key = f"{name}_{color}"
        if key in cls._cache:
            return cls._cache[key]
        glyph = cls._GLYPH_MAP.get(name)
        icon = cls._icon_from_glyph(glyph, color) if glyph else cls._icon_fallback(color)
        cls._cache[key] = icon
        return icon

    @classmethod
    def add_glyph(cls, name: str, glyph: str) -> None:
        """Permette ai temi di aggiungere icone custom al runtime."""
        cls._GLYPH_MAP[name] = glyph

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @staticmethod
    def _icon_from_glyph(glyph: str, color: str) -> QIcon:
        pix = QPixmap(32, 32)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont("Segoe MDL2 Assets", 18)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRect(0, 0, 32, 32), Qt.AlignCenter, glyph)
        p.end()
        return QIcon(pix)

    @staticmethod
    def _icon_fallback(color: str) -> QIcon:
        pix = QPixmap(32, 32)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(color))
        p.drawEllipse(8, 8, 16, 16)
        p.end()
        return QIcon(pix)
