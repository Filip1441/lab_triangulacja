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
DEFAULT_BASE_DISTANCE_MM = 30.0   # Distance between camera sensor and servo rotation axis (default 30mm)
DEFAULT_FOCAL_LENGTH_MM = 3.6     # Camera lens focal length
DEFAULT_SENSOR_WIDTH_MM = 3.6     # Physical width of the camera sensor
DEFAULT_IMAGE_WIDTH_PX = 640      # Default capture width
DEFAULT_IMAGE_HEIGHT_PX = 360     # Default capture height
DEFAULT_OFFSET_ANGLE_DEG = 90.0   # Mechanical offset (e.g. angle when looking straight ahead)

# Camera configuration
DEFAULT_FOV_DEG = 30.0            # Horizontal Field of View in degrees for simulation and geometry matching
DEFAULT_EXPOSURE_MS = 10.0        # Default camera exposure time in milliseconds (10.0 ms)

# Servo limits & base position (wire safety protections)
DEFAULT_SERVO_BASE_ANGLE = 80.0   # Calibrated base/zero position (servo starts here)
SERVO_MIN_ANGLE = 30.0            # Hard safety lower limit (prevents wire twisting)
SERVO_MAX_ANGLE = 130.0           # Hard safety upper limit (prevents wire twisting)
SERVO_MIN_PULSE = 500             # microseconds (legacy pigpio)
SERVO_MAX_PULSE = 2500            # microseconds (legacy pigpio)

# PID Settings & Sweep Protection
PID_UPDATE_RATE_HZ = 15           # Update frequency in Hz (15 Hz is smooth and saves Raspberry Pi CPU)
DEFAULT_SWEEP_ENABLED = False     # Disabled by default so servo won't unexpectedly jerk when spot is lost
DEFAULT_SWEEP_TIMEOUT_SEC = 5.0   # Time in seconds before sweep triggers when spot is lost
DEFAULT_SWEEP_DURATION_SEC = 3.0  # Duration in seconds for sweep
DEFAULT_SWEEP_RANGE_DEG = 25.0    # Safe sweep window around base angle (+/- degrees)
