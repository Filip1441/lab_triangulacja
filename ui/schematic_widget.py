import math
from PySide6.QtWidgets import QWidget, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDoubleSpinBox, QLabel
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPolygonF
from PySide6.QtCore import Qt, QRect, QPointF, Signal

import config

class EditValueDialog(QDialog):
    def __init__(self, title, label, value, min_val, max_val, decimals=1, parent=None):
        # Window flag makes it top-level but it runs modally when exec() is called
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(300)
        
        layout = QVBoxLayout(self)
        
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMinimumWidth(180)
        
        # State
        self.base_distance = getattr(config, 'DEFAULT_BASE_DISTANCE_MM', 70.0)
        self.angle_deg = getattr(config, 'DEFAULT_SERVO_BASE_ANGLE', 90.0)
        self.object_distance = 200.0 # Will be updated by MainWindow
        
        # Hitboxes for clicking
        self.rect_base = QRect()
        self.rect_angle = QRect()
        
        # UI colors
        self.col_bg = QColor("#1e1e1e")
        self.col_cam = QColor("#aaaaaa")
        self.col_laser = QColor("#00aaff")
        self.col_beam = QColor(0, 255, 0, 180) # Green dashed
        self.col_cam_axis = QColor(150, 150, 150, 180) # Gray dashed
        self.col_obj = QColor("#ff8800")
        self.col_text_bg = QColor(0, 0, 0, 150)

    def update_state(self, base: float, angle: float, obj_dist: float):
        self.base_distance = base
        self.angle_deg = angle
        self.object_distance = obj_dist
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        # Clear background
        painter.fillRect(0, 0, w, h, self.col_bg)
        
        # Dynamic horizontal scaling: ensure baseline fits with comfortable margins
        pad_x = 32.0
        avail_w = max(80.0, w - 2 * pad_x)
        scale_x = max(0.4, min(1.2, avail_w / max(50.0, self.base_distance)))
        base_span = self.base_distance * scale_x
        cam_x = (w - base_span) / 2.0
        laser_x = cam_x + base_span
        
        # Position Camera & Laser comfortably above the bottom (leaves ~25px breathing room below base label)
        cam_y = h - 55.0
        laser_y = cam_y
        
        # Available vertical space for the object
        top_margin = 40.0
        avail_h = max(120.0, cam_y - top_margin)
        scale_y = max(0.5, min(1.4, avail_h / 320.0))
        
        # Visual distance mapping with break line if too far
        max_no_break_dist = (avail_h - 20.0) / scale_y
        visual_dist = self.object_distance
        has_break = False
        if self.object_distance > max_no_break_dist:
            visual_dist = max_no_break_dist - 25.0
            has_break = True
            
        obj_y = cam_y - (visual_dist * scale_y)
        
        # Calculate physical intersection
        rad = math.radians(self.angle_deg)
        if abs(math.tan(rad)) > 0.001:
            hit_x_phys = self.base_distance - (self.object_distance / math.tan(rad))
        else:
            hit_x_phys = self.base_distance - (10000.0 if self.angle_deg < 90 else -10000.0)
            
        # Visual position of the hit spot on screen
        hit_x = cam_x + (hit_x_phys * scale_x)
        hit_x_draw = max(-10000, min(10000, hit_x))
        
        # 1. Draw camera axis (dashed gray) with optional break
        pen_cam_axis = QPen(self.col_cam_axis, 2, Qt.DashLine)
        painter.setPen(pen_cam_axis)
        
        if has_break:
            # Draw lower part
            break_start_y = cam_y - (visual_dist * scale * 0.4)
            painter.drawLine(int(cam_x), int(cam_y), int(cam_x), int(break_start_y))
            
            # Draw break symbol "..."
            painter.setPen(Qt.white)
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            painter.drawText(int(cam_x - 10), int(break_start_y - 10), "...")
            
            # Draw upper part
            painter.setPen(pen_cam_axis)
            break_end_y = break_start_y - 20.0
            painter.drawLine(int(cam_x), int(break_end_y), int(cam_x), int(obj_y - 20))
        else:
            painter.drawLine(int(cam_x), int(cam_y), int(cam_x), int(obj_y - 20))
            
        # 2. Draw Object
        painter.setBrush(self.col_obj)
        painter.setPen(Qt.NoPen)
        obj_rect = QRect(int(cam_x - 30), int(obj_y - 10), 60, 20)
        painter.drawRoundedRect(obj_rect, 4, 4)
        
        # 3. Draw Laser beam (dashed green)
        pen_laser_beam = QPen(self.col_beam, 2, Qt.DashLine)
        painter.setPen(pen_laser_beam)
        painter.drawLine(int(laser_x), int(laser_y), int(hit_x_draw), int(obj_y))
        
        # Draw the spot on the object
        painter.setBrush(QColor(0, 255, 0))
        painter.drawEllipse(QPointF(hit_x_draw, obj_y), 4, 4)
        
        # 4. Draw Camera box (placed above cam_y)
        painter.setBrush(self.col_cam)
        painter.drawRect(int(cam_x - 15), int(cam_y - 18), 30, 18)
        painter.setPen(Qt.white)
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.drawText(int(cam_x - 12), int(cam_y - 5), "CAM")
        
        # 5. Draw Laser box (placed above laser_y)
        painter.setBrush(self.col_laser)
        painter.drawRect(int(laser_x - 15), int(laser_y - 18), 30, 18)
        painter.setPen(Qt.black)
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.drawText(int(laser_x - 11), int(laser_y - 5), "LSR")
        
        # 6. Draw Editable Text Overlay (Base distance - centered underneath)
        mid_x = (cam_x + laser_x) / 2
        base_text = f"B: {self.base_distance:.1f}mm"
        
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        fm = painter.fontMetrics()
        
        # Base Distance Rect - cleanly positioned below the boxes
        b_w = fm.horizontalAdvance(base_text) + 12
        self.rect_base = QRect(int(mid_x - b_w/2), int(cam_y + 8), b_w, 22)
        painter.setBrush(self.col_text_bg)
        painter.setPen(QPen(QColor("#444"), 1))
        painter.drawRoundedRect(self.rect_base, 3, 3)
        painter.setPen(Qt.white)
        painter.drawText(self.rect_base, Qt.AlignCenter, base_text)
        
        # Angle Rect - cleanly positioned above the laser box
        angle_text = f"a: {self.angle_deg:.1f}°"
        a_w = fm.horizontalAdvance(angle_text) + 12
        self.rect_angle = QRect(int(laser_x - a_w/2), int(laser_y - 44), a_w, 22)
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
