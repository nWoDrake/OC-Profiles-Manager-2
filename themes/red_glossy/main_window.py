"""
OC Profiles Manager - UI Layer.

Main window, pagine, thread worker e tray icon.
Tutte le interazioni con il dominio passano per ProfileController.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPropertyAnimation, QRectF, QSize, Qt, QThread,
    QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMenu, QPushButton, QSizeGrip, QSpinBox, QStackedWidget, QSystemTrayIcon,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from cfg_editor.editor_widget import VFEditorWidget
from constants import APP_NAME, APP_VERSION, BASE_DIR, TIMING
from oc_utils import (
    check_autostart_registry, open_in_explorer, set_autostart_registry,
)
from profile_info_extractor import ProfileCardInfo, ProfileInfoExtractor

# ── Risorse interne del tema ────────────────────────────────────────────────
from .style import STYLESHEET, THEME

# Pubblica subito il THEME al theme_context così che componenti riusabili (es.
# cfg_editor.editor_widget) leggano i colori corretti già al primo import.
from widgets_common.theme_context import set_current_theme as _set_theme
_set_theme(THEME)

from widgets_common.oc_brand import OCBrandLogo, OCBrandLogoCollapsed

from .widgets import (
    CircularGauge, ExternalToast, IconFactory, LiveChart, ProfileCard,
    ProfileCardView, ProfileIconSelector, StyledInputDialog,
    StyledMessageBox, TelemetryCard, UsageBarChart,
)

# ── Theme system (per il selettore nelle impostazioni) ──────────────────────
from themes import ThemeRegistry

# ── Forward-import solo per type hints ──────────────────────────────────────
from oc_controller import ProfileController  # noqa: F401
from oc_core import (  # noqa: F401
    ConfigManager, GPUMonitor, MSIAfterburnerController, ProcessMonitorLogic,
    ProfileManager,
)
from themes.base import AppContext

logger = logging.getLogger(__name__)


# Indici pagine (single source of truth)
PAGE_DASHBOARD     = 0
PAGE_PROFILES      = 1
PAGE_ASSOCIATIONS  = 2
PAGE_LOGS          = 3
PAGE_MONITORING    = 4
PAGE_HISTORY       = 5
PAGE_CFG_EDITOR    = 6
PAGE_SETTINGS      = 7

PAGE_TITLES = [
    "Dashboard", "Libreria Profili", "Associazioni",
    "Log Attività", "Monitoraggio", "History",
    "CFG Editor", "Impostazioni",
]


# ============================================================================
# THREADS
# ============================================================================

class ProcessMonitorThread(QThread):
    """Thread di polling processi (intervallo configurabile)."""

    profile_changed = Signal(str, str)

    def __init__(self, logic: ProcessMonitorLogic):
        super().__init__()
        self._logic = logic
        self._running = True

    def run(self) -> None:
        while self._running:
            try:
                r = self._logic.check_processes()
                if r:
                    self.profile_changed.emit(r[0], r[1])
            except Exception as e:  # noqa: BLE001
                logger.debug(f"ProcessMonitorThread err: {e}")
            self.msleep(TIMING["process_check_interval"])

    def stop(self) -> None:
        self._running = False


class ProfileApplyWorker(QThread):
    """Worker non-bloccante per apply profilo."""

    finished = Signal(bool, str, bool)

    def __init__(self, controller: ProfileController, profile_name: str, silent: bool = True):
        super().__init__()
        self._ctrl = controller
        self._profile = profile_name
        self._silent = silent

    def run(self) -> None:
        try:
            ok = self._ctrl.apply_profile_blocking(self._profile)
            self.finished.emit(ok, self._profile, self._silent)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Apply worker error: {e}")
            self.finished.emit(False, self._profile, self._silent)


class GpuStatsThread(QThread):
    """
    Telemetria GPU fuori dal thread UI (OPT 4, v2.7).

    Le letture NVML possono bloccare per decine di ms su driver lenti:
    questo thread campiona `GPUMonitor.get_stats()` a intervallo fisso ed
    emette `stats_ready(dict)`; la UI aggiorna i widget nello slot.
    """

    stats_ready = Signal(dict)

    def __init__(self, gpu_monitor, interval_ms: int):
        super().__init__()
        self._gpu = gpu_monitor
        self._interval = max(200, int(interval_ms))
        self._running = True
        self._paused = False

    def run(self) -> None:
        while self._running:
            if not self._paused:
                try:
                    self.stats_ready.emit(self._gpu.get_stats())
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"GpuStatsThread: {e}")
            self.msleep(self._interval)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def stop(self) -> None:
        self._running = False


# ============================================================================
# SCHEDULE RULES DIALOG (Feature E — v2.7)
# ============================================================================

class ScheduleRulesDialog(QDialog):
    """Editor delle regole orarie dello scheduler profili.

    Ogni regola: {"start": "HH:MM", "end": "HH:MM",
                  "profile": str, "enabled": bool}.
    Le fasce possono attraversare la mezzanotte (start > end).
    """

    def __init__(self, rules: list, profiles: list, parent=None):
        super().__init__(parent)
        from .style import STYLESHEET as _SS
        self.result_rules: Optional[list] = None
        self._rules = [dict(r) for r in rules]

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumWidth(520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        container = QFrame(objectName="NotifyCard")
        container.setStyleSheet(_SS)
        outer.addWidget(container)
        l = QVBoxLayout(container)
        l.setContentsMargins(20, 20, 20, 20)
        l.setSpacing(10)

        l.addWidget(QLabel("Regole orarie scheduler",
                           objectName="CompareSectionTitle"))
        hint = QLabel("Formato HH:MM — le fasce possono attraversare la "
                      "mezzanotte (es. 22:00 → 07:00). Doppio click per "
                      "attivare/disattivare una regola.")
        hint.setStyleSheet("color:#aaa;")
        hint.setWordWrap(True)
        l.addWidget(hint)

        self.list_rules = QListWidget()
        self.list_rules.setMinimumHeight(160)
        self.list_rules.itemDoubleClicked.connect(self._toggle_selected)
        l.addWidget(self.list_rules)

        # ── Riga di inserimento ─────────────────────────────────────────
        fl = QHBoxLayout()
        fl.addWidget(QLabel("Dalle"))
        self.ed_start = QLineEdit("22:00")
        self.ed_start.setFixedWidth(64)
        self.ed_start.setAlignment(Qt.AlignCenter)
        fl.addWidget(self.ed_start)
        fl.addWidget(QLabel("alle"))
        self.ed_end = QLineEdit("07:00")
        self.ed_end.setFixedWidth(64)
        self.ed_end.setAlignment(Qt.AlignCenter)
        fl.addWidget(self.ed_end)
        fl.addWidget(QLabel("→"))
        self.cmb_profile = QComboBox()
        self.cmb_profile.addItems(profiles)
        fl.addWidget(self.cmb_profile, 1)
        btn_add = QPushButton("AGGIUNGI", objectName="ActionBtn")
        btn_add.setFixedHeight(30)
        btn_add.clicked.connect(self._add_rule)
        fl.addWidget(btn_add)
        l.addLayout(fl)

        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color:#ff5555;")
        self.lbl_error.hide()
        l.addWidget(self.lbl_error)

        # ── Pulsanti ────────────────────────────────────────────────────
        bl = QHBoxLayout()
        btn_del = QPushButton("RIMUOVI SELEZIONATA", objectName="ActionBtn")
        btn_del.clicked.connect(self._remove_selected)
        bl.addWidget(btn_del)
        bl.addStretch()
        bc = QPushButton("ANNULLA", objectName="ActionBtn")
        bc.setAutoDefault(False)
        bc.clicked.connect(self.reject)
        bl.addWidget(bc)
        bk = QPushButton("SALVA", objectName="ApplyBtn")
        bk.setDefault(True)
        bk.clicked.connect(self._accept)
        bl.addWidget(bk)
        l.addLayout(bl)

        self._refresh_list()

    # ── Helpers ─────────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        self.list_rules.clear()
        for r in self._rules:
            state = "●" if r.get("enabled", True) else "○"
            self.list_rules.addItem(
                f"{state}  {r.get('start', '?')} → {r.get('end', '?')}"
                f"   ⇒   {r.get('profile', '?')}"
            )

    def _add_rule(self) -> None:
        from oc_services import ProfileScheduler
        start = self.ed_start.text().strip()
        end = self.ed_end.text().strip()
        if (ProfileScheduler._parse_hhmm(start) is None
                or ProfileScheduler._parse_hhmm(end) is None):
            self.lbl_error.setText("Orario non valido: usa il formato HH:MM")
            self.lbl_error.show()
            return
        profile = self.cmb_profile.currentText()
        if not profile:
            self.lbl_error.setText("Nessun profilo selezionato")
            self.lbl_error.show()
            return
        self.lbl_error.hide()
        self._rules.append({"start": start, "end": end,
                            "profile": profile, "enabled": True})
        self._refresh_list()

    def _remove_selected(self) -> None:
        row = self.list_rules.currentRow()
        if 0 <= row < len(self._rules):
            self._rules.pop(row)
            self._refresh_list()

    def _toggle_selected(self) -> None:
        row = self.list_rules.currentRow()
        if 0 <= row < len(self._rules):
            self._rules[row]["enabled"] = not self._rules[row].get(
                "enabled", True)
            self._refresh_list()
            self.list_rules.setCurrentRow(row)

    def _accept(self) -> None:
        self.result_rules = self._rules
        self.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)


# ============================================================================
# MAIN WINDOW
# ============================================================================

class OCProfilesManager(QMainWindow):

    def __init__(self, ctx: "AppContext"):
        super().__init__()

        # ------------------------------------------------------------------
        # Core managers — ora forniti dall'AppContext, NON creati qui.
        # Questo è ciò che disaccoppia il tema dalla logica di business.
        # ------------------------------------------------------------------
        self.app_ctx = ctx
        self.config_path = ctx.config_path
        self.config_mgr = ctx.config_mgr
        self.profile_mgr = ctx.profile_mgr
        self.msi_ctrl = ctx.msi_ctrl
        self.gpu_monitor = ctx.gpu_monitor
        self._process_logic = ctx.process_logic
        self.ctrl = ctx.controller

        # Aggancia il log_callback della UI ai manager (creati in main.py senza UI).
        try:
            self.profile_mgr.log_callback = self.add_log
        except AttributeError:
            pass
        try:
            self.ctrl._log_cb = self.add_log
        except AttributeError:
            pass

        start_minimized = ctx.start_minimized

        # State
        self.active_toast: Optional[ExternalToast] = None
        self._apply_worker: Optional[ProfileApplyWorker] = None
        self._apply_buttons: List[QPushButton] = []
        self._profile_extractor = ProfileInfoExtractor()
        self._view_mode: str = "list"
        self._profile_filter: str = ""
        self._closing: bool = False

        # UI
        self._setup_window()
        self._init_ui()
        self._setup_shortcuts()
        self._setup_tray()

        # Init structure
        self.profile_mgr.ensure_structure()

        # Process monitor
        self.process_monitor = ProcessMonitorThread(self._process_logic)
        self.process_monitor.profile_changed.connect(self._on_auto_profile_change)
        self.process_monitor.start()

        # Telemetria GPU in thread dedicato (OPT 4, v2.7)
        self.gpu_thread = GpuStatsThread(
            self.gpu_monitor, TIMING["gpu_update_interval"])
        self.gpu_thread.stats_ready.connect(self._on_gpu_stats)
        self.gpu_thread.start()

        self.msi_status_timer = QTimer(self)
        self.msi_status_timer.timeout.connect(self._update_msi_status)
        self.msi_status_timer.start(TIMING["msi_status_interval"])

        # ── Servizi v2.7 ────────────────────────────────────────────────
        from oc_services import BackupManager, ProfileScheduler, TempWatchdog
        self._backup_mgr = BackupManager(self.profile_mgr.manager_root)
        self._scheduler = ProfileScheduler(self.config_mgr)
        self._watchdog = TempWatchdog(self.config_mgr)
        self._hotkeys = None  # GlobalHotkeyListener (lazy)

        # B — Backup automatico all'avvio (thread daemon, non blocca la UI)
        if self.config_mgr.get("auto_backup_enabled", True):
            retention = int(self.config_mgr.get("auto_backup_retention", 10))
            threading.Thread(
                target=lambda: self._backup_mgr.auto_backup(retention),
                daemon=True,
            ).start()

        # E — Scheduler orario (tick ogni 30 s)
        self.scheduler_timer = QTimer(self)
        self.scheduler_timer.timeout.connect(self._check_scheduler)
        self.scheduler_timer.start(30_000)

        # F — Hotkey globali Ctrl+Alt+1..9
        if self.config_mgr.get("global_hotkeys_enabled", True):
            self._start_global_hotkeys()

        # H — Check aggiornamenti GitHub (thread daemon)
        if self.config_mgr.get("check_updates", True):
            threading.Thread(
                target=self._check_updates_bg, daemon=True).start()

        # Startup
        mode = "Nvidia API" if self.gpu_monitor.is_real_hardware else "Simulazione"
        self.add_log(f"Sistema pronto. Monitor: {mode}")

        if start_minimized:
            self.add_log("Avvio minimizzato.")
            # Non mostriamo la finestra; il tray è già attivo
        else:
            self.show()
            self.ctrl.play_sound("apply")

        # Default profile load (deferred, non bloccante)
        QTimer.singleShot(1000, lambda: self._apply_profile("Default", silent=True))

    # ================================================================
    # PUBLIC API (chiamati da main.py / theme system)
    # ================================================================

    def show_window(self) -> None:
        """Mostra la finestra (no-op se già visibile)."""
        self.show()

    def shutdown(self) -> None:
        """Cleanup pubblico richiamabile dal theme system."""
        self._cleanup()

    # ================================================================
    # CLEANUP
    # ================================================================

    def closeEvent(self, event):
        self._cleanup()
        event.accept()
        # Permette l'effettivo exit dell'applicazione (setQuitOnLastWindowClosed=False)
        QApplication.instance().quit()

    def _cleanup(self) -> None:
        if self._closing:
            return
        self._closing = True

        for timer in (self.msi_status_timer, self.scheduler_timer):
            if timer.isActive():
                timer.stop()

        self.gpu_thread.stop()
        if not self.gpu_thread.wait(2000):
            self.gpu_thread.terminate()
            self.gpu_thread.wait(500)

        self._stop_global_hotkeys()

        self.process_monitor.stop()
        if not self.process_monitor.wait(3000):
            self.process_monitor.terminate()
            self.process_monitor.wait(1000)

        if self._apply_worker and self._apply_worker.isRunning():
            self._apply_worker.wait(2000)

        if self.active_toast:
            try:
                self.active_toast.close()
            except Exception:  # noqa: BLE001
                pass

        # Chiudi sessione history (calcola duration ultima entry)
        try:
            self.ctrl.shutdown()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"controller shutdown error: {e}")

        self.gpu_monitor.shutdown()
        try:
            self.tray.hide()
        except Exception:  # noqa: BLE001
            pass

    def _close_application(self) -> None:
        self.close()

    # ================================================================
    # APPLY BUTTON STATE
    # ================================================================

    def _set_apply_buttons_enabled(self, enabled: bool) -> None:
        for btn in self._apply_buttons:
            try:
                btn.setEnabled(enabled)
            except RuntimeError:
                # Bottone già distrutto (rinomina layout)
                continue

    # ================================================================
    # WINDOW SETUP
    # ================================================================

    def _setup_window(self) -> None:
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1150, 750)
        self.setStyleSheet(STYLESHEET)
        self.setWindowTitle(APP_NAME)

    def _init_ui(self) -> None:
        # Outer wrapper trasparente — i bordi arrotondati sono renderizzati in paintEvent.
        outer = QFrame(self)
        outer.setObjectName("OuterShell")
        outer.setAttribute(Qt.WA_TranslucentBackground)
        self.setCentralWidget(outer)
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)

        # RootContainer: ricevitore del bordo arrotondato visivo (background scuro).
        self.root_container = QFrame()
        self.root_container.setObjectName("RootContainer")
        layout = QHBoxLayout(self.root_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        outer_lay.addWidget(self.root_container)

        layout.addWidget(self._create_sidebar())

        content = QFrame()
        cl = QVBoxLayout(content)
        cl.addLayout(self._create_titlebar())
        self.pages = QStackedWidget()
        self._setup_pages()
        cl.addWidget(self.pages)
        layout.addWidget(content)

        self.sizegrip = QSizeGrip(self)
        self.sizegrip.setVisible(True)
        QTimer.singleShot(50, self._apply_glass_effect)

    # Sidebar a scomparsa
    SIDEBAR_WIDTH_EXPANDED: int = 240
    SIDEBAR_WIDTH_COLLAPSED: int = 70
    SIDEBAR_COLLAPSE_DELAY_MS: int = 500
    SIDEBAR_ANIM_DURATION_MS: int = 220

    def _create_sidebar(self) -> QFrame:
        """
        Sidebar a scomparsa (collapsed=70px, expanded=240px) con animazione.

        Header logo: espanso = OCBrandLogo (monogramma glossy + testo),
        collassato = OCBrandLogoCollapsed (chip animato).
        """
        sb = QFrame(objectName="Sidebar")
        sb.setFixedWidth(self.SIDEBAR_WIDTH_COLLAPSED)
        l = QVBoxLayout(sb)
        l.setContentsMargins(0, 0, 0, 20)
        l.setSpacing(0)

        # --- Header logo (espanso) ---
        self.brand_logo_expanded = OCBrandLogo(sb)
        l.addSpacing(16)
        l.addWidget(self.brand_logo_expanded)
        l.addSpacing(10)

        # --- Header logo (collassato, animato) ---
        from PySide6.QtWidgets import QHBoxLayout as _QH
        self.brand_logo_collapsed = OCBrandLogoCollapsed(sb)
        collapsed_row = _QH()
        collapsed_row.setContentsMargins(0, 0, 0, 0)
        collapsed_row.addStretch()
        collapsed_row.addWidget(self.brand_logo_collapsed)
        collapsed_row.addStretch()
        self._collapsed_logo_row = collapsed_row
        l.addLayout(collapsed_row)
        l.addSpacing(8)

        # Alias legacy (mantiene compatibilità col resto del codice che
        # potrebbe nascondere lbl_sidebar_logo).
        self.lbl_sidebar_logo = self.brand_logo_expanded

        self.nav_btns: List[QPushButton] = []
        items = [
            ("DASHBOARD",        "dashboard"),
            ("LIBRERIA PROFILI", "folder"),
            ("ASSOCIAZIONI",     "link"),
            ("LOG ATTIVITÀ",     "list"),
            ("MONITORAGGIO",     "chart"),
            ("HISTORY",          "history"),
            ("CFG EDITOR",       "edit"),
            ("IMPOSTAZIONI",     "settings"),
        ]
        for i, (label, icon) in enumerate(items):
            btn = QPushButton(label)
            btn.setProperty("class", "NavBtn")
            btn.setProperty("full_label", label)
            btn.setProperty("icon_name", icon)
            btn.setIcon(IconFactory.get_icon(icon))
            btn.setIconSize(QSize(18, 18))
            btn.setToolTip(label)
            btn.clicked.connect(lambda _, idx=i: self._switch_page(idx))
            l.addWidget(btn)
            self.nav_btns.append(btn)
        l.addStretch()

        self._sidebar = sb
        self._sidebar_expanded = False
        self._sidebar_anim = QPropertyAnimation(sb, b"minimumWidth", self)
        self._sidebar_anim.setDuration(self.SIDEBAR_ANIM_DURATION_MS)
        self._sidebar_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._sidebar_anim_max = QPropertyAnimation(sb, b"maximumWidth", self)
        self._sidebar_anim_max.setDuration(self.SIDEBAR_ANIM_DURATION_MS)
        self._sidebar_anim_max.setEasingCurve(QEasingCurve.InOutCubic)
        self._sidebar_anim.finished.connect(self._on_sidebar_anim_finished)

        self._sidebar_collapse_timer = QTimer(self)
        self._sidebar_collapse_timer.setSingleShot(True)
        self._sidebar_collapse_timer.timeout.connect(self._collapse_sidebar)

        sb.installEventFilter(self)
        self._apply_sidebar_collapsed_visuals(True)
        return sb

    # ----------------------------------------------------------------
    # SIDEBAR ANIMATION
    # ----------------------------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is getattr(self, "_sidebar", None):
            if event.type() == QEvent.Enter:
                self._sidebar_collapse_timer.stop()
                if not self._sidebar_expanded:
                    self._expand_sidebar()
            elif event.type() == QEvent.Leave:
                if self._sidebar_expanded:
                    self._sidebar_collapse_timer.start(self.SIDEBAR_COLLAPSE_DELAY_MS)
        return super().eventFilter(obj, event)

    def _expand_sidebar(self) -> None:
        self._sidebar_expanded = True
        self._apply_sidebar_collapsed_visuals(False)
        self._animate_sidebar_width(self._sidebar.width(), self.SIDEBAR_WIDTH_EXPANDED)

    def _collapse_sidebar(self) -> None:
        self._sidebar_expanded = False
        self._animate_sidebar_width(self._sidebar.width(), self.SIDEBAR_WIDTH_COLLAPSED)

    def _animate_sidebar_width(self, from_w: int, to_w: int) -> None:
        self._sidebar_anim.stop()
        self._sidebar_anim_max.stop()
        self._sidebar_anim.setStartValue(from_w)
        self._sidebar_anim.setEndValue(to_w)
        self._sidebar_anim_max.setStartValue(from_w)
        self._sidebar_anim_max.setEndValue(to_w)
        self._sidebar_anim.start()
        self._sidebar_anim_max.start()

    def _on_sidebar_anim_finished(self) -> None:
        if not self._sidebar_expanded:
            self._apply_sidebar_collapsed_visuals(True)

    def _apply_sidebar_collapsed_visuals(self, collapsed: bool) -> None:
        if not hasattr(self, "nav_btns"):
            return
        # Switch tra header espanso e header collassato animato.
        if hasattr(self, "brand_logo_expanded"):
            self.brand_logo_expanded.setVisible(not collapsed)
        if hasattr(self, "brand_logo_collapsed"):
            self.brand_logo_collapsed.setVisible(collapsed)
        for btn in self.nav_btns:
            full = btn.property("full_label") or ""
            btn.setText("" if collapsed else full)
            btn.setProperty("collapsed", collapsed)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _create_titlebar(self) -> QHBoxLayout:
        l = QHBoxLayout()
        l.setContentsMargins(20, 15, 15, 10)
        self.page_title = QLabel("Dashboard", objectName="PageTitle")

        bm = QPushButton("", objectName="WinBtn")
        bm.setFixedSize(40, 30)
        bm.setIcon(IconFactory.get_icon("minimize", "#aaa"))
        bm.setToolTip("Minimizza in tray")
        bm.clicked.connect(self._minimize_to_tray)

        self.btn_maximize = QPushButton("", objectName="WinBtn")
        self.btn_maximize.setFixedSize(40, 30)
        self.btn_maximize.setIcon(IconFactory.get_icon("maximize", "#aaa"))
        self.btn_maximize.setToolTip("Massimizza / Ripristina")
        self.btn_maximize.clicked.connect(self._toggle_maximize)

        bc = QPushButton("", objectName="WinBtn")
        bc.setFixedSize(40, 30)
        bc.setIcon(IconFactory.get_icon("close", "#ff5555"))
        bc.setToolTip("Chiudi (Alt+F4)")
        bc.clicked.connect(self._close_application)

        l.addWidget(self.page_title)
        l.addStretch()
        l.addWidget(bm)
        l.addWidget(self.btn_maximize)
        l.addWidget(bc)
        return l

    # ================================================================
    # PAGES SETUP
    # ================================================================

    def _setup_pages(self) -> None:
        self._setup_dashboard()       # 0
        self._setup_profiles()        # 1
        self._setup_associations()    # 2
        self._setup_logs()            # 3
        self._setup_monitoring()      # 4
        self._setup_history()         # 5
        self._setup_cfg_editor()      # 6
        self._setup_settings()        # 7

    def _setup_dashboard(self) -> None:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(40, 20, 40, 40)

        card = QFrame(objectName="Card")
        cl_layout = QVBoxLayout(card)
        cl_layout.setContentsMargins(25, 25, 25, 25)
        self.lbl_active_prof = QLabel("Profilo Attivo: Default", objectName="ActiveProfileLabel")
        self.lbl_active_app = QLabel("Inizializzazione...", objectName="ActiveAppLabel")
        cl_layout.addWidget(self.lbl_active_prof)
        cl_layout.addWidget(self.lbl_active_app)
        l.addWidget(card)
        l.addSpacing(15)

        cd = QFrame(objectName="Card")
        cdl = QHBoxLayout(cd)
        cdl.setContentsMargins(20, 15, 20, 15)
        vd = QVBoxLayout()
        self.lbl_def_status = QLabel("Default: VirginStock", objectName="DefaultStatusLabel")
        vd.addWidget(self.lbl_def_status)
        vd.addWidget(QLabel("Profilo di fallback (Idle).", objectName="DefaultSubLabel"))
        cdl.addLayout(vd)
        cdl.addStretch()
        br = QPushButton("RESETTA DEFAULT", objectName="ActionBtn")
        br.setIcon(IconFactory.get_icon("reset", "white"))
        br.clicked.connect(self._reset_default)
        cdl.addWidget(br)
        l.addWidget(cd)
        l.addSpacing(30)

        gl = QHBoxLayout()
        gl.setSpacing(30)
        self.gauge_temp = CircularGauge("TEMP", "°C", "#ff2e2e")
        self.gauge_load = CircularGauge("LOAD", "%", "#ffffff")
        self.gauge_fan = CircularGauge("FAN", "%", "#888899")
        gl.addWidget(self.gauge_temp)
        gl.addWidget(self.gauge_load)
        gl.addWidget(self.gauge_fan)
        gl.addStretch()
        l.addLayout(gl)
        l.addSpacing(20)

        tl = QHBoxLayout()
        tl.setSpacing(15)
        self.tel_core = TelemetryCard("CORE CLOCK", "MHz")
        self.tel_mem = TelemetryCard("MEM CLOCK", "MHz")
        self.tel_power = TelemetryCard("POWER", "W")
        self.tel_vram = TelemetryCard("VRAM USAGE", "GB")
        tl.addWidget(self.tel_core)
        tl.addWidget(self.tel_mem)
        tl.addWidget(self.tel_power)
        tl.addWidget(self.tel_vram)
        l.addLayout(tl)
        l.addStretch()

        self.pages.addWidget(page)
        self._update_def_label()

    def _setup_profiles(self) -> None:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(40, 20, 40, 40)
        l.setSpacing(10)

        # Toolbar: search + view toggle
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("🔍 Cerca profilo...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search_changed)
        self.search_box.setMaximumWidth(280)
        toolbar.addWidget(self.search_box)

        toolbar.addSpacing(10)

        lbl_view = QLabel("Vista:")
        lbl_view.setStyleSheet("color: white; font-size: 13px;")
        toolbar.addWidget(lbl_view)

        self.btn_view_list = QPushButton("LISTA", objectName="ActionBtn")
        self.btn_view_list.setCheckable(True)
        self.btn_view_list.setChecked(True)
        self.btn_view_list.setIcon(IconFactory.get_icon("list", "#ccc"))
        self.btn_view_list.clicked.connect(lambda: self._set_view_mode("list"))
        toolbar.addWidget(self.btn_view_list)

        self.btn_view_card = QPushButton("CARD", objectName="ActionBtn")
        self.btn_view_card.setCheckable(True)
        self.btn_view_card.setIcon(IconFactory.get_icon("dashboard", "#ccc"))
        self.btn_view_card.clicked.connect(lambda: self._set_view_mode("card"))
        toolbar.addWidget(self.btn_view_card)

        toolbar.addStretch()
        l.addLayout(toolbar)

        # Stacked widget per le due viste
        self.profile_views_stack = QStackedWidget()

        # Vista 0: Lista classica
        self.profile_list = QListWidget()
        self.profile_list.setFocusPolicy(Qt.NoFocus)
        self.profile_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.profile_list.customContextMenuRequested.connect(self._profile_ctx_menu)
        self.profile_list.itemDoubleClicked.connect(
            lambda item: self._apply_profile(item.text(), silent=False)
        )
        self.profile_views_stack.addWidget(self.profile_list)

        # Vista 1: Card view
        self.profile_card_view = ProfileCardView()
        self.profile_card_view.selection_changed.connect(self._on_card_selection_changed)
        self.profile_card_view.card_double_clicked.connect(
            lambda n: self._apply_profile(n, silent=False)
        )
        self.profile_card_view.icon_change_requested.connect(self._change_profile_icon)
        self.profile_card_view.context_menu_requested.connect(self._profile_card_ctx_menu)
        self.profile_views_stack.addWidget(self.profile_card_view)

        l.addWidget(self.profile_views_stack, 1)

        self._refresh_profiles()

        # Bottoni azione
        bl = QHBoxLayout()
        btn_configs = [
            ("APPLICA",     self._apply_selected,             "ApplyBtn",  "play",  True),
            ("NUOVO",       self._create_profile,             "ActionBtn", "plus",  False),
            ("DUPLICA",     self._duplicate_selected,         "ActionBtn", "save",  False),
            ("MODIFICA OC", self._edit_profile,               "ActionBtn", "edit",  False),
            ("CFG EDITOR",  self._open_cfg_editor_for_selected, "ActionBtn", "gear", False),
            ("DEFAULT",     self._set_default,                "ActionBtn", "save",  False),
            ("ASSOCIA",     self._associate_exe,              "ActionBtn", "link",  False),
        ]
        for text, cb, obj, icon, is_apply in btn_configs:
            b = QPushButton(text, objectName=obj)
            b.setIcon(IconFactory.get_icon(icon, "white" if obj == "ApplyBtn" else "#ccc"))
            b.clicked.connect(cb)
            bl.addWidget(b)
            if is_apply:
                self._apply_buttons.append(b)
        l.addLayout(bl)

        self.pages.addWidget(page)

    def _setup_associations(self) -> None:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(40, 20, 40, 40)
        self.assoc_table = QTableWidget()
        self.assoc_table.setColumnCount(2)
        self.assoc_table.setHorizontalHeaderLabels(["Eseguibile (.exe)", "Profilo Associato"])
        self.assoc_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.assoc_table.verticalHeader().setVisible(False)
        self.assoc_table.setSelectionBehavior(QTableWidget.SelectRows)
        l.addWidget(self.assoc_table)

        bl = QHBoxLayout()
        # Nuovo bottone CREA: apre AssociationCreateDialog (stylable per altri temi).
        bc = QPushButton("CREA", objectName="ApplyBtn")
        bc.setIcon(IconFactory.get_icon("plus", "white"))
        bc.clicked.connect(self._create_assoc)
        bl.addWidget(bc)

        bd = QPushButton("ELIMINA", objectName="ActionBtn")
        bd.setIcon(IconFactory.get_icon("trash", "#ff5555"))
        bd.clicked.connect(self._delete_assoc)
        bl.addWidget(bd)
        bl.addStretch()
        l.addLayout(bl)
        self.pages.addWidget(page)

    def _create_assoc(self) -> None:
        """Apre il dialog di creazione associazione (stylable per altri temi)."""
        from .widgets import AssociationCreateDialog

        profiles = self.profile_mgr.list_profiles()
        if not profiles:
            StyledMessageBox(
                "Info",
                "Nessun profilo disponibile.\nCrea prima almeno un profilo in 'Libreria Profili'.",
                parent=self,
            ).exec()
            return

        dlg = AssociationCreateDialog(profiles, parent=self)
        if not dlg.exec():
            return
        if not dlg.profile_name or not dlg.exe_name:
            return

        existing = self.config_mgr.get_associations()
        if dlg.exe_name in existing:
            old_prof = existing[dlg.exe_name]
            confirm = StyledMessageBox(
                "Associazione esistente",
                f"L'eseguibile '{dlg.exe_name}' è già associato a '{old_prof}'.\n"
                f"Vuoi sostituirlo con '{dlg.profile_name}'?",
                show_cancel=True,
                parent=self,
            )
            if not confirm.exec():
                return

        self.ctrl.add_association(dlg.exe_name, dlg.profile_name)
        self.add_log(f"Associato {dlg.exe_name} → {dlg.profile_name}")
        self._refresh_assoc()
        self._show_notification(f"Associazione creata:\n{dlg.exe_name} → {dlg.profile_name}")

    def _setup_logs(self) -> None:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(40, 20, 40, 40)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        l.addWidget(self.log_area)

        bl = QHBoxLayout()
        btn_clear = QPushButton("PULISCI LOG", objectName="ActionBtn")
        btn_clear.setIcon(IconFactory.get_icon("trash", "#aaa"))
        btn_clear.clicked.connect(lambda: self.log_area.clear())
        bl.addWidget(btn_clear)
        bl.addStretch()
        l.addLayout(bl)

        self.pages.addWidget(page)

    def _setup_monitoring(self) -> None:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(30, 20, 30, 30)
        l.setSpacing(15)
        self.chart_temp = LiveChart("TEMPERATURA GPU", "°C", "#ff2e2e")
        self.chart_load = LiveChart("UTILIZZO GPU", "%", "#ffffff")
        self.chart_power = LiveChart("CONSUMO ENERGETICO", "W", "#ffaa00", auto_scale=True)
        self.chart_vram = LiveChart("MEMORIA VRAM", "GB", "#00ff88", auto_scale=True)
        l.addWidget(self.chart_temp)
        l.addWidget(self.chart_load)
        l.addWidget(self.chart_power)
        l.addWidget(self.chart_vram)
        self.pages.addWidget(page)

    def _setup_history(self) -> None:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(40, 20, 40, 40)
        l.setSpacing(15)

        # Toolbar
        hl = QHBoxLayout()
        hl.addWidget(QLabel("Utilizzo profili negli ultimi", objectName="HistoryComboLabel"))
        self.history_days_combo = QComboBox()
        self.history_days_combo.addItems(["1 giorno", "3 giorni", "7 giorni", "14 giorni", "30 giorni"])
        self.history_days_combo.setCurrentIndex(2)
        self.history_days_combo.currentIndexChanged.connect(self._refresh_history)
        hl.addWidget(self.history_days_combo)
        hl.addStretch()

        btn_export = QPushButton("ESPORTA CSV", objectName="ActionBtn")
        btn_export.setIcon(IconFactory.get_icon("backup", "#aaa"))
        btn_export.clicked.connect(self._export_history_csv)
        hl.addWidget(btn_export)

        btn_refresh = QPushButton("AGGIORNA", objectName="ActionBtn")
        btn_refresh.setIcon(IconFactory.get_icon("reset", "white"))
        btn_refresh.clicked.connect(self._refresh_history)
        hl.addWidget(btn_refresh)
        l.addLayout(hl)

        # Summary stats pills
        self.history_summary = QHBoxLayout()
        self.history_summary.setSpacing(10)
        self.lbl_stat_total = QLabel("Totale: —", objectName="StatPill")
        self.lbl_stat_switches = QLabel("Cambi: —", objectName="StatPill")
        self.lbl_stat_avg = QLabel("Sessione media: —", objectName="StatPill")
        self.lbl_stat_top = QLabel("Più usato: —", objectName="StatPill")
        for lbl in (self.lbl_stat_total, self.lbl_stat_switches,
                    self.lbl_stat_avg, self.lbl_stat_top):
            self.history_summary.addWidget(lbl)
        self.history_summary.addStretch()
        l.addLayout(self.history_summary)

        self.usage_chart = UsageBarChart()
        l.addWidget(self.usage_chart)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["Timestamp", "Profilo", "App", "Durata"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.verticalHeader().setVisible(False)
        l.addWidget(self.history_table)

        self.pages.addWidget(page)

    def _setup_cfg_editor(self) -> None:
        """Crea la pagina CFG Editor con il widget VF integrato."""
        self.vf_editor = VFEditorWidget()
        self.vf_editor.profile_saved.connect(self._on_cfg_editor_saved)
        # Signal dirty (presente solo nella versione full)
        try:
            self.vf_editor.has_unsaved_changes.connect(self._on_editor_dirty_changed)
        except AttributeError:
            pass
        self.pages.addWidget(self.vf_editor)

    def _setup_settings(self) -> None:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(40, 40, 40, 40)

        l.addWidget(QLabel("Impostazioni Generali", objectName="SectionTitleMargin"))

        self.chk_startup = QCheckBox("Avvia con Windows (Minimizzato)")
        self.chk_startup.setChecked(check_autostart_registry(APP_NAME))
        self.chk_startup.stateChanged.connect(self._toggle_startup)
        l.addWidget(self.chk_startup)

        sl = QHBoxLayout()
        self.chk_sounds = QCheckBox("Abilita Suoni")
        self.chk_sounds.setChecked(self.ctrl.sounds_enabled)
        self.chk_sounds.stateChanged.connect(
            lambda s: self.ctrl.set_sounds_enabled(s == Qt.Checked)
        )
        sl.addWidget(self.chk_sounds)
        bt = QPushButton("TEST", objectName="ActionBtn")
        bt.setFixedSize(80, 30)
        bt.clicked.connect(lambda: self.ctrl.play_sound("apply", force=True))
        sl.addWidget(bt)
        sl.addStretch()
        l.addLayout(sl)

        # Pausa monitoraggio
        pl = QHBoxLayout()
        self.chk_pause_monitor = QCheckBox("Pausa monitoraggio automatico")
        self.chk_pause_monitor.setChecked(False)
        self.chk_pause_monitor.stateChanged.connect(
            lambda s: self.ctrl.set_monitoring_paused(s == Qt.Checked)
        )
        pl.addWidget(self.chk_pause_monitor)
        pl.addStretch()
        l.addLayout(pl)

        # Risparmio CPU
        cl = QHBoxLayout()
        self.chk_gpu_pause_hidden = QCheckBox("Pausa monitor GPU quando in tray (risparmio CPU)")
        self.chk_gpu_pause_hidden.setChecked(
            self.config_mgr.get("gpu_pause_when_hidden", True)
        )
        self.chk_gpu_pause_hidden.stateChanged.connect(
            lambda s: self.config_mgr.set("gpu_pause_when_hidden", s == Qt.Checked)
        )
        cl.addWidget(self.chk_gpu_pause_hidden)
        cl.addStretch()
        l.addLayout(cl)

        l.addSpacing(20)

        # ── FUNZIONI v2.7 ────────────────────────────────────────────────
        l.addWidget(QLabel("Protezioni & Automazione", objectName="SectionTitle"))

        # B — Auto backup
        abl = QHBoxLayout()
        self.chk_auto_backup = QCheckBox("Backup automatico profili all'avvio (zip)")
        self.chk_auto_backup.setChecked(
            self.config_mgr.get("auto_backup_enabled", True))
        self.chk_auto_backup.stateChanged.connect(
            lambda s: self.config_mgr.set("auto_backup_enabled", s == Qt.Checked))
        abl.addWidget(self.chk_auto_backup)
        btn_backup_now = QPushButton("BACKUP ORA", objectName="ActionBtn")
        btn_backup_now.setFixedHeight(30)
        btn_backup_now.clicked.connect(self._backup_now)
        abl.addWidget(btn_backup_now)
        btn_backup_dir = QPushButton("APRI CARTELLA BACKUP", objectName="ActionBtn")
        btn_backup_dir.setFixedHeight(30)
        btn_backup_dir.clicked.connect(
            lambda: open_in_explorer(self._backup_mgr.backup_dir))
        abl.addWidget(btn_backup_dir)
        abl.addStretch()
        l.addLayout(abl)

        # F — Hotkey globali
        hkl = QHBoxLayout()
        self.chk_hotkeys = QCheckBox(
            "Hotkey globali Ctrl+Alt+1..9 (applica l'N° profilo)")
        self.chk_hotkeys.setChecked(
            self.config_mgr.get("global_hotkeys_enabled", True))
        self.chk_hotkeys.stateChanged.connect(self._toggle_hotkeys)
        hkl.addWidget(self.chk_hotkeys)
        hkl.addStretch()
        l.addLayout(hkl)

        # H — Check aggiornamenti
        upl = QHBoxLayout()
        self.chk_updates = QCheckBox("Controlla aggiornamenti all'avvio (GitHub)")
        self.chk_updates.setChecked(self.config_mgr.get("check_updates", True))
        self.chk_updates.stateChanged.connect(
            lambda s: self.config_mgr.set("check_updates", s == Qt.Checked))
        upl.addWidget(self.chk_updates)
        upl.addStretch()
        l.addLayout(upl)

        # G — Watchdog temperatura
        wdl = QHBoxLayout()
        self.chk_watchdog = QCheckBox("Watchdog temperatura: sopra")
        self.chk_watchdog.setChecked(
            self.config_mgr.get("temp_watchdog_enabled", False))
        self.chk_watchdog.stateChanged.connect(
            lambda s: self.config_mgr.set("temp_watchdog_enabled", s == Qt.Checked))
        wdl.addWidget(self.chk_watchdog)
        self.spin_wd_temp = QSpinBox()
        self.spin_wd_temp.setRange(60, 110)
        self.spin_wd_temp.setSuffix(" °C")
        self.spin_wd_temp.setValue(
            int(self.config_mgr.get("temp_watchdog_threshold", 90)))
        self.spin_wd_temp.valueChanged.connect(
            lambda v: self.config_mgr.set("temp_watchdog_threshold", int(v)))
        wdl.addWidget(self.spin_wd_temp)
        wdl.addWidget(QLabel("per"))
        self.spin_wd_dur = QSpinBox()
        self.spin_wd_dur.setRange(3, 120)
        self.spin_wd_dur.setSuffix(" s")
        self.spin_wd_dur.setValue(
            int(self.config_mgr.get("temp_watchdog_duration_s", 10)))
        self.spin_wd_dur.valueChanged.connect(
            lambda v: self.config_mgr.set("temp_watchdog_duration_s", int(v)))
        wdl.addWidget(self.spin_wd_dur)
        wdl.addWidget(QLabel("→ applica"))
        self.combo_wd_profile = QComboBox()
        self._reload_wd_profiles()
        self.combo_wd_profile.currentTextChanged.connect(
            lambda t: self.config_mgr.set("temp_watchdog_profile", t) if t else None)
        wdl.addWidget(self.combo_wd_profile)
        wdl.addStretch()
        l.addLayout(wdl)

        # E — Scheduler orario
        schl = QHBoxLayout()
        self.chk_scheduler = QCheckBox("Scheduler orario profili")
        self.chk_scheduler.setChecked(
            self.config_mgr.get("scheduler_enabled", False))
        self.chk_scheduler.stateChanged.connect(
            lambda s: self.config_mgr.set("scheduler_enabled", s == Qt.Checked))
        schl.addWidget(self.chk_scheduler)
        btn_sched = QPushButton("REGOLE ORARIE...", objectName="ActionBtn")
        btn_sched.setFixedHeight(30)
        btn_sched.clicked.connect(self._edit_schedule_rules)
        schl.addWidget(btn_sched)
        self.lbl_sched_count = QLabel()
        self._update_sched_count()
        schl.addWidget(self.lbl_sched_count)
        schl.addStretch()
        l.addLayout(schl)

        l.addSpacing(20)

        l.addWidget(QLabel("Backup & Ripristino", objectName="SectionTitle"))
        bkl = QHBoxLayout()
        bex = QPushButton("ESPORTA TUTTO (JSON)", objectName="ActionBtn")
        bex.setIcon(IconFactory.get_icon("backup", "white"))
        bex.clicked.connect(self._export_data)
        bim = QPushButton("IMPORTA TUTTO (JSON)", objectName="ActionBtn")
        bim.setIcon(IconFactory.get_icon("backup", "#aaa"))
        bim.clicked.connect(self._import_data)
        bkl.addWidget(bex)
        bkl.addWidget(bim)
        bkl.addStretch()
        l.addLayout(bkl)
        l.addSpacing(20)

        l.addWidget(QLabel("MSI Afterburner", objectName="SectionTitle"))
        ml = QHBoxLayout()
        for text, cb in [
            ("AVVIA",                self._start_msi_bg),
            ("AVVIA (PRIMO PIANO)",  self._start_msi_fg),
            ("APRI CARTELLA",        self._open_msi_dir),
            ("APRI PROFILES",        self._open_profiles_dir),
        ]:
            b = QPushButton(text, objectName="ActionBtn")
            b.clicked.connect(cb)
            ml.addWidget(b)
        ml.addStretch()
        l.addLayout(ml)

        self.lbl_msi_status = QLabel()
        self.lbl_msi_status.setObjectName("MsiStatusStopped")
        l.addWidget(self.lbl_msi_status)
        self._update_msi_status()
        l.addSpacing(20)

        # ── ASPETTO (selettore tema) ─────────────────────────────────────
        self._build_appearance_section(l)

        # Info versione
        l.addStretch()
        info = QLabel(f"{APP_NAME} v{APP_VERSION}")
        info.setStyleSheet(f"color: {THEME['text_muted']}; font-size: 11px;")
        info.setAlignment(Qt.AlignCenter)
        l.addWidget(info)

        self.pages.addWidget(page)

    # ----------------------------------------------------------------
    # APPEARANCE / THEME SELECTOR
    # ----------------------------------------------------------------

    def _build_appearance_section(self, parent_layout: QVBoxLayout) -> None:
        """
        Sezione 'Aspetto' nelle impostazioni: permette di scegliere il tema
        della UI tra quelli scoperti da ThemeRegistry.

        Cambiando tema viene salvato in config e proposto un riavvio.
        """
        parent_layout.addWidget(QLabel("Aspetto", objectName="SectionTitle"))

        # Combo + label descrittiva
        row = QHBoxLayout()
        lbl = QLabel("Tema interfaccia:")
        lbl.setStyleSheet("color: white; font-size: 13px;")
        row.addWidget(lbl)

        self.cmb_theme = QComboBox()
        descriptors = ThemeRegistry.list_descriptors()
        current_theme_id = self.config_mgr.get("ui_theme", "red_glossy")
        current_index = 0
        for i, desc in enumerate(descriptors):
            self.cmb_theme.addItem(desc.name, userData=desc.id)
            self.cmb_theme.setItemData(
                i, f"{desc.description}\nAutore: {desc.author}  —  v{desc.version}",
                Qt.ToolTipRole,
            )
            if desc.id == current_theme_id:
                current_index = i
        self.cmb_theme.setCurrentIndex(current_index)
        self.cmb_theme.setMinimumWidth(220)
        self.cmb_theme.currentIndexChanged.connect(self._on_theme_selected)
        row.addWidget(self.cmb_theme)
        row.addStretch()
        parent_layout.addLayout(row)

        # Descrizione del tema correntemente selezionato
        self.lbl_theme_desc = QLabel()
        self.lbl_theme_desc.setWordWrap(True)
        self.lbl_theme_desc.setStyleSheet(
            f"color: {THEME['text_dim']}; font-size: 12px; margin-top: 4px;",
        )
        parent_layout.addWidget(self.lbl_theme_desc)
        self._update_theme_description()

    def _update_theme_description(self) -> None:
        """Aggiorna l'etichetta di descrizione sotto il combo tema."""
        if not hasattr(self, "cmb_theme"):
            return
        theme_id = self.cmb_theme.currentData()
        desc = ThemeRegistry.get(theme_id) if theme_id else None
        if desc:
            self.lbl_theme_desc.setText(
                f"{desc.description}  —  Autore: {desc.author or 'sconosciuto'}, v{desc.version}",
            )
        else:
            self.lbl_theme_desc.setText("")

    def _on_theme_selected(self, _index: int) -> None:
        """
        Handler cambio tema: salva la scelta in config, aggiorna la descrizione
        e chiede all'utente se vuole riavviare ora per applicare il nuovo tema.
        """
        self._update_theme_description()

        new_id = self.cmb_theme.currentData()
        if not new_id:
            return
        old_id = self.config_mgr.get("ui_theme", "red_glossy")
        if new_id == old_id:
            return  # nessun cambio reale

        # Persisti la scelta
        self.config_mgr.set("ui_theme", new_id)
        self.add_log(f"Tema selezionato: {new_id} (riavvio richiesto)")

        dlg = StyledMessageBox(
            "Riavvio richiesto",
            "Il cambio tema verrà applicato al prossimo avvio.\n\n"
            "Vuoi riavviare l'applicazione ora?",
            show_cancel=True,
            parent=self,
        )
        if dlg.exec():
            self._restart_application()

    def _restart_application(self) -> None:
        """Riavvia l'applicazione (cleanup + relaunch dello stesso processo)."""
        try:
            args = [sys.executable] + [a for a in sys.argv if a != "--minimized"]
            self.add_log("Riavvio in corso...")
            self._cleanup()
            subprocess.Popen(args, close_fds=True)
            QApplication.instance().quit()
        except Exception as e:  # noqa: BLE001
            self.add_log(f"Errore riavvio: {e}")
            StyledMessageBox(
                "Errore",
                f"Impossibile riavviare automaticamente:\n{e}\n\n"
                "Chiudi e riapri manualmente l'applicazione.",
                parent=self,
            ).exec()

    # ================================================================
    # KEYBOARD SHORTCUTS
    # ================================================================

    def _setup_shortcuts(self) -> None:
        shortcuts = [
            (QKeySequence("F5"),      self._refresh_profiles),
            (QKeySequence("Ctrl+N"),  self._create_profile),
            (QKeySequence("Ctrl+D"),  self._duplicate_selected),
            (QKeySequence("Delete"),  self._delete_selected_shortcut),
            (QKeySequence("F2"),      self._rename_selected_shortcut),
            (QKeySequence("Ctrl+F"),  self._focus_search),
            (QKeySequence("Ctrl+L"),  lambda: self._switch_page(PAGE_LOGS)),
            (QKeySequence("Ctrl+H"),  lambda: self._switch_page(PAGE_HISTORY)),
            (QKeySequence("Ctrl+,"),  lambda: self._switch_page(PAGE_SETTINGS)),
            (QKeySequence("Escape"),  self._clear_search_or_close),
            (QKeySequence("Return"),  self._apply_selected_shortcut),
            (QKeySequence("Ctrl+1"),  lambda: self._switch_page(PAGE_DASHBOARD)),
            (QKeySequence("Ctrl+2"),  lambda: self._switch_page(PAGE_PROFILES)),
        ]
        for seq, cb in shortcuts:
            sc = QShortcut(seq, self)
            sc.activated.connect(cb)

    def _focus_search(self) -> None:
        if self.pages.currentIndex() != PAGE_PROFILES:
            self._switch_page(PAGE_PROFILES)
        self.search_box.setFocus()
        self.search_box.selectAll()

    def _clear_search_or_close(self) -> None:
        if self.search_box.hasFocus() and self.search_box.text():
            self.search_box.clear()
        # else: lasciato come no-op (evita chiusure accidentali)

    def _delete_selected_shortcut(self) -> None:
        if self.pages.currentIndex() != PAGE_PROFILES:
            return
        name = self._get_selected_profile_name()
        if name:
            self._delete_profile(name)

    def _rename_selected_shortcut(self) -> None:
        if self.pages.currentIndex() != PAGE_PROFILES:
            return
        name = self._get_selected_profile_name()
        if name:
            self._rename_profile(name)

    def _apply_selected_shortcut(self) -> None:
        if self.pages.currentIndex() == PAGE_PROFILES:
            self._apply_selected()

    # ================================================================
    # NAVIGATION
    # ================================================================

    def _switch_page(self, idx: int) -> None:
        # Check unsaved changes quando si esce dal CFG Editor
        if (hasattr(self, "vf_editor")
                and self.pages.currentIndex() == PAGE_CFG_EDITOR
                and idx != PAGE_CFG_EDITOR
                and self._editor_has_pending_changes()):
            dlg = StyledMessageBox(
                "Modifiche non salvate",
                "Il CFG Editor ha modifiche non salvate.\nVuoi continuare senza salvare?",
                show_cancel=True,
                parent=self,
            )
            if not dlg.exec():
                return

        self.pages.setCurrentIndex(idx)
        self.page_title.setText(PAGE_TITLES[idx])
        for i, btn in enumerate(self.nav_btns):
            btn.setProperty("active", i == idx)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if idx == PAGE_ASSOCIATIONS:
            self._refresh_assoc()
        elif idx == PAGE_HISTORY:
            self._refresh_history()

        if hasattr(self, "vf_editor"):
            try:
                self.vf_editor.set_active(idx == PAGE_CFG_EDITOR)
            except AttributeError:
                pass

    def _editor_has_pending_changes(self) -> bool:
        try:
            return bool(self.vf_editor.has_pending_changes())
        except AttributeError:
            return False

    # ================================================================
    # CFG EDITOR OPEN HELPERS
    # ================================================================

    def _open_cfg_editor_for_selected(self) -> None:
        name = self._get_selected_profile_name()
        if not name:
            StyledMessageBox("Info", "Seleziona un profilo dalla lista.", parent=self).exec()
            return
        self._open_cfg_editor_for_profile(name)

    def _open_cfg_editor_for_profile(self, profile_name: str) -> None:
        ven_files = self.ctrl.get_cfg_files_for_profile(profile_name)
        profile1_file = self.ctrl.get_profile1_for_profile(profile_name)
        if not ven_files and not profile1_file:
            StyledMessageBox(
                "Errore",
                f"Nessun file supportato trovato per '{profile_name}'.\n"
                "Sono ammessi solo VEN_*.cfg e Profile1.cfg (no stub vuoti).",
                parent=self,
            ).exec()
            return

        self._switch_page(PAGE_CFG_EDITOR)
        loaded = False
        if hasattr(self.vf_editor, "load_profile_directory"):
            try:
                loaded = bool(
                    self.vf_editor.load_profile_directory(
                        ven_files,
                        profile1_file=profile1_file,
                    )
                )
            except Exception as e:  # noqa: BLE001
                logger.debug(f"load_profile_directory error: {e}")
        if not loaded and hasattr(self.vf_editor, "load_cfg_file"):
            fallback = ven_files[0] if ven_files else profile1_file
            if fallback is not None:
                try:
                    loaded = bool(self.vf_editor.load_cfg_file(fallback))
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"load_cfg_file error: {e}")

        if loaded:
            count = len(ven_files) + (1 if profile1_file else 0)
            self.add_log(f"CFG Editor: aperti {count} file per '{profile_name}'")
        else:
            self.add_log(f"CFG Editor: errore apertura per '{profile_name}'")

    def _on_cfg_editor_saved(self, file_path: str) -> None:
        self.add_log(f"CFG Editor: salvato {Path(file_path).name}")
        self._show_notification("CFG salvato con successo")
        # Invalida cache: i parametri del profilo potrebbero essere cambiati
        for name in self.profile_mgr.list_profiles():
            self._profile_extractor.invalidate(name)
        if self._view_mode == "card":
            self._refresh_card_view()

    def _on_editor_dirty_changed(self, dirty: bool) -> None:
        """Indicatore visivo nella sidebar (asterisco)."""
        btn = self.nav_btns[PAGE_CFG_EDITOR]
        btn.setText("CFG EDITOR *" if dirty else "CFG EDITOR")
        btn.setProperty("dirty", dirty)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    # ================================================================
    # PROFILE APPLY (non-blocking)
    # ================================================================

    def _apply_profile(self, name: str, silent: bool = True) -> None:
        if self._apply_worker and self._apply_worker.isRunning():
            return
        self._set_apply_buttons_enabled(False)
        self._apply_worker = ProfileApplyWorker(self.ctrl, name, silent=silent)
        self._apply_worker.finished.connect(self._on_apply_done)
        self._apply_worker.start()
        if not silent:
            self.add_log(f"Applicazione: {name}...")

    def _on_apply_done(self, ok: bool, name: str, silent: bool) -> None:
        self._set_apply_buttons_enabled(True)
        if not ok:
            if not silent:
                self.add_log(f"Errore applicazione: {name}")
            return
        dn = self.ctrl.get_display_name(name)
        self.lbl_active_prof.setText(f"Profilo Attivo: {dn}")
        if not self._process_logic.is_associated_app_running():
            self.lbl_active_app.setText("App: Desktop (Idle)")
        self._refresh_profiles()
        self._update_tray_tooltip(name, "")
        if not silent:
            self.add_log(f"Applicato: {name}")
            self._show_notification(f"Applicato: {dn}")

    # ================================================================
    # PROFILE ACTIONS
    # ================================================================

    def _apply_selected(self) -> None:
        name = self._get_selected_profile_name()
        if name:
            self._apply_profile(name, silent=False)

    def _create_profile(self) -> None:
        n = self.profile_mgr.get_next_profile_number()
        d = StyledInputDialog("Nuovo Profilo", "Nome:", f"Profile {n}", self)
        if d.exec() and d.text_value:
            ok, msg = self.ctrl.create_profile(d.text_value)
            if ok:
                self._refresh_profiles()
                self._refresh_tray_menu()
            else:
                StyledMessageBox("Errore", msg, parent=self).exec()

    def _duplicate_selected(self) -> None:
        source = self._get_selected_profile_name()
        if not source:
            StyledMessageBox("Info", "Seleziona un profilo da duplicare.", parent=self).exec()
            return
        d = StyledInputDialog("Duplica Profilo", "Nome del nuovo profilo:", f"{source} (copia)", self)
        if d.exec() and d.text_value:
            ok, msg = self.ctrl.duplicate_profile(source, d.text_value)
            if ok:
                self._refresh_profiles()
                self._refresh_tray_menu()
                self.add_log(f"Profilo duplicato: {source} → {msg}")
            else:
                StyledMessageBox("Errore", msg, parent=self).exec()

    def _edit_profile(self) -> None:
        name = self._get_selected_profile_name()
        if not name:
            return
        self.ctrl.start_editing(name)
        self._apply_profile(name, silent=True)
        QTimer.singleShot(500, lambda: self._edit_step2(name))

    def _edit_step2(self, name: str) -> None:
        self.msi_ctrl.start(show_window=True)
        self.add_log("Editor aperto.")
        msg = f"Modifica {name} in Afterburner e SALVA su SLOT 1.\nPoi clicca OK."
        if StyledMessageBox("Editor", msg, parent=self).exec():
            self.ctrl.finish_editing(name)
            QTimer.singleShot(1000, self._edit_resume)
        else:
            self.ctrl.cancel_editing()

    def _edit_resume(self) -> None:
        self.ctrl.resume_after_edit()
        # Invalida cache per il profilo appena editato
        for name in self.profile_mgr.list_profiles():
            self._profile_extractor.invalidate(name)
        if self._view_mode == "card":
            self._refresh_card_view()
        self.add_log("MSI riavviato, monitoraggio ripreso.")

    def _set_default(self) -> None:
        name = self._get_selected_profile_name()
        if not name:
            return
        if StyledMessageBox("Default", f"Usa '{name}' come Default?", True, self).exec():
            if self.ctrl.set_as_default(name):
                self._update_def_label()
                self._refresh_profiles()
                if self.ctrl.current_profile == "Default":
                    self.lbl_active_prof.setText(f"Profilo Attivo: Default ({name})")

    def _set_as_default_by_name(self, name: str) -> None:
        if StyledMessageBox("Default", f"Usa '{name}' come Default?", True, self).exec():
            if self.ctrl.set_as_default(name):
                self._update_def_label()
                self._refresh_profiles()
                if self.ctrl.current_profile == "Default":
                    self.lbl_active_prof.setText(f"Profilo Attivo: Default ({name})")

    def _reset_default(self) -> None:
        if StyledMessageBox("Reset", "Ripristinare Default a VirginStock?", True, self).exec():
            if self.ctrl.reset_default():
                self._update_def_label()
                if self.ctrl.current_profile == "Default":
                    self._apply_profile("Default", silent=False)

    def _associate_exe(self) -> None:
        name = self._get_selected_profile_name()
        if not name:
            return
        fp, _ = QFileDialog.getOpenFileName(self, "Seleziona EXE", "C:\\", "Eseguibili (*.exe)")
        if fp:
            self.ctrl.add_association(Path(fp).name, name)
            self.add_log(f"Associato {Path(fp).name} → {name}")

    def _rename_profile(self, old: str) -> None:
        d = StyledInputDialog("Rinomina", "Nuovo nome:", old, self)
        if d.exec() and d.text_value:
            ok, msg = self.ctrl.rename_profile(old, d.text_value)
            if ok:
                self._refresh_profiles()
                self._refresh_tray_menu()
            else:
                StyledMessageBox("Errore", msg, parent=self).exec()

    def _delete_profile(self, name: str) -> None:
        if StyledMessageBox("Elimina", f"Eliminare '{name}'?", True, self).exec():
            if self.ctrl.delete_profile(name):
                self._refresh_profiles()
                self._refresh_tray_menu()

    # ================================================================
    # SEARCH / FILTER
    # ================================================================

    def _on_search_changed(self, text: str) -> None:
        self._profile_filter = text.strip().lower()
        self._apply_filter_to_list()
        if self._view_mode == "card":
            self._refresh_card_view()

    def _apply_filter_to_list(self) -> None:
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            visible = (not self._profile_filter
                       or self._profile_filter in item.text().lower())
            item.setHidden(not visible)

    # ================================================================
    # PROFILE LIST / CARDS
    # ================================================================

    def _refresh_profiles(self) -> None:
        # Salva selezione corrente per ripristinarla dopo refresh
        current_selected = self._get_selected_profile_name()

        self.profile_list.clear()
        for n in self.profile_mgr.list_profiles():
            self.profile_list.addItem(n)
        self._update_profile_visuals()
        self._apply_filter_to_list()

        # Restore selection
        if current_selected:
            for i in range(self.profile_list.count()):
                if self.profile_list.item(i).text() == current_selected:
                    self.profile_list.setCurrentRow(i)
                    break

        if self._view_mode == "card":
            self._refresh_card_view()

    def _update_profile_visuals(self) -> None:
        """Aggiorna icone della lista profili con badge colorato (LucideIcons)."""
        from widgets_common.lucide_icons import LucideIcons
        from constants import PROFILE_PRESET_ICONS

        target = self.ctrl.current_profile
        if target == "Default":
            target = self.config_mgr.get("default_alias", "VirginStock")

        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            name = item.text()

            icon_key, _custom = self.ctrl.get_profile_icon(name)
            lucide_key = icon_key if (icon_key and LucideIcons.has(icon_key)) else "folder"
            preset_meta = PROFILE_PRESET_ICONS.get(icon_key) if icon_key else None
            preset_color = preset_meta["color"] if preset_meta else "#3a3a44"

            is_active = (name == target)
            if is_active:
                item.setIcon(LucideIcons.badge_icon(
                    lucide_key, size=28,
                    badge_color=THEME["primary"],
                    glyph_color="#ffffff",
                    ring_color="rgba(255,255,255,0.85)",
                ))
                item.setForeground(QColor("white"))
                item.setBackground(QColor(255, 46, 46, 30))
                f = item.font(); f.setBold(True); item.setFont(f)
            else:
                item.setIcon(LucideIcons.badge_icon(
                    lucide_key, size=28,
                    badge_color=preset_color,
                    glyph_color="#ffffff",
                ))
                item.setForeground(QColor("#cfcfd6"))
                item.setBackground(Qt.transparent)
                f = item.font(); f.setBold(False); item.setFont(f)
        self.profile_list.setIconSize(QSize(28, 28))

    def _profile_ctx_menu(self, pos) -> None:
        item = self.profile_list.itemAt(pos)
        if not item:
            return
        name = item.text()
        self._show_profile_menu(name, self.profile_list.mapToGlobal(pos))

    def _profile_card_ctx_menu(self, name: str, global_pos) -> None:
        self._show_profile_menu(name, global_pos)

    def _show_profile_menu(self, name: str, global_pos) -> None:
        menu = QMenu(self)
        menu.addAction(IconFactory.get_icon("play", "white"),
                       "Applica", lambda: self._apply_profile(name, silent=False))
        menu.addAction(IconFactory.get_icon("save", "#ccc"),
                       "Duplica", lambda: self._duplicate_via_menu(name))
        menu.addAction(IconFactory.get_icon("edit", "#ccc"),
                       "Cambia Icona", lambda: self._change_profile_icon(name))
        menu.addAction(IconFactory.get_icon("gear", "#ccc"),
                       "CFG Editor", lambda: self._open_cfg_editor_for_profile(name))
        menu.addAction(IconFactory.get_icon("edit", "#ccc"),
                       "Rinomina (F2)", lambda: self._rename_profile(name))
        menu.addSeparator()
        menu.addAction(IconFactory.get_icon("backup", "#ccc"),
                       "Esporta profilo…", lambda: self._export_single_profile(name))
        menu.addAction(IconFactory.get_icon("save", "#ccc"),
                       "Imposta come Default", lambda: self._set_as_default_by_name(name))
        menu.addSeparator()
        menu.addAction(IconFactory.get_icon("trash", "#ff5555"),
                       "Elimina (Del)", lambda: self._delete_profile(name))
        menu.exec(global_pos)

    def _duplicate_via_menu(self, name: str) -> None:
        d = StyledInputDialog("Duplica Profilo", "Nome del nuovo profilo:", f"{name} (copia)", self)
        if d.exec() and d.text_value:
            ok, msg = self.ctrl.duplicate_profile(name, d.text_value)
            if ok:
                self._refresh_profiles()
                self._refresh_tray_menu()
            else:
                StyledMessageBox("Errore", msg, parent=self).exec()

    def _export_single_profile(self, name: str) -> None:
        fp, _ = QFileDialog.getSaveFileName(
            self, "Esporta profilo",
            str(Path.home() / "Desktop" / f"{name}_profile.json"),
            "JSON (*.json)",
        )
        if not fp:
            return
        if self.ctrl.export_profile(name, Path(fp)):
            self._show_notification(f"Profilo esportato: {name}")
            self.add_log(f"Esportato: {fp}")
        else:
            StyledMessageBox("Errore", "Esportazione fallita.", parent=self).exec()

    # ================================================================
    # ASSOCIATIONS
    # ================================================================

    def _refresh_assoc(self) -> None:
        self.assoc_table.setRowCount(0)
        for row, (exe, prof) in enumerate(self.config_mgr.get_associations().items()):
            self.assoc_table.insertRow(row)
            self.assoc_table.setItem(row, 0, QTableWidgetItem(exe))
            self.assoc_table.setItem(row, 1, QTableWidgetItem(prof))

    def _delete_assoc(self) -> None:
        row = self.assoc_table.currentRow()
        if row < 0:
            return
        exe = self.assoc_table.item(row, 0).text()
        self.ctrl.remove_association(exe)
        self.assoc_table.removeRow(row)

    # ================================================================
    # VIEW MODE TOGGLE
    # ================================================================

    def _set_view_mode(self, mode: str) -> None:
        self._view_mode = mode
        self.btn_view_list.setChecked(mode == "list")
        self.btn_view_card.setChecked(mode == "card")
        if mode == "list":
            self.profile_views_stack.setCurrentIndex(0)
        else:
            self.profile_views_stack.setCurrentIndex(1)
            self._refresh_card_view()

    def _on_card_selection_changed(self, name: str) -> None:
        for i in range(self.profile_list.count()):
            if self.profile_list.item(i).text() == name:
                self.profile_list.setCurrentRow(i)
                break

    def _get_selected_profile_name(self) -> str:
        if self._view_mode == "card":
            return self.profile_card_view.get_selected()
        c = self.profile_list.currentItem()
        return c.text() if c else ""

    def _refresh_card_view(self) -> None:
        default_alias = self.config_mgr.get("default_alias", "VirginStock")
        active = self.ctrl.current_profile
        if active == "Default":
            active = default_alias

        # OPT 3 (v2.7): una sola lettura del file icone per refresh
        all_icons = self.ctrl.get_profile_icons()

        infos: List[ProfileCardInfo] = []
        for name in self.profile_mgr.list_profiles():
            if self._profile_filter and self._profile_filter not in name.lower():
                continue
            profile_dir = self.profile_mgr.get_profile_dir(name)
            icon_data = all_icons.get(name, {})
            icon_key = icon_data.get("key", "")
            icon_custom = icon_data.get("custom", "")
            info = self._profile_extractor.extract(
                profile_name=name,
                profile_dir=profile_dir,
                profile_section="Profile1",
                is_active=(name == active),
                is_default=(name == default_alias),
                icon_key=icon_key,
                icon_custom_path=icon_custom,
            )
            infos.append(info)
        self.profile_card_view.set_profiles(infos)

    # ================================================================
    # PROFILE ICON MANAGEMENT
    # ================================================================

    def _change_profile_icon(self, profile_name: str) -> None:
        current_key, current_custom = self.ctrl.get_profile_icon(profile_name)
        dlg = ProfileIconSelector(current_key, current_custom, parent=self)
        if dlg.exec():
            self.ctrl.set_profile_icon(
                profile_name,
                icon_key=dlg.selected_key,
                custom_path=dlg.selected_custom,
            )
            self._profile_extractor.invalidate(profile_name)
            if self._view_mode == "card":
                self._refresh_card_view()
            self.add_log(f"Icona aggiornata per: {profile_name}")

    # ================================================================
    # GPU STATS
    # ================================================================

    def _on_gpu_stats(self, s: dict) -> None:
        """Slot: dati telemetria dal GpuStatsThread (thread-safe via Signal)."""
        self.gauge_temp.set_value(s["temp"])
        self.gauge_load.set_value(s["load"])
        self.gauge_fan.set_value(s["fan"])
        self.tel_core.set_value(s["core_clk"])
        self.tel_mem.set_value(s["mem_clk"])
        self.tel_power.set_value(s["power"])
        self.tel_vram.set_value(s["vram"])
        self.chart_temp.add_point(s["temp"])
        self.chart_load.add_point(s["load"])
        self.chart_power.add_point(s["power"])
        self.chart_vram.add_point(s["vram"])

        # G — Watchdog temperatura (v2.7)
        try:
            safe_profile = self._watchdog.feed(float(s.get("temp", 0)))
            if safe_profile:
                self.add_log(
                    f"[WATCHDOG] Temperatura critica → applico '{safe_profile}'")
                self.ctrl.play_sound("error")
                self._show_notification(
                    f"⚠ Watchdog temperatura!\nApplico profilo: {safe_profile}")
                self._apply_profile(safe_profile, silent=False)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Watchdog: {e}")

    # ================================================================
    # SERVIZI v2.7 — Backup / Scheduler / Hotkeys / Watchdog / Update
    # ================================================================

    def _backup_now(self) -> None:
        """B — Crea subito un backup zip dei profili (in thread)."""
        def worker() -> None:
            try:
                path = self._backup_mgr.create_backup()
                retention = int(self.config_mgr.get("auto_backup_retention", 10))
                self._backup_mgr.prune_old(keep=retention)
                msg = (f"Backup creato: {path.name}" if path
                       else "Backup fallito (vedi log)")
            except Exception as e:  # noqa: BLE001
                msg = f"Backup fallito: {e}"

            def notify() -> None:
                self.add_log(f"[BACKUP] {msg}")
                self._show_notification(msg)
            QTimer.singleShot(0, notify)

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_hotkeys(self, state: int) -> None:
        """F — Attiva/disattiva le hotkey globali dalla checkbox."""
        enabled = state == Qt.Checked
        self.config_mgr.set("global_hotkeys_enabled", enabled)
        if enabled:
            self._start_global_hotkeys()
            self.add_log("[HOTKEY] Hotkey globali attivate (Ctrl+Alt+1..9)")
        else:
            self._stop_global_hotkeys()
            self.add_log("[HOTKEY] Hotkey globali disattivate")

    def _reload_wd_profiles(self) -> None:
        """G — Ripopola la combo del profilo watchdog dai profili correnti."""
        combo = self.combo_wd_profile
        combo.blockSignals(True)
        try:
            combo.clear()
            profiles = self.profile_mgr.list_profiles() + ["Default"]
            combo.addItems(profiles)
            target = self.config_mgr.get("temp_watchdog_profile", "Default")
            idx = combo.findText(target)
            combo.setCurrentIndex(idx if idx >= 0 else combo.count() - 1)
        finally:
            combo.blockSignals(False)

    def _update_sched_count(self) -> None:
        """E — Aggiorna il contatore regole accanto al pulsante scheduler."""
        rules = self.config_mgr.get("schedule_rules", []) or []
        active = sum(1 for r in rules if r.get("enabled", True))
        self.lbl_sched_count.setText(
            f"{active} regole attive / {len(rules)} totali" if rules
            else "nessuna regola")
        self.lbl_sched_count.setStyleSheet("color:#888;")

    def _edit_schedule_rules(self) -> None:
        """E — Apre il dialog di editing delle regole orarie."""
        rules = self.config_mgr.get("schedule_rules", []) or []
        profiles = self.profile_mgr.list_profiles() + ["Default"]
        dlg = ScheduleRulesDialog(rules, profiles, self)
        if dlg.exec() and dlg.result_rules is not None:
            self.config_mgr.set("schedule_rules", dlg.result_rules)
            self._scheduler.reset()
            self._update_sched_count()
            self.add_log(
                f"[SCHEDULER] Regole aggiornate ({len(dlg.result_rules)})")

    def _check_scheduler(self) -> None:
        """E — Scheduler orario: applica il profilo della regola attiva.

        Il monitor processi ha priorità: se un'app associata è attiva,
        lo scheduler non interviene.
        """
        try:
            if self._process_logic.is_associated_app_running():
                return
            profile = self._scheduler.check()
            if not profile:
                return
            available = self.profile_mgr.list_profiles() + ["Default"]
            if profile not in available:
                self.add_log(f"[SCHEDULER] Profilo '{profile}' inesistente, salto")
                return
            if profile == self.ctrl.current_profile:
                return
            self.add_log(f"[SCHEDULER] Fascia oraria attiva → {profile}")
            self._apply_profile(profile, silent=False)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Scheduler check: {e}")

    def _start_global_hotkeys(self) -> None:
        """F — Registra Ctrl+Alt+1..9 come hotkey globali Windows."""
        from oc_services import GlobalHotkeyListener
        if self._hotkeys is not None:
            return

        def on_hotkey(n: int) -> None:
            # Callback dal thread hotkey → rimbalza sul thread UI
            QTimer.singleShot(0, lambda: self._on_hotkey_profile(n))

        self._hotkeys = GlobalHotkeyListener(on_hotkey)
        self._hotkeys.start()

    def _stop_global_hotkeys(self) -> None:
        if self._hotkeys is not None:
            self._hotkeys.stop()
            self._hotkeys = None

    def _on_hotkey_profile(self, n: int) -> None:
        """Ctrl+Alt+N → applica l'N-esimo profilo (ordine alfabetico)."""
        profiles = self.profile_mgr.list_profiles()
        if n < 1 or n > len(profiles):
            return
        profile = profiles[n - 1]
        self.add_log(f"[HOTKEY] Ctrl+Alt+{n} → {profile}")
        self._apply_profile(profile, silent=False)
        self._show_notification(f"Hotkey: profilo {profile}")

    def _check_updates_bg(self) -> None:
        """H — Check release GitHub (in thread; notifica sul thread UI)."""
        from oc_services import UpdateChecker
        try:
            info = UpdateChecker.check()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Update check: {e}")
            return
        if info:
            def notify() -> None:
                self.add_log(
                    f"[UPDATE] Nuova versione disponibile: {info['version']}")
                self._show_notification(
                    f"Aggiornamento disponibile: {info['version']}\n"
                    f"Vai su GitHub → Releases")
            QTimer.singleShot(0, notify)

    # ================================================================
    # AUTO PROFILE CHANGE
    # ================================================================

    def _on_auto_profile_change(self, profile_name: str, exe_name: str) -> None:
        self.add_log(f"[AUTO] {profile_name}" + (f" ← {exe_name}" if exe_name else ""))
        self._apply_profile(profile_name, silent=False)
        app = exe_name if exe_name else "Desktop (Idle)"
        self.lbl_active_app.setText(f"App: {app}")
        self._update_tray_tooltip(profile_name, exe_name)
        self._show_notification(f"Profilo: {profile_name}\n{app}")

    # ================================================================
    # HISTORY
    # ================================================================

    def _refresh_history(self) -> None:
        days_map = {0: 1, 1: 3, 2: 7, 3: 14, 4: 30}
        days = days_map.get(self.history_days_combo.currentIndex(), 7)
        usage = self.ctrl.get_usage_stats(days)
        self.usage_chart.set_data(usage)

        # Summary stats pills
        stats = self.ctrl.get_summary_stats(days)
        self.lbl_stat_total.setText(f"Totale: {stats['total_hours']:.1f} h")
        self.lbl_stat_switches.setText(f"Cambi: {int(stats['switch_count'])}")
        self.lbl_stat_avg.setText(f"Sessione media: {stats['avg_session_minutes']:.1f} min")
        top = stats.get("top_profile", "—")
        top_h = stats.get("top_profile_hours", 0.0)
        self.lbl_stat_top.setText(f"Più usato: {top} ({top_h:.1f}h)")

        entries = self.ctrl.history.get_recent_entries(200)
        self.history_table.setRowCount(0)
        for i, entry in enumerate(reversed(entries)):
            self.history_table.insertRow(i)
            self.history_table.setItem(i, 0, QTableWidgetItem(entry.timestamp[:19]))
            self.history_table.setItem(i, 1, QTableWidgetItem(entry.profile))
            self.history_table.setItem(i, 2, QTableWidgetItem(entry.exe or "-"))
            if entry.duration_sec > 0:
                mins = entry.duration_sec / 60
                dur_text = f"{mins:.1f} min" if mins < 60 else f"{mins / 60:.1f} h"
            else:
                dur_text = "attivo"
            self.history_table.setItem(i, 3, QTableWidgetItem(dur_text))

    def _export_history_csv(self) -> None:
        fp, _ = QFileDialog.getSaveFileName(
            self, "Esporta History CSV",
            str(Path.home() / "Desktop" / f"oc_history_{datetime.now():%Y%m%d}.csv"),
            "CSV (*.csv)",
        )
        if not fp:
            return
        if self.ctrl.export_history_csv(Path(fp)):
            self._show_notification("History esportata in CSV")
            self.add_log(f"History CSV: {fp}")
        else:
            StyledMessageBox("Errore", "Esportazione fallita.", parent=self).exec()

    # ================================================================
    # NOTIFICATIONS / LOG
    # ================================================================

    def _show_notification(self, message: str) -> None:
        if self.active_toast:
            try:
                self.active_toast.close()
            except Exception:  # noqa: BLE001
                pass
        preset = "default" if "Default" in message else "apply"
        self.ctrl.play_sound(preset)
        if self.config_mgr.get("show_tray_notifications", True):
            self.active_toast = ExternalToast(message)
            self.active_toast.show_toast(TIMING["toast_duration"])

    def add_log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        if hasattr(self, "log_area"):
            self.log_area.append(f"[{ts}] {message}")
        logger.info(message)

    # ================================================================
    # TRAY
    # ================================================================

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        pt = QPainter(pix)
        pt.setRenderHint(QPainter.Antialiasing)
        pt.setBrush(QColor(THEME["primary"]))
        pt.drawEllipse(10, 10, 44, 44)
        pt.end()
        self.tray.setIcon(QIcon(pix))
        self.tray.setToolTip("OC Profiles Manager")

        self.tray_menu = QMenu(self)
        self._build_tray_menu()
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._on_tray_click)
        self.tray.show()

    def _build_tray_menu(self) -> None:
        self.tray_menu.clear()
        a_show = self.tray_menu.addAction(
            IconFactory.get_icon("dashboard", "white"), "Apri Dashboard"
        )
        a_show.triggered.connect(self._restore_from_tray)
        self.tray_menu.addSeparator()

        pm = self.tray_menu.addMenu(IconFactory.get_icon("folder", "white"), "Profili Rapidi")
        ad = pm.addAction("Default")
        ad.triggered.connect(lambda: self._apply_profile("Default", silent=False))
        pm.addSeparator()
        for p in self.profile_mgr.list_profiles():
            a = pm.addAction(p)
            a.triggered.connect(lambda _, n=p: self._apply_profile(n, silent=False))

        self.tray_menu.addSeparator()
        ae = self.tray_menu.addAction(IconFactory.get_icon("power", "#ff5555"), "Esci")
        ae.triggered.connect(self._close_application)

    def _refresh_tray_menu(self) -> None:
        try:
            self._build_tray_menu()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"refresh tray menu: {e}")

    def _on_tray_click(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self._minimize_to_tray()
            else:
                self._restore_from_tray()

    def _update_tray_tooltip(self, profile: str, app: str) -> None:
        self.tray.setToolTip(f"OC Manager\n{profile}\n{app or 'Desktop'}")

    # ================================================================
    # WINDOW MANAGEMENT
    # ================================================================

    def _minimize_to_tray(self) -> None:
        self.hide()
        if self.config_mgr.get("show_tray_notifications", True):
            self.tray.showMessage(
                "OC Manager", "Minimizzato in tray.",
                QSystemTrayIcon.Information, 2000,
            )
        # Risparmio CPU: pausa telemetria GPU
        if self.config_mgr.get("gpu_pause_when_hidden", True):
            self.gpu_thread.set_paused(True)

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.gpu_thread.set_paused(False)

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self.btn_maximize.setIcon(IconFactory.get_icon("maximize", "#aaa"))
        else:
            self.showMaximized()
            self.btn_maximize.setIcon(IconFactory.get_icon("restore", "#aaa"))

    # ================================================================
    # MSI CONTROLS
    # ================================================================

    def _start_msi_bg(self) -> None:
        if self.msi_ctrl.is_running():
            StyledMessageBox("Info", "MSI Afterburner è già in esecuzione.", parent=self).exec()
            return
        self.msi_ctrl.start(show_window=False)
        self.add_log("MSI avviato (background)")
        self._show_notification("MSI Afterburner avviato")
        QTimer.singleShot(2000, self._update_msi_status)

    def _start_msi_fg(self) -> None:
        self.msi_ctrl.start(show_window=True)
        self.add_log("MSI aperto (primo piano)")
        QTimer.singleShot(2000, self._update_msi_status)

    def _open_msi_dir(self) -> None:
        d = self.msi_ctrl.msi_path.parent
        if not open_in_explorer(d):
            StyledMessageBox("Errore", f"Directory non trovata:\n{d}", parent=self).exec()

    def _open_profiles_dir(self) -> None:
        d = self.profile_mgr.manager_root
        if not open_in_explorer(d):
            StyledMessageBox("Errore", f"Directory non trovata:\n{d}", parent=self).exec()

    def _update_msi_status(self) -> None:
        if not hasattr(self, "lbl_msi_status"):
            return
        if self.msi_ctrl.is_running():
            self.lbl_msi_status.setText("● MSI Afterburner: In esecuzione")
            self.lbl_msi_status.setObjectName("MsiStatusRunning")
        else:
            self.lbl_msi_status.setText("● MSI Afterburner: Non attivo")
            self.lbl_msi_status.setObjectName("MsiStatusStopped")
        self.lbl_msi_status.style().unpolish(self.lbl_msi_status)
        self.lbl_msi_status.style().polish(self.lbl_msi_status)

    # ================================================================
    # SETTINGS
    # ================================================================

    def _toggle_startup(self, state) -> None:
        try:
            if state == Qt.Checked:
                cmd = f'"{sys.executable}" "{Path(__file__).resolve()}" --minimized'
                ok = set_autostart_registry(APP_NAME, cmd, enabled=True)
                self.add_log("Avvio automatico abilitato" if ok else "Errore registry")
            else:
                set_autostart_registry(APP_NAME, "", enabled=False)
                self.add_log("Avvio automatico disabilitato")
        except Exception as e:  # noqa: BLE001
            self.add_log(f"Errore Registry: {e}")

    def _update_def_label(self) -> None:
        alias = self.config_mgr.get("default_alias", "VirginStock")
        self.lbl_def_status.setText(f"Default: {alias}")

    # ================================================================
    # BACKUP / RESTORE
    # ================================================================

    def _export_data(self) -> None:
        fp, _ = QFileDialog.getSaveFileName(
            self, "Esporta",
            str(Path.home() / "Desktop" / "OC_Backup.json"),
            "JSON (*.json)",
        )
        if not fp:
            return
        data = {
            "meta": {"app": APP_NAME, "version": APP_VERSION, "date": str(datetime.now())},
            "config": self.config_mgr.config,
            "profiles": {},
        }
        from oc_core import iter_managed_cfg as _iter_mgd
        for pd in self.profile_mgr.manager_root.iterdir():
            if pd.is_dir() and pd.name not in ("Default", "_staging_tmp", "_backup_tmp"):
                data["profiles"][pd.name] = {}
                # Backup SOLO dei .cfg gestiti (VEN_*.cfg + ProfileN.cfg).
                for cf in _iter_mgd(pd):
                    try:
                        data["profiles"][pd.name][cf.name] = cf.read_text(errors="ignore")
                    except Exception:  # noqa: BLE001
                        pass
        try:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            self._show_notification("Backup completato!")
            self.add_log(f"Esportato: {fp}")
        except Exception as e:  # noqa: BLE001
            self.add_log(f"Errore export: {e}")

    def _import_data(self) -> None:
        fp, _ = QFileDialog.getOpenFileName(
            self, "Importa",
            str(Path.home() / "Desktop"),
            "JSON (*.json)",
        )
        if not fp:
            return
        if not StyledMessageBox("Importa", "Sovrascrivere configurazione?", True, self).exec():
            return
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "config" in data:
                local_msi = self.config_mgr.get("msi_path")
                imported = dict(data["config"])
                imp_msi = imported.get("msi_path", "")
                if local_msi and not os.path.exists(imp_msi):
                    imported["msi_path"] = local_msi
                # Sostituzione atomica sotto lock (merge con DEFAULT_CONFIG)
                self.config_mgr.replace_config(imported)
            if "profiles" in data:
                from oc_core import is_managed_cfg as _is_mgd
                for pn, files in data["profiles"].items():
                    td = self.profile_mgr.manager_root / pn
                    td.mkdir(parents=True, exist_ok=True)
                    for fn, content in files.items():
                        safe = Path(fn).name
                        if not _is_mgd(safe):
                            continue  # ignora .cfg estranei in vecchi JSON
                        (td / safe).write_text(content, encoding="utf-8", errors="ignore")
            self._profile_extractor.clear_cache()
            self._refresh_profiles()
            self._refresh_assoc()
            self._refresh_tray_menu()
            self._update_def_label()
            self._show_notification("Ripristino completato!")
            self.add_log("Backup ripristinato")
        except json.JSONDecodeError as e:
            StyledMessageBox("Errore", f"JSON non valido:\n{e}", parent=self).exec()
        except Exception as e:  # noqa: BLE001
            StyledMessageBox("Errore", f"Errore importazione:\n{e}", parent=self).exec()

    # ================================================================
    # GLASS EFFECT (Windows blur)
    # ================================================================

    def _apply_glass_effect(self) -> None:
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

            accent = AccentPolicy(state=3, flags=0, color=0x00222222, anim=0)
            data = WinCompData(
                attrib=19,
                data=ctypes.pointer(accent),
                size=ctypes.sizeof(accent),
            )
            ctypes.windll.user32.SetWindowCompositionAttribute(
                int(self.winId()), ctypes.pointer(data),
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Glass effect: {e}")

    # ================================================================
    # EVENT HANDLERS
    # ================================================================

    def paintEvent(self, event) -> None:
        # Bordi arrotondati + sfondo semitrasparente per lasciare passare
        # l'Acrylic blur di Windows (vedi _apply_glass_effect).
        # NB: il pixel a 0/0/0/1 della v2.6.1 lasciava passare il blur ma
        # non clippava agli angoli. Qui usiamo un alpha ~16 (molto sottile)
        # esteso su tutta l'area dei bordi arrotondati: il blur traspare,
        # ma gli angoli risultano correttamente smussati.
        from .style import THEME as _T
        radius_str = str(_T.get("window_radius", "12px")).replace("px", "").strip()
        try:
            radius = float(radius_str)
        except Exception:
            radius = 12.0
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Velo trasparente: l'Acrylic blur di Windows passa quasi del tutto;
        # il vero colore di fondo arriva dal #RootContainer (semitrasparente).
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 1))
        p.drawRoundedRect(rect, radius, radius)
        # Bordo glassy sottile sui bordi arrotondati
        border = QColor(255, 255, 255, 22)
        pen = QPen(border)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        p.end()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()
            # Disabilita drag sui bordi (resize)
            if e.pos().y() < 10 or e.pos().x() < 10 or e.pos().x() > self.width() - 10:
                self._drag_pos = None

    def mouseMoveEvent(self, e) -> None:
        if (e.buttons() == Qt.LeftButton
                and getattr(self, "_drag_pos", None) is not None):
            delta = e.globalPosition().toPoint() - self._drag_pos
            new_pos = self.pos() + delta
            if new_pos.y() < -50:
                new_pos.setY(-50)
            self.move(new_pos)
            self._drag_pos = e.globalPosition().toPoint()

    def resizeEvent(self, event) -> None:
        if hasattr(self, "sizegrip"):
            self.sizegrip.move(self.width() - 20, self.height() - 20)
        super().resizeEvent(event)

    def changeEvent(self, e) -> None:
        if e.type() == QEvent.WindowStateChange:
            if self.windowState() & Qt.WindowMinimized:
                e.ignore()
                self._minimize_to_tray()
                return
        super().changeEvent(e)
