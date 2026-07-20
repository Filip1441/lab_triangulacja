import math
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QDoubleSpinBox, QGroupBox, QPushButton, QCheckBox
)
from PySide6.QtCore import Qt
import config

class SettingsDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.setWindowTitle("Hidden Settings & Instructor Cheat Sheet")
        self.setMinimumWidth(400)
        
        self.main_window = main_window
        self.camera_worker = main_window.camera_worker
        self.schematic = main_window.schematic
        
        self.init_ui()
        self.update_cheat_sheet()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Camera Mode Settings
        cam_group = QGroupBox("Camera Settings")
        cam_layout = QVBoxLayout(cam_group)
        
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Input Mode:"))
        self.combo_cam_mode = QComboBox()
        self.combo_cam_mode.addItems(["Live", "Static", "Simulation"])
        self.combo_cam_mode.setCurrentText(self.camera_worker.input_mode)
        self.combo_cam_mode.currentTextChanged.connect(self.main_window.change_camera_mode)
        mode_layout.addWidget(self.combo_cam_mode)
        cam_layout.addLayout(mode_layout)
        
        sim_layout = QHBoxLayout()
        sim_layout.addWidget(QLabel("Simulated Distance (mm):"))
        self.spin_sim_dist = QDoubleSpinBox()
        self.spin_sim_dist.setRange(50.0, 5000.0)
        self.spin_sim_dist.setValue(self.schematic.object_distance)
        self.spin_sim_dist.valueChanged.connect(self.main_window.update_simulation_distance)
        sim_layout.addWidget(self.spin_sim_dist)
        cam_layout.addLayout(sim_layout)
        
        # Camera FOV input
        fov_layout = QHBoxLayout()
        fov_layout.addWidget(QLabel("Camera FOV (deg):"))
        self.spin_cam_fov = QDoubleSpinBox()
        self.spin_cam_fov.setRange(5.0, 120.0)
        self.spin_cam_fov.setValue(self.main_window.camera_fov)
        self.spin_cam_fov.valueChanged.connect(self.main_window.update_camera_fov)
        fov_layout.addWidget(self.spin_cam_fov)
        cam_layout.addLayout(fov_layout)
        
        layout.addWidget(cam_group)
        
        # PID Auto Sweep Settings
        sweep_group = QGroupBox("PID Auto Sweep Settings")
        sweep_layout = QVBoxLayout(sweep_group)
        
        self.chk_sweep_enabled = QCheckBox("Enable Auto Sweep")
        self.chk_sweep_enabled.setChecked(self.main_window.pid_worker.sweep_enabled)
        self.chk_sweep_enabled.toggled.connect(self.main_window.update_sweep_enabled)
        sweep_layout.addWidget(self.chk_sweep_enabled)
        
        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("Sweep Trigger Delay (s):"))
        self.spin_sweep_delay = QDoubleSpinBox()
        self.spin_sweep_delay.setRange(0.5, 60.0)
        self.spin_sweep_delay.setSingleStep(0.5)
        self.spin_sweep_delay.setValue(self.main_window.pid_worker.sweep_timeout_sec)
        self.spin_sweep_delay.valueChanged.connect(self.main_window.update_sweep_timeout)
        delay_layout.addWidget(self.spin_sweep_delay)
        sweep_layout.addLayout(delay_layout)
        
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("Full Sweep Duration (s):"))
        self.spin_sweep_duration = QDoubleSpinBox()
        self.spin_sweep_duration.setRange(0.5, 30.0)
        self.spin_sweep_duration.setSingleStep(0.5)
        self.spin_sweep_duration.setValue(self.main_window.pid_worker.sweep_duration_sec)
        self.spin_sweep_duration.valueChanged.connect(self.main_window.update_sweep_duration)
        duration_layout.addWidget(self.spin_sweep_duration)
        sweep_layout.addLayout(duration_layout)
        
        layout.addWidget(sweep_group)
        
        # Instructor Cheat Sheet (Stage 2 Answer)
        cheat_group = QGroupBox("Instructor Cheat Sheet (Stage 2)")
        cheat_layout = QVBoxLayout(cheat_group)
        
        self.lbl_answer = QLabel("Calculating...")
        self.lbl_answer.setAlignment(Qt.AlignCenter)
        self.lbl_answer.setStyleSheet("font-size: 18px; font-weight: bold; color: #00ff00; padding: 10px;")
        cheat_layout.addWidget(self.lbl_answer)
        
        layout.addWidget(cheat_group)
        
        # Close button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)
        
    def update_cheat_sheet(self):
        # Calculate the theoretical distance based on current geometry
        angle = self.main_window.hardware.get_servo_angle()
        base = self.schematic.base_distance
        fov = self.main_window.camera_fov
        
        rad = math.radians(angle)
        if abs(math.tan(rad)) > 0.001:
            if self.main_window.current_spot_x is not None:
                # Perspective calculation matching the simulator:
                # tan(theta) = ((x_px - 320) / 320) * tan(FOV / 2)
                # Z = B / (1/tan(alpha) + tan(theta))
                center_x = 320.0
                tan_half_fov = math.tan(math.radians(fov / 2.0))
                tan_theta = ((self.main_window.current_spot_x - center_x) / center_x) * tan_half_fov
                
                denom = (1.0 / math.tan(rad)) + tan_theta
                if abs(denom) > 0.001:
                    calc_dist = base / denom
                    if calc_dist > 0:
                        self.lbl_answer.setText(f"Theoretical Distance:\n{calc_dist:.1f} mm")
                    else:
                        self.lbl_answer.setText("Laser projection behind camera\nInvalid")
                else:
                    self.lbl_answer.setText("Parallel lines\nInvalid")
            else:
                self.lbl_answer.setText("Spot Lost\nCannot Calculate")
        else:
            self.lbl_answer.setText("Angle near 0° or 180°\nInvalid")
