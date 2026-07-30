"""
VF Curve Editor Widget — integrabile come pagina nel programma principale.
Adattato al tema scuro di OC Profiles Manager.

Funzionalità:
- Shortcuts contestuali (attivi solo quando la pagina è visibile)
- Conferma salvataggio con feedback visivo
- Controllo modifiche non salvate
- Curva originale sovrapposta (ghost curve)
- Selettore file VEN_*.cfg multipli
- Indicatore stato modifiche
- Bottone APPLICA per consolidare modifiche senza salvare su file
"""

from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QComboBox, QFileDialog, QSpinBox, QDialog, QTabBar,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QShortcut, QKeySequence

import pyqtgraph as pg

# THEME non vive piu' in constants: lo leggiamo dal theme_context del tema attivo.
# In questo modo cfg_editor resta agnostico rispetto al tema e si adatta al volo.
from widgets_common.theme_context import get_theme as _get_theme


class _ThemeProxy:
    """Proxy dict-like che rilegge il tema attivo via theme_context.
    Permette agli accessi `THEME["key"]` di restare invariati senza accoppiare
    cfg_editor a un tema specifico."""

    def __getitem__(self, key):
        return _get_theme()[key]

    def get(self, key, default=None):
        return _get_theme().get(key, default)


THEME = _ThemeProxy()
from cfg_editor.cfg_model import AfterburnerCfgFile, AfterburnerProfile
from cfg_editor.vfcurve import (
    VFPoint,
    decode_vfcurve,
    encode_vfcurve,
    apply_single_point_edit_ab_like,
    compile_ab_cfg_points_for_save,
    _snap,
)

logger = logging.getLogger(__name__)


# ============================================================================
# CUSTOM VIEWBOX
# ============================================================================

class VFViewBox(pg.ViewBox):
    """ViewBox con drag editing per punti VF."""

    def __init__(self, editor: VFEditorWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        self.setMouseMode(pg.ViewBox.PanMode)
        self.setMenuEnabled(True)
        self.setAspectLocked(False)
        self.setLimits(
            xMin=200, xMax=1500,
            yMin=0, yMax=4500,
            minXRange=50, minYRange=100,
        )

    def mouseMoveEvent(self, ev):
        super().mouseMoveEvent(ev)
        if self.editor:
            view_pos = self.mapSceneToView(ev.scenePos())
            self.editor._update_mouse_coords(float(view_pos.x()), float(view_pos.y()))

    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == Qt.MouseButton.RightButton:
            return super().mouseDragEvent(ev, axis=axis)
        if ev.button() == Qt.MouseButton.LeftButton:
            if self.editor._try_handle_left_drag(ev):
                ev.accept()
                return
            return super().mouseDragEvent(ev, axis=axis)
        return super().mouseDragEvent(ev, axis=axis)

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            if not self.editor._is_click_on_scatter(ev):
                self.editor._deselect_point()
                ev.accept()
                return
        super().mouseClickEvent(ev)


# ============================================================================
# VF EDITOR WIDGET
# ============================================================================

class VFEditorWidget(QWidget):
    """
    Widget completo per editing curva VF di MSI Afterburner.

    Tre livelli di stato della curva:
    - original_base_points: i punti letti dal file (mai modificati, usati per ghost curve)
    - base_points: stato consolidato corrente (aggiornato da APPLICA)
    - current_points: preview live durante il drag di un punto

    Flusso:
    1. Drag punto → current_points aggiornati da base_points + delta
    2. APPLICA → base_points = current_points (consolida la modifica)
    3. SALVA → scrive su file
    4. RESET CURVA → base_points = original_base_points
    """

    profile_saved = Signal(str)
    has_unsaved_changes = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)

        # === State: tre livelli di curva ===
        self.cfg_file: Optional[AfterburnerCfgFile] = None
        self.current_cfg_path: Optional[Path] = None
        self.profile_section: str = "Profile1"
        self.original_vf_hex: str = ""

        # Punti dal file originale (per ghost e reset totale)
        self.original_base_points: Optional[List[VFPoint]] = None
        # Punti consolidati (aggiornati da APPLICA)
        self.base_points: Optional[List[VFPoint]] = None
        # Punti preview live (aggiornati durante drag)
        self.current_points: Optional[List[VFPoint]] = None

        # Curva di confronto (Feature C, v2.7): punti di un altro profilo
        self._compare_points: Optional[List[VFPoint]] = None
        self._compare_label: str = ""

        self.selected_index: Optional[int] = None
        self.last_edited_index: Optional[int] = None
        self.last_edited_delta_mhz: int = 0
        self._has_pending_edit: bool = False  # True quando c'è un drag non ancora applicato
        self._dirty: bool = False
        self._is_active_page: bool = False

        # Undo/Redo
        self._history: List[dict] = []
        self._history_index: int = -1
        self._max_history: int = 50

        # Valori slider salvati per dirty-check
        self._saved_core: int = 0
        self._saved_mem: int = 0
        self._saved_power: int = 100
        
        self._last_core_slider_delta: int = 0
        self._managed_cfg_paths: List[Path] = []
        self._tab_change_guard: bool = False

        self._init_ui()
        self._setup_shortcuts()

    # ================================================================
    # PAGE VISIBILITY
    # ================================================================

    def set_active(self, active: bool):
        self._is_active_page = active

    def _shortcut_guard(self, callback):
        def guarded():
            if self._is_active_page:
                callback()
        return guarded

    # ================================================================
    # DIRTY STATE
    # ================================================================

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            self.has_unsaved_changes.emit(True)
            self._update_title_dirty()

    def _mark_clean(self):
        if self._dirty:
            self._dirty = False
            self.has_unsaved_changes.emit(False)
            self._update_title_dirty()

    def _update_title_dirty(self):
        if not self.current_cfg_path:
            return
        name = self.current_cfg_path.name
        if self._dirty:
            self.lbl_file_info.setText(f"File: {name} *")
            self.lbl_file_info.setStyleSheet(
                f"color: {THEME['warning']}; font-size: 13px; font-weight: 600;"
            )
        else:
            self.lbl_file_info.setText(f"File: {name}")
            self.lbl_file_info.setStyleSheet("color: white; font-size: 13px;")

    def _check_any_changes(self) -> bool:
        """Verifica se c'è qualsiasi modifica rispetto al file originale."""
        if self._check_sliders_differ():
            return True
        if not self.current_points or not self.original_base_points:
            return False
        for curr, orig in zip(self.current_points, self.original_base_points):
            original_f = orig.f_mhz + orig.c_delta
            if abs(curr.f_mhz - original_f) > 0.1:
                return True
        return False

    def _check_sliders_differ(self) -> bool:
        return (
            self.core_slider.value() != self._saved_core
            or self.mem_slider.value() != self._saved_mem
            or self.power_slider.value() != self._saved_power
        )

    def _update_dirty_state(self):
        if self._check_any_changes():
            self._mark_dirty()
        else:
            self._mark_clean()

    def has_pending_changes(self) -> bool:
        return self._dirty

    # ================================================================
    # PENDING EDIT STATE (per bottone APPLICA)
    # ================================================================

    def _set_pending_edit(self, pending: bool):
        """Aggiorna lo stato del bottone APPLICA."""
        self._has_pending_edit = pending
        self.btn_apply_edit.setEnabled(pending)
        if pending:
            self.btn_apply_edit.setStyleSheet(
                f"background: {THEME['success']}; color: black; border: none; "
                f"padding: 8px 15px; border-radius: {THEME['radius_sm']}; font-weight: bold;"
            )
        else:
            self.btn_apply_edit.setStyleSheet("")

    # ================================================================
    # UI CONSTRUCTION
    # ================================================================

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 15, 30, 30)
        main_layout.setSpacing(12)

        header = self._create_header()
        main_layout.addLayout(header)

        file_tabs = self._create_file_tabs()
        main_layout.addWidget(file_tabs)

        toolbar = self._create_toolbar()
        main_layout.addLayout(toolbar)

        sliders_frame = self._create_sliders()
        main_layout.addWidget(sliders_frame)

        graph_frame = self._create_graph()
        main_layout.addWidget(graph_frame, 1)

        status = self._create_status()
        main_layout.addLayout(status)

    def _create_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.lbl_file_info = QLabel("Nessun file caricato")
        self.lbl_file_info.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 13px;")
        self.lbl_profile_info = QLabel("")
        self.lbl_profile_info.setStyleSheet(
            f"color: {THEME['primary']}; font-size: 13px; font-weight: 600;"
        )
        layout.addWidget(self.lbl_file_info)
        layout.addStretch()
        layout.addWidget(self.lbl_profile_info)
        return layout

    def _create_file_tabs(self) -> QFrame:
        frame = QFrame(objectName="Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        lbl = QLabel("File CFG del profilo")
        lbl.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 11px; font-weight: 700;")
        layout.addWidget(lbl)

        self.file_tabs = QTabBar()
        self.file_tabs.setDocumentMode(True)
        self.file_tabs.setDrawBase(False)
        self.file_tabs.setExpanding(False)
        self.file_tabs.currentChanged.connect(self._on_file_tab_changed)
        layout.addWidget(self.file_tabs)

        frame.setVisible(False)
        self.file_tabs_frame = frame
        return frame

    def _set_available_cfg_tabs(self, paths: List[Path], current_path: Optional[Path] = None) -> None:
        unique_paths: List[Path] = []
        seen = set()
        for p in paths:
            rp = Path(p)
            key = str(rp.resolve()) if rp.exists() else str(rp)
            if key in seen:
                continue
            seen.add(key)
            unique_paths.append(rp)

        self._managed_cfg_paths = unique_paths
        self._tab_change_guard = True
        try:
            while self.file_tabs.count():
                self.file_tabs.removeTab(0)
            for p in unique_paths:
                idx = self.file_tabs.addTab(p.name)
                self.file_tabs.setTabData(idx, str(p))
        finally:
            self._tab_change_guard = False

        visible = len(unique_paths) > 1
        self.file_tabs_frame.setVisible(visible)
        if not unique_paths:
            return

        target = Path(current_path) if current_path else unique_paths[0]
        target_str = str(target)
        for i in range(self.file_tabs.count()):
            if self.file_tabs.tabData(i) == target_str:
                self.file_tabs.setCurrentIndex(i)
                return
        self.file_tabs.setCurrentIndex(0)

    def _sync_current_file_tab(self, path: Path) -> None:
        path_str = str(path)
        for i in range(self.file_tabs.count()):
            if self.file_tabs.tabData(i) == path_str:
                self._tab_change_guard = True
                try:
                    self.file_tabs.setCurrentIndex(i)
                finally:
                    self._tab_change_guard = False
                return

    @staticmethod
    def _is_supported_cfg_path(path: Path) -> bool:
        if not path.exists() or not path.is_file():
            return False
        name = path.name
        if not (name.lower() == "profile1.cfg" or (name.upper().startswith("VEN_") and name.lower().endswith(".cfg"))):
            return False
        try:
            if path.stat().st_size <= 200:
                return False
        except OSError:
            return False
        return True

    def _on_file_tab_changed(self, index: int):
        if self._tab_change_guard or index < 0:
            return
        path_str = self.file_tabs.tabData(index)
        if not path_str:
            return
        next_path = Path(path_str)
        if self.current_cfg_path and next_path == self.current_cfg_path:
            return
        self.load_cfg_file(next_path, self.profile_section)

    def _refresh_toggle_ghost_style(self) -> None:
        active = self.btn_toggle_ghost.isChecked()
        self.btn_toggle_ghost.setProperty("active", active)
        self.btn_toggle_ghost.style().unpolish(self.btn_toggle_ghost)
        self.btn_toggle_ghost.style().polish(self.btn_toggle_ghost)

    def _create_toolbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)

        self.btn_open = QPushButton("APRI FILE", objectName="ActionBtn")
        self.btn_open.setToolTip("Apri solo file supportati (VEN_*.cfg / Profile1.cfg) — Ctrl+O")
        self.btn_open.clicked.connect(self.open_file_dialog)

        self.btn_save = QPushButton("SALVA", objectName="ApplyBtn")
        self.btn_save.setToolTip("Salva modifiche su file (Ctrl+S)")
        self.btn_save.clicked.connect(self.save_cfg)

        self.btn_apply_edit = QPushButton("✔  APPLICA", objectName="ActionBtn")
        self.btn_apply_edit.setToolTip(
            "Consolida la modifica corrente (Ctrl+Enter)\n"
            "La modifica diventa il nuovo stato base\n"
            "per le modifiche successive."
        )
        self.btn_apply_edit.setEnabled(False)
        self.btn_apply_edit.clicked.connect(self._apply_current_edit)

        self.btn_reset_curve = QPushButton("RESET CURVA", objectName="ActionBtn")
        self.btn_reset_curve.setToolTip("Ripristina solo la VF curve mantenendo il Core Clock corrente")
        self.btn_reset_curve.setEnabled(False)
        self.btn_reset_curve.clicked.connect(self._reset_curve)

        self.btn_reset_all = QPushButton("RESET", objectName="ActionBtn")
        self.btn_reset_all.setToolTip("Ripristina immediatamente i valori VirginStock del profilo corrente")
        self.btn_reset_all.setEnabled(False)
        self.btn_reset_all.clicked.connect(self._reset_all_to_virginstock)

        self.btn_reset_view = QPushButton("RESET VISTA", objectName="ActionBtn")
        self.btn_reset_view.setToolTip("Torna alla vista di default")
        self.btn_reset_view.clicked.connect(self._reset_view)

        self.btn_undo = QPushButton("UNDO", objectName="ActionBtn")
        self.btn_undo.setToolTip("Annulla (Ctrl+Z)")
        self.btn_undo.clicked.connect(self._undo)

        self.btn_redo = QPushButton("REDO", objectName="ActionBtn")
        self.btn_redo.setToolTip("Ripeti (Ctrl+Y)")
        self.btn_redo.clicked.connect(self._redo)

        self.btn_toggle_ghost = QPushButton("ORIGINALE")
        self.btn_toggle_ghost.setProperty("class", "ToggleBtn")
        self.btn_toggle_ghost.setToolTip("Mostra/nascondi la curva originale dal file")
        self.btn_toggle_ghost.setCheckable(True)
        self.btn_toggle_ghost.setChecked(True)
        self.btn_toggle_ghost.clicked.connect(self._toggle_ghost_curve)
        self._refresh_toggle_ghost_style()

        self.btn_compare = QPushButton("CONFRONTA")
        self.btn_compare.setProperty("class", "ToggleBtn")
        self.btn_compare.setToolTip(
            "Sovrapponi la curva V/F di un altro profilo per confronto")
        self.btn_compare.setCheckable(True)
        self.btn_compare.clicked.connect(self._toggle_compare_curve)
        self._refresh_compare_style()

        lbl_profile = QLabel("Profilo:")
        lbl_profile.setStyleSheet("color: white; font-size: 13px;")
        self.combo_profile = QComboBox()
        self.combo_profile.addItems([f"Profile{i}" for i in range(1, 6)])
        self.combo_profile.setMinimumWidth(120)
        self.combo_profile.currentTextChanged.connect(self._on_profile_changed)

        layout.addWidget(self.btn_open)
        layout.addWidget(self.btn_save)
        layout.addWidget(self.btn_apply_edit)
        layout.addWidget(self.btn_reset_curve)
        layout.addWidget(self.btn_reset_all)
        layout.addWidget(self.btn_reset_view)
        layout.addWidget(self.btn_undo)
        layout.addWidget(self.btn_redo)
        layout.addWidget(self.btn_toggle_ghost)
        layout.addWidget(self.btn_compare)
        layout.addSpacing(15)
        layout.addWidget(lbl_profile)
        layout.addWidget(self.combo_profile)
        layout.addStretch()

        return layout

    def _create_sliders(self) -> QFrame:
        frame = QFrame(objectName="Card")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(30)

        core_widget, self.core_slider, self.core_label, self.core_spinbox = self._make_slider_widget(
            "CORE CLOCK", -1000, 1000, 15, "MHz"
        )
        self.core_slider.valueChanged.connect(self._on_slider_changed)

        mem_widget, self.mem_slider, self.mem_label, self.mem_spinbox = self._make_slider_widget(
            "MEMORY CLOCK", -2000, 2000, 25, "MHz"
        )
        self.mem_slider.valueChanged.connect(self._on_slider_changed)

        power_widget, self.power_slider, self.power_label, self.power_spinbox = self._make_slider_widget(
            "POWER LIMIT", 34, 130, 1, "%"
        )
        self.power_slider.valueChanged.connect(self._on_slider_changed)

        layout.addWidget(core_widget, 1)
        layout.addWidget(mem_widget, 1)
        layout.addWidget(power_widget, 1)

        return frame

    # Modifica il metodo _on_slider_changed per tracciare il delta core clock:

    def _on_slider_changed(self):
        self.core_label.setText(f"CORE CLOCK: {self.core_slider.value()} MHz")
        self.mem_label.setText(f"MEMORY CLOCK: {self.mem_slider.value()} MHz")
        self.power_label.setText(f"POWER LIMIT: {self.power_slider.value()}%")

        # Se c'è una curva caricata, applica l'offset core clock in tempo reale
        if self.base_points and self.original_base_points:
            core_delta = self.core_slider.value() - self._saved_core
            if core_delta != self._last_core_slider_delta:
                self._apply_core_clock_offset(core_delta)

        self._update_dirty_state()

    def _make_slider_widget(
        self, title: str, min_val: int, max_val: int, step: int, suffix: str
    ) -> tuple[QWidget, QSlider, QLabel, QSpinBox]:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label = QLabel(f"{title}: 0 {suffix}")
        label.setStyleSheet(
            f"color: {THEME['text_dim']}; font-size: 11px; font-weight: 700; letter-spacing: 1px;"
        )

        slider_row = QHBoxLayout()
        slider_row.setSpacing(8)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setSingleStep(step)
        slider.setPageStep(step)

        spinbox = QSpinBox()
        spinbox.setRange(min_val, max_val)
        spinbox.setSingleStep(step)
        spinbox.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        spinbox.setAccelerated(True)
        spinbox.setFixedWidth(80)
        spinbox.setStyleSheet(
            f"QSpinBox {{"
            f"  background: {THEME['bg_input']};"
            f"  border: 1px solid {THEME['glass_border']};"
            f"  color: white;"
            f"  padding: 3px 6px;"
            f"  border-radius: 4px;"
            f"  font-size: 12px;"
            f"  font-weight: 600;"
            f"}}"
            f"QSpinBox:focus {{ border-color: {THEME['primary']}; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{"
            f"  background: rgba(255,255,255,0.08);"
            f"  border: none;"
            f"  width: 16px;"
            f"}}"
            f"QSpinBox::up-button:hover, QSpinBox::down-button:hover {{"
            f"  background: rgba(255,255,255,0.15);"
            f"}}"
        )

        suffix_label = QLabel(suffix)
        suffix_label.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 11px;")

        # Sincronizzazione bidirezionale slider <-> spinbox
        slider.valueChanged.connect(spinbox.setValue)
        spinbox.valueChanged.connect(slider.setValue)

        slider_row.addWidget(slider, 1)
        slider_row.addWidget(spinbox)
        slider_row.addWidget(suffix_label)

        layout.addWidget(label)
        layout.addLayout(slider_row)

        return widget, slider, label, spinbox

    def _create_graph(self) -> QFrame:
        frame = QFrame(objectName="Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 15, 15, 15)

        self.view_box = VFViewBox(self)
        self.plot = pg.PlotWidget(viewBox=self.view_box)
        self._style_plot()

        # Ghost curve (originale dal file)
        self.ghost_curve_item = self.plot.plot(
            [], [],
            pen=pg.mkPen(color=(255, 255, 255, 40), width=1, style=Qt.PenStyle.DashLine),
        )

        # Curva base consolidata (dopo APPLICA, tratteggiata più chiara)
        self.consolidated_curve_item = self.plot.plot(
            [], [],
            pen=pg.mkPen(color=(0, 255, 136, 30), width=1, style=Qt.PenStyle.DotLine),
        )

        # Curva di confronto (altro profilo, Feature C v2.7)
        self.compare_curve_item = self.plot.plot(
            [], [],
            pen=pg.mkPen(color=(0, 200, 255, 160), width=2,
                         style=Qt.PenStyle.DashLine),
        )

        # Curva corrente (preview live)
        self.curve_item = self.plot.plot(
            [], [],
            pen=pg.mkPen(THEME["text_dim"], width=2),
        )

        # Scatter
        self.scatter = pg.ScatterPlotItem(
            size=6,
            brush=pg.mkBrush("#d8d8d8"),
            pen=pg.mkPen("#a0a0a0", width=1),
            hoverable=True,
            hoverBrush=pg.mkBrush("#ffffff"),
            hoverPen=pg.mkPen("#ffffff", width=1),
        )
        self.plot.addItem(self.scatter)

        # Text items
        self.voltage_text = pg.TextItem(anchor=(0, 1), color="#ffffff")
        self.voltage_text.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.plot.addItem(self.voltage_text)
        self.voltage_text.hide()

        self.freq_text = pg.TextItem(anchor=(0, 0), color="#ffffff")
        self.freq_text.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.plot.addItem(self.freq_text)
        self.freq_text.hide()

        self.plot.hideButtons()
        self.scatter.sigClicked.connect(self._on_point_clicked)

        layout.addWidget(self.plot)
        return frame

    def _style_plot(self):
        self.plot.setBackground(THEME["bg_panel"])
        self.plot.showGrid(x=True, y=True, alpha=0.1)

        for axis_name in ("bottom", "left"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(THEME["text_muted"]))
            axis.setTextPen(pg.mkPen(THEME["text_dim"]))
            axis.enableAutoSIPrefix(False)

        self.plot.setLabel("bottom", "Voltage, mV")
        self.plot.setLabel("left", "Frequency, MHz")

        voltage_ticks = [(v, str(v)) for v in range(200, 1501, 25)]
        self.plot.getAxis("bottom").setTicks([voltage_ticks])
        freq_ticks = [(f, str(f)) for f in range(0, 4501, 100)]
        self.plot.getAxis("left").setTicks([freq_ticks])

        self.plot.plotItem.vb.setAutoVisible(x=False, y=False)
        self.plot.plotItem.vb.enableAutoRange(axis="xy", enable=False)
        self._reset_view()

    def _create_status(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        style = f"color: {THEME['text_muted']}; font-size: 11px;"
        sep_style = f"color: {THEME['glass_border']}; font-size: 11px;"

        self.lbl_mouse = QLabel("Mouse: -- mV, -- MHz")
        self.lbl_mouse.setStyleSheet(style)
        self.lbl_point = QLabel("Punto: --")
        self.lbl_point.setStyleSheet(style)
        self.lbl_history = QLabel("History: 0/0")
        self.lbl_history.setStyleSheet(style)
        self.lbl_save_feedback = QLabel("")
        self.lbl_save_feedback.setStyleSheet(
            f"color: {THEME['success']}; font-size: 11px; font-weight: 600;"
        )

        layout.addWidget(self.lbl_mouse)
        s1 = QLabel("|")
        s1.setStyleSheet(sep_style)
        layout.addWidget(s1)
        layout.addWidget(self.lbl_point)
        s2 = QLabel("|")
        s2.setStyleSheet(sep_style)
        layout.addWidget(s2)
        layout.addWidget(self.lbl_history)
        layout.addStretch()
        layout.addWidget(self.lbl_save_feedback)

        return layout

    def _setup_shortcuts(self):
        shortcuts = [
            ("Ctrl+S", self.save_cfg),
            ("Ctrl+O", self.open_file_dialog),
            ("Ctrl+Z", self._undo),
            ("Ctrl+Y", self._redo),
            ("Ctrl+Return", self._apply_current_edit),
            ("Escape", self._deselect_point),
            ("Delete", self._reset_selected_point),
        ]
        for key, callback in shortcuts:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(self._shortcut_guard(callback))

    # ================================================================
    # FILE LOADING
    # ================================================================

    def load_cfg_file(self, file_path: str | Path, profile_section: str = "Profile1") -> bool:
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File non trovato: {path}")
            return False
        if not self._is_supported_cfg_path(path):
            self.lbl_file_info.setText(f"File non supportato: {path.name}")
            self.lbl_file_info.setStyleSheet(f"color: {THEME['error']}; font-size: 13px;")
            return False

        try:
            self.cfg_file = AfterburnerCfgFile.load(path)
            self.current_cfg_path = path

            if not self._managed_cfg_paths or path not in self._managed_cfg_paths:
                self._set_available_cfg_tabs([path], current_path=path)
            else:
                self._sync_current_file_tab(path)

            available = self.cfg_file.get_available_profiles()
            self.combo_profile.blockSignals(True)
            self.combo_profile.clear()
            self.combo_profile.addItems(available)
            if profile_section in available:
                self.combo_profile.setCurrentText(profile_section)
                self.profile_section = profile_section
            elif available:
                self.combo_profile.setCurrentIndex(0)
                self.profile_section = available[0]
            self.combo_profile.blockSignals(False)

            prof = self.cfg_file.get_profile(self.profile_section)
            self._load_profile_data(prof)

            self.lbl_file_info.setText(f"File: {path.name}")
            self.lbl_file_info.setStyleSheet("color: white; font-size: 13px;")
            self.btn_reset_curve.setEnabled(True)
            self.btn_reset_all.setEnabled(True)
            self._mark_clean()
            self._set_pending_edit(False)
            self._refresh_toggle_ghost_style()

            logger.info(f"CFG Editor: caricato {path.name} [{self.profile_section}]")
            return True

        except Exception as e:
            logger.error(f"Errore caricamento CFG: {e}")
            self.lbl_file_info.setText(f"Errore: {e}")
            self.lbl_file_info.setStyleSheet(f"color: {THEME['error']}; font-size: 13px;")
            return False

    def load_profile_directory(
        self,
        ven_files: List[Path],
        profile1_file: Optional[Path] = None,
        profile_section: str = "Profile1",
    ) -> bool:
        supported: List[Path] = []
        for p in ven_files:
            if self._is_supported_cfg_path(Path(p)):
                supported.append(Path(p))
        if profile1_file and self._is_supported_cfg_path(Path(profile1_file)):
            supported.append(Path(profile1_file))

        if not supported:
            return False

        self._set_available_cfg_tabs(supported, current_path=supported[0])
        return self.load_cfg_file(supported[0], profile_section)

    def _load_profile_data(self, prof: AfterburnerProfile):
        self.original_vf_hex = prof.vfcurve_hex

        decoded = decode_vfcurve(prof.vfcurve_hex)
        self.original_base_points = deepcopy(decoded)
        self.base_points = deepcopy(decoded)
        self.current_points = [VFPoint(p.v_mv, p.f_mhz + p.c_delta, 0.0) for p in decoded]

        core_mhz = int(round(prof.core_clk_boost / 1000))
        mem_mhz = int(round(prof.mem_clk_boost / 1000))
        power = prof.power_limit if prof.power_limit else 100

        for w in (self.core_slider, self.mem_slider, self.power_slider, self.core_spinbox, self.mem_spinbox, self.power_spinbox):
            w.blockSignals(True)
        self.core_slider.setValue(core_mhz)
        self.mem_slider.setValue(mem_mhz)
        self.power_slider.setValue(power)
        self.core_spinbox.setValue(core_mhz)
        self.mem_spinbox.setValue(mem_mhz)
        self.power_spinbox.setValue(power)
        for w in (self.core_slider, self.mem_slider, self.power_slider, self.core_spinbox, self.mem_spinbox, self.power_spinbox):
            w.blockSignals(False)

        self._saved_core = core_mhz
        self._saved_mem = mem_mhz
        self._saved_power = power
        self._last_core_slider_delta = 0

        self.selected_index = None
        self.last_edited_index = None
        self.last_edited_delta_mhz = 0
        self._history.clear()
        self._history_index = -1
        self._set_pending_edit(False)

        self.core_label.setText(f"CORE CLOCK: {core_mhz} MHz")
        self.mem_label.setText(f"MEMORY CLOCK: {mem_mhz} MHz")
        self.power_label.setText(f"POWER LIMIT: {power}%")
        self.lbl_profile_info.setText(
            f"{self.profile_section} | Core: {core_mhz:+d} MHz | Mem: {mem_mhz:+d} MHz | Power: {power}%"
        )
        self.lbl_profile_info.setStyleSheet(
            f"color: {THEME['primary']}; font-size: 13px; font-weight: 600;"
        )

        self._redraw()
        self._update_status_point()
        self._update_history_status()

    def open_file_dialog(self):
        # Calcola la directory di partenza: ProfilesManager se esiste, altrimenti cwd
        from constants import BASE_DIR
        profiles_manager_dir = None

        # Cerca la cartella ProfilesManager partendo dal config
        try:
            from oc_core import ConfigManager
            config_path = BASE_DIR / "oc_manager_data.json"
            if config_path.exists():
                cfg = ConfigManager(config_path)
                msi_path = cfg.get("msi_path", "")
                if msi_path:
                    pm_dir = Path(msi_path).parent / "Profiles" / "ProfilesManager"
                    if pm_dir.exists():
                        profiles_manager_dir = pm_dir
        except Exception:
            pass

        start_dir = str(profiles_manager_dir) if profiles_manager_dir else str(Path.cwd())

        path, _ = QFileDialog.getOpenFileName(
            self, "Apri file .cfg",
            start_dir,
            "CFG Files (*.cfg);;Tutti i file (*)",
        )
        if path:
            self.load_cfg_file(path)
   
   # ================================================================
    # Aggiusta la curva dinamicamente con ogni modifica allo slider di 
    # ================================================================
   
    def _apply_core_clock_offset(self, core_delta_mhz: int):
        """
        Applica un offset uniforme a tutta la curva VF basato sul delta
        dello slider Core Clock rispetto al valore salvato.
        """
        if not self.base_points:
            return

        self._last_core_slider_delta = core_delta_mhz
        snapped_delta = int(_snap(core_delta_mhz, 15))

        # Ricalcola current_points partendo dai base_points + offset uniforme
        new_points = []
        for p in self.base_points:
            new_f = float(_snap(p.f_mhz + snapped_delta, 15))
            # Clamp a valori ragionevoli
            new_f = max(0.0, new_f)
            new_points.append(VFPoint(p.v_mv, new_f, 0.0))

        self.current_points = new_points

        # Se il delta è diverso da 0, segna come pending
        if snapped_delta != 0:
            self._set_pending_edit(True)
        else:
            self._set_pending_edit(False)

        self._redraw()

   # ================================================================
    # APPLY — consolida modifica corrente come nuovo base
    # ================================================================

    def _apply_current_edit(self):
        """
        Consolida la modifica corrente:
        - current_points diventa il nuovo base_points
        - Le modifiche successive partiranno da questo stato
        - Non scrive nulla su file
        """
        if not self.current_points or not self._has_pending_edit:
            return

        self._save_to_history()

        # Aggiorna base_points con i valori correnti
        self.base_points = [
            VFPoint(p.v_mv, p.f_mhz, 0.0) for p in self.current_points
        ]

        # Aggiorna il riferimento salvato dello slider core clock
        self._saved_core = self.core_slider.value()
        self._last_core_slider_delta = 0

        # Reset stato editing
        self.last_edited_index = None
        self.last_edited_delta_mhz = 0
        self._set_pending_edit(False)

        # Aggiorna label profilo
        self.lbl_profile_info.setText(
            f"{self.profile_section} | Core: {self.core_slider.value():+d} MHz | "
            f"Mem: {self.mem_slider.value():+d} MHz | Power: {self.power_slider.value()}%"
        )

        # Feedback visivo
        self.lbl_save_feedback.setText("Modifica applicata")
        self.lbl_save_feedback.setStyleSheet(
            f"color: {THEME['success']}; font-size: 11px; font-weight: 600;"
        )
        QTimer.singleShot(2000, lambda: self.lbl_save_feedback.setText(""))

        self._redraw()
        self._update_dirty_state()

        logger.info("CFG Editor: modifica consolidata (APPLICA)")

    # ================================================================
    # SAVE — scrive su file
    # ================================================================

    def save_cfg(self):
        if not self.cfg_file or not self.current_points:
            return

        if self._has_pending_edit:
            self._apply_current_edit()

        try:
            prof = self.cfg_file.get_profile(self.profile_section)
            prof.core_clk_boost = int(self.core_slider.value() * 1000)
            prof.mem_clk_boost = int(self.mem_slider.value() * 1000)
            prof.power_limit = int(self.power_slider.value())

            points_to_save = []
            for i, curr in enumerate(self.current_points):
                orig = self.original_base_points[i]
                overall_delta = curr.f_mhz - (orig.f_mhz + orig.c_delta)
                if abs(overall_delta) > 0.1:
                    points_to_save.append(VFPoint(curr.v_mv, orig.f_mhz, overall_delta))
                else:
                    points_to_save.append(VFPoint(orig.v_mv, orig.f_mhz, orig.c_delta))

            prof.vfcurve_hex = encode_vfcurve(self.original_vf_hex, points_to_save)
            self.cfg_file.save_profile(prof)

            refreshed_cfg = AfterburnerCfgFile.load(self.current_cfg_path)
            refreshed_prof = refreshed_cfg.get_profile(self.profile_section)
            self.cfg_file = refreshed_cfg
            self.original_vf_hex = refreshed_prof.vfcurve_hex
            refreshed_points = decode_vfcurve(refreshed_prof.vfcurve_hex)
            self.original_base_points = deepcopy(refreshed_points)
            self.base_points = deepcopy(refreshed_points)
            self.current_points = [VFPoint(p.v_mv, p.f_mhz + p.c_delta, 0.0) for p in refreshed_points]

            self._saved_core = int(round(refreshed_prof.core_clk_boost / 1000))
            self._saved_mem = int(round(refreshed_prof.mem_clk_boost / 1000))
            self._saved_power = refreshed_prof.power_limit if refreshed_prof.power_limit else 100
            self._last_core_slider_delta = 0
            self._set_pending_edit(False)
            self._mark_clean()

            self.core_label.setText(f"CORE CLOCK: {self._saved_core} MHz")
            self.mem_label.setText(f"MEMORY CLOCK: {self._saved_mem} MHz")
            self.power_label.setText(f"POWER LIMIT: {self._saved_power}%")
            self.lbl_profile_info.setText(
                f"{self.profile_section} | Core: {self._saved_core:+d} MHz | "
                f"Mem: {self._saved_mem:+d} MHz | Power: {self._saved_power}%"
            )
            self._redraw()

            self.lbl_save_feedback.setText("Salvato su file!")
            self.lbl_save_feedback.setStyleSheet(
                f"color: {THEME['success']}; font-size: 11px; font-weight: 600;"
            )
            QTimer.singleShot(3000, lambda: self.lbl_save_feedback.setText(""))

            self.profile_saved.emit(str(self.current_cfg_path))
            logger.info(f"CFG salvato: {self.current_cfg_path}")

        except Exception as e:
            logger.error(f"Errore salvataggio CFG: {e}")
            self.lbl_save_feedback.setText(f"Errore: {e}")
            self.lbl_save_feedback.setStyleSheet(
                f"color: {THEME['error']}; font-size: 11px; font-weight: 600;"
            )
            QTimer.singleShot(5000, lambda: self.lbl_save_feedback.setText(""))

    def _confirm_action(self, title: str, text: str) -> bool:
        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        dlg.setAttribute(Qt.WA_TranslucentBackground)
        root = QVBoxLayout(dlg)
        root.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("Card")
        card.setStyleSheet(
            f"QFrame#Card {{ background: {THEME['bg_panel']}; border: 1px solid {THEME['glass_border']}; border-radius: 10px; }}"
            f"QPushButton {{ min-width: 90px; padding: 8px 14px; border-radius: 6px; }}"
        )
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 18, 18, 18)
        lab_t = QLabel(title)
        lab_t.setStyleSheet(f"color: {THEME['primary']}; font-size: 14px; font-weight: 800;")
        lay.addWidget(lab_t)
        lab_b = QLabel(text)
        lab_b.setWordWrap(True)
        lab_b.setStyleSheet("color: white; margin-top: 6px; margin-bottom: 10px;")
        lay.addWidget(lab_b)
        row = QHBoxLayout()
        row.addStretch()
        btn_cancel = QPushButton("ANNULLA")
        btn_cancel.clicked.connect(dlg.reject)
        btn_cancel.setAutoDefault(False)
        row.addWidget(btn_cancel)
        btn_ok = QPushButton("CONFERMA")
        btn_ok.clicked.connect(dlg.accept)
        btn_ok.setDefault(True)
        btn_ok.setAutoDefault(True)
        btn_ok.setStyleSheet(
            f"background: {THEME['primary']}; color: white; border: none; font-weight: 700;"
        )
        row.addWidget(btn_ok)
        lay.addLayout(row)
        return dlg.exec() == QDialog.Accepted

    def _find_virginstock_cfg(self) -> Optional[Path]:
        if not self.current_cfg_path:
            return None
        for parent in self.current_cfg_path.parents:
            if parent.name == "ProfilesManager":
                candidate = parent / "VirginStock" / self.current_cfg_path.name
                if self._is_supported_cfg_path(candidate):
                    return candidate
                return None
        return None

    def _reset_all_to_virginstock(self):
        if not self.current_cfg_path or not self.cfg_file:
            return
        virgin_path = self._find_virginstock_cfg()
        if not virgin_path:
            self.lbl_save_feedback.setText("VirginStock non trovato")
            self.lbl_save_feedback.setStyleSheet(
                f"color: {THEME['error']}; font-size: 11px; font-weight: 600;"
            )
            QTimer.singleShot(4000, lambda: self.lbl_save_feedback.setText(""))
            return

        if not self._confirm_action(
            "Reset completo",
            "Questa azione caricherà e salverà subito i valori VirginStock nel profilo corrente. Continuare?",
        ):
            return

        try:
            virgin_cfg = AfterburnerCfgFile.load(virgin_path)
            section = self.profile_section if virgin_cfg.has_profile(self.profile_section) else "Profile1"
            virgin_prof = virgin_cfg.get_profile(section)
            virgin_prof.section = self.profile_section
            self.cfg_file.save_profile(virgin_prof)
            self.load_cfg_file(self.current_cfg_path, self.profile_section)
            self.lbl_save_feedback.setText("VirginStock applicato")
            self.lbl_save_feedback.setStyleSheet(
                f"color: {THEME['success']}; font-size: 11px; font-weight: 600;"
            )
            QTimer.singleShot(3000, lambda: self.lbl_save_feedback.setText(""))
            self.profile_saved.emit(str(self.current_cfg_path))
        except Exception as e:
            logger.error(f"Reset VirginStock fallito: {e}")
            self.lbl_save_feedback.setText(f"Errore: {e}")
            self.lbl_save_feedback.setStyleSheet(
                f"color: {THEME['error']}; font-size: 11px; font-weight: 600;"
            )
            QTimer.singleShot(4000, lambda: self.lbl_save_feedback.setText(""))

    # ================================================================
    # GHOST CURVE    # ================================================================
    # GHOST CURVE (originale dal file)
    # ================================================================

    def _toggle_ghost_curve(self):
        visible = self.btn_toggle_ghost.isChecked()
        self.ghost_curve_item.setVisible(visible)
        self._refresh_toggle_ghost_style()
        self._redraw_ghost()

    def _redraw_ghost(self):
        """Disegna la curva originale dal file (immutabile)."""
        if not self.original_base_points or not self.btn_toggle_ghost.isChecked():
            self.ghost_curve_item.setData([], [])
            return
        xs = [p.v_mv for p in self.original_base_points]
        ys = [p.f_mhz + p.c_delta for p in self.original_base_points]
        self.ghost_curve_item.setData(xs, ys)

    # ================================================================
    # COMPARE CURVE (Feature C, v2.7)
    # ================================================================

    def _toggle_compare_curve(self):
        """Attiva/disattiva la sovrapposizione della curva di un altro profilo."""
        if not self.btn_compare.isChecked():
            self._compare_points = None
            self._compare_label = ""
            self.compare_curve_item.setData([], [])
            self._refresh_compare_style()
            return

        # Scegli il cfg da confrontare (parte dalla cartella ProfilesManager)
        from constants import BASE_DIR
        start_dir = str(Path.cwd())
        try:
            from oc_core import ConfigManager
            config_path = BASE_DIR / "oc_manager_data.json"
            if config_path.exists():
                cfg = ConfigManager(config_path)
                msi_path = cfg.get("msi_path", "")
                if msi_path:
                    pm_dir = Path(msi_path).parent / "Profiles" / "ProfilesManager"
                    if pm_dir.exists():
                        start_dir = str(pm_dir)
        except Exception:  # noqa: BLE001
            pass

        path, _ = QFileDialog.getOpenFileName(
            self, "Confronta con profilo (.cfg)",
            start_dir,
            "CFG Files (*.cfg);;Tutti i file (*)",
        )
        if not path:
            self.btn_compare.setChecked(False)
            self._refresh_compare_style()
            return

        try:
            other = AfterburnerCfgFile.load(Path(path))
            prof = other.get_profile(self.profile_section)
            if prof is None or not prof.vfcurve_hex:
                raise ValueError(
                    f"Nessuna VFCurve in [{self.profile_section}]")
            self._compare_points = decode_vfcurve(prof.vfcurve_hex)
            parent = Path(path).parent
            self._compare_label = (
                parent.name if parent.name != "ProfilesManager"
                else Path(path).stem)
            self._redraw_compare()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Confronto curve: {e}")
            self.btn_compare.setChecked(False)
            self._compare_points = None
            self.compare_curve_item.setData([], [])
        self._refresh_compare_style()

    def _refresh_compare_style(self) -> None:
        active = self.btn_compare.isChecked()
        label = "CONFRONTA"
        if active and self._compare_label:
            label = f"VS {self._compare_label.upper()[:14]}"
        self.btn_compare.setText(label)
        self.btn_compare.setProperty("active", active)
        self.btn_compare.style().unpolish(self.btn_compare)
        self.btn_compare.style().polish(self.btn_compare)

    def _redraw_compare(self) -> None:
        """Disegna la curva di confronto (frequenza effettiva = f + delta)."""
        if not self._compare_points or not self.btn_compare.isChecked():
            self.compare_curve_item.setData([], [])
            return
        xs = [p.v_mv for p in self._compare_points]
        ys = [p.f_mhz + p.c_delta for p in self._compare_points]
        self.compare_curve_item.setData(xs, ys)

    def _redraw_consolidated(self):
        """
        Disegna la curva consolidata (dopo APPLICA) se diversa dalla corrente.
        Visibile solo quando c'è un pending edit.
        """
        if not self.base_points or not self._has_pending_edit:
            self.consolidated_curve_item.setData([], [])
            return
        xs = [p.v_mv for p in self.base_points]
        ys = [p.f_mhz for p in self.base_points]
        self.consolidated_curve_item.setData(xs, ys)

    # ================================================================
    # GRAPH RENDERING
    # ================================================================

    def _redraw(self):
        if not self.current_points:
            self.curve_item.setData([], [])
            self.scatter.setData([])
            self.ghost_curve_item.setData([], [])
            self.consolidated_curve_item.setData([], [])
            self.voltage_text.hide()
            self.freq_text.hide()
            return

        xs = [p.v_mv for p in self.current_points]
        ys = [p.f_mhz for p in self.current_points]

        self.curve_item.setPen(pg.mkPen(THEME["text_dim"], width=2))
        self.curve_item.setData(xs, ys)

        # Curve di riferimento
        self._redraw_ghost()
        self._redraw_consolidated()

        # Scatter con colori differenziati
        spots = []
        for i, (x, y) in enumerate(zip(xs, ys)):
            orig = self.original_base_points[i]
            original_freq = orig.f_mhz + orig.c_delta
            is_modified = abs(y - original_freq) > 0.1

            if self.selected_index == i:
                spots.append({
                    "pos": (x, y),
                    "brush": pg.mkBrush(THEME["primary"]),
                    "pen": pg.mkPen(THEME["primary"], width=2),
                    "size": 10,
                })
            elif is_modified:
                spots.append({
                    "pos": (x, y),
                    "brush": pg.mkBrush(THEME["warning"]),
                    "pen": pg.mkPen(THEME["warning"], width=1),
                    "size": 8,
                })
            else:
                spots.append({
                    "pos": (x, y),
                    "brush": pg.mkBrush("#d8d8d8"),
                    "pen": pg.mkPen(THEME["text_muted"], width=1),
                    "size": 6,
                })

        self.scatter.setData(spots)

        if self.selected_index is not None:
            sp = self.current_points[self.selected_index]
            self.voltage_text.setText(f"{sp.v_mv:.1f} mV")
            self.voltage_text.setPos(sp.v_mv, sp.f_mhz)
            self.voltage_text.show()
            self.freq_text.setText(f"{sp.f_mhz:.0f} MHz")
            self.freq_text.setPos(sp.v_mv, sp.f_mhz)
            self.freq_text.show()
        else:
            self.voltage_text.hide()
            self.freq_text.hide()

        self._update_status_point()
        self._update_dirty_state()

    def _reset_view(self):
        self.plot.setXRange(450, 1250, padding=0)
        self.plot.setYRange(450, 3500, padding=0)

    # ================================================================
    # POINT INTERACTION
    # ================================================================

    def _on_point_clicked(self, scatter, points):
        if not points or not self.current_points:
            return
        p = points[0]
        x, y = p.pos()
        idx = min(
            range(len(self.current_points)),
            key=lambda i: abs(self.current_points[i].v_mv - x)
            + abs(self.current_points[i].f_mhz - y),
        )
        self.selected_index = idx
        self._redraw()

    def _is_click_on_scatter(self, ev) -> bool:
        if not self.current_points:
            return False
        view_pos = self.plot.plotItem.vb.mapSceneToView(ev.scenePos())
        mx, my = float(view_pos.x()), float(view_pos.y())
        for p in self.current_points:
            if abs(p.v_mv - mx) <= 15 and abs(p.f_mhz - my) <= 80:
                return True
        return False

    def _deselect_point(self):
        if self.selected_index is not None:
            self.selected_index = None
            self._redraw()

    def _try_handle_left_drag(self, ev) -> bool:
        """Gestisce drag su punto selezionato per editing."""
        if self.selected_index is None or not self.current_points or not self.base_points:
            return False

        mouse_point = self.plot.plotItem.vb.mapSceneToView(ev.scenePos())
        sx, sy = float(mouse_point.x()), float(mouse_point.y())
        sp = self.current_points[self.selected_index]

        if ev.isStart():
            if not (abs(sx - sp.v_mv) <= 12.5 and abs(sy - sp.f_mhz) <= 80):
                return False

            # Se c'è un offset core clock pending, consolidalo prima del drag
            if self._last_core_slider_delta != 0:
                self._apply_current_edit()

            self._save_to_history()

        # Delta calcolato rispetto a base_points (consolidati)
        base_f = self.base_points[self.selected_index].f_mhz
        delta_raw = int(round(sy - base_f))
        delta_snapped = int(_snap(delta_raw, 15))

        self.last_edited_index = self.selected_index
        self.last_edited_delta_mhz = delta_snapped

        self.current_points = apply_single_point_edit_ab_like(
            self.base_points,
            point_index=self.selected_index,
            delta_mhz=delta_snapped,
            snap_mhz=15,
            left_gap_max_mhz=60,
        )

        # Attiva il bottone APPLICA
        self._set_pending_edit(True)

        self._redraw()
        return True

    # ================================================================
    # CURVE OPERATIONS
    # ================================================================

    def _reset_curve(self):
        """Ripristina la sola VF curve mantenendo invariato il Core Clock corrente."""
        if not self.original_base_points:
            return
        self._save_to_history()

        self.base_points = deepcopy(self.original_base_points)
        self.current_points = [
            VFPoint(p.v_mv, p.f_mhz + p.c_delta, 0.0) for p in self.original_base_points
        ]

        self.selected_index = None
        self.last_edited_index = None
        self.last_edited_delta_mhz = 0

        core_delta = self.core_slider.value() - self._saved_core
        if core_delta != 0:
            self._apply_core_clock_offset(core_delta)
        else:
            self._set_pending_edit(False)
            self._redraw()
        self._update_dirty_state()

    def _reset_selected_point(self):
        """Resetta il punto selezionato al valore base consolidato."""
        if self.selected_index is None or not self.base_points:
            return
        self._save_to_history()
        base_p = self.base_points[self.selected_index]
        self.current_points[self.selected_index].f_mhz = base_p.f_mhz
        self.last_edited_index = None
        self.last_edited_delta_mhz = 0
        self._set_pending_edit(False)
        self._redraw()

    # ================================================================
    # UNDO / REDO
    # ================================================================

    def _save_to_history(self):
        if not self.current_points:
            return
        if self._history_index < len(self._history) - 1:
            self._history = self._history[: self._history_index + 1]
        state = {
            "current_points": deepcopy(self.current_points),
            "base_points": deepcopy(self.base_points),
            "selected_index": self.selected_index,
            "last_edited_index": self.last_edited_index,
            "last_edited_delta_mhz": self.last_edited_delta_mhz,
            "has_pending_edit": self._has_pending_edit,
        }
        self._history.append(state)
        if len(self._history) > self._max_history:
            self._history.pop(0)
        else:
            self._history_index += 1
        self._update_history_status()

    def _undo(self):
        if self._history_index > 0:
            self._history_index -= 1
            self._restore_from_history()

    def _redo(self):
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self._restore_from_history()

    def _restore_from_history(self):
        if 0 <= self._history_index < len(self._history):
            state = self._history[self._history_index]
            self.current_points = deepcopy(state["current_points"])
            self.base_points = deepcopy(state["base_points"])
            self.selected_index = state["selected_index"]
            self.last_edited_index = state["last_edited_index"]
            self.last_edited_delta_mhz = state["last_edited_delta_mhz"]
            self._set_pending_edit(state["has_pending_edit"])
            self._redraw()
            self._update_history_status()

    # ================================================================
    # PROFILE SWITCHING
    # ================================================================

    def _on_profile_changed(self, profile_name: str):
        if not self.cfg_file or not profile_name:
            return
        self.profile_section = profile_name
        try:
            prof = self.cfg_file.get_profile(profile_name)
            self._load_profile_data(prof)
            self._mark_clean()
            self._set_pending_edit(False)
        except KeyError:
            self.lbl_profile_info.setText(f"{profile_name} non trovato")
            self.lbl_profile_info.setStyleSheet(
                f"color: {THEME['error']}; font-size: 13px;"
            )

    # ================================================================
    # STATUS
    # ================================================================

    def _update_mouse_coords(self, x: float, y: float):
        self.lbl_mouse.setText(f"Mouse: {x:.1f} mV, {y:.0f} MHz")

    def _update_status_point(self):
        if self.selected_index is not None and self.current_points and self.original_base_points:
            p = self.current_points[self.selected_index]
            orig = self.original_base_points[self.selected_index]
            delta = p.f_mhz - (orig.f_mhz + orig.c_delta)
            self.lbl_point.setText(
                f"Punto: #{self.selected_index} | "
                f"{p.v_mv:.1f}mV @ {p.f_mhz:.0f}MHz ({delta:+.0f}MHz)"
            )
        else:
            self.lbl_point.setText("Punto: --")

    def _update_history_status(self):
        current = self._history_index + 1
        total = len(self._history)
        self.lbl_history.setText(f"History: {current}/{total}")
