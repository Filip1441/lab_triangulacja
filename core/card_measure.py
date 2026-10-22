import math

import cv2
import numpy as np

CARD_W_MM = 85.6   # ISO/IEC 7810 ID-1 (credit card)
CARD_H_MM = 53.98


def measure_card(frame, fov_deg):
    """
    Finds a credit card (bright rectangle) in a BGR frame and returns its distance from the lens in mm,
    from the pinhole model Z = f_px * real_size / size_px. Returns None if no card-like rectangle is found.
    The card should face the camera squarely and be in focus.
    """
    if frame is None:
        return None
    h, w = frame.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in contours:
        if cv2.contourArea(c) < 0.03 * w * h:
            continue
        (_, _), (rw, rh), _ = cv2.minAreaRect(c)
        long_px, short_px = max(rw, rh), min(rw, rh)
        if short_px < 10:
            continue
        aspect = long_px / short_px
        if abs(aspect - CARD_W_MM / CARD_H_MM) > 0.15:
            continue
        if best is None or long_px > best[0]:
            best = (long_px, short_px, aspect)
    if best is None:
        return None
    long_px, short_px, aspect = best
    f_px = (w / 2.0) / math.tan(math.radians(fov_deg / 2.0))
    z_w = f_px * CARD_W_MM / long_px
    z_h = f_px * CARD_H_MM / short_px
    return {"z_mm": z_w, "z_height_mm": z_h, "width_px": long_px, "aspect": aspect}
