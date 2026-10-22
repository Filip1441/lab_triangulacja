import math
import time
import logging
import numpy as np
import cv2
from PySide6.QtCore import QThread, Signal

import config

logger = logging.getLogger(__name__)

MIN_SPOT_BRIGHTNESS = 120


def find_spot(frame):
    """Returns (x, y) centroid of the brightest blob in a BGR frame, or None if no laser spot is visible."""
    if frame is None:
        return None
    gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (9, 9), 0)
    peak = float(gray.max())
    if peak < MIN_SPOT_BRIGHTNESS:
        return None
    mask = (gray >= peak * 0.8).astype(np.uint8)
    n, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return float(centroids[i][0]), float(centroids[i][1])


def logical_angle_for_spot(spot_x, base_mm, wall_mm, fov_deg, frame_w=640):
    """
    Logical servo angle (90 = parallel) at which the beam hits the wall at distance wall_mm
    and appears at pixel spot_x. Inverse of the app's model: Z = B / (1/tan(alpha) + tan(theta)).
    """
    cx = frame_w / 2.0
    tan_theta = ((spot_x - cx) / cx) * math.tan(math.radians(fov_deg / 2.0))
    inv_tan_alpha = base_mm / wall_mm - tan_theta
    return math.degrees(math.atan2(1.0, inv_tan_alpha))


def offset_for_spot(physical_deg, spot_x, base_mm, wall_mm, fov_deg, frame_w=640):
    """Hardware offset so that physical_angle = logical_angle + offset holds for the observed spot."""
    return physical_deg - logical_angle_for_spot(spot_x, base_mm, wall_mm, fov_deg, frame_w)


class CalibrationWorker(QThread):
    """
    Sweeps the servo, tracks the laser spot on the camera, and fits spot_x(angle) to find
    the physical angle at which the spot is centered. From that, geometry (B, wall distance)
    gives the hardware offset, and the fit slope gives the camera FOV.
    """
    progress = Signal(str)
    result = Signal(dict)
    failed = Signal(str)

    def __init__(self, hardware, camera_worker, base_mm, wall_mm, parent=None):
        super().__init__(parent)
        self.hardware = hardware
        self.camera_worker = camera_worker
        self.base_mm = float(base_mm)
        self.wall_mm = float(wall_mm)
        self._stop = False

    def stop(self):
        self._stop = True

    def _measure(self, n=3, timeout=2.0):
        """Median spot position over n fresh frames, or None if the spot is not visible."""
        pts = []
        last = self.camera_worker.frame_counter
        deadline = time.time() + timeout
        while len(pts) < n and time.time() < deadline and not self._stop:
            if self.camera_worker.frame_counter == last:
                time.sleep(0.005)
                continue
            last = self.camera_worker.frame_counter
            p = find_spot(self.camera_worker.last_frame)
            if p:
                pts.append(p)
        if len(pts) < max(1, n - 1):
            return None
        return float(np.median([p[0] for p in pts])), float(np.median([p[1] for p in pts]))

    def _move(self, angle, settle):
        phys = self.hardware.set_physical_angle(angle)
        time.sleep(settle)
        enc = self.hardware.get_physical_encoder_angle()
        return enc if enc is not None else phys

    def run(self):
        try:
            self._run()
        except Exception as e:
            logger.exception("Calibration failed")
            self.failed.emit(f"Error: {e}")

    def _run(self):
        frame_w = 640
        if self.camera_worker.last_frame is not None:
            frame_w = self.camera_worker.last_frame.shape[1]
        cx = frame_w / 2.0
        min_p = getattr(config, 'SERVO_MIN_ANGLE', 30.0)
        max_p = getattr(config, 'SERVO_MAX_ANGLE', 130.0)

        expected = math.degrees(math.atan2(self.wall_mm, self.base_mm)) + config.SERVO_HARDWARE_OFFSET
        self.progress.emit("Coarse scan for the laser spot...")

        # Visible window is only a few degrees wide: scan near the expected angle first, then everything.
        order = sorted(np.arange(min_p + 2, max_p - 1, 3.0), key=lambda a: abs(a - expected))
        found = None
        for a in order:
            if self._stop:
                return self.failed.emit("Cancelled.")
            self._move(a, 0.9 if found is None else 0.5)
            m = self._measure()
            if m:
                found = (a, m[0])
                break
        if not found:
            return self.failed.emit("Laser spot not found in the whole servo range. Check laser, exposure, aim.")

        # Rough estimate of the centered angle from the first detection (slope guess 100 px/deg).
        a0 = found[0] - (found[1] - cx) / 100.0
        self.progress.emit(f"Spot found near {a0:.1f} deg. Fine sweep...")

        start = max(min_p, a0 - 2.5)
        self._move(start, 1.0)  # approach from one side to avoid backlash
        angles, xs = [], []
        a = max(min_p, a0 - 2.0)
        while a <= min(max_p, a0 + 2.0) and not self._stop:
            enc = self._move(a, 0.45)
            m = self._measure()
            if m and 0.05 * frame_w < m[0] < 0.95 * frame_w:
                angles.append(enc)
                xs.append(m[0])
            a += 0.2
        if self._stop:
            return self.failed.emit("Cancelled.")
        if len(angles) < 6:
            return self.failed.emit(f"Too few valid points ({len(angles)}). Spot unstable or out of view.")

        k, b = np.polyfit(angles, xs, 1)
        if abs(k) < 5:
            return self.failed.emit("Spot does not move with the servo (slope ~0). Is the laser mounted on the servo?")
        pred = k * np.array(angles) + b
        rms = float(np.sqrt(np.mean((np.array(xs) - pred) ** 2)))
        center_phys = (cx - b) / k
        f_px = abs(k) * 180.0 / math.pi
        fov = 2.0 * math.degrees(math.atan(cx / f_px))
        alpha_c = math.degrees(math.atan2(self.wall_mm, self.base_mm))
        offset = center_phys - alpha_c

        self.result.emit({
            "offset": offset,
            "fov": fov,
            "center_physical": center_phys,
            "parallel_physical": center_phys + (90.0 - alpha_c),
            "slope_px_per_deg": float(k),
            "rms_px": rms,
            "points": len(angles),
        })
