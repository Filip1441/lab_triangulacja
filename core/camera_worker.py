import cv2
import numpy as np
import time
import logging
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
import math

import config

logger = logging.getLogger(__name__)

class CameraWorker(QThread):
    """
    Background thread for grabbing frames from the camera (Picamera2 CSI or OpenCV USB) or generating simulated frames.
    Emits raw frames as numpy arrays (BGR format).
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
        self.picam2 = None
        self.use_picam2 = False
        
        self._target_distance = 200.0  # Simulated target distance in mm
        self._base_distance = config.DEFAULT_BASE_DISTANCE_MM
        self.paused = False
        self.camera_fov = config.DEFAULT_FOV_DEG

    def set_mode(self, mode: str, path: str = None):
        """Request camera input mode change safely."""
        self.requested_mode = mode
        self.requested_path = path

    def set_simulated_target_distance(self, distance: float):
        """Updates the virtual distance used to calculate simulated spot position."""
        self._target_distance = distance

    def set_base_distance(self, base_distance: float):
        self._base_distance = base_distance

    def set_camera_fov(self, fov: float):
        self.camera_fov = fov

    def set_paused(self, paused: bool):
        self.paused = paused

    def set_exposure_ms(self, val_ms: float):
        """Sets camera exposure time in milliseconds (e.g. 2.0 = 2ms)."""
        self._exposure_ms = float(val_ms)
        shutter_us = max(100, int(val_ms * 1000.0))
        if self.use_picam2 and self.picam2 is not None:
            try:
                self.picam2.set_controls({"AeEnable": False, "ExposureTime": shutter_us})
                logger.info(f"Picamera2 ExposureTime set to {shutter_us} us ({val_ms} ms)")
            except Exception as e:
                logger.warning(f"Failed to set Picamera2 exposure time: {e}")
        elif self.capture is not None and self.capture.isOpened():
            try:
                self.capture.set(cv2.CAP_PROP_EXPOSURE, float(val_ms))
                logger.info(f"OpenCV CAP_PROP_EXPOSURE set to {val_ms} ms")
            except Exception as e:
                logger.warning(f"Failed to set OpenCV exposure time: {e}")

    def set_exposure_ev(self, val_ev: float):
        """Sets camera exposure compensation in EV units (e.g. -5.0, -2.0, 0.0)."""
        self._exposure_ev = float(val_ev)
        if self.use_picam2 and self.picam2 is not None:
            try:
                self.picam2.set_controls({"AeEnable": True, "ExposureValue": float(val_ev)})
                logger.info(f"Picamera2 ExposureValue set to {val_ev} EV")
            except Exception as e:
                logger.warning(f"Failed to set Picamera2 exposure EV: {e}")
        elif self.capture is not None and self.capture.isOpened():
            try:
                self.capture.set(cv2.CAP_PROP_EXPOSURE, float(val_ev))
                logger.info(f"OpenCV CAP_PROP_EXPOSURE set to {val_ev} EV")
            except Exception as e:
                logger.warning(f"Failed to set OpenCV exposure EV: {e}")

    def set_exposure(self, val: float):
        """Sets exposure. If val <= 0, treats as EV compensation; if val > 0, treats as exposure time in ms."""
        if val <= 0:
            self.set_exposure_ev(val)
        else:
            self.set_exposure_ms(val)

    def _init_live_camera(self):
        """Initialize live camera: try Picamera2 (CSI ribbon) first, fallback to OpenCV cv2.VideoCapture."""
        self._release_live_camera()
        
        # 1. Try Picamera2 for Raspberry Pi CSI ribbon camera
        try:
            import os
            from picamera2 import Picamera2
            
            # Check for NoIR tuning profiles to eliminate pink/magenta tint on infrared-sensitive sensors
            tuning_path = None
            noir_candidates = [
                "/usr/share/libcamera/ipa/rpi/vc4/ov5647_noir.json",
                "/usr/share/libcamera/ipa/rpi/pisp/ov5647_noir.json",
                "/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json",
                "/usr/share/libcamera/ipa/rpi/vc4/imx708_noir.json",
            ]
            for candidate in noir_candidates:
                if os.path.exists(candidate):
                    tuning_path = candidate
                    break

            if tuning_path:
                logger.info(f"Initializing Picamera2 with NoIR color tuning profile: {tuning_path}")
                picam2 = Picamera2(tuning=tuning_path)
            else:
                picam2 = Picamera2()

            cam_config = picam2.create_preview_configuration(
                main={
                    "size": (config.DEFAULT_IMAGE_WIDTH_PX, config.DEFAULT_IMAGE_HEIGHT_PX),
                    "format": "BGR888"
                }
            )
            picam2.configure(cam_config)
            picam2.start()
            
            # Enable continuous Auto Exposure and Auto White Balance
            try:
                picam2.set_controls({"AeEnable": True, "AwbEnable": True})
            except Exception:
                pass
                
            self.picam2 = picam2
            self.use_picam2 = True
            logger.info("Live camera initialized via Picamera2 (CSI Ribbon Camera).")
            return
        except Exception as e:
            logger.info(f"Picamera2 not available or no CSI camera ({e}). Trying OpenCV VideoCapture...")
            self.picam2 = None
            self.use_picam2 = False

        # 2. Fallback to cv2.VideoCapture (USB Camera or PC webcam)
        try:
            self.capture = cv2.VideoCapture(config.CAMERA_INDEX)
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.DEFAULT_IMAGE_WIDTH_PX)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.DEFAULT_IMAGE_HEIGHT_PX)
            if self.capture.isOpened():
                logger.info(f"Live camera initialized via OpenCV VideoCapture (index={config.CAMERA_INDEX}).")
            else:
                logger.warning(f"OpenCV VideoCapture failed to open index {config.CAMERA_INDEX}.")
        except Exception as e:
            logger.error(f"Error initializing OpenCV VideoCapture: {e}")

    def _release_live_camera(self):
        """Safely release Picamera2 and OpenCV capture objects."""
        if self.picam2 is not None:
            try:
                self.picam2.stop()
                self.picam2.close()
            except Exception as e:
                logger.warning(f"Error closing Picamera2: {e}")
            self.picam2 = None
            self.use_picam2 = False

        if self.capture is not None:
            try:
                self.capture.release()
            except Exception as e:
                logger.warning(f"Error releasing cv2.VideoCapture: {e}")
            self.capture = None

    def run(self):
        self.running = True
        
        if self.input_mode == "Live":
            self._init_live_camera()

        # Preload static image if in static mode
        static_frame = None
        if self.input_mode == "Static" and self.static_image_path:
            static_frame = cv2.imread(self.static_image_path)

        while self.running:
            start_time = time.time()
            
            # Safe Mode Switching
            if self.requested_mode != self.input_mode:
                self._release_live_camera()
                
                self.input_mode = self.requested_mode
                self.static_image_path = self.requested_path
                
                if self.input_mode == "Live":
                    self._init_live_camera()
                elif self.input_mode == "Static" and self.static_image_path:
                    static_frame = cv2.imread(self.static_image_path)

            if not self.paused:
                frame = None
                if self.input_mode == "Live":
                    if self.use_picam2 and self.picam2 is not None:
                        try:
                            raw = self.picam2.capture_array()
                            if raw is not None:
                                # Picamera2 returns RGB888. Convert to BGR for OpenCV processing and UI
                                frame = cv2.cvtColor(raw, cv2.COLOR_RGB2BGR)
                            else:
                                frame = None
                        except Exception as e:
                            logger.error(f"Picamera2 capture error: {e}")
                            frame = None
                    elif self.capture is not None and self.capture.isOpened():
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
            
        self._release_live_camera()

    def _generate_simulated_frame(self) -> np.ndarray:
        """Generates a synthetic dark frame with a laser spot using a perspective camera model."""
        height = config.DEFAULT_IMAGE_HEIGHT_PX
        width = config.DEFAULT_IMAGE_WIDTH_PX
        
        # Create a dark noisy background
        frame = np.random.randint(0, 30, (height, width, 3), dtype=np.uint8)
        
        # Get servo angle
        angle_deg = self.hardware_manager.get_servo_angle()
        
        # Calculate simulated spot position
        # Object moves along Z axis. Laser is at X = base_distance. 
        # Camera is at X = 0.
        rad = math.radians(angle_deg)
        if math.sin(rad) != 0 and math.cos(rad) != 0:
            x_hit_mm = self._base_distance - (self._target_distance / math.tan(rad))
        else:
            x_hit_mm = self._base_distance
            
        center_x = width // 2
        center_y = height // 2
        
        # Perspective Projection mapping using camera FOV:
        # tan(theta) = X_hit / Z
        # x_pixel = center_x + center_x * (tan(theta) / tan(FOV / 2))
        fov_rad = math.radians(self.camera_fov)
        
        if self._target_distance > 0.001:
            tan_theta = x_hit_mm / self._target_distance
            # Limit maximum deflection to avoid math/float overflow issues at extreme angles
            max_tan_deflection = math.tan(fov_rad / 2.0) * 1.5
            tan_theta = max(-max_tan_deflection, min(max_tan_deflection, tan_theta))
            
            spot_x = int(center_x + center_x * (tan_theta / math.tan(fov_rad / 2.0)))
        else:
            spot_x = center_x
            
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
