from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, 
                               QGraphicsOpacityEffect, QApplication)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QSize
from PySide6.QtGui import QPainter, QBrush, QColor, QFont
from strings import Strings

class TopBarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.setObjectName("TopBar")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(15)
        
        # Logo
        lbl_logo = QLabel(Strings.APP_LOGO)
        lbl_logo.setObjectName("BarLogo")
        lbl_logo.setStyleSheet("font-weight: bold; color: #29A2FF; font-size: 14px;")
        lbl_logo.setAccessibleName(Strings.A11Y_LOGO)
        layout.addWidget(lbl_logo)
        
        # Mode Buttons (Moved to Left)
        self.group = parent.findChild(QWidget, "mode_group") if parent else None # This logic needs fixing in main window integration
        
        # We will re-create buttons here or link them. 
        # For now, let's create them and let MainWindow connect signals.
        self.btn_wake = self._create_mode_btn(Strings.MODE_WAKE, "WAKE")
        self.btn_wake.setAccessibleName(Strings.A11Y_MODE_WAKE)
        self.btn_wake.setAccessibleDescription(Strings.A11Y_DESC_WAKE)
        
        self.btn_manual = self._create_mode_btn(Strings.MODE_MANUAL, "MANUAL")
        self.btn_manual.setAccessibleName(Strings.A11Y_MODE_MANUAL)
        self.btn_manual.setAccessibleDescription(Strings.A11Y_DESC_MANUAL)
        
        self.btn_focus = self._create_mode_btn(Strings.MODE_FOCUS, "FOCUS")
        self.btn_focus.setAccessibleName(Strings.A11Y_MODE_FOCUS)
        self.btn_focus.setAccessibleDescription(Strings.A11Y_DESC_FOCUS)
        
        layout.addWidget(self.btn_wake)
        layout.addWidget(self.btn_manual)
        layout.addWidget(self.btn_focus)
        
        layout.addStretch()
        
        # Audio Visualizer
        self.visualizer = AudioVisualizer(self, bars=10)
        self.visualizer.setFixedWidth(60)
        self.visualizer.setAccessibleName(Strings.A11Y_VISUALIZER)
        layout.addWidget(self.visualizer)
        
        # Status
        self.lbl_status = QLabel(Strings.STATUS_IDLE)
        self.lbl_status.setObjectName("BarStatus")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #555; font-size: 14px;")
        self.lbl_status.setAccessibleName(Strings.A11Y_STATUS_IDLE)
        layout.addWidget(self.lbl_status)

    def _create_mode_btn(self, text, mode):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setObjectName("BarModeButton")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setProperty("mode", mode)
        return btn

    def set_mode(self, mode):
        # Update visual state of buttons
        self.btn_wake.setChecked(mode == "WAKE")
        self.btn_manual.setChecked(mode == "MANUAL")
        self.btn_focus.setChecked(mode == "FOCUS")

    def update_status(self, state, color):
        self.lbl_status.setText(state)
        self.lbl_status.setStyleSheet(f"font-weight: bold; color: {color}; font-size: 14px;")
        self.lbl_status.setAccessibleName(f"{Strings.A11Y_STATUS_PREFIX}{state}")
        
    def update_audio(self, level):
        self.visualizer.update_level(level)

class SlidingDrawer(QWidget):
    def __init__(self, parent=None, side="right", width=300):
        super().__init__(parent)
        self.side = side
        self.max_width = width
        self.is_open = False
        
        self.setFixedWidth(0)
        self.setStyleSheet("background-color: #111; border-left: 1px solid #333;")
        
        # Animation
        self.anim = QPropertyAnimation(self, b"maximumWidth")
        self.anim.setDuration(300)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        
    def toggle(self):
        start = self.width()
        end = self.max_width if not self.is_open else 0
        self.anim.setStartValue(start)
        self.anim.setEndValue(end)
        self.anim.start()
        self.is_open = not self.is_open

class AudioVisualizer(QWidget):
    def __init__(self, parent=None, bars=20):
        super().__init__(parent)
        self.bars = bars
        self.levels = [0.0] * bars
        self.active = False
        self.timer = QTimer()
        self.timer.timeout.connect(self.decay)
        self.timer.start(50)
        
    def update_level(self, level):
        # Shift
        self.levels.pop(0)
        self.levels.append(level)
        self.update()
        
    def decay(self):
        if not self.active:
            self.levels = [max(0, l - 0.05) for l in self.levels]
            self.update()
            
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width() / self.bars
        h = self.height()
        
        for i, level in enumerate(self.levels):
            bar_h = h * level
            x = i * w
            y = h - bar_h
            
            # Color based on level
            c = QColor("#00C8FF")
            if level > 0.8: c = QColor("#FF0055")
            elif level > 0.5: c = QColor("#FFCC00")
            
            painter.fillRect(x, y, w-2, bar_h, QBrush(c))

class HotkeyRecorder(QPushButton):
    def __init__(self, default_key):
        super().__init__(default_key)
        self.key = default_key
        self.recording = False
        self.clicked.connect(self.start_recording)
        self.setStyleSheet("background-color: #222; color: #EEE; border: 1px solid #444; padding: 5px;")
        
    def start_recording(self):
        self.recording = True
        self.setText("Press Key...")
        self.setStyleSheet("background-color: #442222; color: #FFF; border: 1px solid #F55;")
        self.grabKeyboard()
        
    def keyPressEvent(self, event):
        if self.recording:
            key = event.key()
            # Convert Qt key to string representation (simplified)
            # In a real app, use QKeySequence(key).toString()
            from PySide6.QtGui import QKeySequence
            self.key = QKeySequence(key).toString()
            self.setText(self.key)
            self.releaseKeyboard()
            self.recording = False
            self.setStyleSheet("background-color: #222; color: #EEE; border: 1px solid #444; padding: 5px;")
        else:
            super().keyPressEvent(event)

class ToastOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        layout = QVBoxLayout(self)
        self.lbl = QLabel()
        self.lbl.setStyleSheet("""
            background-color: rgba(0, 0, 0, 200); 
            color: white; 
            padding: 10px 20px; 
            border-radius: 10px;
            font-size: 16px;
            font-weight: bold;
        """)
        layout.addWidget(self.lbl)
        
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        
        # Opacity Animation
        self.eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.eff)
        self.anim = QPropertyAnimation(self.eff, b"opacity")
        
    def show_message(self, text, duration=2000):
        self.lbl.setText(text)
        self.adjustSize()
        
        # Center on parent or screen
        if self.parent():
            geo = self.parent().geometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + geo.height() - self.height() - 50
            self.move(x, y)
        
        self.show()
        self.eff.setOpacity(1)
        self.timer.start(duration)
        
        # Fade out
        self.anim.setDuration(500)
        self.anim.setStartValue(1)
        self.anim.setEndValue(0)
        QTimer.singleShot(duration - 500, self.anim.start)

class FloaterWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__() # Top-level window
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(200, 60)
        
        self.dragging = False
        self.offset = None
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Background
        self.bg = QWidget(self)
        self.bg.resize(200, 60)
        self.bg.lower()
        self.bg.setStyleSheet("background-color: rgba(20, 20, 20, 230); border: 1px solid #444; border-radius: 30px;")
        
        # Visualizer (Left)
        self.visualizer = AudioVisualizer(self, bars=10)
        self.visualizer.setFixedSize(50, 40)
        layout.addWidget(self.visualizer)
        
        # Status/Toggle Button (Right)
        self.btn_toggle = QPushButton("IDLE")
        self.btn_toggle.setFixedSize(100, 40)
        self.btn_toggle.setStyleSheet("""
            QPushButton {
                background-color: #333; 
                color: #EEE; 
                border: none; 
                border-radius: 20px; 
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #444;
            }
        """)
        self.btn_toggle.clicked.connect(self.toggle_clicked)
        layout.addWidget(self.btn_toggle)
        
        # Close (Tiny X)
        btn_close = QPushButton("×", self)
        btn_close.setGeometry(180, 5, 15, 15)
        btn_close.setStyleSheet("background: transparent; color: #888; font-weight: bold; border: none;")
        btn_close.clicked.connect(self.hide)

    def toggle_clicked(self):
        # Signal parent or use callback? 
        # Since it's a separate window, we might need a signal or reference.
        # Let's assume parent (MainWindow) connects to this button's clicked signal or we emit a custom one.
        pass

    def update_status(self, state, color):
        self.btn_toggle.setText(state)
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                background-color: {color}; 
                color: #FFF; 
                border: 2px solid rgba(255,255,255,0.2); 
                border-radius: 20px; 
                font-weight: bold;
            }}
        """)

    def update_audio(self, level):
        self.visualizer.update_level(level)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(event.globalPosition().toPoint() - self.offset)

    def mouseReleaseEvent(self, event):
        self.dragging = False

