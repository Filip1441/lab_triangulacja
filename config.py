"""
Configuration file for the Triangulation Rangefinder Desktop App.
"""

# --- Mode Settings ---
# Set to True to run on a PC without physical hardware (mocks servo, ADC, and camera spot).
# Set to False to run on Raspberry Pi with physical pins.
SIMULATION_MODE = False

# --- UI & Application Settings ---
APP_NAME = "Triangulate App"
WINDOW_SIZE = (1280, 660) # Fits comfortably on 1280x720 desktop with taskbar
FPS_TARGET = 30 # Target Frames Per Second for UI updates and camera

# --- Hardware Configuration (Used if SIMULATION_MODE = False) ---
SERVO_PIN = 18  # BCM pin number for Servo PWM
ADC_I2C_ADDRESS = 0x48
CAMERA_INDEX = 1  # Default USB camera index

# --- Calibration Defaults ---
# Default parameters for Analytical Modeling
DEFAULT_BASE_DISTANCE_MM = 70.0   # Calibrated distance between camera sensor and servo rotation axis (70mm)
DEFAULT_FOCAL_LENGTH_MM = 3.6     # Camera lens focal length
DEFAULT_SENSOR_WIDTH_MM = 3.6     # Physical width of the camera sensor
DEFAULT_IMAGE_WIDTH_PX = 640      # Default capture width
DEFAULT_IMAGE_HEIGHT_PX = 360     # Default capture height
DEFAULT_OFFSET_ANGLE_DEG = 90.0   # Reference angle: 90.0 deg is parallel to camera optical axis

# Camera configuration
DEFAULT_FOV_DEG = 5.97            # Horizontal FOV in degrees (measured: telephoto lens, ~6130 px focal length on 640 px frame)
DEFAULT_EXPOSURE_MS = 10.0        # Default camera exposure time in milliseconds (10.0 ms)

# Servo calibration & limits (wire safety protections)
# In GUI and mathematical model, 90.0 deg represents the beam being parallel to camera optical axis.
# Measured on this rig (laser right of camera, wall 1020 mm): spot centered at physical 77.53 deg,
# so parallel is at 81.46 deg and hardware offset is -8.54 deg.
# Re-measure with the auto-calibration in the hidden settings dialog (Cmd+, / Ctrl+,).
DEFAULT_SERVO_BASE_ANGLE = 90.0   # Calibrated base angle in GUI (90.0 deg = parallel to camera optical axis)
SERVO_HARDWARE_OFFSET = -8.54     # Offset added to logical angle: physical_angle = logical_angle + offset
SERVO_MIN_LOGICAL_ANGLE = 40.0    # Lower logical limit in UI (maps to physical ~31.5 deg)
SERVO_MAX_LOGICAL_ANGLE = 135.0   # Upper logical limit in UI (maps to physical ~126.5 deg)
SERVO_MIN_ANGLE = 30.0            # Hard safety physical lower limit (prevents wire twisting)
SERVO_MAX_ANGLE = 130.0           # Hard safety physical upper limit (prevents wire twisting)
SERVO_MIN_PULSE = 500             # microseconds (legacy pigpio)
SERVO_MAX_PULSE = 2500            # microseconds (legacy pigpio)

# PID Settings & Sweep Protection
PID_UPDATE_RATE_HZ = 15           # Update frequency in Hz (15 Hz is smooth and saves Raspberry Pi CPU)
DEFAULT_SWEEP_ENABLED = False     # Disabled by default so servo won't unexpectedly jerk when spot is lost
DEFAULT_SWEEP_TIMEOUT_SEC = 5.0   # Time in seconds before sweep triggers when spot is lost
DEFAULT_SWEEP_DURATION_SEC = 3.0  # Duration in seconds for sweep
DEFAULT_SWEEP_RANGE_DEG = 25.0    # Safe sweep window around base angle (+/- degrees)

# --- Auto-calibration ---
DEFAULT_WALL_DISTANCE_MM = 1020.0  # Wall distance measured from the lens main plane, used by auto-calibration

# Station-specific calibration (written by the hidden settings dialog, not tracked by git)
import json as _json
import os as _os

CALIBRATION_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "calibration.json")


def _load_calibration():
    global SERVO_HARDWARE_OFFSET, DEFAULT_FOV_DEG
    try:
        with open(CALIBRATION_FILE, "r") as f:
            data = _json.load(f)
        SERVO_HARDWARE_OFFSET = float(data.get("servo_hardware_offset", SERVO_HARDWARE_OFFSET))
        DEFAULT_FOV_DEG = float(data.get("camera_fov_deg", DEFAULT_FOV_DEG))
    except (OSError, ValueError):
        pass


def save_calibration(servo_hardware_offset: float, camera_fov_deg: float):
    """Applies calibration to the running app and persists it to calibration.json."""
    global SERVO_HARDWARE_OFFSET, DEFAULT_FOV_DEG
    SERVO_HARDWARE_OFFSET = float(servo_hardware_offset)
    DEFAULT_FOV_DEG = float(camera_fov_deg)
    with open(CALIBRATION_FILE, "w") as f:
        _json.dump({"servo_hardware_offset": SERVO_HARDWARE_OFFSET, "camera_fov_deg": DEFAULT_FOV_DEG}, f, indent=2)


def reset_calibration():
    """Removes the saved calibration; defaults apply again after restart."""
    try:
        _os.remove(CALIBRATION_FILE)
    except OSError:
        pass


_load_calibration()
