import time
from collections import deque
import numpy as np
from PySide6.QtCore import QThread, Signal
import config

class PIDControllerWorker(QThread):
    """
    Smooth, jitter-free background thread that calculates PID output
    and adjusts the servo to keep the laser spot centered on target.
    Includes low-pass filtering, derivative-on-measurement, deadbands,
    and a slew rate limiter to prevent oscillation or jerky jumps.
    """
    # Emits (actual_x, target_x, error, new_angle) for plotting/UI updates
    pid_updated = Signal(float, float, float, float)

    def __init__(self, hardware_manager):
        super().__init__()
        self.hardware_manager = hardware_manager
        self.running = False
        
        # Default tuning gains (empirically optimized for 15 Hz tracking)
        self.kp = 0.0015
        self.ki = 0.0001
        self.kd = 0.0001
        
        self.target_x = 320.0
        self.current_x = 320.0
        self.filtered_x = -1.0
        self.prev_x = -1.0
        self.last_spot_time = 0.0
        self.last_sent_angle = -1.0
        
        self.integral = 0.0
        self.prev_error = 0.0
        self.last_time = time.time()
        
        self.spot_lost = False
        self.spot_lost_frames = 0
        self.current_intensity = 0.0
        
        # Sweep configuration
        self.sweep_enabled = getattr(config, 'DEFAULT_SWEEP_ENABLED', False)
        self.sweep_timeout_sec = getattr(config, 'DEFAULT_SWEEP_TIMEOUT_SEC', 5.0)
        self.sweep_duration_sec = getattr(config, 'DEFAULT_SWEEP_DURATION_SEC', 3.0)
        self.sweep_mode = False
        self._sweep_initialized = False
        self.sweep_data = []
        self.update_hz = getattr(config, 'PID_UPDATE_RATE_HZ', 15)
        self.loop_dt = 1.0 / max(1, self.update_hz)
        self.error_history = deque(maxlen=300)

    def set_rate_hz(self, hz: float):
        """Dynamically adjusts PID loop frequency in Hz. Responds immediately."""
        self.update_hz = max(1.0, min(100.0, float(hz)))
        self.loop_dt = 1.0 / self.update_hz

    def set_gains(self, kp: float, ki: float, kd: float):
        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)
        
    def set_target(self, target_x: float):
        self.target_x = float(target_x)

    def set_sweep_enabled(self, enabled: bool):
        self.sweep_enabled = bool(enabled)
        if not enabled:
            self.sweep_mode = False
            self._sweep_initialized = False
            self.spot_lost_frames = 0

    def set_sweep_timeout(self, timeout_sec: float):
        self.sweep_timeout_sec = max(0.5, float(timeout_sec))

    def set_sweep_duration(self, duration_sec: float):
        self.sweep_duration_sec = max(0.5, float(duration_sec))
        
    def update_current_x(self, x: float, intensity: float = 0.0):
        """Called by the image processor signal slot to update spot position."""
        if x < 0.0 or intensity <= 0.0:
            self.spot_lost = True
            return

        self.last_spot_time = time.time()
        self.spot_lost = False
        self.current_intensity = intensity
        
        # Exponential moving average filter (alpha=0.7) to suppress subpixel noise
        if self.filtered_x < 0:
            self.filtered_x = x
        else:
            self.filtered_x = 0.70 * x + 0.30 * self.filtered_x
        self.current_x = self.filtered_x

    def set_spot_lost(self, lost: bool):
        self.spot_lost = bool(lost)

    def run(self):
        self.running = True
        self.integral = 0.0
        self.prev_error = 0.0
        self.last_time = time.time()
        self.last_sent_angle = self.hardware_manager.get_servo_angle()
        self.prev_x = self.current_x
        self.filtered_x = self.current_x
        self._sweep_initialized = False
        self.sweep_mode = False
        self.spot_lost_frames = 0
        self.error_history.clear()
        
        min_a = getattr(config, 'SERVO_MIN_LOGICAL_ANGLE', 40.0)
        max_a = getattr(config, 'SERVO_MAX_LOGICAL_ANGLE', 135.0)
        base_angle = getattr(config, 'DEFAULT_SERVO_BASE_ANGLE', 90.0)
        
        while self.running:
            loop_dt = getattr(self, 'loop_dt', 0.0667)
            current_time = time.time()
            dt = current_time - self.last_time
            if dt <= 0.0:
                dt = loop_dt
            
            # Watchdog: if no spot coordinate received in 0.35s, flag as lost
            if current_time - self.last_spot_time > 0.35:
                self.spot_lost = True
                
            current_angle = self.hardware_manager.get_servo_angle()
            new_angle = current_angle
            
            # --- Scenario 1: Spot is Lost ---
            if self.spot_lost:
                self.spot_lost_frames += 1
                self.integral = 0.0  # Reset integrator when spot is missing
                self.prev_x = self.current_x
                
                # Check for sweep triggers if explicitly enabled
                if self.sweep_enabled:
                    timeout_frames = int(self.sweep_timeout_sec / loop_dt)
                    if self.spot_lost_frames > timeout_frames and not self.sweep_mode:
                        self.sweep_mode = True
                        self._sweep_initialized = False
                
                if self.sweep_mode:
                    sweep_span = getattr(config, 'DEFAULT_SWEEP_RANGE_DEG', 25.0)
                    min_sweep = max(min_a, base_angle - sweep_span)
                    max_sweep = min(max_a, base_angle + sweep_span)
                    
                    if not self._sweep_initialized:
                        self._sweep_initialized = True
                        self.sweep_angle = min_sweep
                        self.sweep_data = []
                        self.hardware_manager.set_servo_angle(min_sweep)
                        self.last_sent_angle = min_sweep
                    else:
                        step_inc = ((max_sweep - min_sweep) / max(0.5, self.sweep_duration_sec)) * loop_dt
                        self.sweep_angle += step_inc
                        if self.sweep_angle <= max_sweep:
                            self.hardware_manager.set_servo_angle(self.sweep_angle)
                            self.last_sent_angle = self.sweep_angle
                            new_angle = self.sweep_angle
                        else:
                            self.hardware_manager.set_servo_angle(base_angle)
                            self.last_sent_angle = base_angle
                            new_angle = base_angle
                            self.sweep_mode = False
                            self._sweep_initialized = False
                            self.spot_lost_frames = 0
                else:
                    # Not sweeping: if lost for > 3.0 seconds, gently return to base angle
                    lost_limit_frames = int(3.0 / loop_dt)
                    if self.spot_lost_frames > lost_limit_frames:
                        if abs(current_angle - base_angle) > 0.2:
                            drift_step = 0.15 if base_angle > current_angle else -0.15
                            new_angle = current_angle + drift_step
                            self.hardware_manager.set_servo_angle(new_angle)
                            self.last_sent_angle = new_angle
                
                self.pid_updated.emit(-1.0, self.target_x, 0.0, new_angle)
                self.last_time = current_time
                time.sleep(loop_dt)
                continue
                
            # --- Scenario 2: Spot is Actively Tracked ---
            self.spot_lost_frames = 0
            self.sweep_mode = False
            self._sweep_initialized = False
            
            raw_error = self.target_x - self.current_x
            
            # Deadband: +/- 3.5 pixels deadband completely eliminates steady-state servo chatter
            if abs(raw_error) <= 3.5:
                error = 0.0
                step = 0.0
            else:
                error = raw_error
                
                # Proportional Term
                p_term = self.kp * error
                
                # Integral Term with Anti-Windup (only accumulates near target)
                if abs(error) < 60.0:
                    self.integral += error * dt
                    self.integral = max(-30.0, min(30.0, self.integral))
                else:
                    self.integral = 0.0
                i_term = self.ki * self.integral
                
                # Derivative on Measurement (opposes rapid velocity to prevent overshoot)
                if self.prev_x > 0.0:
                    derivative = -(self.current_x - self.prev_x) / dt
                else:
                    derivative = 0.0
                d_term = self.kd * derivative
                
                step = p_term + i_term + d_term
                
                # Slew Rate Limiter: clamp step to max 0.25 deg per tick (~3.75 deg/s max)
                max_step = 0.25
                step = max(-max_step, min(max_step, step))
                
                new_angle = max(min_a, min(max_a, current_angle + step))
                
                # Only send command to servo if change exceeds mechanical threshold (0.05 deg)
                if abs(new_angle - self.last_sent_angle) >= 0.05:
                    self.hardware_manager.set_servo_angle(new_angle)
                    self.last_sent_angle = new_angle
                    
            self.prev_x = self.current_x
            self.prev_error = error
            self.last_time = current_time
            self.pid_updated.emit(self.current_x, self.target_x, raw_error, new_angle)
            time.sleep(loop_dt)
            
        # Clean background exit: reset servo to base
        base = getattr(config, 'DEFAULT_SERVO_BASE_ANGLE', 90.0)
        self.hardware_manager.set_servo_angle(base)
            
    def stop(self):
        self.running = False
        self.sweep_mode = False
        self._sweep_initialized = False
        self.spot_lost_frames = 0
        self.error_history.clear()
        # Non-blocking stop: return immediately without freezing GUI thread!
        base = getattr(config, 'DEFAULT_SERVO_BASE_ANGLE', 90.0)
        self.hardware_manager.set_servo_angle(base)
