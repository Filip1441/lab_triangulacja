import math
import subprocess
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QWidget, QMessageBox,
    QComboBox, QDoubleSpinBox, QGroupBox, QPushButton, QCheckBox
)
from PySide6.QtCore import Qt, QTimer
import config
from core.calibration import CalibrationWorker, find_spot, offset_for_spot
from core.card_measure import measure_card


class SettingsDialog(QDialog):
    """Admin window (behind the password): calibration, camera, tracking, instructor answers, system."""
    def __init__(self, main_window):
        super().__init__(main_window)
        self.setWindowTitle("Admin")
        self.setMinimumWidth(620)

        self.main_window = main_window
        self.camera_worker = main_window.camera_worker
        self.schematic = main_window.schematic
        self.cal_worker = None
        self.pending_cal = None
        self.prev_logical = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        title = QLabel("Admin")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.build_calibration_tab(), "Calibration")
        self.tabs.addTab(self.build_camera_tab(), "Camera")
        self.tabs.addTab(self.build_tracking_tab(), "Tracking")
        self.tabs.addTab(self.build_instructor_tab(), "Instructor")
        self.tabs.addTab(self.build_system_tab(), "System")
        layout.addWidget(self.tabs)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)
        self.update_cheat_sheet()

    # ---------- tabs ----------
    def build_camera_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)

        row = QHBoxLayout()
        row.addWidget(QLabel("Input mode:"))
        self.combo_cam_mode = QComboBox()
        self.combo_cam_mode.addItems(["Live", "Static", "Simulation"])
        self.combo_cam_mode.setCurrentText(self.camera_worker.input_mode)
        self.combo_cam_mode.currentTextChanged.connect(self.main_window.change_camera_mode)
        row.addWidget(self.combo_cam_mode)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Simulated distance (mm):"))
        self.spin_sim_dist = QDoubleSpinBox()
        self.spin_sim_dist.setRange(50.0, 5000.0)
        self.spin_sim_dist.setValue(self.schematic.object_distance)
        self.spin_sim_dist.valueChanged.connect(self.main_window.update_simulation_distance)
        row.addWidget(self.spin_sim_dist)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Camera FOV (deg):"))
        self.spin_cam_fov = QDoubleSpinBox()
        self.spin_cam_fov.setRange(1.0, 120.0)
        self.spin_cam_fov.setDecimals(2)
        self.spin_cam_fov.setValue(self.main_window.camera_fov)
        self.spin_cam_fov.valueChanged.connect(self.main_window.update_camera_fov)
        row.addWidget(self.spin_cam_fov)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    def build_tracking_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        pid = self.main_window.pid_worker

        self.chk_sweep_enabled = QCheckBox("Enable auto sweep when the spot is lost")
        self.chk_sweep_enabled.setChecked(pid.sweep_enabled)
        self.chk_sweep_enabled.toggled.connect(self.main_window.update_sweep_enabled)
        lay.addWidget(self.chk_sweep_enabled)

        row = QHBoxLayout()
        row.addWidget(QLabel("Sweep trigger delay (s):"))
        self.spin_sweep_delay = QDoubleSpinBox()
        self.spin_sweep_delay.setRange(0.5, 60.0)
        self.spin_sweep_delay.setSingleStep(0.5)
        self.spin_sweep_delay.setValue(pid.sweep_timeout_sec)
        self.spin_sweep_delay.valueChanged.connect(self.main_window.update_sweep_timeout)
        row.addWidget(self.spin_sweep_delay)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Full sweep duration (s):"))
        self.spin_sweep_duration = QDoubleSpinBox()
        self.spin_sweep_duration.setRange(0.5, 30.0)
        self.spin_sweep_duration.setSingleStep(0.5)
        self.spin_sweep_duration.setValue(pid.sweep_duration_sec)
        self.spin_sweep_duration.valueChanged.connect(self.main_window.update_sweep_duration)
        row.addWidget(self.spin_sweep_duration)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    def build_instructor_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Stage 2 answer from the live spot and servo angle:"))
        self.lbl_answer = QLabel("Calculating...")
        self.lbl_answer.setAlignment(Qt.AlignCenter)
        self.lbl_answer.setStyleSheet("font-size: 22px; font-weight: bold; color: #00ff00; padding: 16px;")
        lay.addWidget(self.lbl_answer)
        lay.addStretch(1)
        return page

    def build_system_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("The kiosk has no desktop, so app and Pi control lives here."))
        for text, cmd in (("Restart app", ["sudo", "-n", "systemctl", "restart", "lab-triangulacja"]),
                          ("Reboot Pi", ["sudo", "-n", "systemctl", "reboot"]),
                          ("Shut down Pi", ["sudo", "-n", "systemctl", "poweroff"])):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, t=text, c=cmd: self.confirm_system(t, c))
            lay.addWidget(b)
        lay.addStretch(1)
        return page

    def build_calibration_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)

        # Geometry inputs
        geo = QGroupBox("1. Geometry")
        g = QVBoxLayout(geo)
        row = QHBoxLayout()
        row.addWidget(QLabel("B: camera-laser distance (mm):"))
        self.spin_cal_base = QDoubleSpinBox()
        self.spin_cal_base.setRange(50.0, 1000.0)
        self.spin_cal_base.setDecimals(1)
        self.spin_cal_base.setValue(self.schematic.base_distance)
        self.spin_cal_base.valueChanged.connect(self.on_cal_base_changed)
        row.addWidget(self.spin_cal_base)
        g.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Wall distance from lens (mm):"))
        self.spin_cal_wall = QDoubleSpinBox()
        self.spin_cal_wall.setRange(200.0, 5000.0)
        self.spin_cal_wall.setDecimals(1)
        self.spin_cal_wall.setValue(getattr(config, 'DEFAULT_WALL_DISTANCE_MM', 1000.0))
        row.addWidget(self.spin_cal_wall)
        g.addLayout(row)
        self.btn_card = QPushButton("Measure wall distance with a credit card")
        self.btn_card.setToolTip("Put a card on the wall where the laser hits, facing the camera, and press")
        self.btn_card.clicked.connect(self.measure_with_card)
        g.addWidget(self.btn_card)
        self.lbl_card = QLabel("Card on the wall (85.6 mm wide) gives the distance from the image.")
        self.lbl_card.setWordWrap(True)
        g.addWidget(self.lbl_card)
        lay.addWidget(geo)

        # Calibration actions
        cal = QGroupBox("2. Calibrate servo offset")
        c = QVBoxLayout(cal)
        self.lbl_cal_current = QLabel()
        c.addWidget(self.lbl_cal_current)
        self.refresh_cal_current()
        row = QHBoxLayout()
        self.btn_cal_auto = QPushButton("Auto-calibrate (sweep)")
        self.btn_cal_auto.clicked.connect(self.start_auto_calibration)
        self.btn_cal_here = QPushButton("Use current position")
        self.btn_cal_here.setToolTip("Use the servo's present angle and the spot's present pixel position")
        self.btn_cal_here.clicked.connect(self.calibrate_from_current)
        row.addWidget(self.btn_cal_auto)
        row.addWidget(self.btn_cal_here)
        c.addLayout(row)
        self.chk_release = QCheckBox("Release torque (turn the servo by hand)")
        self.chk_release.toggled.connect(self.on_release_toggled)
        c.addWidget(self.chk_release)
        self.lbl_cal_status = QLabel("Aim the laser at the wall, spot visible to the camera.")
        self.lbl_cal_status.setWordWrap(True)
        c.addWidget(self.lbl_cal_status)
        row = QHBoxLayout()
        self.btn_cal_apply = QPushButton("Apply && Save")
        self.btn_cal_apply.setEnabled(False)
        self.btn_cal_apply.clicked.connect(self.apply_calibration)
        self.btn_cal_reset = QPushButton("Reset saved")
        self.btn_cal_reset.setObjectName("secondary")
        self.btn_cal_reset.clicked.connect(self.reset_calibration)
        row.addWidget(self.btn_cal_apply)
        row.addWidget(self.btn_cal_reset)
        c.addLayout(row)
        lay.addWidget(cal)
        lay.addStretch(1)

        hw_ok = self.main_window.hardware.use_st3215
        for w in (self.btn_cal_auto, self.btn_cal_here, self.chk_release):
            w.setEnabled(hw_ok)
        if not hw_ok:
            self.lbl_cal_status.setText("Calibration needs the physical ST3215 servo (not available in simulation).")
        return page

    # ---------- calibration logic ----------
    def refresh_cal_current(self):
        self.lbl_cal_current.setText(
            f"Current: offset {config.SERVO_HARDWARE_OFFSET:+.2f} deg, FOV {self.main_window.camera_fov:.2f} deg")

    def on_cal_base_changed(self, val):
        self.main_window.update_base_distance(val)
        self.schematic.update_state(val, self.schematic.angle_deg, self.schematic.object_distance)

    def measure_with_card(self):
        """Switches the camera to auto exposure for a moment (the laser exposure is too dark to see a card)."""
        cw = self.camera_worker
        self.btn_card.setEnabled(False)
        self.lbl_card.setText("Measuring... (auto exposure for 2 s)")
        cw.set_exposure_ev(0.0)
        QTimer.singleShot(2000, self._finish_card_measure)

    def _finish_card_measure(self):
        frame = self.camera_worker.last_frame
        res = measure_card(frame, self.main_window.camera_fov)
        self.camera_worker.set_exposure_ms(getattr(config, 'DEFAULT_EXPOSURE_MS', 10.0))
        self.btn_card.setEnabled(True)
        if res is None:
            self.lbl_card.setText("No card found. Put it on the wall facing the camera, in focus, filling a good part of the image.")
            return
        self.spin_cal_wall.setValue(res["z_mm"])
        self.lbl_card.setText(
            f"Card {res['width_px']:.1f} px wide (edge jitter {res['spread_px']:.2f} px) -> {res['z_mm']:.0f} mm. "
            f"Distance set. Accuracy follows the FOV value (+-1..3%).")

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
        self.prev_logical = mw.hardware.get_commanded_angle()
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
        if self.prev_logical is not None:
            self.main_window.hardware.set_servo_angle(self.prev_logical)

    def on_cal_failed(self, msg):
        self.lbl_cal_status.setText(msg)
        self.finish_cal_motion()

    def on_cal_result(self, res):
        self.pending_cal = (res["offset"], res["fov"])
        self.lbl_cal_status.setText(
            f"Spot centered at {res['center_physical']:.2f} deg (physical), parallel at {res['parallel_physical']:.2f} deg.\n"
            f"New offset {res['offset']:+.2f} deg, FOV {res['fov']:.2f} deg "
            f"({res['points']} pts, fit error {res['rms_px']:.1f} px). Press Apply & Save.")
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
        off = offset_for_spot(enc, spot[0], self.spin_cal_base.value(), self.spin_cal_wall.value(),
                              mw.camera_fov, frame.shape[1])
        self.pending_cal = (off, mw.camera_fov)
        self.lbl_cal_status.setText(
            f"Servo {enc:.2f} deg, spot at x={spot[0]:.0f} px -> offset {off:+.2f} deg. Press Apply & Save.")
        self.btn_cal_apply.setEnabled(True)

    def apply_calibration(self):
        if not self.pending_cal:
            return
        offset, fov = self.pending_cal
        config.save_calibration(offset, fov)
        mw = self.main_window
        mw.update_camera_fov(fov)
        mw.hardware.set_servo_angle(mw.hardware.get_commanded_angle())
        self.refresh_cal_current()
        self.btn_cal_apply.setEnabled(False)
        self.lbl_cal_status.setText(f"Saved: offset {offset:+.2f} deg, FOV {fov:.2f} deg.")
        self.pending_cal = None

    def reset_calibration(self):
        config.reset_calibration()
        self.lbl_cal_status.setText("Saved calibration removed. Defaults apply after restart.")

    # ---------- misc ----------
    def confirm_system(self, text, cmd):
        if QMessageBox.question(self, text, f"{text}?") == QMessageBox.Yes:
            subprocess.Popen(cmd)

    def closeEvent(self, event):
        if self.cal_worker and self.cal_worker.isRunning():
            self.cal_worker.stop()
            self.cal_worker.wait(3000)
        if self.chk_release.isChecked():
            self.chk_release.setChecked(False)
        super().closeEvent(event)

    def update_cheat_sheet(self):
        # Theoretical distance from the current geometry (measured servo angle, spot pixel, FOV)
        angle = self.main_window.hardware.get_servo_angle()
        base = self.schematic.base_distance
        fov = self.main_window.camera_fov
        rad = math.radians(angle)
        if abs(math.tan(rad)) > 0.001:
            if self.main_window.current_spot_x is not None:
                # tan(theta) = ((x_px - 320) / 320) * tan(FOV / 2);  Z = B / (1/tan(alpha) + tan(theta))
                tan_theta = ((self.main_window.current_spot_x - 320.0) / 320.0) * math.tan(math.radians(fov / 2.0))
                denom = (1.0 / math.tan(rad)) + tan_theta
                if abs(denom) > 0.001:
                    calc_dist = base / denom
                    if calc_dist > 0:
                        self.lbl_answer.setText(f"Theoretical distance:\n{calc_dist:.1f} mm")
                    else:
                        self.lbl_answer.setText("Laser projection behind camera\nInvalid")
                else:
                    self.lbl_answer.setText("Parallel lines\nInvalid")
            else:
                self.lbl_answer.setText("Spot lost\nCannot calculate")
        else:
            self.lbl_answer.setText("Angle near 0 or 180 deg\nInvalid")
