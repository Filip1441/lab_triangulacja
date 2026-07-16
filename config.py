"""
Configuration file for the Triangulation Rangefinder Desktop App.
"""

# --- Mode Settings ---
# Set to True to run on a PC without physical hardware (mocks servo, ADC, and camera spot).
# Set to False to run on Raspberry Pi with physical pins.
SIMULATION_MODE = False

# --- UI & Application Settings ---
APP_NAME = "Triangulate App"
WINDOW_SIZE = (1200, 800)
FPS_TARGET = 30 # Target Frames Per Second for UI updates and camera

# --- Hardware Configuration (Used if SIMULATION_MODE = False) ---
SERVO_PIN = 18  # BCM pin number for Servo PWM
ADC_I2C_ADDRESS = 0x48
CAMERA_INDEX = 0  # Default USB camera index

# --- Calibration Defaults ---
# Default parameters for Analytical Modeling
DEFAULT_BASE_DISTANCE_MM = 200.0  # Distance between camera sensor and servo rotation axis
DEFAULT_FOCAL_LENGTH_MM = 3.6     # Camera lens focal length
DEFAULT_SENSOR_WIDTH_MM = 3.6     # Physical width of the camera sensor
DEFAULT_IMAGE_WIDTH_PX = 640      # Default capture width
DEFAULT_IMAGE_HEIGHT_PX = 360     # Default capture height
DEFAULT_OFFSET_ANGLE_DEG = 90.0   # Mechanical offset (e.g. angle when looking straight ahead)

# Camera scaling
PIXELS_PER_MM = 5.0               # Pixels per mm for simulation and geometry matching

# Servo limits
SERVO_MIN_ANGLE = 0.0
SERVO_MAX_ANGLE = 180.0
SERVO_MIN_PULSE = 500  # microseconds
SERVO_MAX_PULSE = 2500 # microseconds
