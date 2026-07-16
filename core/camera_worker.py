import cv2
import numpy as np
import time
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
import math

import config

class CameraWorker(QThread):
    """
    Background thread for grabbing frames from the camera or generating simulated frames.
    Emits raw frames as numpy arrays.
    """
    # Emits raw frame
    frame_ready = Signal(np.ndarray)
    
    def __init__(self, hardware_manager):
        super().__init__()
        self.hardware_manager = hardware_manager
        self.running = False
        
        # Input modes: "Live", "Static", "Simulation"
        self.input_mode = "Simulation" if config.SIMULATION_MODE else "Live"
        self.requested_mode = self.input_mode
        self.requested_path = None
        self.static_image_path = None
        
        self.capture = None
        self._target_distance = 200.0  # Simulated target distance in mm
        self._base_distance = config.DEFAULT_BASE_DISTANCE_MM
        self.paused = False

    def set_mode(self, mode: str, path: str = None):
        """Request camera input mode change safely."""
        self.requested_mode = mode
        self.requested_path = path

    def set_simulated_target_distance(self, distance: float):
        """Updates the virtual distance used to calculate simulated spot position."""
        self._target_distance = distance

    def set_base_distance(self, base_distance: float):
        self._base_distance = base_distance

    def set_paused(self, paused: bool):
        self.paused = paused

    def run(self):
        self.running = True
        
        if self.input_mode == "Live" and self.capture is None:
            self.capture = cv2.VideoCapture(config.CAMERA_INDEX)

        # Preload static image if in static mode
        static_frame = None
        if self.input_mode == "Static" and self.static_image_path:
            static_frame = cv2.imread(self.static_image_path)
            if static_frame is None:
                # fallback blank
                static_frame = np.zeros((config.DEFAULT_IMAGE_HEIGHT_PX, config.DEFAULT_IMAGE_WIDTH_PX, 3), dtype=np.uint8)

        while self.running:
            # Check for mode change
            if self.requested_mode != self.input_mode:
                if self.capture is not None:
                    self.capture.release()
                    self.capture = None
                
                self.input_mode = self.requested_mode
                self.static_image_path = self.requested_path
                
                if self.input_mode == "Live":
                    self.capture = cv2.VideoCapture(config.CAMERA_INDEX)
                    self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.DEFAULT_IMAGE_WIDTH_PX)
                    self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.DEFAULT_IMAGE_HEIGHT_PX)
                elif self.input_mode == "Static" and self.static_image_path:
                    static_frame = cv2.imread(self.static_image_path)
                    if static_frame is None:
                        static_frame = np.zeros((config.DEFAULT_IMAGE_HEIGHT_PX, config.DEFAULT_IMAGE_WIDTH_PX, 3), dtype=np.uint8)

            start_time = time.time()
            frame = None

            if not self.paused:
                if self.input_mode == "Live":
                    if self.capture and self.capture.isOpened():
                        ret, frame = self.capture.read()
                        if not ret:
                            frame = None
                elif self.input_mode == "Static":
                    if static_frame is not None:
                        frame = static_frame.copy()
                elif self.input_mode == "Simulation":
                    frame = self._generate_simulated_frame()

                if frame is not None:
                    self.frame_ready.emit(frame)

            # Sleep to match target FPS
            elapsed = time.time() - start_time
            sleep_time = max(1.0 / config.FPS_TARGET - elapsed, 0)
            time.sleep(sleep_time)
            
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def _generate_simulated_frame(self) -> np.ndarray:
        """Generates a synthetic dark frame with a laser spot."""
        height = config.DEFAULT_IMAGE_HEIGHT_PX
        width = config.DEFAULT_IMAGE_WIDTH_PX
        
        # Create a dark noisy background
        frame = np.random.randint(0, 30, (height, width, 3), dtype=np.uint8)
        
        # Get servo angle
        angle_deg = self.hardware_manager.get_servo_angle()
        
        # Calculate simulated spot position
        # Object moves along Z axis. Laser is at X = base_distance. 
        # Camera is at X = 0.
        # tan(90 - alpha) = (X_hit - base_distance) / Z
        
        # We need the X coordinate of the hit point.
        # X_hit = base_distance - Z * tan(90 - alpha)
        # However, angle_deg here is given relative to the baseline.
        # Let's assume angle_deg is relative to the baseline between camera and laser.
        # So alpha is the angle. tan(alpha) = Z / (base_distance - X_hit)
        # X_hit = base_distance - Z / tan(alpha)
        
        rad = math.radians(angle_deg)
        if math.sin(rad) != 0:
            x_hit_mm = self._base_distance - (self._target_distance / math.tan(rad))
        else:
            x_hit_mm = self._base_distance
            
        center_x = width // 2
        center_y = height // 2
        
        # Convert physical X hit (mm) to camera sensor pixels
        pixels_per_mm = config.PIXELS_PER_MM
        
        spot_x = int(center_x + x_hit_mm * pixels_per_mm)
        spot_y = center_y # Keep Y constant
        
        # Add some jitter
        spot_x += np.random.randint(-2, 3)
        spot_y += np.random.randint(-2, 3)
        
        # Draw spot if within bounds
        if 0 <= spot_x < width and 0 <= spot_y < height:
            # Draw a bright green spot with a halo
            cv2.circle(frame, (spot_x, spot_y), 8, (0, 100, 0), -1) # Dark green halo
            cv2.circle(frame, (spot_x, spot_y), 4, (100, 255, 100), -1) # Bright green center
            cv2.circle(frame, (spot_x, spot_y), 1, (255, 255, 255), -1) # White hot core
            
        return frame

    def stop(self):
        self.running = False
        self.wait()
