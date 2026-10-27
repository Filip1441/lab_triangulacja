import os
import math
import threading
from datetime import datetime
import numpy as np
try:
    from scipy.optimize import curve_fit
except ImportError:
    pass

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QStackedWidget, QLabel, QGroupBox, 
    QTableWidget, QTableWidgetItem, QHeaderView,
    QDoubleSpinBox, QSpinBox, QStatusBar, QCheckBox, QTabWidget,
    QMessageBox, QTextEdit, QComboBox, QFileDialog, QButtonGroup
)
from PySide6.QtGui import QShortcut, QKeySequence, QFont, QAction
from PySide6.QtCore import Qt, Slot, QTimer

import pyqtgraph as pg

import config
from core.hardware_manager import HardwareManager
from core.camera_worker import CameraWorker
from core.pid_controller import PIDControllerWorker
from core.script_runner import ScriptRunner
from ui.widgets import CameraDisplayWidget, ParameterSlider, FloatParameterSlider
from ui.highlighter import PythonSyntaxHighlighter
from utils.data_logger import DataLogger
from ui.schematic_widget import InteractiveSchematicWidget
from ui.settings_dialog import SettingsDialog
from ui.export_page import ExportPage
from ui.admin_gate import request_admin_access
from utils.settings_store import SettingsStore
from core.share_server import ShareServer
from core import results

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.APP_NAME)
        self.resize(*config.WINDOW_SIZE)
        
        # Load Stylesheet
        style_path = os.path.join(os.path.dirname(__file__), "styles.qss")
        if os.path.exists(style_path):
            with open(style_path, "r") as f:
                self.setStyleSheet(f.read())
        
        # Setup Core Components
        self.hardware = HardwareManager()
        self.camera_worker = CameraWorker(self.hardware)
        self.pid_worker = PIDControllerWorker(self.hardware)
        self.data_logger = DataLogger()
        self.script_runner = None
        self._autorun_pending = False
        self.settings_dialog = None
        self.s1_frames = []
        self.s2_verifications = []   # (ok, window screenshot) after each 'Verify Answer', exported with the results
        self.new_frame_event = threading.Event()
        
        # Internal State
        self.camera_fov = config.DEFAULT_FOV_DEG
        self.current_raw_frame = None
        self.current_processed_frame = None
        self.current_spot_x = None
        self.current_spot_y = None
        
        self.autorun_timer = QTimer(self)
        self.autorun_timer.setSingleShot(True)
        self.autorun_timer.setInterval(1000)  # 1s debounce
        self.autorun_timer.timeout.connect(self._autorun_trigger)
        
        # Fitted curve state
        self.active_fit_type = None  # "linear" or "exp"
        self.active_fit_popt = None
        
        self.settings = SettingsStore()
        self.init_ui()
        self.connect_signals()
        self.settings.enabled = False
        self.restore_settings()
        self.settings.enabled = True
        self.settings_timer = QTimer(self)
        self.settings_timer.timeout.connect(self.settings.flush)
        self.settings_timer.start(1000)
        
        # Start Workers
        self.camera_worker.start()

        # Result sharing: download page + weekly cleanup of old packages
        self.share_server = ShareServer()
        self.share_server.start()
        results.purge_old()
        self.purge_timer = QTimer(self)
        self.purge_timer.timeout.connect(results.purge_old)
        self.purge_timer.start(6 * 3600 * 1000)
        
        # Hidden shortcut for Settings (cross-platform Preferences standard: Cmd+, on mac, Ctrl+, on Win/Linux)
        self.shortcut_settings = QShortcut(QKeySequence(QKeySequence.Preferences), self)
        self.shortcut_settings.setContext(Qt.ApplicationShortcut)
        self.shortcut_settings.activated.connect(self.open_admin)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Top Navigation
        nav_layout = QHBoxLayout()
        self.btn_stage0 = QPushButton("0. Setup && Scripting")
        self.btn_stage1 = QPushButton("1. Empirical Calibration")
        self.btn_stage2 = QPushButton("2. Analytical Modeling")
        self.btn_stage3 = QPushButton("3. Active Tracking")
        
        self.btn_stage0.setCheckable(True)
        self.btn_stage1.setCheckable(True)
        self.btn_stage2.setCheckable(True)
        self.btn_stage3.setCheckable(True)
        
        # Exclusive navigation button group
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_group.addButton(self.btn_stage0, 0)
        self.nav_group.addButton(self.btn_stage1, 1)
        self.nav_group.addButton(self.btn_stage2, 2)
        self.nav_group.addButton(self.btn_stage3, 3)
        self.nav_group.idClicked.connect(self.switch_stage)
        
        # Stage 0 is default
        self.btn_stage0.setChecked(True)
        
        nav_layout.addWidget(self.btn_stage0, 1)
        nav_layout.addWidget(self.btn_stage1, 1)
        nav_layout.addWidget(self.btn_stage2, 1)
        nav_layout.addWidget(self.btn_stage3, 1)
        self.btn_stage4 = QPushButton("4. Export Results")
        self.btn_stage4.setCheckable(True)
        self.btn_stage4.setObjectName("exportTab")
        self.nav_group.addButton(self.btn_stage4, 4)
        nav_layout.addWidget(self.btn_stage4, 1)
        self.btn_admin = QPushButton("admin")
        self.btn_admin.setObjectName("adminButton")
        self.btn_admin.setFlat(True)
        self.btn_admin.setFixedWidth(54)   # tiny, far right: the stage buttons share all the other width
        self.btn_admin.clicked.connect(self.open_admin)
        nav_layout.addWidget(self.btn_admin)
        main_layout.addLayout(nav_layout)
        
        # Content Area (Widescreen 16:9 layout)
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(8, 4, 8, 8)
        content_layout.setSpacing(8)
        main_layout.addLayout(content_layout, 1)
        
        # Left Panel - Visual representation (Schematic + Camera)
        self.left_panel = QVBoxLayout()
        content_layout.addLayout(self.left_panel, 3)
        
        # Horizontal layout for Schematic (left) and Camera Display (right)
        visual_layout = QHBoxLayout()
        visual_layout.setSpacing(8)
        self.schematic = InteractiveSchematicWidget()
        self.schematic.setMinimumHeight(180)
        self.schematic.setMaximumWidth(1200)
        
        # Right visual column (Spot Position widget + Camera widget)
        right_column = QVBoxLayout()
        right_column.setSpacing(6)
        
        self.spot_info_group = QGroupBox("Spot Location Details")
        self.spot_info_group.setMaximumHeight(80)
        spot_info_layout = QVBoxLayout(self.spot_info_group)
        spot_info_layout.setContentsMargins(8, 4, 8, 4)
        spot_info_layout.setSpacing(1)
        
        self.lbl_spot_title = QLabel("Spot Location")
        self.lbl_spot_title.setStyleSheet("font-weight: bold; color: #4daafc;")
        self.lbl_spot_x = QLabel("X: --- px")
        self.lbl_spot_y = QLabel("Y: --- px")
        
        spot_info_layout.addWidget(self.lbl_spot_title)
        spot_info_layout.addWidget(self.lbl_spot_x)
        spot_info_layout.addWidget(self.lbl_spot_y)
        
        self.camera_display = CameraDisplayWidget()
        
        right_column.addWidget(self.spot_info_group)
        right_column.addWidget(self.camera_display, 1)
        
        visual_layout.addWidget(self.schematic, 1)
        visual_layout.addLayout(right_column, 3)
        self.left_panel.addLayout(visual_layout)
        
        # Right Panel - Dynamic Stage Views
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 2)
        
        self.init_stage0_ui()
        self.init_stage1_ui()
        self.init_stage2_ui()
        self.init_stage3_ui()
        self.export_page = ExportPage(self)
        self.stack.addWidget(self.export_page)
        
        # Default stack index is 0 (Stage 0)
        self.stack.setCurrentIndex(0)

    def init_stage0_ui(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        # Code Sandbox Group
        code_group = QGroupBox("Python Image Processing Sandbox")
        code_layout = QVBoxLayout(code_group)
        
        # Code Editor
        self.txt_code = QTextEdit()
        self.txt_code.setFont(QFont("Courier", 10))
        # The editor starts completely empty; the demo solution lives in the admin window.
        
        # Syntax highlighter
        self.highlighter = PythonSyntaxHighlighter(self.txt_code.document())
        self.txt_code.textChanged.connect(self.on_code_changed)
        
        code_layout.addWidget(self.txt_code, 1)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.chk_autorun = QCheckBox("Auto-run")
        self.chk_autorun.setChecked(True)
        btn_layout.addWidget(self.chk_autorun)
        
        self.btn_run_script = QPushButton("Run Script")
        self.btn_stop_script = QPushButton("Stop Script")
        self.btn_stop_script.setEnabled(False)
        btn_layout.addWidget(self.btn_run_script)
        btn_layout.addWidget(self.btn_stop_script)
        code_layout.addLayout(btn_layout)
        
        layout.addWidget(code_group, 2)
        
        # Console output
        console_group = QGroupBox("Console Output")
        console_layout = QVBoxLayout(console_group)
        self.txt_console = QTextEdit()
        self.txt_console.setReadOnly(True)
        self.txt_console.setFont(QFont("Courier", 9))
        console_layout.addWidget(self.txt_console)
        
        layout.addWidget(console_group, 1)
        
        self.stack.addWidget(page)

    def init_stage1_ui(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        # Hardware Control
        self.hw_group = QGroupBox("Hardware Control")
        hw_layout = QVBoxLayout(self.hw_group)
        
        base_angle = int(round(getattr(config, 'DEFAULT_SERVO_BASE_ANGLE', 90.0)))
        slider_span = int(getattr(config, 'SERVO_SLIDER_RANGE_DEG', 10.0))
        min_angle = max(int(getattr(config, 'SERVO_MIN_LOGICAL_ANGLE', 40.0)), base_angle - slider_span)
        max_angle = min(int(getattr(config, 'SERVO_MAX_LOGICAL_ANGLE', 135.0)), base_angle + slider_span)
        self.slider_servo = ParameterSlider("Servo Angle", min_angle, max_angle, base_angle)
        hw_layout.addWidget(self.slider_servo)
        layout.addWidget(self.hw_group)
        
        # Sub-Stages Tabs
        self.tabs_s1 = QTabWidget()
        
        # Tab A: Calibration
        tab_a = QWidget()
        tab_a_layout = QVBoxLayout(tab_a)
        
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("Physical Object Distance (mm):"))
        self.spin_physical_dist = QDoubleSpinBox()
        self.spin_physical_dist.setRange(1.0, 5000.0)
        self.spin_physical_dist.setValue(200.0)
        # Directly connect physical distance changes to simulation updates
        self.spin_physical_dist.valueChanged.connect(self.update_simulation_distance)
        input_layout.addWidget(self.spin_physical_dist)
        
        self.btn_capture_s1 = QPushButton("Capture Point")
        input_layout.addWidget(self.btn_capture_s1)
        tab_a_layout.addLayout(input_layout)
        
        self.table_s1 = QTableWidget(0, 4)
        self.table_s1.setHorizontalHeaderLabels(["Angle (deg)", "Px X", "Px Y", "Dist (mm)"])
        self.table_s1.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_s1.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_s1.setMaximumHeight(125)
        tab_a_layout.addWidget(self.table_s1)
        
        fit_btn_layout = QGridLayout()
        fit_btn_layout.setSpacing(6)
        self.btn_delete_s1 = QPushButton("Delete Selected")
        self.btn_export_s1 = QPushButton("Export CSV")
        self.btn_fit_linear = QPushButton("Fit Linear")
        self.btn_fit_exp = QPushButton("Fit Exponential")
        self.btn_clear_fit = QPushButton("Remove Fit")
        self.btn_clear_fit.setObjectName("secondary")
        self.btn_clear_fit.setToolTip("Delete the current fit (e.g. after clicking the wrong model); the points stay")
        fit_btn_layout.addWidget(self.btn_delete_s1, 0, 0)
        fit_btn_layout.addWidget(self.btn_export_s1, 0, 1)
        fit_btn_layout.addWidget(self.btn_fit_linear, 1, 0)
        fit_btn_layout.addWidget(self.btn_fit_exp, 1, 1)
        fit_btn_layout.addWidget(self.btn_clear_fit, 2, 0, 1, 2)
        tab_a_layout.addLayout(fit_btn_layout)
        
        self.lbl_fit_eq = QLabel("Equation: N/A")
        tab_a_layout.addWidget(self.lbl_fit_eq)
        
        self.tabs_s1.addTab(tab_a, "A. Calibration")
        
        # Tab B: Measurements
        tab_b = QWidget()
        tab_b_layout = QVBoxLayout(tab_b)
        
        tab_b_layout.addWidget(QLabel("Live estimated distance based on calibration curve:"))
        
        self.lbl_live_distance = QLabel("--- mm")
        font = QFont("Arial", 24, QFont.Bold)
        self.lbl_live_distance.setFont(font)
        self.lbl_live_distance.setAlignment(Qt.AlignCenter)
        self.lbl_live_distance.setStyleSheet("color: #00ff00; padding: 20px;")
        tab_b_layout.addWidget(self.lbl_live_distance)
        
        tab_b_layout.addStretch()
        self.tabs_s1.addTab(tab_b, "B. Measurements")
        
        layout.addWidget(self.tabs_s1)
        
        # Calibration Plot
        self.calib_plot = pg.PlotWidget()
        self.calib_plot.setBackground('#1e1e1e')
        self.calib_plot.setLabel('bottom', 'Displacement X (px)')
        self.calib_plot.setLabel('left', 'Distance (mm)')
        self.calib_plot.setMinimumHeight(150)
        
        self.scatter_item = pg.ScatterPlotItem(size=10, pen=pg.mkPen(None), brush=pg.mkBrush(255, 136, 0, 200))
        self.calib_plot.addItem(self.scatter_item)
        
        self.fit_line_item = pg.PlotDataItem(pen=pg.mkPen('g', width=2))
        self.calib_plot.addItem(self.fit_line_item)
        
        self.live_point_item = pg.ScatterPlotItem(size=15, pen=pg.mkPen('w', width=2), brush=pg.mkBrush(255, 0, 0, 255))
        self.calib_plot.addItem(self.live_point_item)
        
        layout.addWidget(self.calib_plot)
        self.stack.addWidget(page)

    def init_stage2_ui(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        info_group = QGroupBox("Analytical Calculations (Dashboard)")
        info_layout = QVBoxLayout(info_group)
        
        desc = QLabel(
            "Calculate the distance on paper using perspective camera geometry:\n\n"
            "1. Calculate spot deviation angle θ:\n"
            "   tan(θ) = ((X_px - 320) / 320) * tan(FOV / 2)\n"
            "2. Calculate oblique spot distance R via Law of Sines:\n"
            "   R = B * sin(α) / cos(α - θ)\n"
            "3. Calculate target distance Z:\n"
            "   Z = R * cos(θ)\n\n"
            "System variables:"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #ccc; margin-bottom: 15px;")
        info_layout.addWidget(desc)
        
        font_large = QFont("Arial", 18, QFont.Bold)
        
        self.lbl_s2_base = QLabel(f"B (Base Distance): {self.schematic.base_distance:.1f} mm")
        self.lbl_s2_base.setFont(font_large)
        self.lbl_s2_base.setStyleSheet("color: #ffa500;")
        info_layout.addWidget(self.lbl_s2_base)
        
        self.lbl_s2_angle = QLabel(f"α (Laser Angle): {self.hardware.get_servo_angle():.1f}°")
        self.lbl_s2_angle.setFont(font_large)
        self.lbl_s2_angle.setStyleSheet("color: #ffa500;")
        info_layout.addWidget(self.lbl_s2_angle)
        
        self.lbl_s2_spot = QLabel("X_px (Spot Position): No Spot Detected")
        self.lbl_s2_spot.setFont(font_large)
        self.lbl_s2_spot.setStyleSheet("color: #ffa500;")
        info_layout.addWidget(self.lbl_s2_spot)
        
        self.lbl_s2_fov = QLabel(f"Camera FOV (deg): {self.camera_fov:.1f}°")
        self.lbl_s2_fov.setFont(font_large)
        self.lbl_s2_fov.setStyleSheet("color: #ffa500;")
        info_layout.addWidget(self.lbl_s2_fov)
        
        layout.addWidget(info_group)
        
        # Field for students to input their results
        ans_group = QGroupBox("Submit Your Answer")
        ans_layout = QHBoxLayout(ans_group)
        ans_layout.addWidget(QLabel("Your Calculated Distance (mm):"))
        self.spin_s2_ans = QDoubleSpinBox()
        self.spin_s2_ans.setRange(1.0, 5000.0)
        self.spin_s2_ans.setValue(200.0)
        ans_layout.addWidget(self.spin_s2_ans)
        
        self.btn_s2_verify = QPushButton("Verify Answer")
        self.btn_s2_verify.clicked.connect(self.verify_s2_answer)
        ans_layout.addWidget(self.btn_s2_verify)
        layout.addWidget(ans_group)
        
        self.lbl_s2_result = QLabel("")
        self.lbl_s2_result.setWordWrap(True)
        self.lbl_s2_result.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_s2_result)
        
        layout.addStretch()
        self.stack.addWidget(page)

    def init_stage3_ui(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        pid_group = QGroupBox("PID Tuning")
        pid_layout = QVBoxLayout(pid_group)
        
        self.slider_kp = FloatParameterSlider("Kp", 0.0, 0.0500, 0.0050, 4)
        self.slider_ki = FloatParameterSlider("Ki", 0.0, 0.0020, 0.0001, 5)
        self.slider_kd = FloatParameterSlider("Kd", 0.0, 0.0010, 0.0004, 5)
        
        self.slider_target_x = ParameterSlider("Target X (px)", 0, 640, 320)
        default_rate = int(getattr(config, 'PID_UPDATE_RATE_HZ', 15))
        self.slider_pid_rate = ParameterSlider("PID Rate (Hz)", 1, 50, default_rate)
        
        pid_layout.addWidget(self.slider_kp)
        pid_layout.addWidget(self.slider_ki)
        pid_layout.addWidget(self.slider_kd)
        pid_layout.addWidget(self.slider_target_x)
        pid_layout.addWidget(self.slider_pid_rate)
        
        self.btn_toggle_pid = QPushButton("Start PID Tracking")
        self.btn_toggle_pid.setCheckable(True)
        pid_layout.addWidget(self.btn_toggle_pid)
        
        layout.addWidget(pid_group)
        
        self.lbl_s3_calc_dist = QLabel("Calculated Dist: --- mm")
        font = QFont("Arial", 16, QFont.Bold)
        self.lbl_s3_calc_dist.setFont(font)
        self.lbl_s3_calc_dist.setAlignment(Qt.AlignCenter)
        self.lbl_s3_calc_dist.setStyleSheet("color: #00ffff; padding: 10px;")
        layout.addWidget(self.lbl_s3_calc_dist)
        
        plot_group = QGroupBox("Real-time Tracking")
        plot_layout = QVBoxLayout(plot_group)
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#1e1e1e')
        self.plot_widget.setYRange(0, 640)
        self.plot_widget.setLabel('left', 'X_px [px]')
        self.plot_widget.setLabel('bottom', 'time [s]')
        self.plot_widget.getAxis('bottom').setScale(1.0 / max(1, default_rate))
        self.plot_widget.setMinimumHeight(150)
        
        self.target_line = self.plot_widget.plot(pen=pg.mkPen('r', width=2))
        self.actual_line = self.plot_widget.plot(pen=pg.mkPen('g', width=2))
        
        self.plot_data_target = np.zeros(100)
        self.plot_data_actual = np.zeros(100)
        
        plot_layout.addWidget(self.plot_widget)
        self.lbl_s3_error = QLabel("Error e = target - X_px:  --- px")
        self.lbl_s3_error.setAlignment(Qt.AlignCenter)
        self.lbl_s3_error.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffa500; padding: 4px;")
        plot_layout.addWidget(self.lbl_s3_error)
        layout.addWidget(plot_group)
        
        self.stack.addWidget(page)

    def connect_signals(self):
        
        # Camera / Hardware Signals
        self.camera_worker.frame_ready.connect(self.process_and_display_frame)
        
        # Schematic interactions
        self.schematic.base_distance_changed.connect(self.update_base_distance)
        self.schematic.angle_changed.connect(self.update_angle_from_schematic)
        
        # Stage 0 Script Buttons
        self.btn_run_script.clicked.connect(self.run_custom_script)
        self.btn_stop_script.clicked.connect(self.stop_custom_script)
        
        # Stage 1 Controls
        self.tabs_s1.currentChanged.connect(self.handle_s1_tab_change)
        self.slider_servo.slider.valueChanged.connect(self.update_angle_from_slider)
        self.btn_capture_s1.clicked.connect(self.capture_point_s1)
        self.btn_delete_s1.clicked.connect(self.delete_point_s1)
        self.btn_export_s1.clicked.connect(self.export_s1)
        
        self.btn_fit_linear.clicked.connect(self.fit_linear)
        self.btn_fit_exp.clicked.connect(self.fit_exponential)
        self.btn_clear_fit.clicked.connect(self.clear_fit)
        
        # Stage 3 Controls
        self.slider_kp.spinbox.valueChanged.connect(self.update_pid_gains)
        self.slider_ki.spinbox.valueChanged.connect(self.update_pid_gains)
        self.slider_kd.spinbox.valueChanged.connect(self.update_pid_gains)
        self.slider_target_x.slider.valueChanged.connect(self.update_pid_target)
        self.slider_pid_rate.slider.valueChanged.connect(self.update_pid_rate)
        self.slider_pid_rate.spinbox.valueChanged.connect(self.update_pid_rate)
        self.btn_toggle_pid.toggled.connect(self.toggle_pid)
        self.pid_worker.pid_updated.connect(self.update_pid_plot)

    def open_admin(self):
        """Hidden settings (instructor cheat sheet, calibration, system) are behind the admin password."""
        if request_admin_access(self):
            self.show_settings_dialog()

    def restore_settings(self):
        """Re-applies remembered settings (PID, B, sweep). Signals fire as values are set, which also applies them."""
        st = self.settings
        for key, slider in (('pid_kp', self.slider_kp), ('pid_ki', self.slider_ki), ('pid_kd', self.slider_kd)):
            v = st.get(key)
            if v is not None:
                slider.setValue(float(v))
        for key, slider in (('pid_target_x', self.slider_target_x), ('pid_rate_hz', self.slider_pid_rate)):
            v = st.get(key)
            if v is not None:
                slider.setValue(int(v))
        base = st.get('base_distance_mm')
        if base is not None:
            self.schematic.update_state(float(base), self.schematic.angle_deg, self.schematic.object_distance)
            self.update_base_distance(float(base))
        self.pid_worker.set_sweep_enabled(bool(st.get('sweep_enabled', self.pid_worker.sweep_enabled)))
        self.pid_worker.set_sweep_timeout(float(st.get('sweep_timeout_sec', self.pid_worker.sweep_timeout_sec)))
        self.pid_worker.set_sweep_duration(float(st.get('sweep_duration_sec', self.pid_worker.sweep_duration_sec)))
        self.update_pid_gains()
        self.update_pid_rate()
        self.update_pid_target()

    def closeEvent(self, event):
        self.settings.flush()
        super().closeEvent(event)

    def show_settings_dialog(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def handle_s1_tab_change(self, index):
        locked = (index == 1)
        self.hw_group.setEnabled(not locked)
        if index == 0:
            self.live_point_item.clear()
        self._sync_schematic_override()

    def _sync_schematic_override(self, live_dist=None):
        """
        Stage 1 shows on the schematic the distance the app believes, so the numbers agree everywhere:
        calibration tab -> the distance typed by the student; measurement tab -> the distance estimated from the
        fitted curve (the typed one until a fit and a spot exist). Other stages use the triangulated distance.
        """
        override = None
        if self.stack.currentIndex() == 1:
            if self.tabs_s1.currentIndex() == 1 and live_dist is not None:
                override = live_dist
            else:
                override = self.spin_physical_dist.value()
        self.schematic.distance_override = override
        self.schematic.update()

    def switch_stage(self, index: int):
        self.stack.setCurrentIndex(index)
        self.schematic.show_distance = (index != 2)   # Stage 2: the distance is to be calculated by the students
        self._sync_schematic_override()
        if index == 4:
            self.export_page.refresh()  # results are packed automatically when the tab opens
        btn = self.nav_group.button(index)
        if btn and not btn.isChecked():
            btn.setChecked(True)
        
        if index == 3:
            self.slider_servo.setEnabled(False) 
        else:
            self.slider_servo.setEnabled(True)
            if self.pid_worker.running:
                self.btn_toggle_pid.setChecked(False) 

    def change_camera_mode(self, mode: str):
        path = None
        if mode == "Static":
            path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg)")
            if not path:
                return
        self.camera_worker.set_mode(mode, path)

    def update_base_distance(self, val: float):
        self.settings.set('base_distance_mm', float(val))
        self.camera_worker.set_base_distance(val)
        self.lbl_s2_base.setText(f"B (Base Distance): {val:.1f} mm")

    def update_angle_from_schematic(self, val: float):
        self.slider_servo.setValue(int(val))
        self.hardware.set_servo_angle(val)

    def update_angle_from_slider(self, val: int):
        self.hardware.set_servo_angle(float(val))
        self.schematic.update_state(self.schematic.base_distance, float(val), self.schematic.object_distance)

    def update_simulation_distance(self, val: float):
        # Update simulation mode targets
        self.camera_worker.set_simulated_target_distance(val)
        self.schematic.update_state(self.schematic.base_distance, self.schematic.angle_deg, val)
        
        self._sync_schematic_override()
        
        # Sync other inputs without recursive feedback
        if hasattr(self, 'spin_physical_dist'):
            self.spin_physical_dist.blockSignals(True)
            self.spin_physical_dist.setValue(val)
            self.spin_physical_dist.blockSignals(False)
            
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.spin_sim_dist.blockSignals(True)
            self.settings_dialog.spin_sim_dist.setValue(val)
            self.settings_dialog.spin_sim_dist.blockSignals(False)

    def update_camera_fov(self, val: float):
        self.camera_fov = val
        self.camera_worker.set_camera_fov(val)
        if hasattr(self, 'lbl_s2_fov'):
            self.lbl_s2_fov.setText(f"Camera FOV (deg): {val:.1f}°")
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.spin_cam_fov.blockSignals(True)
            self.settings_dialog.spin_cam_fov.setValue(val)
            self.settings_dialog.spin_cam_fov.blockSignals(False)

    def update_sweep_enabled(self, enabled: bool):
        self.settings.set('sweep_enabled', bool(enabled))
        self.pid_worker.set_sweep_enabled(enabled)
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.chk_sweep_enabled.blockSignals(True)
            self.settings_dialog.chk_sweep_enabled.setChecked(enabled)
            self.settings_dialog.chk_sweep_enabled.blockSignals(False)

    def update_sweep_timeout(self, val: float):
        self.settings.set('sweep_timeout_sec', float(val))
        self.pid_worker.set_sweep_timeout(val)
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.spin_sweep_delay.blockSignals(True)
            self.settings_dialog.spin_sweep_delay.setValue(val)
            self.settings_dialog.spin_sweep_delay.blockSignals(False)

    def update_sweep_duration(self, val: float):
        self.settings.set('sweep_duration_sec', float(val))
        self.pid_worker.set_sweep_duration(val)
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.spin_sweep_duration.blockSignals(True)
            self.settings_dialog.spin_sweep_duration.setValue(val)
            self.settings_dialog.spin_sweep_duration.blockSignals(False)

    @Slot(np.ndarray)
    def process_and_display_frame(self, frame: np.ndarray):
        self.current_raw_frame = frame
        self.new_frame_event.set()
        
        # Always update Stage 2 base/angle dashboard labels in real-time
        self.lbl_s2_base.setText(f"B (Base Distance): {self.schematic.base_distance:.1f} mm")
        self.lbl_s2_angle.setText(f"α (Laser Angle): {self.hardware.get_servo_angle():.1f}°")
        
        # Safely sync theoretical cheat sheet calculations in real-time
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.update_cheat_sheet()
            
        # Update schematic with current hardware servo angle in real-time
        self.schematic.update_state(
            self.schematic.base_distance, 
            self.hardware.get_servo_angle(), 
            self.schematic.object_distance
        )
        
        # Empty screen by default! No updates to camera display unless send_to_screen is called
        if self.script_runner and self.script_runner.isRunning():
            return
            
        self.current_spot_x = None
        self.current_spot_y = None
        self.schematic.set_spot(None, self.camera_fov)
        
        if self.stack.currentIndex() == 1 and self.tabs_s1.currentIndex() == 1:
            self.lbl_live_distance.setText("Run script to detect spot")
            self.live_point_item.setData([], [])
            
        if self.stack.currentIndex() == 2:
            self.lbl_s2_spot.setText("X_px (Spot Position): Run script to detect spot")

    def calculate_distance_from_val(self, val: float) -> float:
        if self.active_fit_type == "linear":
            a, b = self.active_fit_popt
            return a * val + b
        elif self.active_fit_type == "exp":
            a, b, c = self.active_fit_popt
            return a * np.exp(b * val) + c
        return 0.0

    # --- Stage 0 Python Scripting Logic ---
    def on_code_changed(self):
        if hasattr(self, 'chk_autorun') and self.chk_autorun.isChecked():
            # Restart debounce timer on every keystroke
            self.autorun_timer.start()

    def _autorun_trigger(self):
        """Called after debounce timer fires. Stops old script and schedules re-run."""
        if self.script_runner and self.script_runner.isRunning():
            # Mark that we want to re-run once the old script finishes
            self._autorun_pending = True
            self.script_runner.stop()
        else:
            # Nothing running — start immediately
            self.run_custom_script()

    def run_custom_script(self):
        self.txt_console.clear()
        self.txt_console.append("[INFO] Starting Python Sandbox Script...")
        
        self.script_runner = ScriptRunner(self.txt_code.toPlainText(), self)
        self.script_runner.log_signal.connect(self.append_console_log)
        self.script_runner.screen_signal.connect(self.update_script_screen)
        self.script_runner.servo_signal.connect(self.update_servo_from_script)
        self.script_runner.spot_signal.connect(self.update_spot_from_script)
        self.script_runner.finished_signal.connect(self.on_script_finished)
        
        # Clear Spot Location display on run
        self.lbl_spot_x.setText("X: --- px")
        self.lbl_spot_y.setText("Y: --- px")
        
        self.btn_run_script.setEnabled(False)
        self.btn_stop_script.setEnabled(True)
        self.script_runner.start()
        
    def stop_custom_script(self):
        if self.script_runner and self.script_runner.isRunning():
            self.txt_console.append("\n[INFO] Requesting script stop...")
            self.script_runner.stop()
            
    def on_script_finished(self):
        # Ignore finished signals from old threads if a new one is already running
        if self.script_runner and self.script_runner.isRunning():
            return
        
        # If auto-run requested a restart, do it now that the old script is done
        if self._autorun_pending:
            self._autorun_pending = False
            self.run_custom_script()
            return
            
        self.btn_run_script.setEnabled(True)
        self.btn_stop_script.setEnabled(False)
        self.txt_console.append("\n[INFO] Script runner finished.")
        # Clear output display and spot label when stopped
        self.camera_display.clear()
        self.lbl_spot_x.setText("X: --- px")
        self.lbl_spot_y.setText("Y: --- px")
        
    @Slot(str)
    def append_console_log(self, text):
        self.txt_console.insertPlainText(text)
        self.txt_console.ensureCursorVisible()
        
    @Slot(np.ndarray)
    def update_script_screen(self, frame):
        self.camera_display.update_frame(frame)
        
    @Slot(float)
    def update_servo_from_script(self, angle):
        self.hardware.set_servo_angle(angle)
        self.slider_servo.setValue(int(angle))
        self.schematic.update_state(self.schematic.base_distance, angle, self.schematic.object_distance)

    @Slot(float, float, float)
    def update_spot_from_script(self, x, y, intensity):
        if x < 0.0 or y < 0.0 or intensity <= 0.0:
            self.current_spot_x = None
            self.current_spot_y = None
            self.schematic.set_spot(None, self.camera_fov)
            self.lbl_spot_x.setText("X: --- px")
            self.lbl_spot_y.setText("Y: --- px")
            if self.pid_worker.running:
                self.pid_worker.update_current_x(-1.0, 0.0)
            return

        self.current_spot_x = x
        self.current_spot_y = y
        self.schematic.set_spot(x, self.camera_fov)
        self.lbl_spot_x.setText(f"X: {x:.1f} px")
        self.lbl_spot_y.setText(f"Y: {y:.1f} px")
        
        if self.pid_worker.running:
            self.pid_worker.update_current_x(x, intensity)
            
        # Update Stage 2 cheat sheet in real-time
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.update_cheat_sheet()
            
        # Update Stage 1 live distance during script execution
        if self.stack.currentIndex() == 1 and self.tabs_s1.currentIndex() == 1:
            if self.active_fit_type is not None and self.active_fit_popt is not None:
                dist = self.calculate_distance_from_val(x)
                self.lbl_live_distance.setText(f"{dist:.1f} mm")
                self.live_point_item.setData([x], [dist])
                self._sync_schematic_override(dist)
            else:
                self.lbl_live_distance.setText("No Fit Data")
                self.live_point_item.setData([], [])
                self._sync_schematic_override(None)
                
        # Update Stage 2 spot label during script execution
        if self.stack.currentIndex() == 2:
            self.lbl_s2_spot.setText(f"X_px (Spot Position): {x:.1f} px")

    # --- Stage 1 Calibration Logic ---
    def capture_point_s1(self):
        angle = self.hardware.get_servo_angle()
        px = self.current_spot_x if self.current_spot_x is not None else -1
        py = self.current_spot_y if self.current_spot_y is not None else -1
        dist = self.spin_physical_dist.value()
            
        row = self.table_s1.rowCount()
        self.table_s1.insertRow(row)
        self.table_s1.setItem(row, 0, QTableWidgetItem(f"{angle:.1f}"))
        self.table_s1.setItem(row, 1, QTableWidgetItem(str(px)))
        self.table_s1.setItem(row, 2, QTableWidgetItem(str(py)))
        self.table_s1.setItem(row, 3, QTableWidgetItem(str(dist)))
        frame = self.current_raw_frame
        self.s1_frames.insert(row, frame.copy() if frame is not None else None)
        del self.s1_frames[50:]  # keep memory bounded
        self.update_calibration_plot_points()

    def delete_point_s1(self):
        rows = set()
        for item in self.table_s1.selectedItems():
            rows.add(item.row())
        for row in sorted(rows, reverse=True):
            self.table_s1.removeRow(row)
            if row < len(self.s1_frames):
                del self.s1_frames[row]
        self.update_calibration_plot_points()

    def export_s1(self):
        headers = ["Angle", "Px_X", "Px_Y", "Dist_mm"]
        data = []
        for r in range(self.table_s1.rowCount()):
            row_data = [self.table_s1.item(r, c).text() for c in range(4)]
            data.append(row_data)
        
        fname = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        saved = self.data_logger.export_csv(fname, headers, data)

    def get_calibration_data(self):
        x_data = []
        y_data = []
        for r in range(self.table_s1.rowCount()):
            try:
                px = float(self.table_s1.item(r, 1).text())
                dist = float(self.table_s1.item(r, 3).text())
                
                # Calibration targets X Position Displacement
                if px >= 0:
                    x_data.append(px)
                    y_data.append(dist)
            except (ValueError, AttributeError):
                pass
        return np.array(x_data), np.array(y_data)

    def update_calibration_plot_points(self):
        x, y = self.get_calibration_data()
        self.scatter_item.setData(x, y)

    def clear_fit(self):
        """Removes the fitted curve (the captured points stay), so a wrongly clicked model can be redone."""
        self.active_fit_type = None
        self.active_fit_popt = None
        self.fit_line_item.setData([], [])
        self.live_point_item.setData([], [])
        self.lbl_fit_eq.setText("Equation: N/A")
        self.lbl_live_distance.setText("No Fit Data")
        self._sync_schematic_override(None)

    def fit_linear(self):
        x, y = self.get_calibration_data()
        if len(x) < 2:
            self.lbl_fit_eq.setText("Not enough points to fit.")
            return
            
        def lin_func(x, a, b): return a * x + b
        try:
            popt, _ = curve_fit(lin_func, x, y)
            fit_x = np.linspace(min(x), max(x), 100)
            fit_y = lin_func(fit_x, *popt)
            self.fit_line_item.setData(fit_x, fit_y)
            self.lbl_fit_eq.setText(f"y = {popt[0]:.2f}x + {popt[1]:.2f}")
            self.active_fit_type = "linear"
            self.active_fit_popt = popt
        except Exception as e:
            self.lbl_fit_eq.setText("Fit failed.")

    def fit_exponential(self):
        x, y = self.get_calibration_data()
        if len(x) < 3:
            self.lbl_fit_eq.setText("Exponential fit needs at least 3 points.")
            return
        if np.ptp(x) < 1e-6:
            self.lbl_fit_eq.setText("All points have the same X_px; move the screen between captures.")
            return

        # Fit y = a*exp(b*xn) + c on x normalised to 0..1 (raw pixel values overflow exp() and make curve_fit fail),
        # trying several starting shapes and keeping the best, then convert back to y = a'*exp(b'*x) + c'.
        x0, span = float(np.min(x)), float(np.ptp(x))
        xn = (x - x0) / span
        y_span = max(float(np.ptp(y)), 1.0)

        def exp_func(t, a, b, c):
            return a * np.exp(b * t) + c

        best = None
        for b0 in (-3.0, 3.0, -1.0, 1.0, -8.0, 8.0):
            try:
                a0 = float(y[np.argmin(xn)] - y[np.argmax(xn)]) / (1.0 - np.exp(b0))
                c0 = float(y[np.argmin(xn)]) - a0
                popt, _ = curve_fit(exp_func, xn, y, p0=(a0, b0, c0), bounds=([-np.inf, -25.0, -np.inf], [np.inf, 25.0, np.inf]),
                                    maxfev=20000)
                err = float(np.sum((exp_func(xn, *popt) - y) ** 2))
                if np.isfinite(err) and (best is None or err < best[0]):
                    best = (err, popt)
            except Exception:
                continue
        if best is None:
            self.lbl_fit_eq.setText("Fit failed: the points do not follow an exponential trend. Check the captured points.")
            return
        a, bb, c = best[1]
        popt = np.array([a * np.exp(-bb * x0 / span), bb / span, c])
        fit_x = np.linspace(x.min(), x.max(), 100)
        self.fit_line_item.setData(fit_x, popt[0] * np.exp(popt[1] * fit_x) + popt[2])
        self.lbl_fit_eq.setText(f"y = {popt[0]:.4g} * e^({popt[1]:.5f} x) + {popt[2]:.2f}")
        self.active_fit_type = "exp"
        self.active_fit_popt = popt

    # --- Stage 2 Verification Logic ---
    def verify_s2_answer(self):
        if self.current_spot_x is None:
            QMessageBox.warning(self, "Verification Failed", "No spot detected on screen to verify distance calculations. Start Python script first.")
            return
            
        center_x = 320.0
        tan_half_fov = math.tan(math.radians(self.camera_fov / 2.0))
        tan_theta = ((self.current_spot_x - center_x) / center_x) * tan_half_fov
        
        angle = self.hardware.get_servo_angle()
        rad = math.radians(angle)
        
        denom = (1.0 / math.tan(rad)) + tan_theta
        
        if abs(denom) > 0.001:
            theoretical = self.schematic.base_distance / denom
            student_ans = self.spin_s2_ans.value()
            
            if theoretical <= 0:
                QMessageBox.warning(self, "Invalid Geometry", "Laser projection angle points away from camera sensor.")
                return
                
            # Allow 5% error margin
            error_margin = abs(theoretical - student_ans) / theoretical
            if error_margin <= 0.05:
                self._show_s2_result(True, f"CORRECT. The distance from the model is {theoretical:.1f} mm; your answer of "
                                           f"{student_ans:.1f} mm is within 5% ({error_margin * 100:.1f}% off).")
            else:
                self._show_s2_result(False, "INCORRECT. Your calculation does not match the geometric model. Try again.")
        else:
            QMessageBox.warning(self, "Invalid Angle", "Laser beam is parallel to the camera. Recalculate with a different angle.")

    def _show_s2_result(self, ok: bool, text: str):
        """Shows the verdict on the Stage 2 page (so it is visible in screenshots) and keeps a screenshot for the report."""
        color = "#00e676" if ok else "#ff5252"
        self.lbl_s2_result.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: bold; padding: 8px;")
        self.lbl_s2_result.setText(text)
        self.s2_verifications.append((ok, self.grab()))
        del self.s2_verifications[:-10]

    # --- Stage 3 Logic ---
    def update_pid_gains(self):
        kp = self.slider_kp.value()
        ki = self.slider_ki.value()
        kd = self.slider_kd.value()
        self.pid_worker.set_gains(kp, ki, kd)
        self.settings.set('pid_kp', kp)
        self.settings.set('pid_ki', ki)
        self.settings.set('pid_kd', kd)

    def update_pid_rate(self):
        hz = self.slider_pid_rate.value()
        self.pid_worker.set_rate_hz(hz)
        self.plot_widget.getAxis('bottom').setScale(1.0 / max(1.0, float(hz)))   # x axis in seconds (one sample per PID tick)
        self.settings.set('pid_rate_hz', int(hz))

    def update_pid_target(self):
        self.pid_worker.set_target(self.slider_target_x.value())
        self.settings.set('pid_target_x', int(self.slider_target_x.value()))

    def toggle_pid(self, checked: bool):
        if checked:
            self.btn_toggle_pid.setText("Stop PID Tracking")
            self.update_pid_gains()
            self.update_pid_rate()
            self.update_pid_target()
            self.pid_worker.start()
        else:
            self.btn_toggle_pid.setText("Start PID Tracking")
            self.pid_worker.stop()

    @Slot(float, float, float, float)
    def update_pid_plot(self, actual, target, error, new_angle):
        # Only spend CPU redrawing plots if Stage 3 is currently visible
        if self.stack.currentIndex() != 3:
            return
            
        if actual >= 0:
            self.lbl_s3_error.setText(f"Error e = target - X_px:  {error:+.1f} px")
        else:
            self.lbl_s3_error.setText("Error e = target - X_px:  spot lost")
        
        self.plot_data_actual = np.roll(self.plot_data_actual, -1)
        self.plot_data_actual[-1] = actual
        
        self.plot_data_target = np.roll(self.plot_data_target, -1)
        self.plot_data_target[-1] = target
        
        self.actual_line.setData(self.plot_data_actual)
        self.target_line.setData(self.plot_data_target)
        
        self.schematic.update_state(self.schematic.base_distance, new_angle, self.schematic.object_distance)
        
        # Calculate system estimated distance using perspective geometry:
        # tan(theta) = ((target_px - 320) / 320) * tan(FOV / 2)
        # Z = B / (1/tan(alpha) + tan(theta))
        center_x = 320.0
        tan_half_fov = math.tan(math.radians(self.camera_fov / 2.0))
        tan_theta = ((target - center_x) / center_x) * tan_half_fov
        
        rad = math.radians(new_angle)
        denom = (1.0 / math.tan(rad)) + tan_theta
        
        if abs(denom) > 0.001:
            estimated_dist = self.schematic.base_distance / denom
        else:
            estimated_dist = 9999.0
            
        estimated_dist = max(0.0, estimated_dist)
        
        if hasattr(self, 'lbl_s3_calc_dist'):
            if self.pid_worker.sweep_mode:
                self.lbl_s3_calc_dist.setText("SWEEPING FOR SPOT...")
                self.lbl_s3_calc_dist.setStyleSheet("color: #ff3333; font-size: 20px; font-weight: bold; padding: 10px;")
            else:
                self.lbl_s3_calc_dist.setText(f"Calculated Dist: {estimated_dist:.1f} mm")
                self.lbl_s3_calc_dist.setStyleSheet("color: #00ffff; font-size: 16px; font-weight: bold; padding: 10px;")

    def closeEvent(self, event):
        try:
            self.camera_worker.frame_ready.disconnect()
        except Exception:
            pass
        self.camera_worker.stop()
        self.pid_worker.stop()
        if self.pid_worker.isRunning():
            self.pid_worker.wait(500)
        if self.script_runner and self.script_runner.isRunning():
            self.script_runner.stop()
        self.hardware.cleanup()
        event.accept()
