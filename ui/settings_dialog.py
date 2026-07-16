import math
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QDoubleSpinBox, QGroupBox, QPushButton
)
from PySide6.QtCore import Qt
import config

class SettingsDialog(QDialog):
    def __init__(self, main_window, parent=None):
        # Pass Qt.Window flag so it acts as an independent window and doesn't block the main thread
        super().__init__(None, Qt.Window)
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
        
        layout.addWidget(cam_group)
        
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
        
        rad = math.radians(angle)
        if abs(math.tan(rad)) > 0.001:
            if self.main_window.current_spot_x is not None:
                px_per_mm = config.PIXELS_PER_MM
                center_x = 320.0
                x_hit_mm = (self.main_window.current_spot_x - center_x) / px_per_mm
                calc_dist = (base - x_hit_mm) * math.tan(rad)
                self.lbl_answer.setText(f"Theoretical Distance:\n{calc_dist:.1f} mm")
            else:
                self.lbl_answer.setText("Spot Lost\nCannot Calculate")
        else:
            self.lbl_answer.setText("Angle near 0° or 180°\nInvalid")
