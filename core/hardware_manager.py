import time
import glob
import logging
import threading
from PySide6.QtCore import QObject, Signal, QTimer

import config

logger = logging.getLogger(__name__)


class ST3215ServoDriver:
    """
    Driver for Waveshare ST3215 Serial Bus Servo over UART (/dev/ttyACM* or /dev/ttyUSB*).
    12-bit magnetic encoder (0-4095 steps for 360 deg, ~11.378 steps/deg).
    Baudrate: 1,000,000 baud (1 Mbps). Thread-safe via internal mutex lock.
    """
    def __init__(self, port=None, baudrate=1000000, servo_id=1):
        self.servo_id = servo_id
        self.baudrate = baudrate
        self.ser = None
        self.port = port
        self._lock = threading.Lock()
        self._init_port()

    def _init_port(self):
        import serial
        candidates = []
        if self.port:
            candidates.append(self.port)
        candidates.extend(sorted(glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')))
        for p in candidates:
            try:
                s = serial.Serial(p, self.baudrate, timeout=0.05)
                time.sleep(0.05)
                if self._ping(s, self.servo_id):
                    self.ser = s
                    self.port = p
                    logger.info(f"ST3215 Servo ID {self.servo_id} detected on {p}!")
                    # Enable torque (Address 40 = 1)
                    self._write_reg(40, [1])
                    return
                s.close()
            except Exception as e:
                logger.debug(f"Failed to probe {p}: {e}")
        raise RuntimeError("No ST3215 servo detected on serial ports.")

    def _checksum(self, buf):
        return (~(sum(buf)) & 0xFF)

    def _ping(self, s, sid):
        cmd = [sid, 2, 0x01]
        pkt = bytearray([0xFF, 0xFF]) + bytearray(cmd) + bytearray([self._checksum(cmd)])
        s.reset_input_buffer()
        s.write(pkt)
        time.sleep(0.01)
        resp = s.read(6)
        return len(resp) >= 6 and resp[0] == 0xFF and resp[1] == 0xFF and resp[2] == sid

    def _write_reg(self, addr, data_bytes):
        if not self.ser or not getattr(self.ser, 'is_open', False):
            return
        with self._lock:
            try:
                cmd = [self.servo_id, len(data_bytes) + 3, 0x03, addr] + list(data_bytes)
                pkt = bytearray([0xFF, 0xFF]) + bytearray(cmd) + bytearray([self._checksum(cmd)])
                self.ser.reset_input_buffer()
                self.ser.write(pkt)
            except Exception as e:
                logger.debug(f"ST3215 write_reg failed: {e}")

    def _read_reg(self, addr, length):
        if not self.ser or not getattr(self.ser, 'is_open', False):
            return None
        with self._lock:
            try:
                cmd = [self.servo_id, 4, 0x02, addr, length]
                pkt = bytearray([0xFF, 0xFF]) + bytearray(cmd) + bytearray([self._checksum(cmd)])
                self.ser.reset_input_buffer()
                self.ser.write(pkt)
                
                # Read response with packet header search and checksum verification
                start_t = time.time()
                buf = bytearray()
                expected_len = 6 + length
                while time.time() - start_t < 0.03:
                    if self.ser.in_waiting:
                        buf.extend(self.ser.read(self.ser.in_waiting))
                        idx = 0
                        while idx <= len(buf) - expected_len:
                            if buf[idx] == 0xFF and buf[idx+1] == 0xFF and buf[idx+2] == self.servo_id:
                                pkt_len = buf[idx+3]
                                if pkt_len == length + 2 and idx + 4 + pkt_len <= len(buf):
                                    chk_calc = (~sum(buf[idx+2 : idx+3+pkt_len])) & 0xFF
                                    if buf[idx+3+pkt_len] == chk_calc:
                                        return bytes(buf[idx+5 : idx+5+length])
                            idx += 1
                    time.sleep(0.002)
            except Exception as e:
                logger.debug(f"ST3215 read_reg failed: {e}")
            return None

    def set_angle(self, angle_deg, speed=1200):
        """Sets servo angle in degrees, clamped to safe physical limits to prevent wire twisting."""
        min_a = getattr(config, 'SERVO_MIN_ANGLE', 30.0)
        max_a = getattr(config, 'SERVO_MAX_ANGLE', 130.0)
        angle_deg = max(min_a, min(max_a, angle_deg))
        target_steps = int((angle_deg / 360.0) * 4096.0)
        data = [
            target_steps & 0xFF, (target_steps >> 8) & 0xFF,
            0, 0,  # Time = 0
            speed & 0xFF, (speed >> 8) & 0xFF  # Speed
        ]
        self._write_reg(42, data)

    def get_angle(self):
        """Reads current angle in degrees directly from 12-bit magnetic encoder."""
        try:
            data = self._read_reg(56, 2)
            if data:
                steps = (data[0] | (data[1] << 8)) & 0x0FFF
                return (steps / 4096.0) * 360.0
        except Exception as e:
            logger.debug(f"ST3215 get_angle error: {e}")
        return None

    def close(self):
        if self.ser:
            with self._lock:
                try:
                    self.ser.close()
                except Exception:
                    pass


class HardwareManager(QObject):
    """
    Hardware abstraction layer supporting:
    1. Waveshare ST3215 Serial Bus Servo (via UART USB adapter)
    2. Legacy GPIO PWM Servo (pigpio)
    3. Simulation Mode fallback
    """
    
    adc_updated = Signal(list)
    
    def __init__(self):
        super().__init__()
        self.simulation_mode = config.SIMULATION_MODE
        self.use_st3215 = False
        self.st3215 = None
        self.use_pigpio = False
        base_angle = getattr(config, 'DEFAULT_SERVO_BASE_ANGLE', 80.0)
        self.current_angle = base_angle
        self.target_angle = base_angle
        self.sim_pot_value = 0.0
        
        # Simulation timer for mock movement
        self.servo_sim_timer = QTimer(self)
        self.servo_sim_timer.timeout.connect(self._update_simulated_servo)
        
        if not self.simulation_mode:
            self._init_hardware()

        if self.simulation_mode:
            logger.info("HardwareManager started in Simulation Mode.")
            self.servo_sim_timer.start(50)  # 20Hz update for smooth simulation

    def _init_hardware(self):
        # 1. Try Waveshare ST3215 Serial Bus Servo first
        try:
            logger.info("Probing for Waveshare ST3215 Serial Bus Servo...")
            self.st3215 = ST3215ServoDriver()
            self.use_st3215 = True
            logger.info("Waveshare ST3215 Serial Bus Servo initialized successfully!")
            
            # Read initial real position from magnetic encoder for diagnostic log
            enc_angle = self.st3215.get_angle()
            if enc_angle is not None:
                logger.info(f"Initial ST3215 raw encoder angle: {enc_angle:.2f} deg")
            
            # Immediately position servo at calibrated base position on startup!
            self.set_servo_angle(self.current_angle)
            logger.info(f"Servo set to initial base position: {self.current_angle:.2f} deg")
            return
        except Exception as e:
            logger.info(f"ST3215 not available ({e}). Trying pigpio PWM servo...")

        # 2. Try legacy pigpio PWM Servo
        try:
            import pigpio
            self.pi = pigpio.pi()
            if not self.pi.connected:
                raise RuntimeError("pigpio daemon not running.")
            self.servo_pin = config.SERVO_PIN
            self.pi.set_mode(self.servo_pin, pigpio.OUTPUT)
            self.use_pigpio = True
            self.set_servo_angle(self.current_angle)
            logger.info("GPIO PWM Servo initialized successfully.")
            return
        except Exception as e:
            logger.info(f"pigpio not available ({e}). Falling back to Simulation Mode.")
            self.simulation_mode = True

    def set_servo_angle(self, angle: float):
        """Sets the servo to a specific angle, strictly clamped to safe bounds to prevent wire twisting."""
        min_a = getattr(config, 'SERVO_MIN_ANGLE', 30.0)
        max_a = getattr(config, 'SERVO_MAX_ANGLE', 130.0)
        angle = max(min_a, min(max_a, angle))
        print(f"(SERVO_SET_POSITION) {angle:.2f}", flush=True)
        self.target_angle = angle
        self.current_angle = angle
        
        if self.use_st3215 and self.st3215:
            try:
                self.st3215.set_angle(angle)
            except Exception as e:
                logger.warning(f"set_servo_angle ST3215 error: {e}")
        elif self.use_pigpio:
            try:
                pulse = config.SERVO_MIN_PULSE + (angle / config.SERVO_MAX_ANGLE) * (config.SERVO_MAX_PULSE - config.SERVO_MIN_PULSE)
                self.pi.set_servo_pulsewidth(self.servo_pin, pulse)
            except Exception as e:
                logger.warning(f"set_servo_angle pigpio error: {e}")
        else:
            pass  # Handled by simulation timer

    def get_servo_angle(self) -> float:
        """Returns the current angle of the servo instantly from cache (non-blocking for UI & camera)."""
        return self.current_angle

    def get_physical_encoder_angle(self) -> float:
        """Explicitly reads the physical magnetic encoder over serial (thread-safe)."""
        if self.use_st3215 and self.st3215:
            try:
                enc = self.st3215.get_angle()
                if enc is not None:
                    self.current_angle = enc
            except Exception as e:
                logger.debug(f"get_physical_encoder_angle error: {e}")
        return self.current_angle

    def read_adc(self) -> list:
        """Reads values from the ADC (or returns simulated values)."""
        vals = [self.sim_pot_value, 0.0, 0.0, 0.0]
        self.adc_updated.emit(vals)
        return vals

    def _update_simulated_servo(self):
        """Simulates servo delay and movement in simulation mode."""
        if self.simulation_mode:
            diff = self.target_angle - self.current_angle
            if abs(diff) > 0.5:
                step = 2.0 if diff > 0 else -2.0
                if abs(diff) < 2.0:
                    step = diff
                self.current_angle += step
            else:
                self.current_angle = self.target_angle

    def cleanup(self):
        """Clean up hardware resources."""
        if self.use_st3215 and self.st3215:
            self.st3215.close()
        if self.use_pigpio:
            try:
                self.pi.set_servo_pulsewidth(self.servo_pin, 0)
                self.pi.stop()
            except Exception as e:
                logger.error(f"Error during pigpio cleanup: {e}")
