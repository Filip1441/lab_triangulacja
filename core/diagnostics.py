"""
Hidden diagnostics: watches latency and hangs of the app and writes a rolling log, so a slowdown that appears
only after a long time can be examined afterwards.

- GUI lag: a 100 ms timer on the GUI thread measures how late it fires (event loop busy = lag).
- Hang watchdog: faulthandler dumps the stacks of ALL threads into hang.log when the GUI thread has not run for
  HANG_SECONDS, which shows where it is stuck.
- Every SAMPLE_SECONDS one line goes to diag.log: GUI lag, camera/script frame rates, drops, frame age,
  memory, threads, load, temperature, Pi throttling.
"""
import faulthandler
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
from collections import deque

from PySide6.QtCore import QObject, QTimer

TICK_MS = 100
SAMPLE_SECONDS = 5
HANG_SECONDS = 8
HISTORY = 120   # samples kept for the plot (10 min)
DIAG_DIR = os.path.join(os.path.expanduser("~"), "lab_diag")

COLUMNS = ["time", "gui_lag_avg_ms", "gui_lag_max_ms", "cam_fps", "cam_dropped", "frame_age_ms", "script_fps",
           "screen_shown", "screen_dropped", "rss_mb", "threads", "console_lines", "load1", "temp_c", "throttled",
           "stage", "script"]


def _rss_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return r / (1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0)
    except Exception:
        return 0.0


def _temp_c():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except OSError:
        return 0.0


class Diagnostics(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        os.makedirs(DIAG_DIR, exist_ok=True)
        self.log_path = os.path.join(DIAG_DIR, "diag.log")
        self.hang_path = os.path.join(DIAG_DIR, "hang.log")
        self.logger = logging.getLogger("lab.diag")
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            h = logging.handlers.RotatingFileHandler(self.log_path, maxBytes=1_000_000, backupCount=3)
            h.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(h)
            self.logger.info(";".join(COLUMNS))
        self._hang_file = open(self.hang_path, "a")

        self.history = deque(maxlen=HISTORY)   # dicts, newest last
        self.last = {}
        self._lags = []
        self._last_tick = time.monotonic()
        self._frame_ages = []
        self._shown = 0
        self._prev = {"cam": 0, "cam_drop": 0, "iters": 0, "sent": 0, "drops": 0, "runner": None}
        self._prev_t = time.monotonic()
        self._throttled = ""
        self._throttle_t = 0.0

        self.tick_timer = QTimer(self)
        self.tick_timer.setInterval(TICK_MS)
        self.tick_timer.timeout.connect(self._tick)
        self.sample_timer = QTimer(self)
        self.sample_timer.setInterval(SAMPLE_SECONDS * 1000)
        self.sample_timer.timeout.connect(self._sample)

    def start(self):
        self._last_tick = time.monotonic()
        self.tick_timer.start()
        self.sample_timer.start()
        self._arm_watchdog()

    def stop(self):
        self.tick_timer.stop()
        self.sample_timer.stop()
        faulthandler.cancel_dump_traceback_later()

    # ---------- hooks called by the app ----------
    def on_frame(self, age_s):
        """A camera frame reached the GUI; age = time since it was captured."""
        self._frame_ages.append(age_s * 1000.0)

    def on_screen_shown(self):
        self._shown += 1

    # ---------- GUI thread watchdog ----------
    def _arm_watchdog(self):
        faulthandler.dump_traceback_later(HANG_SECONDS, repeat=True, file=self._hang_file)

    def _tick(self):
        now = time.monotonic()
        self._lags.append(max(0.0, (now - self._last_tick) * 1000.0 - TICK_MS))
        self._last_tick = now
        self._arm_watchdog()   # re-arming restarts the countdown: it only fires if this tick stops running

    def dump_threads(self):
        """Writes the stacks of all threads into hang.log (manual trigger) and returns them as text."""
        lines = [f"--- manual dump {time.strftime('%Y-%m-%d %H:%M:%S')} ---"]
        names = {t.ident: t.name for t in threading.enumerate()}
        import traceback
        for tid, frame in sys._current_frames().items():
            lines.append(f"Thread {tid} ({names.get(tid, '?')}):")
            lines += [l.rstrip() for l in traceback.format_stack(frame)]
        text = "\n".join(lines)
        try:
            self._hang_file.write(text + "\n")
            self._hang_file.flush()
        except OSError:
            pass
        return text

    # ---------- sampling ----------
    def _throttle_state(self):
        """Pi power/thermal flags (vcgencmd), refreshed every 15 s; '' when unavailable."""
        if time.monotonic() - self._throttle_t > 15:
            self._throttle_t = time.monotonic()
            try:
                out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=1).stdout
                self._throttled = out.strip().split("=")[-1]
            except Exception:
                self._throttled = ""
        return self._throttled

    def _sample(self):
        mw = self.mw
        now = time.monotonic()
        dt = max(now - self._prev_t, 1e-3)
        self._prev_t = now
        cam = mw.camera_worker
        runner = mw.script_runner
        run_id = id(runner) if runner is not None else None
        iters = getattr(runner, "iterations", 0) if runner else 0
        sent = getattr(runner, "screen_sent", 0) if runner else 0
        drops = getattr(runner, "screen_drops", 0) if runner else 0
        if run_id != self._prev["runner"]:   # new script: counters start again
            self._prev.update(iters=0, sent=0, drops=0, runner=run_id)
        lags, ages = self._lags, self._frame_ages
        row = {
            "time": time.strftime("%H:%M:%S"),
            "gui_lag_avg_ms": sum(lags) / len(lags) if lags else 0.0,
            "gui_lag_max_ms": max(lags) if lags else 0.0,
            "cam_fps": (cam.frame_counter - self._prev["cam"]) / dt,
            "cam_dropped": cam.dropped_frames - self._prev["cam_drop"],
            "frame_age_ms": sum(ages) / len(ages) if ages else 0.0,
            "script_fps": (iters - self._prev["iters"]) / dt,
            "screen_shown": self._shown,
            "screen_dropped": drops - self._prev["drops"],
            "rss_mb": _rss_mb(),
            "threads": threading.active_count(),
            "console_lines": mw.txt_console.document().blockCount(),
            "load1": os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0,
            "temp_c": _temp_c(),
            "throttled": self._throttle_state(),
            "stage": mw.stack.currentIndex(),
            "script": int(bool(runner and runner.isRunning())),
        }
        self._prev.update(cam=cam.frame_counter, cam_drop=cam.dropped_frames, iters=iters, sent=sent, drops=drops)
        self._lags, self._frame_ages, self._shown = [], [], 0
        self.last = row
        self.history.append(row)
        self.logger.info(";".join(
            f"{row[c]:.1f}" if isinstance(row[c], float) else str(row[c]) for c in COLUMNS))
        if row["gui_lag_max_ms"] > 300:
            self.logger.info(f"# SPIKE: GUI blocked {row['gui_lag_max_ms']:.0f} ms (stage {row['stage']}, script {row['script']})")

    def summary(self):
        r = self.last
        if not r:
            return "No sample yet (first one after 5 s)."
        thr = r["throttled"]
        flags = ""
        if thr and thr != "0x0":
            flags = f"   POWER/THERMAL FLAGS {thr}"
        return (f"GUI lag avg {r['gui_lag_avg_ms']:.0f} ms, max {r['gui_lag_max_ms']:.0f} ms   |   "
                f"camera {r['cam_fps']:.1f} fps (dropped {r['cam_dropped']}), frame age {r['frame_age_ms']:.0f} ms\n"
                f"script {r['script_fps']:.1f} it/s, screen drops {r['screen_dropped']}   |   "
                f"memory {r['rss_mb']:.0f} MB, threads {r['threads']}, console lines {r['console_lines']}\n"
                f"load {r['load1']:.2f}, CPU {r['temp_c']:.0f} C{flags}")

    def tail(self, n=40):
        try:
            with open(self.log_path) as f:
                return "".join(f.readlines()[-n:])
        except OSError:
            return ""
