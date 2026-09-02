import os
import math
from datetime import datetime
import numpy as np
try:
    from scipy.optimize import curve_fit
except ImportError:
    pass

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QStackedWidget, QLabel, QGroupBox, 
    QTableWidget, QTableWidgetItem, QHeaderView,
    QDoubleSpinBox, QSpinBox, QStatusBar, QCheckBox, QTabWidget,
    QMessageBox, QTextEdit, QComboBox, QFileDialog
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
        
        self.init_ui()
        self.connect_signals()
        
        # Start Workers
        self.camera_worker.start()
        
        # Hidden shortcut for Settings (cross-platform Preferences standard: Cmd+, on mac, Ctrl+, on Win/Linux)
        self.shortcut_settings = QShortcut(QKeySequence(QKeySequence.Preferences), self)
        self.shortcut_settings.setContext(Qt.ApplicationShortcut)
        self.shortcut_settings.activated.connect(self.show_settings_dialog)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Top Navigation
        nav_layout = QHBoxLayout()
        self.btn_stage0 = QPushButton("0. Setup & Scripting")
        self.btn_stage1 = QPushButton("1. Empirical Calibration")
        self.btn_stage2 = QPushButton("2. Analytical Modeling")
        self.btn_stage3 = QPushButton("3. Active Tracking")
        
        self.btn_stage0.setCheckable(True)
        self.btn_stage1.setCheckable(True)
        self.btn_stage2.setCheckable(True)
        self.btn_stage3.setCheckable(True)
        
        # Stage 0 is default
        self.btn_stage0.setChecked(True)
        
        nav_layout.addWidget(self.btn_stage0)
        nav_layout.addWidget(self.btn_stage1)
        nav_layout.addWidget(self.btn_stage2)
        nav_layout.addWidget(self.btn_stage3)
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
        self.schematic.setMinimumHeight(350)
        
        # Right visual column (Spot Position widget + Camera widget)
        right_column = QVBoxLayout()
        right_column.setSpacing(6)
        
        self.spot_info_group = QGroupBox("Spot Location Details")
        self.spot_info_group.setMaximumHeight(85)
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
        visual_layout.addLayout(right_column, 2)
        self.left_panel.addLayout(visual_layout)
        
        # Right Panel - Dynamic Stage Views
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 2)
        
        self.init_stage0_ui()
        self.init_stage1_ui()
        self.init_stage2_ui()
        self.init_stage3_ui()
        
        # Default stack index is 0 (Stage 0)
        self.stack.setCurrentIndex(0)

    def init_stage0_ui(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        # Exposure configuration
        exp_group = QGroupBox("Camera Settings")
        exp_layout = QHBoxLayout(exp_group)
        exp_layout.addWidget(QLabel("Exposure (Value):"))
        self.spin_exposure = QSpinBox()
        self.spin_exposure.setRange(-13, 0)
        self.spin_exposure.setValue(-5)
        self.spin_exposure.valueChanged.connect(self.update_exposure)
        exp_layout.addWidget(self.spin_exposure)
        layout.addWidget(exp_group)
        
        # Code Sandbox Group
        code_group = QGroupBox("Python Image Processing Sandbox")
        code_layout = QVBoxLayout(code_group)
        
        # Code Editor
        self.txt_code = QTextEdit()
        self.txt_code.setFont(QFont("Courier", 10))
        self.txt_code.setPlainText(
            "# Available API functions:\n"
            "#   capture_frame() -> np.ndarray (or None if no camera signal)\n"
            "#   send_to_screen(frame) or send_to_screen(frame1, frame2) (outputs frames to display)\n"
            "#   set_servo_angle(angle: float) -> sets servo position (0.0 to 180.0)\n"
            "#   get_servo_angle() -> float (returns current servo angle)\n"
            "#   set_detected_spot(x: float, y: float, intensity: float) -> reports spot back to system\n"
            "#   send_location(x: float, y: float) -> updates the Spot Location details panel\n"
            "#   draw_cross_on_location(img, x, y, size=15, thickness=None) -> returns a copy of the image with a cross drawn at (x, y)\n"
            "#   find_spot_center(img) -> returns (x, y) centroid of brightest spot in image\n"
            "#   crop_frame(img, x, y, w, h) -> returns cropped image safely from out-of-bounds\n\n"
            "import cv2\n"
            "import numpy as np\n"
            "import time\n\n"
            "# Full calibration and tracking pipeline template:\n"
            "while True:\n"
            "    frame = capture_frame()\n"
            "    if frame is not None:\n"
            "        # 1. Convert to grayscale\n"
            "        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)\n"
            "        \n"
            "        # 2. Gaussian Blur to reduce noise\n"
            "        blurred = cv2.GaussianBlur(gray, (5, 5), 0)\n"
            "        \n"
            "        # 3. Thresholding\n"
            "        _, binary = cv2.threshold(blurred, 200, 255, cv2.THRESH_BINARY)\n"
            "        \n"
            "        # 4. Detect blobs (contours)\n"
            "        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)\n"
            "        \n"
            "        if contours:\n"
            "            # Find the largest blob\n"
            "            largest_contour = max(contours, key=cv2.contourArea)\n"
            "            \n"
            "            # Create a mask with only the largest blob\n"
            "            mask = np.zeros_like(binary)\n"
            "            cv2.drawContours(mask, [largest_contour], -1, 255, -1)\n"
            "            \n"
            "            # 5. Multiple erosions to shrink the blob to a single point\n"
            "            eroded = mask.copy()\n"
            "            kernel = np.ones((3, 3), np.uint8)\n"
            "            # Erode iteratively until only a few pixels are left\n"
            "            for _ in range(10):\n"
            "                temp = cv2.erode(eroded, kernel)\n"
            "                if np.sum(temp == 255) > 0:\n"
            "                    eroded = temp\n"
            "                else:\n"
            "                    break\n"
            "            \n"
            "            # 6. Loop through pixels to find the remaining point\n"
            "            points = np.argwhere(eroded == 255)\n"
            "            if len(points) > 0:\n"
            "                # np.argwhere returns [row, col] -> y, x\n"
            "                y, x = points[0]\n"
            "                \n"
            "                # Report spot coordinates and update local panels\n"
            "                send_location(x, y)\n"
            "                set_detected_spot(x, y, 255.0)\n"
            "                \n"
            "                # Draw tracking crosshair\n"
            "                frame = draw_cross_on_location(frame, x, y, size=100)\n"
            "                binary = draw_cross_on_location(binary, x, y, size=100)\n"
            "                \n"
            "        # Display stacked original and binary output (forms 16x18 display layout)\n"
            "        send_to_screen(frame, binary)\n"
            "        \n"
            "    time.sleep(0.1)\n"
        )
        
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
        
        self.slider_servo = ParameterSlider("Servo Angle", 0, 180, 45)
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
        tab_a_layout.addWidget(self.table_s1)
        
        fit_btn_layout = QHBoxLayout()
        self.btn_delete_s1 = QPushButton("Delete Selected")
        self.btn_fit_linear = QPushButton("Fit Linear")
        self.btn_fit_exp = QPushButton("Fit Exponential")
        self.btn_export_s1 = QPushButton("Export CSV")
        fit_btn_layout.addWidget(self.btn_delete_s1)
        fit_btn_layout.addWidget(self.btn_fit_linear)
        fit_btn_layout.addWidget(self.btn_fit_exp)
        fit_btn_layout.addWidget(self.btn_export_s1)
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
        
        layout.addStretch()
        self.stack.addWidget(page)

    def init_stage3_ui(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        pid_group = QGroupBox("PID Tuning")
        pid_layout = QVBoxLayout(pid_group)
        
        self.slider_kp = FloatParameterSlider("Kp", 0.0, 1.0, 0.002, 4)
        self.slider_ki = FloatParameterSlider("Ki", 0.0, 1.0, 0.0, 4)
        self.slider_kd = FloatParameterSlider("Kd", 0.0, 1.0, 0.001, 4)
        
        self.slider_target_x = ParameterSlider("Target X (px)", 0, 640, 320)
        
        pid_layout.addWidget(self.slider_kp)
        pid_layout.addWidget(self.slider_ki)
        pid_layout.addWidget(self.slider_kd)
        pid_layout.addWidget(self.slider_target_x)
        
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
        
        self.target_line = self.plot_widget.plot(pen=pg.mkPen('r', width=2))
        self.actual_line = self.plot_widget.plot(pen=pg.mkPen('g', width=2))
        
        self.plot_data_target = np.zeros(100)
        self.plot_data_actual = np.zeros(100)
        
        plot_layout.addWidget(self.plot_widget)
        layout.addWidget(plot_group)
        
        self.stack.addWidget(page)

    def connect_signals(self):
        # Nav Buttons
        self.btn_stage0.clicked.connect(lambda: self.switch_stage(0))
        self.btn_stage1.clicked.connect(lambda: self.switch_stage(1))
        self.btn_stage2.clicked.connect(lambda: self.switch_stage(2))
        self.btn_stage3.clicked.connect(lambda: self.switch_stage(3))
        
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
        
        # Stage 3 Controls
        self.slider_kp.spinbox.valueChanged.connect(self.update_pid_gains)
        self.slider_ki.spinbox.valueChanged.connect(self.update_pid_gains)
        self.slider_kd.spinbox.valueChanged.connect(self.update_pid_gains)
        self.slider_target_x.slider.valueChanged.connect(self.update_pid_target)
        self.btn_toggle_pid.toggled.connect(self.toggle_pid)
        self.pid_worker.pid_updated.connect(self.update_pid_plot)

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

    def switch_stage(self, index: int):
        self.stack.setCurrentIndex(index)
        self.btn_stage0.setChecked(index == 0)
        self.btn_stage1.setChecked(index == 1)
        self.btn_stage2.setChecked(index == 2)
        self.btn_stage3.setChecked(index == 3)
        
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
        
        # Sync other inputs without recursive feedback
        if hasattr(self, 'spin_physical_dist'):
            self.spin_physical_dist.blockSignals(True)
            self.spin_physical_dist.setValue(val)
            self.spin_physical_dist.blockSignals(False)
            
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.spin_sim_dist.blockSignals(True)
            self.settings_dialog.spin_sim_dist.setValue(val)
            self.settings_dialog.spin_sim_dist.blockSignals(False)

    def update_exposure(self, val: int):
        self.camera_worker.set_exposure(val)

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
        self.pid_worker.set_sweep_enabled(enabled)
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.chk_sweep_enabled.blockSignals(True)
            self.settings_dialog.chk_sweep_enabled.setChecked(enabled)
            self.settings_dialog.chk_sweep_enabled.blockSignals(False)

    def update_sweep_timeout(self, val: float):
        self.pid_worker.set_sweep_timeout(val)
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.spin_sweep_delay.blockSignals(True)
            self.settings_dialog.spin_sweep_delay.setValue(val)
            self.settings_dialog.spin_sweep_delay.blockSignals(False)

    def update_sweep_duration(self, val: float):
        self.pid_worker.set_sweep_duration(val)
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.spin_sweep_duration.blockSignals(True)
            self.settings_dialog.spin_sweep_duration.setValue(val)
            self.settings_dialog.spin_sweep_duration.blockSignals(False)

    @Slot(np.ndarray)
    def process_and_display_frame(self, frame: np.ndarray):
        self.current_raw_frame = frame
        
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
        self.current_spot_x = x
        self.current_spot_y = y
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
            else:
                self.lbl_live_distance.setText("No Fit Data")
                self.live_point_item.setData([], [])
                
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
        self.update_calibration_plot_points()

    def delete_point_s1(self):
        rows = set()
        for item in self.table_s1.selectedItems():
            rows.add(item.row())
        for row in sorted(rows, reverse=True):
            self.table_s1.removeRow(row)
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
        if len(x) < 2:
            self.lbl_fit_eq.setText("Not enough points to fit.")
            return
            
        def exp_func(x, a, b, c): return a * np.exp(b * x) + c
        try:
            popt, _ = curve_fit(exp_func, x, y, p0=(1, 0.01, 1))
            fit_x = np.linspace(min(x), max(x), 100)
            fit_y = exp_func(fit_x, *popt)
            self.fit_line_item.setData(fit_x, fit_y)
            self.lbl_fit_eq.setText(f"y = {popt[0]:.2f}e^({popt[1]:.4f}x) + {popt[2]:.2f}")
            self.active_fit_type = "exp"
            self.active_fit_popt = popt
        except Exception as e:
            self.lbl_fit_eq.setText("Fit failed.")

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
                QMessageBox.information(self, "Success!", f"Correct! The actual calculated distance is {theoretical:.1f} mm. Your answer of {student_ans:.1f} mm is within acceptable range.")
            else:
                QMessageBox.critical(self, "Incorrect Answer", f"Try again. Your calculations do not match the geometric model.")
        else:
            QMessageBox.warning(self, "Invalid Angle", "Laser beam is parallel to the camera. Recalculate with a different angle.")

    # --- Stage 3 Logic ---
    def update_pid_gains(self):
        kp = self.slider_kp.value()
        ki = self.slider_ki.value()
        kd = self.slider_kd.value()
        self.pid_worker.set_gains(kp, ki, kd)

    def update_pid_target(self):
        self.pid_worker.set_target(self.slider_target_x.value())

    def toggle_pid(self, checked: bool):
        if checked:
            self.btn_toggle_pid.setText("Stop PID Tracking")
            self.update_pid_gains()
            self.update_pid_target()
            self.pid_worker.start()
        else:
            self.btn_toggle_pid.setText("Start PID Tracking")
            self.pid_worker.stop()

    @Slot(float, float, float, float)
    def update_pid_plot(self, actual, target, error, new_angle):
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
        self.camera_worker.stop()
        self.pid_worker.stop()
        if self.script_runner and self.script_runner.isRunning():
            self.script_runner.stop()
        self.hardware.cleanup()
        event.accept()
