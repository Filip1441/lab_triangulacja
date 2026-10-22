import math

import cv2
import numpy as np

CARD_W_MM = 85.6   # ISO/IEC 7810 ID-1 (credit card)


def _longest_bright_run(row, level):
    """Sub-pixel (left, right) edges of the longest run above `level` in a 1-D profile, or None."""
    above = row > level
    best, start = None, None
    for i, v in enumerate(np.append(above, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    if best is None or best[0] < 1 or best[1] >= len(row):
        return None
    a, b = best
    left = (a - 1) + (level - row[a - 1]) / (row[a] - row[a - 1])
    right = (b - 1) + (level - row[b - 1]) / (row[b] - row[b - 1])
    return left, right


def measure_card(frame, fov_deg):
    """
    Measures the card's width in pixels at several rows of the card's upper part and returns its distance from
    the lens in mm (pinhole model Z = f_px * 85.6 mm / width_px). None if no card-like bright bar is found.
    The card should face the camera squarely, be in focus, and be brighter than its background.
    """
    if frame is None:
        return None
    h, w = frame.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    x, y, bw, bh = cv2.boundingRect(c)
    if bw < 0.15 * w or bh < 0.1 * h:
        return None
    widths = []
    for row in range(y + 25, min(h - 1, y + 25 + int(0.45 * bh)), 5):
        prof = gray[row].astype(np.float32)
        level = (np.percentile(prof, 5) + np.percentile(prof, 95)) / 2.0
        edges = _longest_bright_run(prof, level)
        if edges:
            widths.append(edges[1] - edges[0])
    if len(widths) < 5:
        return None
    width_px = float(np.median(widths))
    spread = float(np.std(widths))
    if width_px < 0.15 * w or spread > 0.02 * width_px:
        return None  # unstable edges: not a clean rectangle
    f_px = (w / 2.0) / math.tan(math.radians(fov_deg / 2.0))
    return {"z_mm": f_px * CARD_W_MM / width_px, "width_px": width_px, "spread_px": spread}
