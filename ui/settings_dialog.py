import math
import subprocess
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QWidget, QMessageBox,
    QComboBox, QDoubleSpinBox, QGroupBox, QPushButton, QCheckBox, QStackedWidget, QSpinBox, QProgressBar
)
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
import config
from core.calibration import CalibrationWorker, find_spot, offset_for_spot
from core.card_measure import measure_card
from core.pid_autotune import PidAutoTuneWorker
from core.demo_script import DEMO_SCRIPT, STARTER_TEMPLATE
from core import results
from core import profile_scan as ps


def _note(text):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    return lbl


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
        self.tune_worker = None
        self.profile_worker = None
        self.profile_flat = None
        self.profile_wave = None
        self.profile_kind = "flat"
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
        self.tabs.addTab(self.build_demo_tab(), "Demo")
        self.tabs.addTab(self.build_profile_tab(), "Profile")
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

        tune = QGroupBox("PID auto-tune")
        t = QVBoxLayout(tune)
        t.addWidget(_note("Tests several gain sets on the real servo (spot must be visible) and picks the one that "
                          "settles fast without jitter. Takes about 1 minute; the servo moves."))
        self.btn_tune = QPushButton("PID auto")
        self.btn_tune.clicked.connect(self.start_pid_autotune)
        t.addWidget(self.btn_tune)
        self.lbl_tune = QLabel("")
        self.lbl_tune.setWordWrap(True)
        t.addWidget(self.lbl_tune)
        lay.addWidget(tune)
        if not self.main_window.hardware.use_st3215:
            self.btn_tune.setEnabled(False)
            self.lbl_tune.setText("Needs the physical servo (not available in simulation).")
        lay.addStretch(1)
        return page

    def build_instructor_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(_note("Stage 2 answer from the live spot and servo angle:"))
        self.lbl_answer = QLabel("Calculating...")
        self.lbl_answer.setAlignment(Qt.AlignCenter)
        self.lbl_answer.setStyleSheet("font-size: 22px; font-weight: bold; color: #00ff00; padding: 16px;")
        lay.addWidget(self.lbl_answer)
        lay.addStretch(1)
        return page

    def build_demo_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(_note("The code editor starts with outline comments only. Paste the demo solution (full spot detection pipeline) "
                            "when showing the exercise to someone."))
        b = QPushButton("Paste demo code into the editor")
        b.clicked.connect(lambda: self.paste_demo(False))
        lay.addWidget(b)
        b = QPushButton("Paste demo code and run it")
        b.clicked.connect(lambda: self.paste_demo(True))
        lay.addWidget(b)
        b = QPushButton("Reset the editor to the starter comments")
        b.setObjectName("secondary")
        b.clicked.connect(self.clear_editor)
        lay.addWidget(b)
        lay.addStretch(1)
        return page

    def paste_demo(self, run):
        mw = self.main_window
        if mw.txt_code.toPlainText().strip() != STARTER_TEMPLATE.strip():
            if QMessageBox.question(self, "Replace code", "The editor is not empty. Replace its content?") != QMessageBox.Yes:
                return
        mw.stop_custom_script()
        mw.txt_code.setPlainText(DEMO_SCRIPT)
        mw.switch_stage(0)
        if run:
            QTimer.singleShot(300, mw.run_custom_script)
        self.close()

    def clear_editor(self):
        mw = self.main_window
        mw.stop_custom_script()
        mw.txt_code.setPlainText(STARTER_TEMPLATE)

    # ---------- profile scan demo (printed double-sided plate: flat / wavy) ----------
    def build_profile_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.profile_stack = QStackedWidget()
        lay.addWidget(self.profile_stack)

        # 0: flat side instruction + settings
        p0 = QWidget()
        l0 = QVBoxLayout(p0)
        l0.addWidget(_note(
            "Step 1 of 2: mount the plate on the rail with the FLAT side toward the camera. The plate's axis of rotation "
            "stays in the same place for both sides. Laser spot must hit the plate, camera sees about 14 cm of it at 1 m."))
        self.chk_prof_auto_z = QCheckBox("Measure the distance automatically (PID locks the spot on the flat face)")
        self.chk_prof_auto_z.setChecked(True)
        l0.addWidget(self.chk_prof_auto_z)
        row = QHBoxLayout()
        row.addWidget(QLabel("Distance camera to flat face (mm), measured or typed:"))
        self.spin_prof_z = QDoubleSpinBox()
        self.spin_prof_z.setRange(300.0, 3000.0)
        self.spin_prof_z.setDecimals(1)
        self.spin_prof_z.setValue(1000.0)
        row.addWidget(self.spin_prof_z)
        l0.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Servo speed during the scan (steps/s, 6 = 0.5 deg/s):"))
        self.spin_prof_speed = QSpinBox()
        self.spin_prof_speed.setRange(2, 40)
        self.spin_prof_speed.setValue(6)
        row.addWidget(self.spin_prof_speed)
        l0.addLayout(row)
        l0.addWidget(_note("B (camera-laser distance) comes from the Calibration tab."))
        b = QPushButton("Flat side is set: start scan")
        b.clicked.connect(lambda: self.start_profile_scan("flat"))
        l0.addWidget(b)
        l0.addStretch(1)
        self.profile_stack.addWidget(p0)

        # 1: scanning
        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        self.lbl_prof_status = _note("")
        l1.addWidget(self.lbl_prof_status)
        bar = QProgressBar()
        bar.setRange(0, 0)
        l1.addWidget(bar)
        b = QPushButton("Cancel")
        b.setObjectName("secondary")
        b.clicked.connect(self.cancel_profile_scan)
        l1.addWidget(b)
        l1.addStretch(1)
        self.profile_stack.addWidget(p1)

        # 2: curved side instruction
        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        self.lbl_prof_flat = _note("")
        l2.addWidget(self.lbl_prof_flat)
        l2.addWidget(_note(
            "Step 2 of 2: rotate the plate by 180 degrees so the CURVED side faces the camera, up to the same stop. "
            "Do not move the rail."))
        b = QPushButton("Curved side is set: start scan")
        b.clicked.connect(lambda: self.start_profile_scan("wave"))
        l2.addWidget(b)
        b = QPushButton("Back to step 1")
        b.setObjectName("secondary")
        b.clicked.connect(lambda: self.profile_stack.setCurrentIndex(0))
        l2.addWidget(b)
        l2.addStretch(1)
        self.profile_stack.addWidget(p2)

        # 3: result
        p3 = QWidget()
        l3 = QVBoxLayout(p3)
        self.prof_plot = pg.PlotWidget()
        self.prof_plot.setBackground("#1e1e1e")
        self.prof_plot.showGrid(x=True, y=True, alpha=0.3)
        self.prof_plot.setLabel("bottom", "Position across the plate (mm)")
        self.prof_plot.setLabel("left", "Height toward camera (mm)")
        self.prof_plot.addLegend()
        self.prof_plot.setMinimumHeight(260)
        l3.addWidget(self.prof_plot)
        self.lbl_prof_result = _note("")
        l3.addWidget(self.lbl_prof_result)
        row = QHBoxLayout()
        self.chk_prof_mirror = QCheckBox("Mirror the reference profile")
        self.chk_prof_mirror.toggled.connect(self.draw_profile_result)
        row.addWidget(self.chk_prof_mirror)
        b = QPushButton("New measurement")
        b.clicked.connect(lambda: self.profile_stack.setCurrentIndex(0))
        row.addWidget(b)
        l3.addLayout(row)
        self.profile_stack.addWidget(p3)

        if not self.main_window.hardware.use_st3215:
            p0.setEnabled(False)
        return page

    def start_profile_scan(self, kind):
        mw = self.main_window
        if self.profile_worker and self.profile_worker.isRunning():
            return
        if mw.pid_worker.running:
            mw.btn_toggle_pid.setChecked(False)
        if self.chk_release.isChecked():
            self.chk_release.setChecked(False)
        if mw.camera_worker.last_frame is None:
            QMessageBox.warning(self, "Profile", "No camera frames yet.")
            return
        self.profile_kind = kind
        self.prev_logical = mw.hardware.get_commanded_angle()
        if kind == "flat" and self.chk_prof_auto_z.isChecked():
            self.pid_distance_start()
            return
        self.launch_profile_scan()

    def pid_distance_start(self):
        """The PID centres the spot on the flat face; then B*tan(alpha) with the measured angle gives the distance."""
        mw = self.main_window
        self.profile_stack.setCurrentIndex(1)
        self.lbl_prof_status.setText("PID is locking the spot on the flat face...")
        self.pid_z_samples = []
        mw.slider_target_x.setValue(320)
        mw.btn_toggle_pid.setChecked(True)
        QTimer.singleShot(4000, self.pid_distance_collect)

    def pid_distance_collect(self):
        self.lbl_prof_status.setText("Measuring the distance...")
        self.pid_timer = QTimer(self)
        self.pid_timer.timeout.connect(self.pid_distance_sample)
        self.pid_timer.start(50)
        QTimer.singleShot(2000, self.pid_distance_finish)

    def pid_distance_sample(self):
        mw = self.main_window
        if mw.current_spot_x is not None:
            self.pid_z_samples.append((mw.hardware.get_servo_angle(), mw.current_spot_x))

    def pid_distance_finish(self):
        mw = self.main_window
        self.pid_timer.stop()
        mw.btn_toggle_pid.setChecked(False)
        if len(self.pid_z_samples) < 20:
            self.profile_stack.setCurrentIndex(0)
            QMessageBox.warning(self, "Profile", "PID could not hold the spot. Check that the laser hits the flat face.")
            return
        a, x = np.array(self.pid_z_samples).T
        z = float(np.nanmedian(ps.distance_mm(a, x, self.spin_cal_base.value(), mw.camera_fov)))
        self.spin_prof_z.setValue(z)
        self.launch_profile_scan()

    def launch_profile_scan(self):
        mw = self.main_window
        if self.profile_kind == "wave" and self.profile_flat:
            z_ref = self.profile_flat["z_ref"]   # both sides share one reference plane
        else:
            z_ref = self.spin_prof_z.value()
        self.set_cal_busy(True)
        self.profile_stack.setCurrentIndex(1)
        self.lbl_prof_status.setText("Starting...")
        w = ps.ProfileScanWorker(mw.hardware, mw.camera_worker, self.spin_cal_base.value(), mw.camera_fov,
                                 z_ref, self.spin_prof_speed.value(), self)
        w.progress.connect(self.lbl_prof_status.setText)
        w.result.connect(self.on_profile_scan_done)
        w.failed.connect(self.on_profile_scan_failed)
        self.profile_worker = w
        w.start()

    def cancel_profile_scan(self):
        if self.profile_worker and self.profile_worker.isRunning():
            self.profile_worker.stop()

    def on_profile_scan_failed(self, msg):
        self.finish_cal_motion()
        self.profile_stack.setCurrentIndex(2 if self.profile_kind == "wave" else 0)
        QMessageBox.warning(self, "Profile scan", msg)

    def on_profile_scan_done(self, res):
        self.finish_cal_motion()
        mw = self.main_window
        z_ref = self.profile_flat["z_ref"] if self.profile_kind == "wave" else self.spin_prof_z.value()
        base, fov, fw = self.spin_cal_base.value(), mw.camera_fov, res["frame_w"]
        if self.profile_kind == "flat":
            delta = ps.flat_correction_deg(res["alpha"], res["x_px"], z_ref, base, fov, fw)
            if delta is None or res["points"] < 30:
                self.profile_stack.setCurrentIndex(0)
                QMessageBox.warning(self, "Profile scan", "Spot not seen well enough on the flat side. Check aim and exposure.")
                return
            x_mm, h = ps.to_profile(res["alpha"], res["x_px"], delta, z_ref, base, fov, fw)
            self.profile_flat = {"z_ref": z_ref, "delta": delta, "x": x_mm, "h": h, "std": float(np.std(h)),
                                 "fit_rms": res["fit_rms_deg"]}
            self.lbl_prof_flat.setText(
                f"Distance to the flat face {z_ref:.0f} mm. Flat side done: {res['points']} points, angle correction {delta:+.3f} deg, "
                f"flatness error {self.profile_flat['std']:.2f} mm rms, encoder fit {res['fit_rms_deg']:.3f} deg.")
            self.profile_stack.setCurrentIndex(2)
        else:
            f = self.profile_flat
            x_mm, h = ps.to_profile(res["alpha"], res["x_px"], f["delta"], z_ref, base, fov, fw)
            ext = ps.find_plate_extent(x_mm, h)
            scale = 1.0
            if ext and 0.96 <= ps.PLATE_WIDTH_MM / (ext[1] - ext[0]) <= 1.04:   # larger mismatch = edge not clean, ignore
                scale = ps.PLATE_WIDTH_MM / (ext[1] - ext[0])   # the plate's known 100 mm calibrates the lateral axis
                ext = (ext[0] * scale, ext[1] * scale)
                x_mm = x_mm * scale
                self.profile_flat["x"] = self.profile_flat["x"] * scale
            else:
                ext = None
            self.profile_wave = {"x": x_mm, "h": h, "fit_rms": res["fit_rms_deg"], "points": res["points"],
                                 "extent": ext, "scale": scale}
            self.draw_profile_result()
            self.profile_stack.setCurrentIndex(3)

    def draw_profile_result(self, *_):
        f, w = self.profile_flat, getattr(self, "profile_wave", None)
        if not f or not w:
            return
        pl = self.prof_plot
        pl.clear()
        pl.plot(f["x"], f["h"], pen=None, symbol="o", symbolSize=3, symbolBrush=(140, 140, 140), name="flat side (should be 0)")
        pl.plot(w["x"], w["h"], pen=None, symbol="o", symbolSize=3, symbolBrush=(255, 170, 60), name="measured, curved side")
        xc, hc = ps.bin_profile(w["x"], w["h"])
        pl.plot(xc, hc, pen=pg.mkPen((255, 120, 0), width=3), name="measured, smoothed")
        ext = w.get("extent")
        fixed = (ext[0] + ext[1]) / 2.0 if ext else None
        cmp_ = ps.compare_with_model(xc, hc, self.chk_prof_mirror.isChecked(), fixed)
        if cmp_ is None:
            self.lbl_prof_result.setText("Too few points on the curved side.")
            return
        shift, rms, level = cmp_
        xm = np.linspace(shift - ps.PLATE_WIDTH_MM / 2, shift + ps.PLATE_WIDTH_MM / 2, 200)
        ref = ps.plate_height(xm - shift, self.chk_prof_mirror.isChecked()) + level
        pl.plot(xm, ref, pen=pg.mkPen((90, 220, 120), width=2, style=Qt.DashLine), name="actual plate profile")
        inside = np.abs(xc - shift) <= ps.PLATE_WIDTH_MM / 2
        err = hc[inside] - (ps.plate_height(xc[inside] - shift, self.chk_prof_mirror.isChecked()) + level)
        self.lbl_prof_result.setText(
            f"Error against the true plate profile: {rms:.2f} mm rms, {np.abs(err).max():.2f} mm max "
            f"(profile height 12 mm peak to peak). Plate placed {shift:+.0f} mm from the camera axis, "
            f"level offset {level:+.2f} mm. Flat side was flat to {f['std']:.2f} mm. "
            + (f"Plate edges found at {ext[0]:+.0f} and {ext[1]:+.0f} mm (the known 100 mm sets the lateral scale; "
               f"correction {w['scale']:.3f})." if ext else "Plate edges not both seen, placement searched."))

    def build_system_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(_note("The kiosk has no desktop, so app and Pi control lives here."))
        for text, cmd in (("Restart app", ["sudo", "-n", "systemctl", "restart", "lab-triangulacja"]),
                          ("Reboot Pi", ["sudo", "-n", "systemctl", "reboot"]),
                          ("Shut down Pi", ["sudo", "-n", "systemctl", "poweroff"])):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, t=text, c=cmd: self.confirm_system(t, c))
            lay.addWidget(b)
        b = QPushButton("Delete all saved results (reset session)")
        b.setObjectName("secondary")
        b.clicked.connect(self.delete_all_results)
        lay.addWidget(b)
        b = QPushButton("Reset remembered settings (PID, B, sweep)")
        b.setObjectName("secondary")
        b.clicked.connect(self.reset_settings)
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

    # ---------- PID auto-tune ----------
    def start_pid_autotune(self):
        mw = self.main_window
        if self.tune_worker and self.tune_worker.isRunning():
            self.tune_worker.stop()
            return
        if mw.pid_worker.running:
            mw.btn_toggle_pid.setChecked(False)
        if mw.camera_worker.last_frame is None:
            self.lbl_tune.setText("No camera frames yet.")
            return
        mw.hw_group.setEnabled(False)
        self.btn_tune.setText("Cancel auto-tune")
        self.tune_worker = PidAutoTuneWorker(mw.hardware, mw.camera_worker, mw.pid_worker, mw.camera_fov, self)
        self.tune_worker.progress.connect(self.lbl_tune.setText)
        self.tune_worker.result.connect(self.on_tune_result)
        self.tune_worker.failed.connect(self.on_tune_failed)
        self.tune_worker.start()

    def _tune_done(self):
        self.btn_tune.setText("PID auto")
        self.main_window.hw_group.setEnabled(True)

    def on_tune_failed(self, msg):
        self.lbl_tune.setText(msg)
        self._tune_done()

    def on_tune_result(self, r):
        mw = self.main_window
        mw.slider_kp.setValue(min(r["kp"], 0.0100))
        mw.slider_ki.setValue(min(r["ki"], 0.0020))
        mw.slider_kd.setValue(min(r["kd"], 0.0010))
        mw.slider_target_x.setValue(320)
        mw.update_pid_gains()   # sliders may already hold these values (no signal), so push them to the worker explicitly
        self.lbl_tune.setText(
            f"Applied: Kp {r['kp']:.4f}, Ki {r['ki']:.5f}, Kd {r['kd']:.5f}  "
            f"(settles in {r['settle']:.1f} s, overshoot {r['overshoot']:.0f} px, jitter {r['jitter']:.1f} px; "
            f"{r['trials']} trials). Saved.")
        self._tune_done()

    # ---------- misc ----------
    def delete_all_results(self):
        """Between classes: removes all result ZIPs and exports from the SD card and the screenshots kept in memory."""
        mw = self.main_window
        if QMessageBox.question(self, "Delete all results",
                                "Delete ALL saved result packages and CSV exports from the SD card?\nThis cannot be undone.") != QMessageBox.Yes:
            return
        n, size = results.delete_all_results([mw.data_logger.export_dir])
        mw.s1_frames.clear()
        mw.s2_verifications.clear()
        QMessageBox.information(self, "Done", f"Deleted {n} file(s), freed {size / 1024 / 1024:.1f} MB.")

    def reset_settings(self):
        if QMessageBox.question(self, "Reset settings", "Forget remembered settings and restart the app?") == QMessageBox.Yes:
            self.main_window.settings.reset()
            subprocess.Popen(["sudo", "-n", "systemctl", "restart", "lab-triangulacja"])

    def confirm_system(self, text, cmd):
        if QMessageBox.question(self, text, f"{text}?") == QMessageBox.Yes:
            subprocess.Popen(cmd)

    def closeEvent(self, event):
        if self.cal_worker and self.cal_worker.isRunning():
            self.cal_worker.stop()
            self.cal_worker.wait(3000)
        if self.tune_worker and self.tune_worker.isRunning():
            self.tune_worker.stop()
            self.tune_worker.wait(5000)
        if self.profile_worker and self.profile_worker.isRunning():
            self.profile_worker.stop()
            self.profile_worker.wait(5000)
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
