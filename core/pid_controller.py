import time
from collections import deque
import numpy as np
from PySide6.QtCore import QThread, Signal
import config

class PIDControllerWorker(QThread):
    """
    Background thread that calculates PID output and adjusts the servo to keep the spot on target.
    """
    # Emits (actual_x, target_x, error, new_angle) for plotting/UI updates
    pid_updated = Signal(float, float, float, float)

    def __init__(self, hardware_manager):
        super().__init__()
        self.hardware_manager = hardware_manager
        self.running = False
        
        self.kp = 0.01
        self.ki = 0.0
        self.kd = 0.0
        
        self.target_x = 320.0
        self.current_x = 320.0 # Updated from main thread via method
        
        self.integral = 0.0
        self.prev_error = 0.0
        self.last_time = time.time()
        
        self.spot_lost = False
        self.error_history = deque(maxlen=500)
        self.spot_lost_frames = 0
        self.sweep_mode = False
        self.sweep_dir = 1.0
        self.stable_frames = 0
        self.current_intensity = 0.0
        self.sweep_data = []
        self.sweep_angle = 0.0
        
        # Sweep configuration
        self.sweep_enabled = config.DEFAULT_SWEEP_ENABLED
        self.sweep_timeout_sec = config.DEFAULT_SWEEP_TIMEOUT_SEC
        self.sweep_duration_sec = config.DEFAULT_SWEEP_DURATION_SEC
        
    def set_gains(self, kp: float, ki: float, kd: float):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        
    def set_target(self, target_x: float):
        self.target_x = target_x

    def set_sweep_enabled(self, enabled: bool):
        self.sweep_enabled = enabled
        if not enabled:
            self.sweep_mode = False
            self._sweep_initialized = False
            self.spot_lost_frames = 0
            self.error_history.clear()

    def set_sweep_timeout(self, timeout_sec: float):
        self.sweep_timeout_sec = max(0.5, float(timeout_sec))

    def set_sweep_duration(self, duration_sec: float):
        self.sweep_duration_sec = max(0.5, float(duration_sec))
        
    def update_current_x(self, x: float, intensity: float = 0.0):
        """Called by the image processor signal slot to update the actual position and intensity."""
        self.current_x = x
        self.current_intensity = intensity
        self.spot_lost = False

    def set_spot_lost(self, lost: bool):
        self.spot_lost = lost

    def run(self):
        self.running = True
        self.integral = 0.0
        self.prev_error = 0.0
        self.last_time = time.time()
        self._sweep_initialized = False
        self.sweep_mode = False
        self.spot_lost_frames = 0
        self.error_history.clear()
        
        while self.running:
            current_time = time.time()
            dt = current_time - self.last_time
            if dt <= 0.0:
                dt = 0.001
            
            # Calculate Error
            error = self.target_x - self.current_x
            
            if self.spot_lost:
                self.spot_lost_frames += 1
            else:
                self.spot_lost_frames = 0
                
            self.error_history.append(error)
            
            # Check for Sweep triggers
            if self.sweep_enabled and not self.sweep_mode:
                timeout_frames = int(self.sweep_timeout_sec / 0.02)
                trigger_sweep = False
                if self.spot_lost_frames > timeout_frames:
                    trigger_sweep = True
                elif len(self.error_history) >= timeout_frames and np.std(self.error_history) > 100.0:
                    trigger_sweep = True
                    
                if trigger_sweep:
                    self.sweep_mode = True
                    self._sweep_initialized = False
                    self.error_history.clear()
                    self.integral = 0.0
            
            current_angle = self.hardware_manager.get_servo_angle()
            
            if self.sweep_mode:
                if not self._sweep_initialized:
                    self._sweep_initialized = True
                    self.sweep_angle = 0.0
                    self.sweep_data = []
                    self.hardware_manager.set_servo_angle(0.0)
                    for _ in range(10):
                        if not self.running or not self.sweep_mode:
                            break
                        time.sleep(0.02)
                    
                # Calculate angle increment per 0.02s loop iteration for requested duration
                step_increment = 3.6 / max(0.5, self.sweep_duration_sec)
                self.sweep_angle += step_increment
                
                if self.sweep_angle <= 180.0:
                    self.hardware_manager.set_servo_angle(self.sweep_angle)
                    intensity = self.current_intensity if not self.spot_lost else 0.0
                    self.sweep_data.append((self.sweep_angle, intensity))
                    new_angle = self.sweep_angle
                else:
                    if self.sweep_data:
                        best_angle, max_int = max(self.sweep_data, key=lambda x: x[1])
                        if max_int > 5.0:
                            self.hardware_manager.set_servo_angle(best_angle)
                            new_angle = best_angle
                        else:
                            self.hardware_manager.set_servo_angle(90.0)
                            new_angle = 90.0
                    else:
                        new_angle = 90.0
                        
                    self.sweep_mode = False
                    self._sweep_initialized = False
                    self.error_history.clear()
                    self.spot_lost_frames = 0
                    self.stable_frames = 0
            else:
                # Proportional
                p_term = self.kp * error
                
                # Integral
                self.integral += error * dt
                # Anti-windup
                self.integral = max(-500.0, min(500.0, self.integral))
                i_term = self.ki * self.integral
                
                # Derivative
                derivative = (error - self.prev_error) / dt
                d_term = self.kd * derivative
                
                output = p_term + i_term + d_term
                
                # Clamp step
                output = max(-1.0, min(1.0, output))
                new_angle = current_angle + output
                self.hardware_manager.set_servo_angle(new_angle)

            self.pid_updated.emit(self.current_x, self.target_x, error, new_angle)
            
            self.prev_error = error
            self.last_time = current_time
            
            # Run at approx 50 Hz
            time.sleep(0.02)
            
    def stop(self):
        self.running = False
        self.sweep_mode = False
        self._sweep_initialized = False
        self.spot_lost_frames = 0
        self.error_history.clear()
        self.wait()
