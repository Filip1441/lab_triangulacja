"""
Configuration file for the Triangulation Rangefinder Desktop App.
"""

# --- Mode Settings ---
# Set to True to run on a PC without physical hardware (mocks servo, ADC, and camera spot).
# Set to False to run on Raspberry Pi with physical pins.
SIMULATION_MODE = False

# --- UI & Application Settings ---
APP_NAME = "Triangulate App"
WINDOW_SIZE = (1280, 720) # 16:9 standard HD
FPS_TARGET = 30 # Target Frames Per Second for UI updates and camera

# --- Hardware Configuration (Used if SIMULATION_MODE = False) ---
SERVO_PIN = 18  # BCM pin number for Servo PWM
ADC_I2C_ADDRESS = 0x48
CAMERA_INDEX = 1  # Default USB camera index

# --- Calibration Defaults ---
# Default parameters for Analytical Modeling
DEFAULT_BASE_DISTANCE_MM = 200.0  # Distance between camera sensor and servo rotation axis
DEFAULT_FOCAL_LENGTH_MM = 3.6     # Camera lens focal length
DEFAULT_SENSOR_WIDTH_MM = 3.6     # Physical width of the camera sensor
DEFAULT_IMAGE_WIDTH_PX = 640      # Default capture width
DEFAULT_IMAGE_HEIGHT_PX = 360     # Default capture height
DEFAULT_OFFSET_ANGLE_DEG = 90.0   # Mechanical offset (e.g. angle when looking straight ahead)

# Camera configuration
DEFAULT_FOV_DEG = 30.0            # Horizontal Field of View in degrees for simulation and geometry matching

# Servo limits
SERVO_MIN_ANGLE = 0.0
SERVO_MAX_ANGLE = 180.0
SERVO_MIN_PULSE = 500  # microseconds
SERVO_MAX_PULSE = 2500 # microseconds

# PID Sweep Defaults
DEFAULT_SWEEP_ENABLED = True
DEFAULT_SWEEP_TIMEOUT_SEC = 10.0   # Time in seconds before sweep triggers when spot is lost
DEFAULT_SWEEP_DURATION_SEC = 4.5   # Duration in seconds for full 0 to 180 deg sweep
