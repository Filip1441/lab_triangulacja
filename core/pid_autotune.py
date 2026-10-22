import math
import time
import logging
import numpy as np
from PySide6.QtCore import QThread, Signal

import config
from core.calibration import find_spot

logger = logging.getLogger(__name__)

TARGET_X = 320.0
START_OFFSET_PX = 150.0      # each trial starts with the spot this far left of the target
TRIAL_SEC = 4.5
RATE_HZ = 15


class PidAutoTuneWorker(QThread):
    """
    Tunes the tracking PID on the real hardware. Gains are expressed through the loop gain per tick
    g = kp * (px per degree), ki = 0.02 * kp, kd = h * kp. A step response is measured for a few values of g,
    then of h, and the set with the best settling time, overshoot and (most of all) low jitter wins.
    """
    progress = Signal(str)
    result = Signal(dict)
    failed = Signal(str)

    def __init__(self, hardware, camera_worker, pid_worker, fov_deg, parent=None):
        super().__init__(parent)
        self.hardware = hardware
        self.camera_worker = camera_worker
        self.pid = pid_worker
        self.fov_deg = float(fov_deg)
        self._stop = False

    def stop(self):
        self._stop = True

    def _spot_x(self, timeout=1.5):
        last = self.camera_worker.frame_counter
        end = time.time() + timeout
        xs = []
        while time.time() < end and len(xs) < 3 and not self._stop:
            if self.camera_worker.frame_counter != last:
                last = self.camera_worker.frame_counter
                p = find_spot(self.camera_worker.last_frame)
                if p:
                    xs.append(p[0])
            else:
                time.sleep(0.005)
        return float(np.median(xs)) if len(xs) >= 2 else None

    def _trial(self, start_angle, kp, ki, kd):
        """Runs one step response; returns metrics or None if the spot was lost."""
        self.hardware.set_servo_angle(start_angle)
        time.sleep(1.4)
        x0 = self._spot_x()
        if x0 is None:
            return None
        pid = self.pid
        pid.set_gains(kp, ki, kd)
        pid.set_target(TARGET_X)
        pid.set_rate_hz(RATE_HZ)
        pid.filtered_x = -1.0
        pid.current_x = x0
        pid.start()
        samples, last = [], -1
        t0 = time.time()
        while time.time() - t0 < TRIAL_SEC and not self._stop:
            if self.camera_worker.frame_counter != last:
                last = self.camera_worker.frame_counter
                p = find_spot(self.camera_worker.last_frame)
                if p:
                    pid.update_current_x(p[0], 255.0)
                    samples.append((time.time() - t0, p[0]))
            else:
                time.sleep(0.003)
        pid.stop()
        pid.wait(2000)
        if len(samples) < 20:
            return None
        t = np.array([s[0] for s in samples])
        x = np.array([s[1] for s in samples])
        err = np.abs(x - TARGET_X)
        settle = next((t[i] for i in range(len(t)) if np.all(err[i:] < 10.0)), TRIAL_SEC + 2.0)
        overshoot = float(max(0.0, x.max() - TARGET_X))
        tail = x[t > TRIAL_SEC - 1.5]
        jitter = float(tail.std()) if len(tail) > 5 else 99.0
        offset = float(abs(tail.mean() - TARGET_X)) if len(tail) > 5 else 99.0
        cost = settle + 0.04 * overshoot + 1.0 * jitter + 0.05 * offset
        return {"settle": float(settle), "overshoot": overshoot, "jitter": jitter, "offset": offset, "cost": cost}

    def run(self):
        try:
            self._run()
        except Exception as e:
            logger.exception("PID auto-tune failed")
            self.failed.emit(f"Error: {e}")
        finally:
            self.pid.stop()

    def _run(self):
        x_now = self._spot_x()
        if x_now is None:
            return self.failed.emit("No laser spot visible. Aim the laser at the wall inside the camera view.")
        f_px = 320.0 / math.tan(math.radians(self.fov_deg / 2.0))
        ppd = f_px * math.pi / 180.0                       # pixels per degree at the image centre
        centered = self.hardware.get_servo_angle() + (TARGET_X - x_now) / ppd   # spot moves right as angle grows
        start = centered - START_OFFSET_PX / ppd
        lo, hi = getattr(config, 'SERVO_MIN_LOGICAL_ANGLE', 40.0), getattr(config, 'SERVO_MAX_LOGICAL_ANGLE', 135.0)
        if not (lo + 1 < start < hi - 1 and lo + 1 < centered < hi - 1):
            return self.failed.emit("Servo angle out of range for the test. Move the spot closer to the image centre.")
        restore = self.hardware.get_commanded_angle()

        results = []
        def run_set(g, h):
            kp = g / ppd
            gains = (kp, 0.02 * kp, h * kp)
            self.progress.emit(f"Trial {len(results) + 1}: loop gain {g:.2f}, damping {h:.2f} ...")
            m = self._trial(start, *gains)
            if m is None:
                return None
            m.update(g=g, h=h, kp=gains[0], ki=gains[1], kd=gains[2])
            results.append(m)
            return m

        best = None
        for g in (0.2, 0.3, 0.4, 0.55):                      # stage 1: loop gain
            if self._stop:
                break
            m = run_set(g, 0.08)
            if m is None:
                self.hardware.set_servo_angle(restore)
                return self.failed.emit("Lost the spot during a trial. Check the laser and exposure.")
            if best is None or m["cost"] < best["cost"]:
                best = m
        for h in (0.0, 0.04, 0.16, 0.3):                     # stage 2: derivative damping at the best gain
            if self._stop:
                break
            m = run_set(best["g"], h)
            if m is not None and m["cost"] < best["cost"]:
                best = m

        self.hardware.set_servo_angle(restore)
        if self._stop:
            return self.failed.emit("Cancelled.")
        best = dict(best)
        best["trials"] = len(results)
        best["px_per_deg"] = ppd
        self.result.emit(best)
