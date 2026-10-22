import logging
import math
import time
from PySide6.QtWidgets import QWidget, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDoubleSpinBox, QLabel
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPolygonF
from PySide6.QtCore import Qt, QRect, QRectF, QPointF, Signal

import config

class EditValueDialog(QDialog):
    def __init__(self, title, label, value, min_val, max_val, decimals=1, parent=None):
        # Window flag makes it top-level but it runs modally when exec() is called
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(340)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        
        lbl_title = QLabel(title)
        lbl_title.setObjectName("dialogTitle")
        layout.addWidget(lbl_title)
        
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel(label))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(min_val, max_val)
        self.spin.setValue(value)
        self.spin.setDecimals(decimals)
        input_layout.addWidget(self.spin)
        layout.addLayout(input_layout)
        
        btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton("Apply")
        self.btn_ok = QPushButton("OK")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("secondary")
        
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)
        
        self.btn_apply.clicked.connect(self.apply_value)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        
        self.value_applied = None
        
    def apply_value(self):
        if self.value_applied:
            self.value_applied(self.spin.value())

    def get_value(self):
        return self.spin.value()

class InteractiveSchematicWidget(QWidget):
    """
    A custom widget that draws the triangulation setup:
    Camera looking up, laser at an angle, object at a distance.
    Allows clicking on values to edit them.
    """
    
    # Signals emitted when user edits values on the schematic
    base_distance_changed = Signal(float)
    angle_changed = Signal(float)

    NICE_RANGES_MM = tuple(round(250 * 1.2 ** i) for i in range(0, 30))   # 250 mm ... ~13 m in 20% steps

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMinimumWidth(180)
        
        # State
        self.base_distance = getattr(config, 'DEFAULT_BASE_DISTANCE_MM', 70.0)
        self.angle_deg = getattr(config, 'DEFAULT_SERVO_BASE_ANGLE', 90.0)
        self.object_distance = 200.0 # Will be updated by MainWindow
        self.spot_x = None           # spot pixel detected by the camera (None = not detected)
        self.fov_deg = getattr(config, 'DEFAULT_FOV_DEG', 30.0)
        self._scale = None           # px per mm, kept stable between frames
        self._range = None           # distance range (mm) the vertical axis currently shows
        self.show_distance = True    # False in Stage 2: students must calculate Z themselves
        self.distance_override = None  # Stage 1: the distance the app currently believes (typed or fitted), in mm
        self._z_ema = None           # smoothed triangulated distance
        self._z_time = 0.0
        self._breaking = False       # break state with hysteresis, so the cut does not flicker
        
        # Hitboxes for clicking
        self.rect_base = QRect()
        self.rect_angle = QRect()
        
        # UI colors
        self.col_bg = QColor("#1e1e1e")
        self.col_cam = QColor("#aaaaaa")
        self.col_laser = QColor("#00aaff")
        self.col_beam = QColor(255, 40, 40, 220) # Red dashed (the laser is red)
        self.col_cam_axis = QColor(150, 150, 150, 180) # Gray dashed
        self.col_obj = QColor("#ff8800")
        self.col_text_bg = QColor(0, 0, 0, 150)

    def update_state(self, base: float, angle: float, obj_dist: float):
        self.base_distance = base
        self.angle_deg = angle
        self.object_distance = obj_dist
        self.update()

    def set_spot(self, spot_x, fov_deg):
        """Pixel position of the spot as detected by the camera (None = not detected) and the camera FOV."""
        self.spot_x = spot_x
        self.fov_deg = float(fov_deg)

    def paintEvent(self, event):
        # Never let a drawing error blank the schematic: always close the painter, log, and repaint next frame.
        painter = QPainter(self)
        try:
            self._paint(painter)
        except Exception:
            logging.getLogger(__name__).exception("Schematic paint failed")
        finally:
            painter.end()

    @staticmethod
    def _cot(deg):
        """cot(alpha) clamped so that alpha near 0/180 deg stays finite."""
        r = math.radians(deg)
        return max(-1000.0, min(1000.0, math.cos(r) / math.sin(r))) if abs(math.sin(r)) > 1e-3 else (1000.0 if math.cos(r) > 0 else -1000.0)

    def _distance_mm(self):
        """
        Distance drawn: triangulated from the detected spot and the servo angle, smoothed so the drawing does not
        shake, and held for 3 s when the spot drops out. Falls back to the set object distance after that.
        """
        if self.distance_override is not None:
            return max(100.0, min(50000.0, float(self.distance_override)))
        now = time.time()
        if self.spot_x is not None:
            tan_theta = ((self.spot_x - 320.0) / 320.0) * math.tan(math.radians(self.fov_deg / 2.0))
            denom = self._cot(self.angle_deg) + tan_theta
            if denom > 1e-4:
                raw = max(100.0, min(50000.0, self.base_distance / denom))
                self._z_ema = raw if self._z_ema is None else 0.8 * self._z_ema + 0.2 * raw
                self._z_time = now
        if self._z_ema is not None and now - self._z_time < 3.0:
            return self._z_ema
        self._z_ema = None
        return max(100.0, min(50000.0, self.object_distance))

    def _paint(self, painter):
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, self.col_bg)

        B = max(1.0, self.base_distance)
        Z = self._distance_mm()
        cot = self._cot(self.angle_deg)
        fov_half_tan = math.tan(math.radians(self.fov_deg / 2.0))
        field_w = 2.0 * Z * fov_half_tan            # width of what the camera sees at distance Z (mm)

        # One scale (px/mm) for x and y, so the beam angle on screen is the real angle.
        pad_x = 10.0
        avail_w = max(80.0, w - 2 * pad_x)
        fw = max(field_w, 20.0)
        # Vertical range shown: the smallest "nice" distance that holds Z, with hysteresis so the view does not jitter.
        need = Z * 1.04
        if self._range is None or need > self._range or Z < 0.72 * self._range:
            self._range = next((r for r in self.NICE_RANGES_MM if r >= need), self.NICE_RANGES_MM[-1])
        span_est = max(100.0, h - 106.0)                   # vertical room between the boxes and the screen
        s_vertical = span_est / self._range
        # Horizontal limits: label column (left), screen and laser box must fit in the widget width
        s_h = max(0.02, min((avail_w - 126.0) / B, (avail_w - 8.0) / fw, (avail_w - 26.0) / (fw / 2.0 + B)))
        # Use the whole height, but never shrink the base below ~50 px (then the far part is cut with a break)
        s_target = min(s_h, max(s_vertical, min(50.0 / B, s_h)), 8.0)
        if self._scale is None or abs(s_target - self._scale) / self._scale > 0.04:
            self._scale = s_target
        s = self._scale

        cam_y = h - 62.0
        top = 24.0
        screen_h = 14.0                                  # low, wide strip
        screen_w = max(40.0, min(avail_w, field_w * s))   # true width of the camera view at distance Z
        left_px = max(screen_w / 2.0 + 4.0, 104.0)      # room for the distance label left of the axis
        right_px = max(screen_w / 2.0 + 4.0, B * s + 22.0)
        cam_x = (w - (left_px + right_px)) / 2.0 + left_px
        laser_x = cam_x + B * s
        obj_y_min = top + screen_h / 2.0
        span_px = cam_y - obj_y_min - screen_h / 2.0 - 6.0   # vertical room between boxes and screen

        # Vertical mapping with an optional break: the middle of the path is cut out and replaced by a gap.
        # True scale while the screen fits; only when it is farther than the drawing area is the middle cut out.
        lower_px, gap_px = 0.30 * span_px, 34.0
        if not self._breaking and Z * s > span_px:
            self._breaking = True
        elif self._breaking and Z * s < 0.88 * span_px:
            self._breaking = False
        has_break = self._breaking
        if has_break:
            upper_px = max(30.0, span_px - lower_px - gap_px)
            z1 = lower_px / s
            z2 = Z - upper_px / s
            y1 = cam_y - lower_px                     # top of the lower part
            y2 = y1 - gap_px                          # bottom of the upper part
            def y_of(z):
                return cam_y - z * s if z <= z1 else y2 - (z - z2) * s
        else:
            z1 = z2 = None
            y1 = y2 = None
            def y_of(z):
                return cam_y - z * s
        obj_y = y_of(Z)
        def x_of(z):
            return max(-5000.0, min(5000.0, cam_x + (B - z * cot) * s))

        # Camera axis (dashed gray)
        painter.setPen(QPen(self.col_cam_axis, 2, Qt.DashLine))
        if has_break:
            painter.drawLine(QPointF(cam_x, cam_y), QPointF(cam_x, y1))
            painter.drawLine(QPointF(cam_x, y2), QPointF(cam_x, obj_y))
        else:
            painter.drawLine(QPointF(cam_x, cam_y), QPointF(cam_x, obj_y))

        # Screen = what the camera sees at distance Z; the spot lands where the camera detected it.
        scr = QRectF(cam_x - screen_w / 2.0, obj_y - screen_h / 2.0, screen_w, screen_h)
        painter.setBrush(QColor(255, 136, 0, 215))
        painter.setPen(QPen(QColor("#ffb84d"), 2))
        painter.drawRoundedRect(scr, 3, 3)
        painter.setPen(QPen(QColor(0, 0, 0, 110), 1))
        painter.drawLine(QPointF(cam_x, scr.top() + 2), QPointF(cam_x, scr.bottom() - 2))   # image centre (x = 320 px)
        for k in (-1.0, -0.5, 0.5, 1.0):
            tx = cam_x + k * screen_w / 2.0 * 0.98
            painter.drawLine(QPointF(tx, scr.bottom() - 5), QPointF(tx, scr.bottom() - 2))

        # Distance label on the camera axis (the segment joining camera and screen)
        seg_top, seg_bottom = scr.bottom(), (y2 if has_break else cam_y - 18.0)
        if has_break and (y1 - cam_y) * -1 > (seg_bottom - seg_top):   # lower part is the longer segment
            seg_top, seg_bottom = y1, cam_y - 18.0
        if self.show_distance:
            label = f"\u2195 {Z:.0f} mm"
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            lw = painter.fontMetrics().horizontalAdvance(label) + 12
            chip = QRectF(cam_x - lw - 6, (seg_top + seg_bottom) / 2.0 - 11, lw, 22)
            painter.setBrush(QColor(0, 0, 0, 170))
            painter.setPen(QPen(QColor("#ffb84d"), 1))
            painter.drawRoundedRect(chip, 4, 4)
            painter.setPen(QColor("#ffd699"))
            painter.drawText(chip, Qt.AlignCenter, label)

        # Spot on the screen. hit_x_phys is where the beam meets the screen plane; when a spot is detected, Z was
        # computed from it, so this is exactly the detected position, and the beam stays a true straight line.
        hit_x_phys = B - Z * cot
        spot_sx = cam_x + hit_x_phys * s
        in_view = self.spot_x is not None
        spot_sx = max(scr.left() + 3, min(scr.right() - 3, spot_sx))

        # Laser beam (dashed green): lower part, then the same slope shifted past the break
        painter.setPen(QPen(self.col_beam, 2, Qt.DashLine))
        if has_break:
            painter.drawLine(QPointF(laser_x, cam_y), QPointF(x_of(z1), y1))
            painter.drawLine(QPointF(x_of(z2), y2), QPointF(spot_sx, obj_y))
            # break marks: only the two cut lines (camera axis and laser beam) get a slash at each end of the gap
            painter.setPen(QPen(Qt.white, 2))
            for bx, by in ((cam_x, y1), (cam_x, y2), (x_of(z1), y1), (x_of(z2), y2)):
                painter.drawLine(QPointF(bx - 7, by + 4), QPointF(bx + 7, by - 4))
        else:
            painter.drawLine(QPointF(laser_x, cam_y), QPointF(spot_sx, obj_y))

        # Spot marker
        painter.setPen(QPen(Qt.white, 1))
        painter.setBrush(QColor(255, 30, 30) if in_view else QColor(120, 120, 120))
        painter.drawEllipse(QPointF(spot_sx, obj_y), 6, 6)
        painter.setBrush(Qt.white)
        painter.drawEllipse(QPointF(spot_sx, obj_y), 2, 2)

        # Baseline joining camera and laser (dashed)
        painter.setPen(QPen(QColor(200, 200, 200, 170), 2, Qt.DashLine))
        painter.drawLine(QPointF(cam_x + 15, cam_y - 9), QPointF(laser_x - 15, cam_y - 9))

        # Camera box and laser box
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.col_cam)
        painter.drawRect(int(cam_x - 15), int(cam_y - 18), 30, 18)
        painter.setPen(Qt.white)
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.drawText(int(cam_x - 12), int(cam_y - 5), "CAM")
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.col_laser)
        painter.drawRect(int(laser_x - 15), int(cam_y - 18), 30, 18)
        painter.setPen(Qt.black)
        painter.drawText(int(laser_x - 11), int(cam_y - 5), "LSR")

        # Editable overlays: B below the boxes, angle above the laser
        mid_x = (cam_x + laser_x) / 2
        base_text = f"B: {self.base_distance:.1f}mm"
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        fm = painter.fontMetrics()
        b_w = fm.horizontalAdvance(base_text) + 12
        self.rect_base = QRect(int(mid_x - b_w / 2), int(cam_y + 8), b_w, 22)
        painter.setBrush(self.col_text_bg)
        painter.setPen(QPen(QColor("#444"), 1))
        painter.drawRoundedRect(self.rect_base, 3, 3)
        painter.setPen(Qt.white)
        painter.drawText(self.rect_base, Qt.AlignCenter, base_text)

        angle_text = f"a: {self.angle_deg:.1f}°"
        a_w = fm.horizontalAdvance(angle_text) + 12
        self.rect_angle = QRect(int(laser_x - a_w / 2), int(cam_y - 44), a_w, 22)
        painter.setBrush(self.col_text_bg)
        painter.setPen(QPen(QColor("#00aaff"), 1))
        painter.drawRoundedRect(self.rect_angle, 3, 3)
        painter.setPen(Qt.white)
        painter.drawText(self.rect_angle, Qt.AlignCenter, angle_text)

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        
        if self.rect_base.contains(pos):
            dlg = EditValueDialog("Edit Base Distance", "Distance (mm):", self.base_distance, 1.0, 1000.0, 1, self)
            def on_apply(val):
                self.base_distance_changed.emit(val)
                self.base_distance = val
                self.update()
            dlg.value_applied = on_apply
            if dlg.exec() == QDialog.Accepted:
                on_apply(dlg.get_value())
                
        elif self.rect_angle.contains(pos):
            dlg = EditValueDialog("Edit Laser Angle", "Angle (deg):", self.angle_deg, 0.0, 180.0, 1, self)
            def on_apply(val):
                self.angle_changed.emit(val)
                self.angle_deg = val
                self.update()
            dlg.value_applied = on_apply
            if dlg.exec() == QDialog.Accepted:
                on_apply(dlg.get_value())
