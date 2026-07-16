import cv2
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, 
    QSlider, QSpinBox, QDoubleSpinBox, QGroupBox
)
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt, Slot

class CameraDisplayWidget(QLabel):
    """
    A QLabel that displays OpenCV frames efficiently.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 240)
        self.setStyleSheet("background-color: black; border: 1px solid #555;")

    @Slot(np.ndarray)
    def update_frame(self, frame: np.ndarray):
        if frame is None:
            return
            
        # Convert BGR to RGB
        if len(frame.shape) == 3:
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            qimg = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        else: # Grayscale/Binary
            h, w = frame.shape
            bytes_per_line = w
            qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_Grayscale8)

        # Scale keeping aspect ratio
        pixmap = QPixmap.fromImage(qimg)
        scaled_pixmap = pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(scaled_pixmap)

class ParameterSlider(QWidget):
    """
    A reusable widget containing a label, slider, and spinbox.
    """
    def __init__(self, label_text: str, min_val: int, max_val: int, default_val: int, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(label_text)
        self.label.setMinimumWidth(100)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(min_val, max_val)
        self.slider.setValue(default_val)
        
        self.spinbox = QSpinBox()
        self.spinbox.setRange(min_val, max_val)
        self.spinbox.setValue(default_val)
        
        # Connect slider and spinbox
        self.slider.valueChanged.connect(self.spinbox.setValue)
        self.spinbox.valueChanged.connect(self.slider.setValue)

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.slider)
        self.layout.addWidget(self.spinbox)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, val: int):
        self.slider.setValue(val)

class FloatParameterSlider(QWidget):
    """
    A reusable widget containing a label, slider, and double spinbox for floats.
    """
    def __init__(self, label_text: str, min_val: float, max_val: float, default_val: float, decimals: int = 3, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(label_text)
        self.label.setMinimumWidth(100)
        
        self.scale = 10 ** decimals
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(min_val * self.scale), int(max_val * self.scale))
        self.slider.setValue(int(default_val * self.scale))
        
        self.spinbox = QDoubleSpinBox()
        self.spinbox.setDecimals(decimals)
        self.spinbox.setRange(min_val, max_val)
        self.spinbox.setValue(default_val)
        self.spinbox.setSingleStep(1.0 / self.scale)
        
        # Connect slider and spinbox
        self.slider.valueChanged.connect(lambda v: self.spinbox.setValue(v / self.scale))
        self.spinbox.valueChanged.connect(lambda v: self.slider.setValue(int(v * self.scale)))

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.slider)
        self.layout.addWidget(self.spinbox)

    def value(self) -> float:
        return self.spinbox.value()

    def setValue(self, val: float):
        self.spinbox.setValue(val)
