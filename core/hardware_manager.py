import time
import logging
from PySide6.QtCore import QObject, Signal, QTimer

import config

logger = logging.getLogger(__name__)

class HardwareManager(QObject):
    """
    Hardware abstraction layer for Servo and ADC.
    If SIMULATION_MODE is True, it mocks hardware responses.
    """
    
    # Signal emitted when ADC values are read (useful for continuous polling)
    adc_updated = Signal(list)
    
    def __init__(self):
        super().__init__()
        self.simulation_mode = config.SIMULATION_MODE
        self.current_angle = 45.0
        self.target_angle = 45.0
        self.sim_pot_value = 0.0  # Simulated potentiometer (e.g. for distance)
        
        # We simulate the servo moving over time
        self.servo_sim_timer = QTimer(self)
        self.servo_sim_timer.timeout.connect(self._update_simulated_servo)
        
        if not self.simulation_mode:
            try:
                self._init_hardware()
            except ImportError as e:
                logger.error(f"Hardware imports failed: {e}. Falling back to Simulation Mode.")
                self.simulation_mode = True
            except Exception as e:
                logger.error(f"Hardware init failed: {e}. Falling back to Simulation Mode.")
                self.simulation_mode = True

        if self.simulation_mode:
            logger.info("HardwareManager started in Simulation Mode.")
            self.servo_sim_timer.start(50) # 20Hz update for smooth simulation

    def _init_hardware(self):
        # Local imports so we don't crash on PC without them
        import pigpio
        import board
        import busio
        import adafruit_ads1x15.ads1115 as ADS
        from adafruit_ads1x15.analog_in import AnalogIn

        # Initialize pigpio
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("pigpio daemon not running.")
        self.servo_pin = config.SERVO_PIN
        self.pi.set_mode(self.servo_pin, pigpio.OUTPUT)

        # Initialize I2C and ADC
        self.i2c = busio.I2C(board.SCL, board.SDA)
        self.ads = ADS.ADS1115(self.i2c, address=config.ADC_I2C_ADDRESS)
        # Setup channels
        self.chan0 = AnalogIn(self.ads, ADS.P0)
        self.chan1 = AnalogIn(self.ads, ADS.P1)
        self.chan2 = AnalogIn(self.ads, ADS.P2)
        
        # Ensure initial position
        self.set_servo_angle(self.current_angle)
        logger.info("Physical hardware initialized successfully.")

    def set_servo_angle(self, angle: float):
        """Sets the servo to a specific angle."""
        angle = max(config.SERVO_MIN_ANGLE, min(config.SERVO_MAX_ANGLE, angle))
        
        # Output print tag to standard output
        print(f"(SERVO_SET_POSITION) {angle:.2f}", flush=True)
        
        self.target_angle = angle
        
        if self.simulation_mode:
            pass # The timer will step towards target_angle
        else:
            pulse = config.SERVO_MIN_PULSE + (angle / config.SERVO_MAX_ANGLE) * (config.SERVO_MAX_PULSE - config.SERVO_MIN_PULSE)
            self.pi.set_servo_pulsewidth(self.servo_pin, pulse)
            self.current_angle = angle

    def get_servo_angle(self) -> float:
        """Returns the current angle of the servo."""
        return self.current_angle

    def read_adc(self) -> list:
        """Reads values from the ADC."""
        if self.simulation_mode:
            # Return simulated values. 
            # E.g., pot 1 controls something, pot 2 another
            vals = [self.sim_pot_value, 0.0, 0.0, 0.0]
            self.adc_updated.emit(vals)
            return vals
        else:
            try:
                vals = [self.chan0.voltage, self.chan1.voltage, self.chan2.voltage, 0.0]
                self.adc_updated.emit(vals)
                return vals
            except Exception as e:
                logger.error(f"Error reading ADC: {e}")
                return [0.0, 0.0, 0.0, 0.0]

    def _update_simulated_servo(self):
        """Simulates servo delay and movement."""
        if self.simulation_mode:
            # Step towards target angle
            diff = self.target_angle - self.current_angle
            if abs(diff) > 0.5:
                # Move 5 degrees per update (simulated speed)
                step = 2.0 if diff > 0 else -2.0
                if abs(diff) < 2.0:
                    step = diff
                self.current_angle += step
            else:
                self.current_angle = self.target_angle

    def cleanup(self):
        """Clean up hardware resources."""
        if not self.simulation_mode:
            try:
                self.pi.set_servo_pulsewidth(self.servo_pin, 0)
                self.pi.stop()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
