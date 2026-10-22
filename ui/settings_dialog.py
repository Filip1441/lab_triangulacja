import math
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QDoubleSpinBox, QGroupBox, QPushButton, QCheckBox
)
from PySide6.QtCore import Qt
import config
from core.calibration import CalibrationWorker, find_spot, offset_for_spot

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
        layout.addWidget(self.build_calibration_group())
        
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
        
    # --- Servo / camera calibration ---
    def build_calibration_group(self):
        group = QGroupBox("Servo Offset Calibration")
        lay = QVBoxLayout(group)

        row_b = QHBoxLayout()
        row_b.addWidget(QLabel("B: camera-laser distance (mm):"))
        self.spin_cal_base = QDoubleSpinBox()
        self.spin_cal_base.setRange(50.0, 1000.0)
        self.spin_cal_base.setDecimals(1)
        self.spin_cal_base.setValue(self.schematic.base_distance)
        self.spin_cal_base.valueChanged.connect(self.on_cal_base_changed)
        row_b.addWidget(self.spin_cal_base)
        lay.addLayout(row_b)

        row_z = QHBoxLayout()
        row_z.addWidget(QLabel("Wall distance from lens (mm):"))
        self.spin_cal_wall = QDoubleSpinBox()
        self.spin_cal_wall.setRange(200.0, 5000.0)
        self.spin_cal_wall.setDecimals(1)
        self.spin_cal_wall.setValue(getattr(config, 'DEFAULT_WALL_DISTANCE_MM', 1000.0))
        row_z.addWidget(self.spin_cal_wall)
        lay.addLayout(row_z)

        self.lbl_cal_current = QLabel()
        lay.addWidget(self.lbl_cal_current)
        self.refresh_cal_current()

        self.chk_release = QCheckBox("Release torque (turn servo by hand)")
        self.chk_release.toggled.connect(self.on_release_toggled)
        lay.addWidget(self.chk_release)

        row_btn = QHBoxLayout()
        self.btn_cal_auto = QPushButton("Auto-calibrate (sweep)")
        self.btn_cal_auto.clicked.connect(self.start_auto_calibration)
        self.btn_cal_here = QPushButton("Use current position")
        self.btn_cal_here.setToolTip("Use the servo's present angle and the spot's present pixel position")
        self.btn_cal_here.clicked.connect(self.calibrate_from_current)
        row_btn.addWidget(self.btn_cal_auto)
        row_btn.addWidget(self.btn_cal_here)
        lay.addLayout(row_btn)

        self.lbl_cal_status = QLabel("Aim the laser at the wall, spot visible to the camera.")
        self.lbl_cal_status.setWordWrap(True)
        lay.addWidget(self.lbl_cal_status)

        row_apply = QHBoxLayout()
        self.btn_cal_apply = QPushButton("Apply && Save")
        self.btn_cal_apply.setEnabled(False)
        self.btn_cal_apply.clicked.connect(self.apply_calibration)
        self.btn_cal_reset = QPushButton("Reset saved")
        self.btn_cal_reset.clicked.connect(self.reset_calibration)
        row_apply.addWidget(self.btn_cal_apply)
        row_apply.addWidget(self.btn_cal_reset)
        lay.addLayout(row_apply)

        self.cal_worker = None
        self.pending_cal = None
        hw_ok = self.main_window.hardware.use_st3215
        self.btn_cal_auto.setEnabled(hw_ok)
        self.btn_cal_here.setEnabled(hw_ok)
        self.chk_release.setEnabled(hw_ok)
        if not hw_ok:
            self.lbl_cal_status.setText("Calibration needs the physical ST3215 servo (not available in simulation).")
        return group

    def refresh_cal_current(self):
        self.lbl_cal_current.setText(
            f"Current: offset {config.SERVO_HARDWARE_OFFSET:+.2f} deg, FOV {self.main_window.camera_fov:.2f} deg")

    def on_cal_base_changed(self, val):
        self.main_window.update_base_distance(val)
        self.schematic.update_state(val, self.schematic.angle_deg, self.schematic.object_distance)

    def on_release_toggled(self, released):
        hw = self.main_window.hardware
        if released:
            if self.main_window.pid_worker.running:
                self.main_window.btn_toggle_pid.setChecked(False)
            hw.set_torque(False)
        else:
            enc = hw.get_physical_encoder_angle()
            if enc is not None:
                hw.set_physical_angle(enc)  # hold where the user left it
            hw.set_torque(True)

    def set_cal_busy(self, busy):
        self.btn_cal_auto.setEnabled(not busy)
        self.btn_cal_here.setEnabled(not busy)
        self.chk_release.setEnabled(not busy)
        self.main_window.hw_group.setEnabled(not busy)

    def start_auto_calibration(self):
        if self.cal_worker and self.cal_worker.isRunning():
            return
        mw = self.main_window
        if mw.pid_worker.running:
            mw.btn_toggle_pid.setChecked(False)
        if self.chk_release.isChecked():
            self.chk_release.setChecked(False)
        if mw.camera_worker.last_frame is None:
            self.lbl_cal_status.setText("No camera frames yet.")
            return
        self.prev_logical = mw.hardware.get_servo_angle()
        self.btn_cal_apply.setEnabled(False)
        self.set_cal_busy(True)
        self.cal_worker = CalibrationWorker(
            mw.hardware, mw.camera_worker, self.spin_cal_base.value(), self.spin_cal_wall.value(), self)
        self.cal_worker.progress.connect(self.lbl_cal_status.setText)
        self.cal_worker.result.connect(self.on_cal_result)
        self.cal_worker.failed.connect(self.on_cal_failed)
        self.cal_worker.start()

    def finish_cal_motion(self):
        self.set_cal_busy(False)
        self.main_window.hardware.set_servo_angle(self.prev_logical)

    def on_cal_failed(self, msg):
        self.lbl_cal_status.setText(msg)
        self.finish_cal_motion()

    def on_cal_result(self, res):
        self.pending_cal = (res["offset"], res["fov"])
        self.lbl_cal_status.setText(
            f"Spot centered at {res['center_physical']:.2f} deg (physical), parallel at {res['parallel_physical']:.2f} deg.\n"
            f"New offset {res['offset']:+.2f} deg, FOV {res['fov']:.2f} deg "
            f"({res['points']} pts, fit error {res['rms_px']:.1f} px). Press Apply && Save.")
        self.btn_cal_apply.setEnabled(True)
        self.finish_cal_motion()

    def calibrate_from_current(self):
        """Manual method: user aims the spot by hand, offset is computed from servo angle + spot pixel."""
        mw = self.main_window
        enc = mw.hardware.get_physical_encoder_angle()
        frame = mw.camera_worker.last_frame
        spot = find_spot(frame)
        if enc is None or spot is None:
            self.lbl_cal_status.setText("Need a readable servo encoder and a visible laser spot.")
            return
        frame_w = frame.shape[1]
        off = offset_for_spot(enc, spot[0], self.spin_cal_base.value(), self.spin_cal_wall.value(),
                              mw.camera_fov, frame_w)
        self.pending_cal = (off, mw.camera_fov)
        self.lbl_cal_status.setText(
            f"Servo {enc:.2f} deg, spot at x={spot[0]:.0f} px -> offset {off:+.2f} deg. Press Apply && Save.")
        self.btn_cal_apply.setEnabled(True)

    def apply_calibration(self):
        if not self.pending_cal:
            return
        offset, fov = self.pending_cal
        config.save_calibration(offset, fov)
        mw = self.main_window
        mw.update_camera_fov(fov)
        mw.hardware.set_servo_angle(mw.hardware.get_servo_angle())
        self.refresh_cal_current()
        self.btn_cal_apply.setEnabled(False)
        self.lbl_cal_status.setText(f"Saved: offset {offset:+.2f} deg, FOV {fov:.2f} deg.")
        self.pending_cal = None

    def reset_calibration(self):
        config.reset_calibration()
        self.lbl_cal_status.setText("Saved calibration removed. Defaults apply after restart.")

    def closeEvent(self, event):
        if self.cal_worker and self.cal_worker.isRunning():
            self.cal_worker.stop()
            self.cal_worker.wait(3000)
        if self.chk_release.isChecked():
            self.chk_release.setChecked(False)
        super().closeEvent(event)

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
