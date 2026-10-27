import csv
import json
import os
import shutil
import time
import zipfile
import logging
from datetime import datetime

import cv2

import config

logger = logging.getLogger(__name__)

PACKAGE_PREFIX = "wyniki_"


def results_dir() -> str:
    path = os.path.expanduser(getattr(config, 'RESULTS_DIR', '~/lab_results'))
    os.makedirs(path, exist_ok=True)
    return path


def list_packages():
    """Newest first: [(filename, size_bytes, mtime)]."""
    d = results_dir()
    items = []
    for name in os.listdir(d):
        if name.startswith(PACKAGE_PREFIX) and name.endswith(".zip"):
            st = os.stat(os.path.join(d, name))
            items.append((name, st.st_size, st.st_mtime))
    return sorted(items, key=lambda t: t[2], reverse=True)


def purge_old():
    """Deletes packages older than RESULTS_KEEP_DAYS, then oldest-first while free disk space is low."""
    d = results_dir()
    cutoff = time.time() - getattr(config, 'RESULTS_KEEP_DAYS', 7) * 86400
    removed = 0
    for name, _, mtime in list_packages():
        if mtime < cutoff:
            _remove(os.path.join(d, name))
            removed += 1
    min_free = getattr(config, 'RESULTS_MIN_FREE_MB', 500) * 1024 * 1024
    for name, _, _ in reversed(list_packages()):
        if shutil.disk_usage(d).free >= min_free:
            break
        _remove(os.path.join(d, name))
        removed += 1
    if removed:
        logger.info(f"Results cleanup: removed {removed} old package(s).")
    return removed


def delete_all_results(extra_dirs=()):
    """
    Deletes every saved result package (wyniki_*.zip, leftover .tmp_* folders) and the CSV/PNG exports in extra_dirs.
    Returns (files_deleted, bytes_freed).
    """
    count, freed = 0, 0
    d = results_dir()
    for name in os.listdir(d):
        path = os.path.join(d, name)
        if name.startswith(PACKAGE_PREFIX) and name.endswith(".zip") and os.path.isfile(path):
            freed += os.path.getsize(path)
            _remove(path)
            count += 1
        elif name.startswith(".tmp_") and os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    for ed in extra_dirs:
        if not os.path.isdir(ed):
            continue
        for name in os.listdir(ed):
            path = os.path.join(ed, name)
            if name.lower().endswith((".csv", ".png")) and os.path.isfile(path):
                freed += os.path.getsize(path)
                _remove(path)
                count += 1
    return count, freed


def _remove(path):
    try:
        os.remove(path)
    except OSError as e:
        logger.warning(f"Could not remove {path}: {e}")


def _save_png(path, frame):
    if frame is not None:
        cv2.imwrite(path, frame)


def _export_plot(plot_widget, path):
    try:
        import pyqtgraph.exporters
        pyqtgraph.exporters.ImageExporter(plot_widget.getPlotItem()).export(path)
    except Exception as e:
        logger.warning(f"Plot export failed ({path}): {e}")


def build_package(mw, note: str = "") -> str:
    """
    Collects everything the student produced (script, console, camera frames, calibration data and plots,
    tracking plot, window screenshot, parameters) into one ZIP. Must run in the GUI thread.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = os.path.join(results_dir(), f".tmp_{stamp}")
    os.makedirs(work, exist_ok=True)
    try:
        with open(os.path.join(work, "script.py"), "w", encoding="utf-8") as f:
            f.write(mw.txt_code.toPlainText())
        with open(os.path.join(work, "console.txt"), "w", encoding="utf-8") as f:
            f.write(mw.txt_console.toPlainText())

        _save_png(os.path.join(work, "camera_frame.png"), mw.current_raw_frame)
        pix = getattr(mw.camera_display, "_current_pixmap", None)
        if pix is not None and not pix.isNull():
            pix.save(os.path.join(work, "script_output.png"))
        mw.grab().save(os.path.join(work, "window.png"))

        points = []
        for r in range(mw.table_s1.rowCount()):
            points.append([mw.table_s1.item(r, c).text() if mw.table_s1.item(r, c) else "" for c in range(4)])
        if points:
            with open(os.path.join(work, "calibration_points.csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Angle_deg", "Px_X", "Px_Y", "Dist_mm"])
                w.writerows(points)
            _export_plot(mw.calib_plot, os.path.join(work, "calibration_plot.png"))
            for i, frame in enumerate(getattr(mw, "s1_frames", [])):
                _save_png(os.path.join(work, f"calibration_point_{i + 1:02d}.png"), frame)
        for i, (ok, pix) in enumerate(getattr(mw, "s2_verifications", [])):
            pix.save(os.path.join(work, f"stage2_verify_{i + 1:02d}_{'ok' if ok else 'fail'}.png"))
        with open(os.path.join(work, "calibration_fit.txt"), "w", encoding="utf-8") as f:
            f.write(mw.lbl_fit_eq.text() + "\n")
        _export_plot(mw.plot_widget, os.path.join(work, "tracking_plot.png"))

        params = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "note": note,
            "base_distance_mm": mw.schematic.base_distance,
            "servo_angle_deg": mw.hardware.get_servo_angle(),
            "servo_hardware_offset_deg": config.SERVO_HARDWARE_OFFSET,
            "camera_fov_deg": mw.camera_fov,
            "spot_x_px": mw.current_spot_x,
            "spot_y_px": mw.current_spot_y,
            "pid": {"kp": mw.pid_worker.kp, "ki": mw.pid_worker.ki, "kd": mw.pid_worker.kd,
                    "target_x": mw.pid_worker.target_x, "rate_hz": mw.pid_worker.update_hz},
            "fit": mw.active_fit_type,
        }
        with open(os.path.join(work, "parameters.json"), "w", encoding="utf-8") as f:
            json.dump(params, f, indent=2)

        zip_path = os.path.join(results_dir(), f"{PACKAGE_PREFIX}{stamp}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(os.listdir(work)):
                z.write(os.path.join(work, name), name)
        return zip_path
    finally:
        shutil.rmtree(work, ignore_errors=True)
