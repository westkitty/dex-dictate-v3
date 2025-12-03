from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QApplication
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QColor
from gui.widgets import AudioVisualizer
from strings import Strings

class DexBar(QWidget):
    request_open_gui = Signal()
    request_quit = Signal()

    def __init__(self, state_manager):
        super().__init__()
        self.state_manager = state_manager
        
        # Window Flags: Frameless, Always on Top, Tool (no taskbar entry usually)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Full width, fixed height
        screen = QApplication.primaryScreen().geometry()
        self.setFixedWidth(screen.width())
        self.setFixedHeight(32)
        self.move(0, 0) # Top of screen
        
        # Layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0) # Increased side margins
        layout.setSpacing(15) # Increased spacing
        
        # Background
        self.bg = QWidget(self)
        self.bg.resize(self.width(), self.height())
        self.bg.lower()
        self.bg.setStyleSheet("background-color: rgba(10, 10, 10, 240); border-bottom: 1px solid #333;")
        
        # 1. Logo / Main Button
        self.btn_main = QPushButton("DEX DICTATE")
        self.btn_main.setFlat(True)
        self.btn_main.setStyleSheet("color: #FFF; font-weight: bold; font-size: 12px; text-align: left;")
        self.btn_main.setCursor(Qt.PointingHandCursor)
        self.btn_main.clicked.connect(self.request_open_gui.emit)
        layout.addWidget(self.btn_main)
        
        # 2. Mode Buttons
        self.btn_wake = self._create_mode_btn("WAKE WORD", "WAKE")
        self.btn_manual = self._create_mode_btn("MANUAL", "MANUAL")
        self.btn_focus = self._create_mode_btn("FOCUS (VAD)", "FOCUS")
        
        layout.addWidget(self.btn_wake)
        layout.addWidget(self.btn_manual)
        layout.addWidget(self.btn_focus)
        
        layout.addStretch()
        
        # 3. Visualizer
        self.visualizer = AudioVisualizer(self, bars=20)
        self.visualizer.setFixedSize(100, 20)
        layout.addWidget(self.visualizer)
        
        # 4. Status
        self.lbl_status = QLabel("OFFLINE")
        self.lbl_status.setStyleSheet("color: #888; font-weight: bold; font-size: 11px;")
        layout.addWidget(self.lbl_status)
        
        # 5. Quit (Small X)
        btn_quit = QPushButton("×")
        btn_quit.setFixedSize(20, 20)
        btn_quit.setStyleSheet("color: #666; font-weight: bold; border: none; background: transparent;")
        btn_quit.setCursor(Qt.PointingHandCursor)
        btn_quit.clicked.connect(self.request_quit.emit)
        layout.addWidget(btn_quit)
        
        # Connect Signals
        self.state_manager.mode_changed.connect(self.on_mode_changed)
        self.state_manager.status_changed.connect(self.on_status_changed)
        self.state_manager.audio_level_changed.connect(self.visualizer.update_level)
        
        # Init State
        self.on_mode_changed(self.state_manager.mode)
        self.on_status_changed(self.state_manager.status, self.state_manager.extra_status)

    def _create_mode_btn(self, text, mode):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setFixedSize(90, 24)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.state_manager.set_mode(mode))
        # Stylesheet handled in update
        return btn

    def on_mode_changed(self, mode):
        self.btn_wake.setChecked(mode == "WAKE")
        self.btn_manual.setChecked(mode == "MANUAL")
        self.btn_focus.setChecked(mode == "FOCUS")
        
        # Update Styles
        accent = self.state_manager.get_config("accent", "#00C8FF")
        base_style = """
            QPushButton {
                background-color: transparent;
                color: #888;
                border: 1px solid #444;
                border-radius: 4px;
                font-size: 10px;
            }
            QPushButton:hover { background-color: #222; }
        """
        active_style = f"""
            QPushButton {{
                background-color: {accent};
                color: #000;
                border: 1px solid {accent};
                border-radius: 4px;
                font-weight: bold;
                font-size: 10px;
            }}
        """
        
        self.btn_wake.setStyleSheet(active_style if mode == "WAKE" else base_style)
        self.btn_manual.setStyleSheet(active_style if mode == "MANUAL" else base_style)
        self.btn_focus.setStyleSheet(active_style if mode == "FOCUS" else base_style)

    def on_status_changed(self, status, extra):
        text = status
        color = "#888"
        
        if status == "CONNECTED":
            if extra == "REC":
                text = "RECORDING"
                color = "#FF4444"
            else:
                text = "IDLE"
                color = self.state_manager.get_config("accent", "#00C8FF")
        elif status == "ERROR":
            color = "#FF0000"
            
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 11px;")
