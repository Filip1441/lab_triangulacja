import math
import time
import logging
import numpy as np
from PySide6.QtCore import QThread, Signal

import config
from core.calibration import find_spot

logger = logging.getLogger(__name__)

# Cross-section of the printed demo plate (generator: profile_demo/make_profile.py).
# Height = distance toward the camera from the wave's mean plane, which lies in the same plane as the flat face.
PLATE_AMP_MM = 6.0
PLATE_LAMBDA_MM = 70.0
PLATE_H2 = 0.2
PLATE_PHASE2 = 1.0
PLATE_WIDTH_MM = 100.0


def _raw_wave(x):
    u = 2 * np.pi * np.asarray(x, float) / PLATE_LAMBDA_MM
    return np.sin(u) + PLATE_H2 * np.sin(2 * u + PLATE_PHASE2)


_g = _raw_wave(np.linspace(-PLATE_WIDTH_MM / 2, PLATE_WIDTH_MM / 2, 4001))
_G_MID, _G_HALF = (_g.max() + _g.min()) / 2, (_g.max() - _g.min()) / 2


def plate_height(x_mm, mirror=False):
    """Ideal plate height (mm toward the camera) at lateral position x_mm; mirror flips the plate left-right."""
    x = -np.asarray(x_mm, float) if mirror else np.asarray(x_mm, float)
    return PLATE_AMP_MM * (_raw_wave(x) - _G_MID) / _G_HALF


# ---------- triangulation model (same as the app: Z = B / (1/tan(alpha) + tan(theta))) ----------
def tan_theta(x_px, fov_deg, frame_w=640):
    cx = frame_w / 2.0
    return ((np.asarray(x_px, float) - cx) / cx) * math.tan(math.radians(fov_deg / 2.0))


def distance_mm(alpha_deg, x_px, base_mm, fov_deg, frame_w=640):
    inv = 1.0 / np.tan(np.radians(np.asarray(alpha_deg, float))) + tan_theta(x_px, fov_deg, frame_w)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(inv > 1e-6, base_mm / inv, np.nan)
    return z


def centered_angle_deg(z_mm, base_mm):
    """Logical servo angle at which the spot sits in the image centre on a wall at z_mm."""
    return math.degrees(math.atan2(z_mm, base_mm))


# ---------- scan worker ----------
class ProfileScanWorker(QThread):
    """
    One slow one-way servo sweep across the camera's field of view. For every camera frame the spot pixel
    and the raw servo encoder reading are logged with a timestamp. The encoder only has 0.088 deg steps, so the
    angle at each frame is reconstructed afterwards from a smooth fit of the encoder readings against time.
    """
    progress = Signal(str)
    result = Signal(dict)
    failed = Signal(str)

    APPROACH_SPEED = 600

    def __init__(self, hardware, camera_worker, base_mm, fov_deg, z_ref_mm, speed_steps, parent=None):
        super().__init__(parent)
        self.hardware = hardware
        self.camera_worker = camera_worker
        self.base_mm = float(base_mm)
        self.fov_deg = float(fov_deg)
        self.z_ref_mm = float(z_ref_mm)
        self.speed_steps = int(speed_steps)
        self._stop = False

    def stop(self):
        self._stop = True

    def _phys(self):
        enc = self.hardware.get_physical_encoder_angle()
        if enc is None:
            enc = self.hardware.get_servo_angle() + config.SERVO_HARDWARE_OFFSET
        return enc

    def run(self):
        try:
            self._run()
        except Exception as e:
            logger.exception("Profile scan failed")
            self.failed.emit(f"Error: {e}")

    def _run(self):
        hw, cam = self.hardware, self.camera_worker
        if not hw.use_st3215:
            return self.failed.emit("Profile scan needs the physical ST3215 servo.")
        half = self.fov_deg / 2.0 + 0.4
        centre = centered_angle_deg(self.z_ref_mm, self.base_mm)
        a0, a1 = centre - half, centre + half   # increasing angle: the spot travels right to left in the image
        p0 = a0 + config.SERVO_HARDWARE_OFFSET
        p1 = a1 + config.SERVO_HARDWARE_OFFSET

        self.progress.emit("Moving to the start of the scan...")
        hw.set_servo_angle(a0, speed=self.APPROACH_SPEED)
        t_end = time.time() + 8.0
        while time.time() < t_end and not self._stop:
            if abs(self._phys() - p0) < 0.12:
                break
            time.sleep(0.05)
        time.sleep(0.8)   # settle: the sweep starts from rest, always from the same side
        if self._stop:
            return self.failed.emit("Cancelled.")

        deg_per_s = self.speed_steps * 360.0 / 4096.0
        duration = (p1 - p0) / max(deg_per_s, 0.05)
        self.progress.emit(f"Scanning {a0:.1f} to {a1:.1f} deg, about {duration:.0f} s...")
        hw.set_servo_angle(a1, speed=self.speed_steps)
        t_cmd = time.time()
        rows = []   # (t, phys, spot_x or nan)
        last = cam.frame_counter
        deadline = t_cmd + duration + 6.0
        while time.time() < deadline and not self._stop:
            if cam.frame_counter == last:
                time.sleep(0.002)
                continue
            last = cam.frame_counter
            frame = cam.last_frame
            t = time.time()
            phys = self._phys()
            spot = find_spot(frame)
            rows.append((t, phys, spot[0] if spot else float("nan")))
            if phys >= p1 - 0.05:
                break
        if self._stop:
            return self.failed.emit("Cancelled.")
        if len(rows) < 30:
            return self.failed.emit(f"Too few frames ({len(rows)}). Is the camera running?")

        arr = np.array(rows)
        res = reconstruct_angles(arr[:, 0], arr[:, 1], arr[:, 2])
        if res is None:
            return self.failed.emit("Servo did not move through the scan range (check speed and torque).")
        res["frame_w"] = cam.last_frame.shape[1] if cam.last_frame is not None else 640
        res["deg_per_s"] = deg_per_s
        self.result.emit(res)


def reconstruct_angles(t, phys, spot_x, poly_deg=3):
    """
    Smooth the quantized encoder readings over the moving part of the sweep; returns logical angles at the
    frames where the spot was visible. None if the servo barely moved.
    """
    t, phys, spot_x = np.asarray(t, float), np.asarray(phys, float), np.asarray(spot_x, float)
    start, end = float(np.median(phys[:5])), float(np.median(phys[-5:]))
    if end - start < 1.0:
        return None
    moving = (phys > start + 0.15) & (phys < end - 0.15)
    if moving.sum() < 20:
        return None
    tn = t - t[0]
    coef = np.polyfit(tn[moving], phys[moving], poly_deg)
    fit_phys = np.polyval(coef, tn)
    fit_rms = float(np.sqrt(np.mean((fit_phys[moving] - phys[moving]) ** 2)))
    ok = moving & np.isfinite(spot_x)
    return {
        "alpha": fit_phys[ok] - config.SERVO_HARDWARE_OFFSET,   # logical angle (90 = parallel)
        "x_px": spot_x[ok],
        "fit_rms_deg": fit_rms,
        "frames": int(len(t)),
        "points": int(ok.sum()),
    }


# ---------- analysis ----------
def flat_correction_deg(alpha, x_px, z_ref_mm, base_mm, fov_deg, frame_w=640):
    """
    Angle correction (deg) that makes the flat face read exactly z_ref_mm on average. It absorbs the servo
    offset error and the constant camera/encoder time lag in one number; the wave scan reuses it.
    """
    deltas = np.linspace(-3.0, 3.0, 1201)
    err = np.array([np.nanmean(distance_mm(alpha + d, x_px, base_mm, fov_deg, frame_w)) - z_ref_mm for d in deltas])
    good = np.isfinite(err)
    if good.sum() < 5:
        return None
    deltas, err = deltas[good], err[good]
    i = int(np.argmin(np.abs(err)))
    lo, hi = max(0, i - 3), min(len(deltas), i + 4)
    k, b = np.polyfit(deltas[lo:hi], err[lo:hi], 1)
    return float(-b / k) if abs(k) > 1e-9 else float(deltas[i])


def to_profile(alpha, x_px, delta_deg, z_ref_mm, base_mm, fov_deg, frame_w=640):
    """Returns (x_mm, h_mm): lateral position of each spot and its height toward the camera above the flat plane."""
    z = distance_mm(alpha + delta_deg, x_px, base_mm, fov_deg, frame_w)
    x_mm = z * tan_theta(x_px, fov_deg, frame_w)
    h = z_ref_mm - z
    ok = np.isfinite(z) & (np.abs(h) < 300.0)
    return x_mm[ok], h[ok]


def bin_profile(x_mm, h_mm, width_mm=2.0):
    """Mean height per lateral bin, ignoring bins with too few points."""
    if len(x_mm) == 0:
        return np.array([]), np.array([])
    edges = np.arange(np.floor(x_mm.min()), np.ceil(x_mm.max()) + width_mm, width_mm)
    idx = np.digitize(x_mm, edges)
    xc, hc = [], []
    for i in np.unique(idx):
        m = idx == i
        if m.sum() >= 3:
            xc.append(x_mm[m].mean())
            hc.append(np.median(h_mm[m]))
    return np.array(xc), np.array(hc)


def find_plate_extent(x_mm, h_mm, max_h=20.0, max_gap=6.0):
    """
    Lateral extent (left, right) of the plate: the longest run of spots lying within max_h of the flat plane.
    Spots past the plate edge land on the far background, so the distance jumps and the run ends.
    """
    m = np.abs(h_mm) < max_h
    if m.sum() < 10:
        return None
    x = np.sort(x_mm[m])
    breaks = np.where(np.diff(x) > max_gap)[0]
    starts = np.concatenate([[0], breaks + 1])
    ends = np.concatenate([breaks, [len(x) - 1]])
    i = int(np.argmax(x[ends] - x[starts]))
    return float(x[starts[i]]), float(x[ends[i]])


def compare_with_model(xc, hc, mirror=False, fixed_shift=None):
    """
    Ideal plate profile laid onto the measured one: (shift_mm, rms_mm, level_mm). The lateral shift is searched
    unless fixed_shift (plate centre found from its edges) is given.
    """
    if len(xc) < 5:
        return None
    best = None
    shifts = [fixed_shift] if fixed_shift is not None else np.arange(-30.0, 30.01, 0.5)
    for s in shifts:
        inside = np.abs(xc - s) <= PLATE_WIDTH_MM / 2
        if inside.sum() < 5:
            continue
        model = plate_height(xc[inside] - s, mirror)
        diff = hc[inside] - model
        level = float(diff.mean())
        rms = float(np.sqrt(np.mean((diff - level) ** 2)))
        if best is None or rms < best[1]:
            best = (float(s), rms, level)
    return best
