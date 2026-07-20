import sys
import io
import time
import math
import traceback
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

class ScriptRunner(QThread):
    log_signal = Signal(str)
    screen_signal = Signal(np.ndarray)
    servo_signal = Signal(float)
    spot_signal = Signal(float, float, float)
    finished_signal = Signal()
    
    def __init__(self, code_text, main_window):
        super().__init__()
        self.code_text = code_text
        self.main_window = main_window
        self.running = False
        
    def run(self):
        self.running = True
        
        import ast
        try:
            tree = ast.parse(self.code_text)
            has_sleep = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == 'time' and node.func.attr == 'sleep':
                        if node.args and isinstance(node.args[0], ast.Constant):
                            val = node.args[0].value
                            if isinstance(val, (int, float)) and val >= 0.01:
                                has_sleep = True
                                break
            if not has_sleep:
                self.log_signal.emit("\n[ERROR] Missing sleep! Script must include a time.sleep(x) call where x >= 0.01\n")
                self.running = False
                self.finished_signal.emit()
                return
        except SyntaxError as e:
            self.log_signal.emit(f"\n[ERROR] Syntax error (SyntaxError): {e}\n")
            self.running = False
            self.finished_signal.emit()
            return
        
        # Line-by-line trace function to forcefully terminate thread loops when self.running is False
        def trace_func(frame, event, arg):
            if not self.running:
                raise InterruptedError("Script stopped by user")
            return trace_func
            
        sys.settrace(trace_func)
        
        def capture_frame():
            return self.main_window.current_raw_frame
            
        def send_to_screen(*frames):
            if not frames:
                return
            if len(frames) == 1:
                frame = frames[0]
                if frame is not None:
                    self.screen_signal.emit(frame.copy())
            else:
                f1 = frames[0]
                f2 = frames[1]
                if f1 is None or f2 is None:
                    return
                # Handle shape matching
                if f1.shape[1] != f2.shape[1]:
                    w = f1.shape[1]
                    h = int(f2.shape[0] * (w / f2.shape[1]))
                    f2 = cv2.resize(f2, (w, h))
                # Convert grayscale to color if mismatch
                if len(f1.shape) == 2 and len(f2.shape) == 3:
                    f1 = cv2.cvtColor(f1, cv2.COLOR_GRAY2BGR)
                elif len(f1.shape) == 3 and len(f2.shape) == 2:
                    f2 = cv2.cvtColor(f2, cv2.COLOR_GRAY2BGR)
                # Create a 10px black spacer gap
                ch = f1.shape[2] if len(f1.shape) == 3 else 1
                if ch == 3:
                    gap = np.zeros((10, f1.shape[1], 3), dtype=np.uint8)
                else:
                    gap = np.zeros((10, f1.shape[1]), dtype=np.uint8)
                # Stack vertically with gap
                stacked = np.vstack((f1, gap, f2))
                self.screen_signal.emit(stacked)
                
        def set_servo_angle(angle):
            self.servo_signal.emit(float(angle))
            
        def get_servo_angle():
            return self.main_window.hardware.get_servo_angle()
            
        def set_detected_spot(x, y, intensity=255.0):
            self.spot_signal.emit(float(x), float(y), float(intensity))
            
        def send_location(x, y):
            self.spot_signal.emit(float(x), float(y), 255.0)
            
        def draw_cross_on_location(img, x, y, size=15, thickness=None):
            if img is None:
                return None
            out = img.copy()
            ix, iy = int(x), int(y)
            if thickness is None:
                thickness = max(2, int(size / 10))
            # Support color or grayscale drawing
            color = (0, 0, 255) if len(out.shape) == 3 else 255
            cv2.line(out, (ix, iy - size), (ix, iy + size), color, thickness)
            cv2.line(out, (ix - size, iy), (ix + size, iy), color, thickness)
            return out
            
        def find_spot_center(img):
            if img is None:
                return None
            if len(img.shape) == 3:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray = img.copy()
            _, max_val, _, max_loc = cv2.minMaxLoc(gray)
            if max_val > 10.0:
                return float(max_loc[0]), float(max_loc[1])
            return None
            
        def crop_frame(img, x, y, w, h):
            if img is None:
                return None
            x, y, w, h = int(x), int(y), int(w), int(h)
            height, width = img.shape[:2]
            x = max(0, min(x, width))
            y = max(0, min(y, height))
            w = max(0, min(w, width - x))
            h = max(0, min(h, height - y))
            if w <= 0 or h <= 0:
                return img.copy()
            return img[y:y+h, x:x+w].copy()
            
        class StdoutRedirector:
            def __init__(self, signal):
                self.signal = signal
            def write(self, string):
                if string:
                    self.signal.emit(string)
            def flush(self):
                pass
                
        sys.stdout = StdoutRedirector(self.log_signal)
        sys.stderr = StdoutRedirector(self.log_signal)
        
        # Custom time class that wraps the standard time module
        import time as standard_time
        class CustomTime:
            def __getattr__(c_self, name):
                return getattr(standard_time, name)
            def sleep(c_self, seconds):
                t_start = standard_time.time()
                while standard_time.time() - t_start < seconds:
                    if not self.running:
                        raise InterruptedError("Script stopped by user")
                    standard_time.sleep(0.01)
                    
        custom_time = CustomTime()
        
        # Intercept import time inside script
        import builtins
        original_import = builtins.__import__
        def custom_import(name, *args, **kwargs):
            if name == 'time':
                return custom_time
            return original_import(name, *args, **kwargs)
            
        global_vars = {
            'capture_frame': capture_frame,
            'send_to_screen': send_to_screen,
            'set_servo_angle': set_servo_angle,
            'get_servo_angle': get_servo_angle,
            'set_detected_spot': set_detected_spot,
            'send_location': send_location,
            'draw_cross_on_location': draw_cross_on_location,
            'find_spot_center': find_spot_center,
            'crop_frame': crop_frame,
            'cv2': cv2,
            'np': np,
            'time': custom_time,
            'math': math,
            'print': print,
            '__import__': custom_import,
        }
        
        try:
            exec(self.code_text, global_vars)
        except InterruptedError:
            self.log_signal.emit("\n[INFO] Script stopped by user.")
        except Exception as e:
            tb = traceback.format_exc()
            self.log_signal.emit(f"\n[ERROR] Script Exception:\n{tb}")
        finally:
            sys.settrace(None) # disable trace
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
            self.running = False
            self.finished_signal.emit()
            
    def stop(self):
        self.running = False
        # Wait up to 500ms for thread to exit cleanly
        if not self.wait(500):
            # Forcefully terminate if it's stuck in a tight loop
            self.terminate()
            self.wait()
