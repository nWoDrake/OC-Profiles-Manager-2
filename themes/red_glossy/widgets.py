"""
OC Profiles Manager - Widget Custom UI
Tutti gli stili sono gestiti via objectName e STYLESHEET globale.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional, Dict, List

from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QDialog, QLineEdit, QFileDialog, QStackedWidget, QGridLayout,
    QScrollArea, QSizePolicy, QComboBox,
)
from PySide6.QtCore import Qt, QRect, QTimer, QPropertyAnimation, Signal, QSize
from PySide6.QtGui import (
    QPainter, QPainterPath, QColor, QPen, QFont, QPixmap, QIcon, QLinearGradient,
)

from .style import THEME, STYLESHEET


# ============================================================================
# ICON FACTORY — Segoe MDL2 Assets
# ============================================================================

class IconFactory:
    _GLYPH_MAP: dict = {
        "dashboard": "\uE80F", "folder": "\uE8B7", "link": "\uE71B",
        "list": "\uE8FD", "chart": "\uE9D9", "settings": "\uE713",
        "play": "\uE768", "play_circle": "\uE768", "plus": "\uE710",
        "gear": "\uE713", "edit": "\uE70F", "save": "\uE74E",
        "trash": "\uE74D", "power": "\uE7E8", "reset": "\uE72C",
        "volume": "\uE767", "backup": "\uE896", "maximize": "\uE740",
        "restore": "\uE73F", "compare": "\uE8F1", "history": "\uE81C",
        "minimize": "\uE949",   # NUOVO — Segoe MDL2 "ChromeMinimize"
        "close": "\uE8BB",      # NUOVO — Segoe MDL2 "Cancel" (X)
    }
    _cache: dict = {}

    @classmethod
    def get_icon(cls, name: str, color: str = THEME["text_dim"]) -> QIcon:
        key = f"{name}_{color}"
        if key in cls._cache:
            return cls._cache[key]
        glyph = cls._GLYPH_MAP.get(name)
        icon = cls._icon_from_glyph(glyph, color) if glyph else cls._icon_fallback(color)
        cls._cache[key] = icon
        return icon

    @classmethod
    def _icon_from_glyph(cls, glyph: str, color: str) -> QIcon:
        pix = QPixmap(24, 24)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(color))
        p.setFont(QFont("Segoe MDL2 Assets", 14))
        p.drawText(QRect(0, 0, 24, 24), Qt.AlignCenter, glyph)
        p.end()
        return QIcon(pix)

    @classmethod
    def _icon_fallback(cls, color: str) -> QIcon:
        pix = QPixmap(24, 24)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 16, 16, 3, 3)
        p.end()
        return QIcon(pix)

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()


# ============================================================================
# GAUGES & CHARTS
# ============================================================================

class CircularGauge(QWidget):
    def __init__(self, title: str, suffix: str = "%", color: str = THEME["primary"], parent=None):
        super().__init__(parent)
        self.title = title
        self.suffix = suffix
        self.color = QColor(color)
        self._value: int = 0
        self.setFixedSize(120, 120)

    def set_value(self, v: int) -> None:
        self._value = max(0, min(100, v))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRect(10, 10, 100, 100)
        p.setPen(QPen(QColor(255, 255, 255, 20), 8, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, -45 * 16, 270 * 16)
        p.setPen(QPen(self.color, 8, Qt.SolidLine, Qt.RoundCap))
        span = int(270 * 16 * (self._value / 100))
        p.drawArc(rect, 225 * 16, -span)
        p.setPen(Qt.white)
        p.setFont(QFont("Segoe UI", 18, QFont.Bold))
        p.drawText(rect, Qt.AlignCenter, f"{self._value}{self.suffix}")
        p.setPen(QColor(THEME["text_dim"]))
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        p.drawText(QRect(0, 85, 120, 20), Qt.AlignCenter, self.title)
        p.end()


class TelemetryCard(QFrame):
    def __init__(self, label: str, suffix: str, parent=None):
        super().__init__(parent)
        self.setObjectName("TelemBox")
        self.suffix = suffix
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(2)
        self.val_label = QLabel("0", objectName="TelemVal")
        self.val_label.setAlignment(Qt.AlignCenter)
        self.title_label = QLabel(label, objectName="TelemLbl")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.val_label)
        layout.addWidget(self.title_label)

    def set_value(self, v) -> None:
        self.val_label.setText(f"{v} {self.suffix}")


class LiveChart(QWidget):
    def __init__(self, title: str, suffix: str, color: str, max_points: int = 60, auto_scale: bool = False, parent=None):
        super().__init__(parent)
        self.title = title
        self.suffix = suffix
        self.color = QColor(color)
        self.max_points = max_points
        self.auto_scale = auto_scale
        self._data: list = [0.0] * max_points
        self.setFixedHeight(120)
        self.setObjectName("LiveChart")
        self.setStyleSheet(f"background:{THEME['bg_panel']};border:1px solid {THEME['glass_border']};border-radius:8px;")

    def add_point(self, value: float) -> None:
        self._data.pop(0)
        self._data.append(value)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QColor(THEME["text_dim"]))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(10, 20, self.title)
        curr = self._data[-1]
        p.setPen(Qt.white)
        p.setFont(QFont("Segoe UI", 14, QFont.Bold))
        p.drawText(w - 70, 20, 60, 20, Qt.AlignRight, f"{curr}{self.suffix}")
        gr = QRect(10, 30, w - 20, h - 40)
        p.setPen(QColor(255, 255, 255, 10))
        p.drawRect(gr)
        mx = max(self._data) if self.auto_scale and max(self._data) > 0 else 100.0
        mn = min(self._data) if self.auto_scale and max(self._data) > 0 else 0.0
        if mx == mn:
            mx = mn + 10
        sx = gr.width() / (self.max_points - 1)
        path = QPainterPath()
        for i, val in enumerate(self._data):
            norm = (val - mn) / (mx - mn)
            x = gr.left() + i * sx
            y = gr.bottom() - (norm * gr.height())
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        p.setPen(QPen(self.color, 2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        path.lineTo(gr.right(), gr.bottom())
        path.lineTo(gr.left(), gr.bottom())
        grad = QLinearGradient(0, 30, 0, h - 10)
        ct = QColor(self.color)
        ct.setAlpha(50)
        ce = QColor(self.color)
        ce.setAlpha(0)
        grad.setColorAt(0, ct)
        grad.setColorAt(1, ce)
        p.setBrush(grad)
        p.setPen(Qt.NoPen)
        p.drawPath(path)
        p.end()


# ============================================================================
# USAGE BAR CHART — per History page
# ============================================================================

class UsageBarChart(QWidget):
    """Grafico a barre orizzontali per utilizzo profili."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: Dict[str, float] = {}
        self.setMinimumHeight(150)
        self.setStyleSheet(f"background:{THEME['bg_panel']};border:1px solid {THEME['glass_border']};border-radius:8px;")

    def set_data(self, data: Dict[str, float]) -> None:
        self._data = data
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        if not self._data:
            p.setPen(QColor(THEME["text_dim"]))
            p.setFont(QFont("Segoe UI", 12))
            p.drawText(self.rect(), Qt.AlignCenter, "Nessun dato disponibile")
            p.end()
            return

        w, h = self.width(), self.height()
        margin_left = 130
        margin_right = 80
        margin_top = 15
        margin_bottom = 15
        bar_area_w = w - margin_left - margin_right
        max_val = max(self._data.values()) if self._data.values() else 1.0
        if max_val == 0:
            max_val = 1.0

        sorted_data = sorted(self._data.items(), key=lambda x: x[1], reverse=True)
        bar_count = len(sorted_data)
        bar_h = min(30, max(15, (h - margin_top - margin_bottom) // max(bar_count, 1) - 5))

        colors = [
            QColor("#ff2e2e"), QColor("#00ff88"), QColor("#ffaa00"),
            QColor("#4488ff"), QColor("#ff44ff"), QColor("#44ffff"),
            QColor("#ff8844"), QColor("#88ff44"),
        ]

        for i, (name, hours) in enumerate(sorted_data):
            y = margin_top + i * (bar_h + 5)
            if y + bar_h > h - margin_bottom:
                break
            p.setPen(QColor(THEME["text_dim"]))
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(5, y, margin_left - 10, bar_h, Qt.AlignVCenter | Qt.AlignRight, name)
            bar_w = int((hours / max_val) * bar_area_w)
            bar_w = max(bar_w, 3)
            color = colors[i % len(colors)]
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(margin_left, y, bar_w, bar_h, 4, 4)
            p.setPen(Qt.white)
            p.setFont(QFont("Segoe UI", 9, QFont.Bold))
            p.drawText(
                margin_left + bar_w + 5, y, margin_right - 10, bar_h,
                Qt.AlignVCenter | Qt.AlignLeft, f"{hours:.1f}h"
            )

        p.end()


# ============================================================================
# DIALOGS
# ============================================================================

class StyledMessageBox(QDialog):
    """
    Dialog di conferma/notifica.

    Tastiera:
      - Invio  -> conferma (OK)
      - Esc    -> annulla (se show_cancel) o chiude
    """

    def __init__(self, title: str, text: str, show_cancel: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._has_cancel = bool(show_cancel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        container = QFrame()
        container.setObjectName("NotifyCard")
        container.setStyleSheet(STYLESHEET)
        layout.addWidget(container)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(20, 20, 20, 20)
        lbl_t = QLabel(title, objectName="CompareSectionTitle")
        inner.addWidget(lbl_t)
        lbl_tx = QLabel(text)
        lbl_tx.setStyleSheet("color:white;margin-top:5px;margin-bottom:15px;")
        lbl_tx.setWordWrap(True)
        inner.addWidget(lbl_tx)
        bl = QHBoxLayout()
        bl.addStretch()
        if show_cancel:
            bc = QPushButton("ANNULLA", objectName="ActionBtn")
            bc.clicked.connect(self.reject)
            bc.setAutoDefault(False)
            bl.addWidget(bc)
        bo = QPushButton("OK", objectName="ApplyBtn")
        bo.clicked.connect(self.accept)
        bo.setDefault(True)
        bo.setAutoDefault(True)
        bl.addWidget(bo)
        inner.addLayout(bl)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(event)


class StyledInputDialog(QDialog):
    """
    Dialog con campo di testo.

    Tastiera:
      - Invio in QLineEdit -> conferma
      - Esc                -> annulla
    """

    def __init__(self, title: str, label_text: str, default_value: str = "", parent=None):
        super().__init__(parent)
        self.text_value: Optional[str] = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        container = QFrame()
        container.setObjectName("NotifyCard")
        container.setStyleSheet(STYLESHEET)
        layout.addWidget(container)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(20, 20, 20, 20)
        lbl_t = QLabel(title, objectName="CompareSectionTitle")
        inner.addWidget(lbl_t)
        lbl_d = QLabel(label_text)
        lbl_d.setStyleSheet("color:#aaa;margin-bottom:5px;")
        inner.addWidget(lbl_d)
        self.input_field = QLineEdit(default_value)
        self.input_field.selectAll()
        self.input_field.returnPressed.connect(self._accept)
        inner.addWidget(self.input_field)
        bl = QHBoxLayout()
        bl.addStretch()
        bc = QPushButton("ANNULLA", objectName="ActionBtn")
        bc.clicked.connect(self.reject)
        bc.setAutoDefault(False)
        bl.addWidget(bc)
        bk = QPushButton("CONFERMA", objectName="ApplyBtn")
        bk.clicked.connect(self._accept)
        bk.setDefault(True)
        bk.setAutoDefault(True)
        bl.addWidget(bk)
        inner.addLayout(bl)
        self.input_field.setFocus()

    def _accept(self):
        self.text_value = self.input_field.text()
        self.accept()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._accept()
            return
        super().keyPressEvent(event)


# ============================================================================
# ASSOCIATION CREATE DIALOG
# ============================================================================

class AssociationCreateDialog(QDialog):
    """
    Dialog per creare una nuova associazione tra un eseguibile e un profilo.

    Output dopo accept(): self.profile_name, self.exe_name

    Tastiera:
      - Invio  -> conferma (se entrambi i campi sono validi)
      - Esc    -> annulla

    Stylable: per cambiare aspetto in un tema futuro, riscrivere la classe in
    themes/<tuo_tema>/widgets.py e usarla nel main_window di quel tema.
    """

    def __init__(self, profiles, parent=None):
        super().__init__(parent)
        self.profile_name = None
        self.exe_name = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        container = QFrame()
        container.setObjectName("NotifyCard")
        container.setStyleSheet(STYLESHEET)
        container.setMinimumWidth(460)
        layout.addWidget(container)

        inner = QVBoxLayout(container)
        inner.setContentsMargins(22, 22, 22, 22)
        inner.setSpacing(10)

        title = QLabel("Crea nuova associazione", objectName="CompareSectionTitle")
        inner.addWidget(title)

        subtitle = QLabel(
            "Associa un eseguibile (.exe) a un profilo di overclock. "
            "Quando il programma rileva l'eseguibile in esecuzione, "
            "applicherà automaticamente il profilo associato."
        )
        subtitle.setStyleSheet(
            f"color:{THEME['text_dim']};font-size:12px;margin-bottom:8px;"
        )
        subtitle.setWordWrap(True)
        inner.addWidget(subtitle)

        lbl_prof = QLabel("Profilo")
        lbl_prof.setStyleSheet("color:#ccc;font-size:13px;font-weight:600;")
        inner.addWidget(lbl_prof)

        self.cmb_profile = QComboBox()
        self.cmb_profile.setMinimumHeight(32)
        for p in profiles:
            self.cmb_profile.addItem(p)
        inner.addWidget(self.cmb_profile)

        lbl_exe = QLabel("Eseguibile (.exe)")
        lbl_exe.setStyleSheet("color:#ccc;font-size:13px;font-weight:600;margin-top:6px;")
        inner.addWidget(lbl_exe)

        exe_row = QHBoxLayout()
        exe_row.setSpacing(8)
        self.input_exe = QLineEdit()
        self.input_exe.setPlaceholderText("es. game.exe oppure clicca SFOGLIA")
        self.input_exe.setMinimumHeight(32)
        exe_row.addWidget(self.input_exe, 1)

        btn_browse = QPushButton("SFOGLIA", objectName="ActionBtn")
        btn_browse.setAutoDefault(False)
        btn_browse.clicked.connect(self._browse_exe)
        exe_row.addWidget(btn_browse)
        inner.addLayout(exe_row)

        inner.addSpacing(8)
        bl = QHBoxLayout()
        bl.addStretch()
        btn_cancel = QPushButton("ANNULLA", objectName="ActionBtn")
        btn_cancel.clicked.connect(self.reject)
        btn_cancel.setAutoDefault(False)
        bl.addWidget(btn_cancel)
        btn_ok = QPushButton("CREA", objectName="ApplyBtn")
        btn_ok.clicked.connect(self._on_confirm)
        btn_ok.setDefault(True)
        btn_ok.setAutoDefault(True)
        bl.addWidget(btn_ok)
        inner.addLayout(bl)

        if profiles:
            self.input_exe.setFocus()
        else:
            self.cmb_profile.setEnabled(False)
            btn_ok.setEnabled(False)

        self.input_exe.returnPressed.connect(self._on_confirm)

    def _browse_exe(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "Seleziona eseguibile", "C:\\", "Eseguibili (*.exe)"
        )
        if fp:
            self.input_exe.setText(Path(fp).name)

    def _on_confirm(self):
        prof = self.cmb_profile.currentText().strip()
        exe = self.input_exe.text().strip()
        if not prof or not exe:
            return
        exe = Path(exe).name
        if not exe.lower().endswith(".exe"):
            exe += ".exe"
        self.profile_name = prof
        self.exe_name = exe
        self.accept()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._on_confirm()
            return
        super().keyPressEvent(event)


# ============================================================================
# NOTIFICATIONS
# ============================================================================

class ExternalToast(QWidget):
    def __init__(self, message: str, title: str = "OC Profiles Manager"):
        super().__init__()
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        container = QFrame()
        container.setObjectName("NotifyCard")
        container.setStyleSheet(STYLESHEET)
        container.setFixedSize(320, 75)
        cl = QVBoxLayout(container)
        lt = QLabel(title, objectName="CompareSectionTitle")
        lt.setStyleSheet(f"font-size:10px;font-weight:900;")
        cl.addWidget(lt)
        lm = QLabel(message)
        lm.setStyleSheet("color:white;font-weight:600;font-size:13px;")
        cl.addWidget(lm)
        layout.addWidget(container)
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            self.move(geom.width() - 340, geom.height() - 95)
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(400)
        self.anim.setStartValue(0)
        self.anim.setEndValue(1)

    def show_toast(self, duration_ms: int = 4000):
        self.show()
        self.anim.start()
        QTimer.singleShot(duration_ms, self.close)


# ============================================================================
# WIZARD
# ============================================================================

class WizardProgressBar(QWidget):
    def __init__(self, total_steps: int = 3, parent=None):
        super().__init__(parent)
        self.total_steps = total_steps
        self.current_step = 0
        self.setFixedHeight(80)

    def set_step(self, step: int):
        self.current_step = step
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        cy = 30
        sw = w / (self.total_steps + 1)
        pos = [sw * (i + 1) for i in range(self.total_steps)]
        for i in range(len(pos) - 1):
            c = QColor(THEME["success"]) if i < self.current_step else QColor(THEME["glass_border"])
            p.setPen(QPen(c, 3))
            p.drawLine(int(pos[i] + 15), cy, int(pos[i + 1] - 15), cy)
        labels = ["Setup", "Profilo Base", "Fine"]
        for i, x in enumerate(pos):
            if i < self.current_step:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(THEME["success"]))
                p.drawEllipse(int(x - 15), cy - 15, 30, 30)
                p.setPen(QPen(Qt.white, 2))
                ck = QPainterPath()
                ck.moveTo(x - 6, cy)
                ck.lineTo(x - 2, cy + 5)
                ck.lineTo(x + 6, cy - 5)
                p.drawPath(ck)
            elif i == self.current_step:
                p.setPen(QPen(QColor(THEME["primary"]), 3))
                p.setBrush(QColor(THEME["primary"]))
                p.drawEllipse(int(x - 15), cy - 15, 30, 30)
                p.setPen(Qt.white)
                p.setFont(QFont("Segoe UI", 12, QFont.Bold))
                p.drawText(QRect(int(x - 15), cy - 15, 30, 30), Qt.AlignCenter, str(i + 1))
            else:
                p.setPen(QPen(QColor(THEME["glass_border"]), 2))
                p.setBrush(QColor(THEME["bg_panel"]))
                p.drawEllipse(int(x - 15), cy - 15, 30, 30)
                p.setPen(QColor(THEME["text_dim"]))
                p.setFont(QFont("Segoe UI", 10, QFont.Bold))
                p.drawText(QRect(int(x - 15), cy - 15, 30, 30), Qt.AlignCenter, str(i + 1))
            lbl_color = THEME["primary"] if i == self.current_step else THEME["text_dim"]
            lbl_weight = QFont.Bold if i == self.current_step else QFont.Normal
            p.setPen(QColor(lbl_color))
            p.setFont(QFont("Segoe UI", 9, lbl_weight))
            p.drawText(QRect(int(x - 50), cy + 25, 100, 20), Qt.AlignCenter, labels[i])
        p.end()


# ============================================================================
# PROFILE ICON SELECTOR DIALOG
# ============================================================================

class ProfileIconSelector(QDialog):
    """Dialog per scegliere icona profilo: preset o custom PNG."""

    def __init__(self, current_key: str = "", current_custom: str = "", parent=None):
        super().__init__(parent)
        self.selected_key: str = current_key
        self.selected_custom: str = current_custom
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(500, 420)
        self._init_ui()

    def _init_ui(self):
        from constants import PROFILE_PRESET_ICONS
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("NotifyCard")
        container.setStyleSheet(STYLESHEET)
        layout.addWidget(container)

        inner = QVBoxLayout(container)
        inner.setContentsMargins(20, 20, 20, 20)
        inner.setSpacing(12)

        title = QLabel("Scegli Icona Profilo", objectName="CompareSectionTitle")
        inner.addWidget(title)

        subtitle = QLabel("Seleziona un'icona predefinita o carica un'immagine PNG.")
        subtitle.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 12px; margin-bottom: 8px;")
        inner.addWidget(subtitle)

        grid_frame = QFrame()
        grid_frame.setStyleSheet(
            f"background: rgba(0,0,0,0.2); border: 1px solid {THEME['glass_border']}; "
            f"border-radius: 8px; padding: 8px;"
        )
        grid = QGridLayout(grid_frame)
        grid.setSpacing(6)

        self._icon_buttons: dict = {}
        row, col = 0, 0
        max_cols = 5

        btn_none = QPushButton("\u2715")
        btn_none.setFixedSize(48, 48)
        btn_none.setToolTip("Nessuna icona")
        btn_none.setStyleSheet(self._icon_btn_style(self.selected_key == "" and not self.selected_custom))
        btn_none.clicked.connect(lambda: self._select_preset(""))
        grid.addWidget(btn_none, row, col)
        self._icon_buttons[""] = btn_none
        col += 1

        for key, preset in PROFILE_PRESET_ICONS.items():
            btn = QPushButton()
            btn.setFixedSize(48, 48)
            btn.setToolTip(preset["label"])
            btn.setIcon(self._make_preset_icon(preset["glyph"], preset["color"], 32))
            btn.setIconSize(QSize(32, 32))
            is_selected = (key == self.selected_key and not self.selected_custom)
            btn.setStyleSheet(self._icon_btn_style(is_selected))
            btn.clicked.connect(lambda _, k=key: self._select_preset(k))
            grid.addWidget(btn, row, col)
            self._icon_buttons[key] = btn
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        inner.addWidget(grid_frame)

        custom_row = QHBoxLayout()
        self.lbl_custom = QLabel("Custom: Nessuno")
        if self.selected_custom:
            name = Path(self.selected_custom).name
            self.lbl_custom.setText(f"Custom: {name}")
        self.lbl_custom.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 11px;")
        btn_browse = QPushButton("CARICA PNG", objectName="ActionBtn")
        btn_browse.clicked.connect(self._browse_custom)
        btn_clear = QPushButton("RIMUOVI", objectName="ActionBtn")
        btn_clear.clicked.connect(self._clear_custom)
        custom_row.addWidget(self.lbl_custom, 1)
        custom_row.addWidget(btn_browse)
        custom_row.addWidget(btn_clear)
        inner.addLayout(custom_row)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(64, 64)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            f"background: rgba(255,255,255,0.05); border: 1px solid {THEME['glass_border']}; "
            f"border-radius: 8px;"
        )
        self._update_preview()

        preview_row = QHBoxLayout()
        preview_row.addStretch()
        preview_row.addWidget(QLabel("Anteprima:"))
        preview_row.addWidget(self.preview_label)
        preview_row.addStretch()
        inner.addLayout(preview_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("ANNULLA", objectName="ActionBtn")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("CONFERMA", objectName="ApplyBtn")
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        inner.addLayout(btn_row)

    def _icon_btn_style(self, selected: bool) -> str:
        if selected:
            return (
                f"background: rgba(255,46,46,0.3); border: 2px solid {THEME['primary']}; "
                f"border-radius: 8px; color: white; font-size: 16px;"
            )
        return (
            f"background: rgba(255,255,255,0.05); border: 1px solid {THEME['glass_border']}; "
            f"border-radius: 8px; color: {THEME['text_dim']}; font-size: 16px;"
        )

    def _make_preset_icon(self, glyph: str, color: str, size: int = 32) -> QIcon:
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(color))
        p.setFont(QFont("Segoe MDL2 Assets", int(size * 0.6)))
        p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, glyph)
        p.end()
        return QIcon(pix)

    def _select_preset(self, key: str):
        self.selected_key = key
        self.selected_custom = ""
        self.lbl_custom.setText("Custom: Nessuno")
        for k, btn in self._icon_buttons.items():
            btn.setStyleSheet(self._icon_btn_style(k == key))
        self._update_preview()

    def _browse_custom(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "Seleziona icona PNG", "",
            "Immagini (*.png *.jpg *.jpeg *.bmp *.ico)"
        )
        if fp:
            self.selected_custom = fp
            self.selected_key = ""
            self.lbl_custom.setText(f"Custom: {Path(fp).name}")
            for k, btn in self._icon_buttons.items():
                btn.setStyleSheet(self._icon_btn_style(False))
            self._update_preview()

    def _clear_custom(self):
        self.selected_custom = ""
        self.lbl_custom.setText("Custom: Nessuno")
        self._update_preview()

    def _update_preview(self):
        from constants import PROFILE_PRESET_ICONS
        if self.selected_custom and Path(self.selected_custom).exists():
            pix = QPixmap(self.selected_custom).scaled(
                48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.preview_label.setPixmap(pix)
        elif self.selected_key and self.selected_key in PROFILE_PRESET_ICONS:
            preset = PROFILE_PRESET_ICONS[self.selected_key]
            icon = self._make_preset_icon(preset["glyph"], preset["color"], 48)
            self.preview_label.setPixmap(icon.pixmap(48, 48))
        else:
            self.preview_label.clear()
            self.preview_label.setText("\u2013")
            self.preview_label.setStyleSheet(
                self.preview_label.styleSheet() + f"color: {THEME['text_dim']}; font-size: 20px;"
            )


# ============================================================================
# PROFILE CARD — Aggiornata allo stile "v1" (Layout Grid + Info dettagliate)
# ============================================================================

class ProfileCard(QFrame):
    """
    Card widget per un singolo profilo nella vista Card della libreria.
    Mostra nome, icona, stato (attivo/default) e informazioni dettagliate (Griglia stats).
    """

    clicked = Signal()
    double_clicked = Signal()
    icon_change_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        from constants import CARD_MIN_WIDTH, CARD_MAX_WIDTH, CARD_HEIGHT
        
        self.setObjectName("ProfileCard")
        # Dimensioni aggiornate prese da constants.py
        self.setMinimumWidth(CARD_MIN_WIDTH)
        self.setMaximumWidth(CARD_MAX_WIDTH)
        self.setFixedHeight(CARD_HEIGHT)
        
        self.setCursor(Qt.PointingHandCursor)
        self._selected = False
        self._info = None
        
        self._init_ui()
        self._apply_style()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # --- Top row: icon + name + badges ---
        top = QHBoxLayout()
        top.setSpacing(10)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(40, 40)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet(
            f"background: rgba(255,255,255,0.06); border-radius: 8px;"
        )
        self.icon_label.setCursor(Qt.PointingHandCursor)
        # Intercetta click sull'icona
        self.icon_label.mousePressEvent = lambda e: self.icon_change_requested.emit()
        top.addWidget(self.icon_label)

        name_col = QVBoxLayout()
        name_col.setSpacing(1)
        self.lbl_name = QLabel("Profile")
        self.lbl_name.setStyleSheet(
            "color: white; font-size: 14px; font-weight: 700; font-family: 'Segoe UI';"
        )
        name_col.addWidget(self.lbl_name)

        self.lbl_badges = QLabel("")
        self.lbl_badges.setStyleSheet("font-size: 10px;")
        name_col.addWidget(self.lbl_badges)
        top.addLayout(name_col, 1)

        layout.addLayout(top)

        # --- Separator ---
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background: {THEME['glass_border']}; max-height: 1px;")
        layout.addWidget(sep)

        # --- Stats grid (2 colonne x 3 righe) ---
        stats_grid = QGridLayout()
        stats_grid.setSpacing(3)
        stats_grid.setContentsMargins(0, 2, 0, 0)

        self.stat_labels: dict = {}
        # Definizione posizioni: (chiave, Label Visibile, riga, colonna)
        stat_defs = [
            ("core",   "CORE",    0, 0),
            ("mem",    "MEM",     0, 1),
            ("power",  "POWER",   1, 0),
            ("fan",    "FAN",     1, 1),
            ("peak_f", "PEAK F",  2, 0),
            ("peak_v", "PEAK V",  2, 1),
        ]

        for key, label, row, col in stat_defs:
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(4, 2, 4, 2)
            cell_layout.setSpacing(0)

            lbl_title = QLabel(label)
            lbl_title.setStyleSheet(
                f"color: {THEME['text_muted']}; font-size: 9px; font-weight: 700; "
                f"letter-spacing: 1px;"
            )
            lbl_val = QLabel("—")
            lbl_val.setStyleSheet(
                "color: white; font-size: 12px; font-weight: 600; font-family: 'Segoe UI';"
            )

            cell_layout.addWidget(lbl_title)
            cell_layout.addWidget(lbl_val)
            stats_grid.addWidget(cell, row, col)
            self.stat_labels[key] = lbl_val

        layout.addLayout(stats_grid)

        # --- Bottom: VF curve indicator ---
        self.lbl_curve = QLabel("")
        self.lbl_curve.setStyleSheet(
            f"color: {THEME['text_muted']}; font-size: 9px; font-weight: 600;"
        )
        layout.addWidget(self.lbl_curve)

        layout.addStretch()

    def _apply_style(self):
        """Applica lo stile in base alla selezione."""
        if self._selected:
            self.setStyleSheet(
                f"QFrame#ProfileCard {{"
                f"  background: rgba(255, 46, 46, 0.12);"
                f"  border: 2px solid {THEME['primary']};"
                f"  border-radius: {THEME['radius']};"
                f"}}"
            )
        else:
            self.setStyleSheet(
                f"QFrame#ProfileCard {{"
                f"  background: {THEME['glass_bg']};"
                f"  border: 1px solid {THEME['glass_border']};"
                f"  border-radius: {THEME['radius']};"
                f"}}"
                f"QFrame#ProfileCard:hover {{"
                f"  background: rgba(255, 255, 255, 0.08);"
                f"  border: 1px solid rgba(255, 255, 255, 0.2);"
                f"}}"
            )

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style()

    def set_info(self, info) -> None:
        """Popola la card con i dati estratti (ProfileCardInfo)."""
        self._info = info

        # 1. Nome
        self.lbl_name.setText(info.profile_name)

        # 2. Badges (Attivo / Default / Errori)
        badges = []
        if info.is_active:
            badges.append(f'<span style="color:{THEME["primary"]};font-weight:900;">● ATTIVO</span>')
        if info.is_default:
            badges.append(f'<span style="color:{THEME["success"]};font-weight:700;">★ DEFAULT</span>')
        if info.load_error:
            badges.append(f'<span style="color:{THEME["error"]};">⚠ {info.load_error}</span>')
        self.lbl_badges.setText("  ".join(badges) if badges else "")

        # 3. Icona
        self._set_icon(info)

        # 4. Statistiche Griglia
        # Core
        if info.core_clock_boost_mhz != 0:
            val = f"{info.core_clock_boost_mhz:+.0f} MHz"
            color = THEME["success"] if info.core_clock_boost_mhz > 0 else THEME["warning"]
            self.stat_labels["core"].setText(val)
            self.stat_labels["core"].setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")
        else:
            self.stat_labels["core"].setText("±0 MHz")
            self.stat_labels["core"].setStyleSheet(f"color: {THEME['text_dim']}; font-size: 12px; font-weight: 600;")

        # Mem
        if info.mem_clock_boost_mhz != 0:
            val = f"{info.mem_clock_boost_mhz:+.0f} MHz"
            color = THEME["success"] if info.mem_clock_boost_mhz > 0 else THEME["warning"]
            self.stat_labels["mem"].setText(val)
            self.stat_labels["mem"].setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")
        else:
            self.stat_labels["mem"].setText("±0 MHz")
            self.stat_labels["mem"].setStyleSheet(f"color: {THEME['text_dim']}; font-size: 12px; font-weight: 600;")

        # Power
        pwr = info.power_limit_pct if info.power_limit_pct else 100
        pwr_color = THEME["warning"] if pwr > 100 else (THEME["success"] if pwr < 100 else "white")
        self.stat_labels["power"].setText(f"{pwr}%")
        self.stat_labels["power"].setStyleSheet(f"color: {pwr_color}; font-size: 12px; font-weight: 600;")

        # Fan
        fan_text = f"{info.fan_speed_pct}%" if info.fan_mode == "Manuale" else "Auto"
        self.stat_labels["fan"].setText(fan_text)

        # Peak Freq / Volt
        if info.peak_frequency_mhz > 0:
            self.stat_labels["peak_f"].setText(f"{info.peak_frequency_mhz:.0f} MHz")
        else:
            self.stat_labels["peak_f"].setText("—")

        if info.peak_voltage_mv > 0:
            self.stat_labels["peak_v"].setText(f"{info.peak_voltage_mv:.0f} mV")
        else:
            self.stat_labels["peak_v"].setText("—")

        # 5. VF Curve Info
        if info.has_vf_curve:
            parts = [f"VF: {info.vf_point_count} punti"]
            if info.curve_is_modified:
                parts.append("MODIFICATA")
            if info.freq_at_1000mv > 0:
                parts.append(f"@1V: {info.freq_at_1000mv:.0f}MHz")
            self.lbl_curve.setText(" | ".join(parts))
            curve_color = THEME["warning"] if info.curve_is_modified else THEME["text_muted"]
            self.lbl_curve.setStyleSheet(f"color: {curve_color}; font-size: 9px; font-weight: 600;")
        else:
            self.lbl_curve.setText("VF Curve: non disponibile")

        # Highlight nome se attivo
        if info.is_active:
            self.lbl_name.setStyleSheet(f"color: {THEME['primary']}; font-size: 14px; font-weight: 700;")

    def _set_icon(self, info):
        """Gestisce il rendering dell'icona (custom PNG o preset glyph)."""
        from constants import PROFILE_PRESET_ICONS

        # A. Custom PNG
        if info.has_custom_icon:
            pix = QPixmap(info.icon_custom_path).scaled(
                32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.icon_label.setPixmap(pix)
            return

        # B. Preset Glyph
        if info.icon_key and info.icon_key in PROFILE_PRESET_ICONS:
            preset = PROFILE_PRESET_ICONS[info.icon_key]
            pix = QPixmap(32, 32)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QColor(preset["color"]))
            p.setFont(QFont("Segoe MDL2 Assets", 18))
            p.drawText(QRect(0, 0, 32, 32), Qt.AlignCenter, preset["glyph"])
            p.end()
            self.icon_label.setPixmap(pix)
            return

        # C. Fallback (Lettera)
        self.icon_label.setText(info.profile_name[0].upper() if info.profile_name else "?")
        self.icon_label.setStyleSheet(
            f"background: rgba(255,255,255,0.06); border-radius: 8px; "
            f"color: {THEME['text_dim']}; font-size: 18px; font-weight: 700;"
        )

    def get_profile_name(self) -> str:
        return self._info.profile_name if self._info else ""

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        # Propaga al parent per gestire il menu contestuale
        event.ignore()


# ============================================================================
# PROFILE CARD VIEW — Griglia responsiva (Aggiornata per nuove dimensioni)
# ============================================================================

class ProfileCardView(QWidget):
    """
    Vista a griglia di ProfileCard, alternativa alla QListWidget.
    """

    selection_changed = Signal(str)
    card_double_clicked = Signal(str)
    icon_change_requested = Signal(str)
    context_menu_requested = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._cards: Dict[str, ProfileCard] = {}
        self._selected_name: str = ""

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {THEME['bg_panel']}; width: 8px; border-radius: 4px; }}"
            f"QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.15); "
            f"border-radius: 4px; min-height: 30px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.25); }}"
        )

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;") # Assicura sfondo trasparente
        self._grid = QGridLayout(self._container)
        self._grid.setSpacing(12)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._scroll.setWidget(self._container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)

    def set_profiles(self, infos: list) -> None:
        """Aggiorna la griglia con la lista di ProfileCardInfo."""
        current_names = {info.profile_name for info in infos}

        # Rimuovi card vecchie
        for name in list(self._cards.keys()):
            if name not in current_names:
                card = self._cards.pop(name)
                self._grid.removeWidget(card)
                card.deleteLater()

        # Calcolo colonne dinamico basato sulle nuove dimensioni
        from constants import CARD_MIN_WIDTH
        available_w = self._scroll.viewport().width() - 20
        cols = max(1, available_w // (CARD_MIN_WIDTH + 12))

        # Reset layout per riordinare
        for card in self._cards.values():
            self._grid.removeWidget(card)

        # Crea o aggiorna card
        for i, info in enumerate(infos):
            name = info.profile_name
            if name in self._cards:
                card = self._cards[name]
            else:
                card = ProfileCard()
                card.clicked.connect(lambda n=name: self._on_card_clicked(n))
                card.double_clicked.connect(lambda n=name: self.card_double_clicked.emit(n))
                card.icon_change_requested.connect(lambda n=name: self.icon_change_requested.emit(n))
                self._cards[name] = card

            card.set_info(info)
            card.set_selected(name == self._selected_name)

            row = i // cols
            col = i % cols
            self._grid.addWidget(card, row, col)

    def get_selected(self) -> str:
        return self._selected_name

    def set_selected(self, name: str):
        self._selected_name = name
        for n, card in self._cards.items():
            card.set_selected(n == name)

    def _on_card_clicked(self, name: str):
        self._selected_name = name
        for n, card in self._cards.items():
            card.set_selected(n == name)
        self.selection_changed.emit(name)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._cards:
            QTimer.singleShot(50, self._relayout)

    def _relayout(self):
        """Ricalcola il grid layout."""
        from constants import CARD_MIN_WIDTH
        available_w = self._scroll.viewport().width() - 20
        cols = max(1, available_w // (CARD_MIN_WIDTH + 12))

        cards = list(self._cards.values())
        for card in cards:
            self._grid.removeWidget(card)

        for i, card in enumerate(cards):
            row = i // cols
            col = i % cols
            self._grid.addWidget(card, row, col)

    def contextMenuEvent(self, event):
        pos = event.pos()
        for name, card in self._cards.items():
            card_pos = card.mapFrom(self, pos)
            if card.rect().contains(card_pos):
                self.context_menu_requested.emit(name, event.globalPos())
                return

# ============================================================================
# SETUP WIZARD
# ============================================================================

class SetupWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.msi_path: Optional[str] = None
        self.current_step = 0
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(650, 500)
        self._init_ui()

    def _init_ui(self):
        self.main_container = QFrame(self)
        self.main_container.setObjectName("NotifyCard")
        self.main_container.setStyleSheet(STYLESHEET)
        ml = QVBoxLayout(self.main_container)
        ml.setContentsMargins(30, 20, 30, 30)
        ml.setSpacing(15)
        self.progress_bar = WizardProgressBar(3)
        ml.addWidget(self.progress_bar)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{THEME['glass_border']};max-height:1px;")
        ml.addWidget(sep)
        self.stack = QStackedWidget()
        self._create_step1()
        self._create_step2()
        self._create_step3()
        ml.addWidget(self.stack)
        ol = QVBoxLayout(self)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.addWidget(self.main_container)

    def _validate_msi_installation(self, exe_path: Path) -> tuple:
        if not exe_path.exists():
            return False, "File non trovato."
        if exe_path.name.lower() != "msiafterburner.exe":
            return False, "Seleziona MSIAfterburner.exe!"
        try:
            with open(exe_path, "rb") as f:
                header = f.read(2)
                if header != b"MZ":
                    return False, "Non \u00e8 un eseguibile valido."
        except Exception:
            pass
        profiles_dir = exe_path.parent / "Profiles"
        if not profiles_dir.exists():
            return False, (
                "Directory 'Profiles' non trovata.\n"
                "Avvia MSI Afterburner almeno una volta prima di usare il manager."
            )
        return True, ""

    def _create_step1(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setSpacing(20)
        t = QLabel("Configurazione Iniziale - Passo 1/3", objectName="SectionTitle")
        t.setAlignment(Qt.AlignCenter)
        l.addWidget(t)
        st = QLabel("Benvenuto in OC Profiles Manager!\nSeleziona il percorso di MSI Afterburner.")
        st.setStyleSheet(f"font-size:14px;color:{THEME['text_dim']};margin-bottom:20px;")
        st.setAlignment(Qt.AlignCenter)
        l.addWidget(st)
        ml_label = QLabel("Percorso MSI Afterburner:")
        ml_label.setStyleSheet("font-size:14px;color:white;font-weight:600;")
        l.addWidget(ml_label)
        pl = QHBoxLayout()
        self.path_display = QLabel("Nessun file selezionato")
        self.path_display.setObjectName("PathDisplay")
        self.path_display.setStyleSheet(
            f"background:{THEME['bg_input']};border:1px solid {THEME['glass_border']};"
            f"color:{THEME['text_dim']};padding:10px;border-radius:6px;font-size:12px;"
        )
        self.path_display.setWordWrap(True)
        pl.addWidget(self.path_display, 1)
        bb = QPushButton("SFOGLIA", objectName="ActionBtn")
        bb.setIcon(IconFactory.get_icon("folder", "white"))
        bb.setFixedWidth(120)
        bb.clicked.connect(self._browse_msi_path)
        pl.addWidget(bb)
        l.addLayout(pl)
        self.step1_error = QLabel("")
        self.step1_error.setStyleSheet(f"color:{THEME['error']};font-size:11px;font-weight:bold;")
        self.step1_error.setWordWrap(True)
        self.step1_error.setVisible(False)
        l.addWidget(self.step1_error)
        it = QLabel(
            "Seleziona l'eseguibile MSIAfterburner.exe\n"
            "Tipicamente in: C:\\Program Files (x86)\\MSI Afterburner\\"
        )
        it.setStyleSheet(f"color:{THEME['text_muted']};font-size:11px;margin-top:5px;margin-bottom:20px;")
        l.addWidget(it)
        l.addStretch()
        bl = QHBoxLayout()
        bl.addStretch()
        be = QPushButton("ESCI", objectName="ActionBtn")
        be.setIcon(IconFactory.get_icon("power", "#ff5555"))
        be.clicked.connect(self.reject)
        bl.addWidget(be)
        self.btn_next_step1 = QPushButton("AVANTI", objectName="ApplyBtn")
        self.btn_next_step1.setIcon(IconFactory.get_icon("play", "white"))
        self.btn_next_step1.setEnabled(False)
        self.btn_next_step1.clicked.connect(lambda: self._go_to_step(1))
        bl.addWidget(self.btn_next_step1)
        l.addLayout(bl)
        self.stack.addWidget(page)

    def _create_step2(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setSpacing(20)
        t = QLabel("Configurazione Iniziale - Passo 2/3", objectName="SectionTitle")
        t.setAlignment(Qt.AlignCenter)
        l.addWidget(t)
        st = QLabel("Crea il profilo predefinito")
        st.setStyleSheet(f"font-size:14px;color:{THEME['text_dim']};margin-bottom:20px;")
        st.setAlignment(Qt.AlignCenter)
        l.addWidget(st)
        ic = QFrame(objectName="Card")
        il = QVBoxLayout(ic)
        il.setContentsMargins(20, 20, 20, 20)
        il.setSpacing(15)
        it_title = QLabel("Istruzioni:", objectName="CompareSectionTitle")
        il.addWidget(it_title)
        ix = QLabel(
            "1. Clicca 'Apri MSI Afterburner'\n"
            "2. Configura impostazioni BASE\n"
            "3. Salva nello SLOT 1\n"
            "4. Torna qui e clicca 'Avanti'"
        )
        ix.setStyleSheet("color:white;font-size:13px;")
        ix.setWordWrap(True)
        il.addWidget(ix)
        l.addWidget(ic)
        bo = QPushButton("APRI MSI AFTERBURNER", objectName="ApplyBtn")
        bo.setIcon(IconFactory.get_icon("play_circle", "white"))
        bo.setFixedHeight(45)
        bo.clicked.connect(self._open_msi_afterburner)
        l.addWidget(bo)
        self.step2_status = QLabel("")
        self.step2_status.setStyleSheet(f"color:{THEME['text_dim']};font-size:12px;")
        self.step2_status.setAlignment(Qt.AlignCenter)
        l.addWidget(self.step2_status)
        l.addStretch()
        bl = QHBoxLayout()
        bk = QPushButton("INDIETRO", objectName="ActionBtn")
        bk.setIcon(IconFactory.get_icon("reset", "#aaa"))
        bk.clicked.connect(lambda: self._go_to_step(0))
        bl.addWidget(bk)
        bl.addStretch()
        be = QPushButton("ESCI", objectName="ActionBtn")
        be.setIcon(IconFactory.get_icon("power", "#ff5555"))
        be.clicked.connect(self.reject)
        bl.addWidget(be)
        self.btn_next_step2 = QPushButton("AVANTI", objectName="ApplyBtn")
        self.btn_next_step2.setIcon(IconFactory.get_icon("play", "white"))
        self.btn_next_step2.clicked.connect(self._try_advance_step2)
        bl.addWidget(self.btn_next_step2)
        l.addLayout(bl)
        self.stack.addWidget(page)

    def _create_step3(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setSpacing(20)
        t = QLabel("Configurazione Iniziale - Passo 3/3")
        t.setStyleSheet(f"font-size:24px;font-weight:bold;color:{THEME['success']};margin-bottom:10px;")
        t.setAlignment(Qt.AlignCenter)
        l.addWidget(t)
        fc = QFrame(objectName="Card")
        fl = QVBoxLayout(fc)
        fl.setContentsMargins(25, 25, 25, 25)
        ft = QLabel(
            "Configurazione completata!\n\n"
            "Verranno creati:\n"
            "- ProfilesManager\n"
            "- VirginStock (base)\n"
            "- Default (attivo)"
        )
        ft.setStyleSheet("color:white;font-size:14px;")
        ft.setAlignment(Qt.AlignCenter)
        ft.setWordWrap(True)
        fl.addWidget(ft)
        l.addWidget(fc)
        l.addStretch()
        bl = QHBoxLayout()
        bk = QPushButton("INDIETRO", objectName="ActionBtn")
        bk.setIcon(IconFactory.get_icon("reset", "#aaa"))
        bk.clicked.connect(lambda: self._go_to_step(1))
        bl.addWidget(bk)
        bl.addStretch()
        be = QPushButton("ESCI", objectName="ActionBtn")
        be.setIcon(IconFactory.get_icon("power", "#ff5555"))
        be.clicked.connect(self.reject)
        bl.addWidget(be)
        bf = QPushButton("FINE", objectName="ApplyBtn")
        bf.setIcon(IconFactory.get_icon("save", "white"))
        bf.clicked.connect(self.accept)
        bl.addWidget(bf)
        l.addLayout(bl)
        self.stack.addWidget(page)

    def _go_to_step(self, step: int):
        self.current_step = step
        self.stack.setCurrentIndex(step)
        self.progress_bar.set_step(step)

    def _try_advance_step2(self):
        if not self.msi_path:
            return
        p1 = Path(self.msi_path).parent / "Profiles" / "Profile1.cfg"
        if p1.exists() and p1.stat().st_size > 0:
            self.step2_status.setText("")
            self._go_to_step(2)
        else:
            self.step2_status.setText("Profile1.cfg non trovato! Salva nello SLOT 1 in MSI Afterburner.")
            self.step2_status.setStyleSheet(f"color:{THEME['error']};font-size:12px;font-weight:bold;")

    def _browse_msi_path(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "Seleziona MSIAfterburner.exe",
            r"C:\Program Files (x86)\MSI Afterburner",
            "Eseguibili (*.exe)",
        )
        if fp:
            exe_path = Path(fp)
            is_valid, error_msg = self._validate_msi_installation(exe_path)

            if is_valid:
                self.msi_path = fp
                self.path_display.setText(fp)
                self.path_display.setStyleSheet(
                    f"background:{THEME['bg_input']};border:1px solid {THEME['primary']};"
                    f"color:white;padding:10px;border-radius:6px;font-size:12px;"
                )
                self.btn_next_step1.setEnabled(True)
                self.step1_error.setVisible(False)
            else:
                self.path_display.setText(fp)
                self.path_display.setStyleSheet(
                    f"background:{THEME['bg_input']};border:1px solid {THEME['error']};"
                    f"color:{THEME['error']};padding:10px;border-radius:6px;font-size:12px;"
                )
                self.btn_next_step1.setEnabled(False)
                self.step1_error.setText(error_msg)
                self.step1_error.setVisible(True)

    def _open_msi_afterburner(self):
        if not self.msi_path:
            return
        try:
            subprocess.Popen([self.msi_path, "-s"], creationflags=0x00000008)
            self.step2_status.setText("MSI Afterburner aperto. Salva SLOT 1 e torna qui.")
            self.step2_status.setStyleSheet(f"color:{THEME['success']};font-size:12px;")
        except Exception as e:
            self.step2_status.setText(f"Errore: {e}")
            self.step2_status.setStyleSheet(f"color:{THEME['error']};font-size:12px;")
