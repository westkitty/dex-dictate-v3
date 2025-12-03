#!/usr/bin/env python3
import sys
import os
import json
import socket
import threading
import time
import subprocess
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                               QLabel, QPushButton, QSlider, QLineEdit, QTextEdit, QFrame, 
                               QStatusBar, QRadioButton, QButtonGroup, QSpinBox, QDialog, 
                               QScrollArea, QSizePolicy, QSplitter, QTableWidget, 
                               QTableWidgetItem, QHeaderView, QComboBox, QCheckBox, QGridLayout,
                               QSystemTrayIcon, QMenu, QListWidget, QStackedWidget, QToolButton, QMessageBox)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QSize, QPropertyAnimation, QEasingCurve, QObject
from PySide6.QtGui import QFont, QColor, QPalette, QPainter, QBrush, QPen, QIcon

# --- CONFIG ---
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
SOCK_PATH = os.path.join(RUNTIME, "dex3.sock")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STYLESHEET_PATH = os.path.join(BASE_DIR, "starsilk.qss")

# --- HELPER CLASSES ---

class TelemetryClient(QObject):
    telemetry_updated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(100)  # 10 Hz
        self._timer.timeout.connect(self.poll)
        self._timer.start()

    def poll(self):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.05)
                s.connect(SOCK_PATH)
                s.sendall(b"GET_TELEMETRY\n")
                data = s.recv(8192)
        except (ConnectionRefusedError, FileNotFoundError, socket.timeout, OSError):
            return

        if not data: return

        try:
            text = data.decode("utf-8").strip()
            if not text: return
            payload = json.loads(text)
        except json.JSONDecodeError: return

        if payload.get("type") == "telemetry":
            t = payload.get("data", {})
            if isinstance(t, dict):
                self.telemetry_updated.emit(t)

class FocusPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("focusPanel")
        self.setProperty("mode", "idle")
        self._refresh_style()

    def _refresh_style(self):
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_mode(self, mode: str):
        if mode not in ("idle", "listening", "transcribing", "injecting"):
            mode = "idle"
        if self.property("mode") == mode:
            return
        self.setProperty("mode", mode)
        self._refresh_style()

# --- DAEMON CLIENT THREAD ---
class DaemonClient(QThread):
    status_signal = Signal(str, str) # status, extra
    log_signal = Signal(str)
    telemetry_signal = Signal(dict) # New signal for JSON telemetry
    
    def __init__(self):
        super().__init__()
        self.socket_path = SOCK_PATH # Use global SOCK_PATH
        self.running = True
        self.connected = False
        self.cmd_queue = []

    def run(self):
        while self.running:
            try:
                if not self.connected:
                    # Try to connect/ping
                    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    client.connect(self.socket_path)
                    client.send(b"PING")
                    resp = client.recv(4096).decode().strip() # Increased buffer
                    client.close()
                    
                    if resp.startswith("PONG"):
                        parts = resp.split(":")
                        status = parts[1] if len(parts) > 1 else "IDLE"
                        log_msg = parts[2] if len(parts) > 2 else ""
                        self.status_signal.emit("CONNECTED", status)
                        if log_msg: self.log_signal.emit(log_msg)
                        self.connected = True
                    else:
                        self.status_signal.emit("DISCONNECTED", "Bad Resp")
                        self.connected = False
                
                # Process Command Queue
                if self.connected and self.cmd_queue:
                    cmd = self.cmd_queue.pop(0)
                    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    client.connect(self.socket_path)
                    client.send(cmd.encode())
                    resp = client.recv(4096).decode().strip()
                    client.close()
                    
                    if cmd == "GET_TELEMETRY":
                        try:
                            data = json.loads(resp)
                            self.telemetry_signal.emit(data)
                        except: pass
                    # Other commands just return OK
                    
                time.sleep(0.1) # 10Hz Poll
            except Exception as e:
                self.status_signal.emit("DISCONNECTED", str(e))
                self.connected = False
                time.sleep(1)

    def send_cmd(self, cmd):
        self.cmd_queue.append(cmd)

    def stop(self):
        self.running = False
        self.wait()

# --- WIDGETS ---

# --- NEW WIDGETS ---

class AudioVisualizer(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("AudioVisualizer")
        self.setFixedSize(300, 60)
        self.bars = [0.1] * 30
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_bars)
        self.timer.start(30)
        self.active = False
        
    def update_bars(self):
        import random
        if self.active:
            # Simulate FFT decay
            self.bars = [max(0.1, b * 0.85) for b in self.bars]
            # Add new energy
            for i in range(len(self.bars)):
                if random.random() > 0.7:
                    self.bars[i] = min(1.0, self.bars[i] + random.uniform(0.3, 0.8))
        else:
            self.bars = [max(0.05, b * 0.9) for b in self.bars]
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width() / 30
        for i, h in enumerate(self.bars):
            color = QColor("#00C8FF")
            color.setAlphaF(h)
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            height = self.height() * h
            painter.drawRect(i * w, (self.height() - height) / 2, w - 2, height)

class HotkeyRecorder(QPushButton):
    def __init__(self, key_name, parent=None):
        super().__init__("Click to Set", parent)
        self.key_name = key_name
        self.recording = False
        self.current_keys = set()
        self.clicked.connect(self.start_recording)
        
    def start_recording(self):
        self.setText("Listening...")
        self.setProperty("state", "recording")
        self.style().unpolish(self)
        self.style().polish(self)
        self.recording = True
        self.current_keys = set()
        self.grabKeyboard()
        
    def keyPressEvent(self, event):
        if not self.recording: return
        key = event.key()
        if key == Qt.Key_Control: self.current_keys.add("CTRL")
        elif key == Qt.Key_Alt: self.current_keys.add("ALT")
        elif key == Qt.Key_Shift: self.current_keys.add("SHIFT")
        else:
            # Map Qt Key to String
            txt = QKeySequence(key).toString()
            if txt: self.current_keys.add(txt)
            self.finish_recording()
            
    def finish_recording(self):
        self.releaseKeyboard()
        self.recording = False
        combo = "+".join(sorted(self.current_keys))
        self.setText(combo)
        self.setProperty("state", "valid")
        self.style().unpolish(self)
        self.style().polish(self)

class AudioVisualizer(QWidget):
    def __init__(self, parent=None, bars=20):
        super().__init__(parent)
        self.bars = bars
        self.values = [0.0] * bars
        self.setObjectName("AudioVisualizer")
        self.setFixedHeight(30)
        
        # Timer for smooth decay
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._decay)
        self.timer.start(50)
        
    def update_level(self, level):
        # Shift values
        self.values.pop(0)
        self.values.append(level)
        self.update()
        
    def _decay(self):
        # Decay all values slightly
        self.values = [max(0.0, v - 0.05) for v in self.values]
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        bar_w = w / self.bars
        
        # Get Accent Color from Parent or default
        accent = "#00C8FF"
        # Try to get from parent window if possible, or just use a default/property
        # For now, hardcode or use a property if set
        
        painter.setBrush(QBrush(QColor(accent)))
        painter.setPen(Qt.NoPen)
        
        for i, val in enumerate(self.values):
            # Height based on value (0.0 to 1.0)
            bar_h = val * h
            x = i * bar_w
            y = (h - bar_h) / 2 # Center vertically
            
            # Draw bar
            painter.drawRoundedRect(x + 1, y, bar_w - 2, bar_h, 2, 2)

class TopBarWidget(QWidget):
    mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__() # No parent = Separate Window
        self.setObjectName("TopBarWidget")
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Geometry: Full Width, 40px Height, Top-Left (0,0)
        screen_geo = QApplication.primaryScreen().geometry()
        self.setGeometry(0, 0, screen_geo.width(), 40)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)
        layout.setSpacing(15)
        
        # Logo
        lbl_logo = QLabel("DEX DICTATE")
        lbl_logo.setObjectName("BarLogo")
        lbl_logo.setStyleSheet("font-weight: bold; color: #29A2FF; font-size: 14px;")
        layout.addWidget(lbl_logo)
        
        # Mode Buttons (Moved to Left)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        
        self.btn_wake = self._create_mode_btn("Wake Word", "WAKE")
        self.btn_manual = self._create_mode_btn("Manual", "MANUAL")
        self.btn_focus = self._create_mode_btn("Focus (VAD)", "FOCUS")
        
        layout.addWidget(self.btn_wake)
        layout.addWidget(self.btn_manual)
        layout.addWidget(self.btn_focus)
        
        layout.addStretch()
        
        # Audio Visualizer
        self.visualizer = AudioVisualizer(self, bars=10)
        self.visualizer.setFixedWidth(60)
        layout.addWidget(self.visualizer)
        
        # Status
        self.lbl_status = QLabel("IDLE")
        self.lbl_status.setObjectName("BarStatus")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #555; font-size: 14px;")
        layout.addWidget(self.lbl_status)

    def _create_mode_btn(self, text, mode):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setObjectName("BarModeButton")
        btn.setCursor(Qt.PointingHandCursor)
        # Add specific style for checked state to ensure visibility
        btn.setStyleSheet("""
            QPushButton#BarModeButton {
                background-color: rgba(0, 0, 0, 0.5);
                color: #888;
                border: 1px solid #444;
                padding: 5px 10px;
                border-radius: 4px;
            }
            QPushButton#BarModeButton:checked {
                background-color: #00C8FF;
                color: black;
                border: 1px solid #00C8FF;
                font-weight: bold;
            }
            QPushButton#BarModeButton:hover {
                border: 1px solid #00C8FF;
                color: #00C8FF;
            }
            QPushButton#BarModeButton:checked:hover {
                color: black;
            }
        """)
        btn.clicked.connect(lambda: self.mode_changed.emit(mode))
        self.group.addButton(btn)
        return btn

    def set_mode(self, mode):
        if mode == "WAKE": self.btn_wake.setChecked(True)
        elif mode == "MANUAL": self.btn_manual.setChecked(True)
        elif mode == "FOCUS": self.btn_focus.setChecked(True)

    def update_status(self, state, color):
        self.lbl_status.setText(state)
        self.lbl_status.setStyleSheet(f"font-weight: bold; color: {color}; font-size: 14px;")
        
    def update_audio(self, level):
        self.visualizer.update_level(level)

class SlidingDrawer(QWidget):
    def __init__(self, parent, direction="RIGHT", width=300):
        super().__init__(parent)
        self.direction = direction
        self.target_width = width
        self.setObjectName("SlidingDrawer")
        
        # Initial Geometry (Hidden)
        self.resize(width, parent.height())
        self._update_pos(closed=True)
        
        self.anim = QPropertyAnimation(self, b"pos")
        self.anim.setDuration(300)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        
        self.is_open = False
        
        # Layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0,0,0,0)

    def _update_pos(self, closed=True):
        p_w = self.parent().width()
        p_h = self.parent().height()
        self.resize(self.target_width, p_h)
        
        if self.direction == "RIGHT":
            x = p_w if closed else p_w - self.target_width
            self.move(x, 0)
        else: # LEFT
            x = -self.target_width if closed else 0
            self.move(x, 0)

    def toggle(self):
        self._update_pos(closed=not self.is_open) # Ensure start pos is correct (Open if Open, Closed if Closed)
        start = self.pos()
        
        p_w = self.parent().width()
        if self.direction == "RIGHT":
            end = QPoint(p_w, 0) if self.is_open else QPoint(p_w - self.target_width, 0)
        else: # LEFT
            end = QPoint(-self.target_width, 0) if self.is_open else QPoint(0, 0)
            
        self.anim.setStartValue(start)
        self.anim.setEndValue(end)
        self.anim.start()
        
        self.is_open = not self.is_open
        if self.is_open:
            self.raise_()
            self.setFocus()

class HistoryPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10,10,10,10)
        
        layout.addWidget(QLabel("TRANSCRIPT HISTORY"))
        
        self.list = QListWidget()
        self.list.setObjectName("HistoryList")
        layout.addWidget(self.list)
        
        btn_clear = QPushButton("CLEAR HISTORY")
        btn_clear.clicked.connect(self.list.clear)
        layout.addWidget(btn_clear)
        
    def add_item(self, text):
        ts = time.strftime("%H:%M:%S")
        item = f"[{ts}] {text}"
        self.list.addItem(item)
        self.list.scrollToBottom()

class ClipboardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10,10,10,10)
        
        # Close Button
        btn_close = QPushButton("CLOSE DRAWER")
        btn_close.setStyleSheet("background-color: #333; color: #FFF; border: 1px solid #555;")
        btn_close.clicked.connect(lambda: self.parent().toggle() if hasattr(self.parent(), 'toggle') else None)
        layout.addWidget(btn_close)
        
        # Last Clipboard
        layout.addWidget(QLabel("LAST CLIPBOARD (CAPTURED)"))
        self.txt_last = QTextEdit()
        self.txt_last.setReadOnly(True)
        # self.txt_last.setMaximumHeight(100) # Removed to allow expansion
        layout.addWidget(self.txt_last)
        
        hbox1 = QHBoxLayout()
        btn_cap = QPushButton("Capture Now")
        btn_cap.clicked.connect(self.capture_clipboard)
        btn_copy_last = QPushButton("Copy")
        btn_copy_last.clicked.connect(lambda: QApplication.clipboard().setText(self.txt_last.toPlainText()))
        hbox1.addWidget(btn_cap)
        hbox1.addWidget(btn_copy_last)
        layout.addLayout(hbox1)
        
        # Pinned Note
        layout.addWidget(QLabel("PINNED NOTE (PERSISTENT)"))
        self.txt_pinned = QTextEdit()
        layout.addWidget(self.txt_pinned)
        
        hbox2 = QHBoxLayout()
        btn_save = QPushButton("Save Pinned") # Auto-save on change? Yes, but button for reassurance
        btn_save.clicked.connect(self.save_pinned)
        btn_copy_pinned = QPushButton("Copy")
        btn_copy_pinned.clicked.connect(lambda: QApplication.clipboard().setText(self.txt_pinned.toPlainText()))
        hbox2.addWidget(btn_save)
        hbox2.addWidget(btn_copy_pinned)
        layout.addLayout(hbox2)
        
    def capture_clipboard(self):
        text = QApplication.clipboard().text()
        if text:
            ts = time.strftime("%H:%M:%S")
            self.txt_last.setText(f"[{ts}] {text}")
            # Trigger save in parent
            if self.parent() and hasattr(self.parent(), 'save_clipboard'):
                self.parent().save_clipboard(text, self.txt_pinned.toPlainText())

    def save_pinned(self):
        if self.parent() and hasattr(self.parent(), 'save_clipboard'):
            self.parent().save_clipboard(self.txt_last.toPlainText(), self.txt_pinned.toPlainText())

    def set_data(self, last, pinned):
        self.txt_last.setText(last)
        self.txt_pinned.setText(pinned)

class CommandListWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Available Commands")
        self.resize(600, 600)
        layout = QVBoxLayout(self)
        
        lbl = QLabel("VOICE COMMANDS & MACROS")
        lbl.setObjectName("SectionLabel")
        layout.addWidget(lbl)
        
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Trigger", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)
        
        commands = [
            ("SYSTEM", ""),
            ("Computer, open Firefox", "Launches Firefox Browser"),
            ("Computer, open Terminal", "Launches Gnome Terminal"),
            ("Computer, open File Manager", "Launches Nautilus"),
            ("Computer, open Calculator", "Launches Calculator"),
            ("Computer, open Editor", "Launches Text Editor"),
            ("Computer, lock screen", "Locks the screen"),
            ("Computer, take screenshot", "Takes a screenshot"),
            
            ("MEDIA", ""),
            ("Computer, pause music", "Pauses media playback"),
            ("Computer, resume music", "Resumes media playback"),
            ("Computer, next track", "Skips to next track"),
            ("Computer, previous track", "Goes to previous track"),
            ("Computer, volume up", "Increases volume by 5%"),
            ("Computer, volume down", "Decreases volume by 5%"),
            ("Computer, mute", "Toggles mute"),
            
            ("SNIPPETS", ""),
            ("Insert Signature", "Inserts email signature"),
            ("Insert Date", "Inserts YYYY-MM-DD"),
            ("Insert Time", "Inserts HH:MM"),
            ("Insert Code Block", "Inserts Markdown code block"),
            ("Insert Todo", "Inserts '- [ ] '"),
            ("Insert Lorem Ipsum", "Inserts placeholder text"),
            ("Clear Selection", "Deletes selected text (Backspace)"),
            
            ("UTILITY", ""),
            ("Computer, what time is it", "Types current time"),
            ("Computer, date today", "Types current date"),
            
            ("BROWSER", ""),
            ("Computer, new tab", "Ctrl+T"),
            ("Computer, close tab", "Ctrl+W"),
            ("Computer, reopen tab", "Ctrl+Shift+T"),
            ("Computer, next tab", "Ctrl+Tab"),
            ("Computer, previous tab", "Ctrl+Shift+Tab"),
            ("Computer, refresh page", "F5"),
            ("Computer, browser history", "Ctrl+H"),
            ("Computer, downloads", "Ctrl+J"),
            ("Computer, private window", "Ctrl+Shift+P"),
            
            ("EDITING", ""),
            ("Computer, select all", "Ctrl+A"),
            ("Computer, copy selection", "Ctrl+C"),
            ("Computer, paste clipboard", "Ctrl+V"),
            ("Computer, cut selection", "Ctrl+X"),
            ("Computer, undo action", "Ctrl+Z"),
            ("Computer, redo action", "Ctrl+Shift+Z"),
            ("Computer, save file", "Ctrl+S"),
            ("Computer, find text", "Ctrl+F"),
            
            ("WINDOW", ""),
            ("Computer, close window", "Alt+F4"),
            ("Computer, switch window", "Alt+Tab"),
            ("Computer, show desktop", "Super+D"),
            
            ("NAVIGATION", ""),
            ("Computer, page up", "PageUp"),
            ("Computer, page down", "PageDown"),
            ("Computer, go home", "Alt+Home"),
            
            ("TILING", ""),
            ("Computer, maximize window", "Super+Up"),
            ("Computer, minimize window", "Super+Down"),
            ("Computer, snap left", "Super+Left"),
            ("Computer, snap right", "Super+Right"),
            ("Computer, fullscreen", "F11"),
            
            ("TEXT NAV", ""),
            ("Computer, go to start", "Home"),
            ("Computer, go to end", "End"),
            ("Computer, top of page", "Ctrl+Home"),
            ("Computer, bottom of page", "Ctrl+End"),
            ("Computer, delete word", "Ctrl+Backspace"),
            ("Computer, delete next word", "Ctrl+Delete"),
            ("Computer, select word left", "Ctrl+Shift+Left"),
            ("Computer, select word right", "Ctrl+Shift+Right"),
            
            ("ZOOM", ""),
            ("Computer, zoom in", "Ctrl++"),
            ("Computer, zoom out", "Ctrl+-"),
            ("Computer, reset zoom", "Ctrl+0"),
            
            ("APPS", ""),
            ("Computer, open monitor", "System Monitor"),
            ("Computer, open documents", "~/Documents"),
            ("Computer, open downloads folder", "~/Downloads"),
            ("Computer, open pictures", "~/Pictures"),
            ("Computer, open trash", "Trash"),
            
            ("WORKSPACES", ""),
            ("Computer, workspace one", "Super+1"),
            ("Computer, workspace two", "Super+2"),
            ("Computer, workspace three", "Super+3"),
            ("Computer, workspace four", "Super+4"),
            ("Computer, move to workspace one", "Super+Shift+1"),
            ("Computer, move to workspace two", "Super+Shift+2"),
            ("Computer, move to workspace three", "Super+Shift+3"),
            ("Computer, move to workspace four", "Super+Shift+4"),
            
            ("FUNCTION KEYS", ""),
            ("Computer, press F1-F12", "F1...F12"),
            
            ("MARKDOWN", ""),
            ("Computer, bold text", "Ctrl+B"),
            ("Computer, italic text", "Ctrl+I"),
            ("Computer, underline text", "Ctrl+U"),
            ("Computer, insert link", "Ctrl+K"),
            
            ("TERMINAL", ""),
            ("Computer, clear terminal", "Ctrl+L"),
            ("Computer, stop process", "Ctrl+C"),
            ("Computer, exit terminal", "Ctrl+D"),
            
            ("KEYS", ""),
            ("Computer, press enter", "Enter"),
            ("Computer, press escape", "Esc"),
            ("Computer, press tab", "Tab"),
            ("Computer, press space", "Space"),
            ("Computer, press backspace", "Backspace"),
            ("Computer, press delete", "Delete"),
            
            ("ARROWS", ""),
            ("Computer, press up/down/left/right", "Arrow Keys"),
            
            ("APPS EXTRA", ""),
            ("Computer, open spotify", "Spotify"),
            ("Computer, open discord", "Discord"),
            ("Computer, open code", "VS Code"),
            ("Computer, open tweaks", "Gnome Tweaks"),
            ("Computer, open weather", "Gnome Weather"),

            ("MODES", ""),
            ("Focus Mode (Silence)", "Auto-records when you speak"),
            ("Manual Mode (Ctrl+')", "Toggle recording on/off")
        ]
        
        self.table.setRowCount(len(commands))
        for i, (trig, act) in enumerate(commands):
            self.table.setItem(i, 0, QTableWidgetItem(trig))
            self.table.setItem(i, 1, QTableWidgetItem(act))

class CommandEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10,10,10,10)
        
        # Close Button
        btn_close = QPushButton("CLOSE DRAWER")
        btn_close.setStyleSheet("background-color: #333; color: #FFF; border: 1px solid #555;")
        btn_close.clicked.connect(lambda: self.parent().toggle() if hasattr(self.parent(), 'toggle') else None)
        layout.addWidget(btn_close)
        
        layout.addWidget(QLabel("ADD NEW COMMAND"))
        
        # Inputs (Moved to Top)
        form = QGridLayout()
        form.addWidget(QLabel("Trigger:"), 0, 0)
        self.inp_trigger = QTextEdit()
        self.inp_trigger.setMaximumHeight(30)
        self.inp_trigger.setPlaceholderText("e.g. 'open my folder'")
        form.addWidget(self.inp_trigger, 0, 1)
        
        form.addWidget(QLabel("Action:"), 1, 0)
        self.inp_action = QTextEdit()
        self.inp_action.setMaximumHeight(30)
        self.inp_action.setPlaceholderText("e.g. '!nautilus /home' or 'CTRL+C'")
        form.addWidget(self.inp_action, 1, 1)
        
        layout.addLayout(form)
        
        # Add Button (Top)
        btn_add = QPushButton("ADD COMMAND")
        btn_add.setStyleSheet("background-color: #00C8FF; color: black; font-weight: bold; padding: 5px;")
        btn_add.clicked.connect(self.add_command)
        layout.addWidget(btn_add)
        
        layout.addWidget(QLabel("EXISTING COMMANDS"))
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Trigger", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        layout.addWidget(self.table)
        
        # Remove Button (Bottom)
        btn_del = QPushButton("REMOVE SELECTED")
        btn_del.clicked.connect(self.remove_command)
        layout.addWidget(btn_del)
        
    def load_commands(self, macros):
        self.table.setRowCount(0)
        
        # 1. User Macros
        for trig, act in macros.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(trig))
            self.table.setItem(row, 1, QTableWidgetItem(act))
            
        # 2. System Commands (Read-Only / Reference)
        # We'll add a separator or just list them
        # For now, just listing them.
        
        system_cmds = [
            ("open firefox", "Launch Firefox"),
            ("open terminal", "Launch Terminal"),
            ("open file manager", "Launch Nautilus"),
            ("open calculator", "Launch Calculator"),
            ("open editor", "Launch Text Editor"),
            ("lock screen", "Lock System"),
            ("take screenshot", "Gnome Screenshot"),
            ("volume up/down/mute", "Media Control"),
            ("next/previous track", "Media Control"),
            ("play/pause music", "Media Control"),
            ("insert date/time", "Type Date/Time"),
            ("new tab", "CTRL+T"),
            ("close tab", "CTRL+W"),
            ("copy/paste/cut", "CTRL+C/V/X"),
            ("select all", "CTRL+A"),
            ("undo/redo", "CTRL+Z / CTRL+SHIFT+Z"),
            ("save file", "CTRL+S"),
            ("find text", "CTRL+F"),
            ("switch window", "ALT+TAB"),
            ("show desktop", "SUPER+D"),
            ("run command", "ALT+F2"),
            ("workspace one/two...", "Switch Workspace"),
            ("move to workspace...", "Move Window"),
            ("press f1-f12", "Function Keys"),
            ("scroll up/down", "Mouse Scroll"),
            ("click/right click", "Mouse Click"),
            ("stop listening", "Pause Daemon"),
            ("shutdown system", "Power Off"),
            ("git status/pull/push", "Git Commands"),
            ("npm start/test", "NPM Commands"),
            ("list files", "ls -la"),
            ("change directory", "cd"),
            ("make directory", "mkdir"),
            ("open spotify/discord/code", "Launch Apps"),
            ("brightness up/down", "Screen Brightness"),
            ("wifi/bluetooth on/off", "Hardware Control"),
            ("heading one/two...", "Markdown Headers"),
            ("checkbox/list", "Markdown Lists"),
            ("code fence", "Markdown Code Block"),
        ]
        
        for trig, act in system_cmds:
            row = self.table.rowCount()
            self.table.insertRow(row)
            item_trig = QTableWidgetItem(trig)
            item_act = QTableWidgetItem(act)
            # Gray out system commands to indicate they are built-in
            item_trig.setForeground(QColor("#888"))
            item_act.setForeground(QColor("#888"))
            item_trig.setFlags(item_trig.flags() ^ Qt.ItemIsEditable)
            item_act.setFlags(item_act.flags() ^ Qt.ItemIsEditable)
            
            self.table.setItem(row, 0, item_trig)
            self.table.setItem(row, 1, item_act)
        
        self.table.resizeRowsToContents()
            
    def add_command(self):
        trig = self.inp_trigger.toPlainText().strip().lower()
        act = self.inp_action.toPlainText().strip()
        if not trig or not act: return
        
        # Add to table (Top, before system commands?)
        # For simplicity, just append to macros dict and reload
        # But here we insert into table first
        
        row = 0 # Insert at top
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(trig))
        self.table.setItem(row, 1, QTableWidgetItem(act))
        
        self.inp_trigger.clear()
        self.inp_action.clear()
        
        # Trigger Save in Parent
        if self.parent() and hasattr(self.parent(), 'save_macros'):
            self.parent().save_macros()

    def remove_command(self):
        row = self.table.currentRow()
        if row >= 0:
            # Check if it's a system command (gray)
            item = self.table.item(row, 0)
            if item.foreground().color().name() == "#888888":
                return # Can't delete system commands
                
            self.table.removeRow(row)
            if self.parent() and hasattr(self.parent(), 'save_macros'):
                self.parent().save_macros()
                
    def get_macros(self):
        macros = {}
        # Only save non-system commands
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item.foreground().color().name() != "#888888":
                trig = item.text()
                act = self.table.item(i, 1).text()
                macros[trig] = act
        return macros
        for i in range(self.table.rowCount()):
            t = self.table.item(i, 0).text()
            a = self.table.item(i, 1).text()
            macros[t] = a
        return macros

class SettingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        
        # Header
        header_layout = QHBoxLayout()
        lbl_head = QLabel("SETTINGS")
        lbl_head.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px; background: #111;")
        header_layout.addWidget(lbl_head)
        
        btn_close = QPushButton("X")
        btn_close.setFixedSize(30, 30)
        btn_close.setStyleSheet("background-color: #333; color: #FFF; border: 1px solid #555; border-radius: 4px;")
        btn_close.clicked.connect(lambda: self.parent().toggle() if hasattr(self.parent(), 'toggle') else None)
        header_layout.addWidget(btn_close)
        
        layout.addLayout(header_layout)
        
        # Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        
        # --- GENERAL SETTINGS ---
        lbl_gen = QLabel("GENERAL")
        lbl_gen.setStyleSheet("color: #888; font-weight: bold; margin-top: 10px;")
        self.content_layout.addWidget(lbl_gen)
        
        # Theme Accent
        lbl_theme = QLabel("THEME ACCENT")
        lbl_theme.setObjectName("SectionLabel")
        self.content_layout.addWidget(lbl_theme)
        
        self.group_theme = QButtonGroup(self)
        self.group_theme.setExclusive(True)
        
        accents = [
            ("Cyan", "#00C8FF"),
            ("Amber", "#FFB000"),
            ("Emerald", "#00FF6A"),
            ("Rose", "#FF0055"),
            ("Violet", "#BD00FF")
        ]
        
        grid_theme = QGridLayout()
        for i, (name, col) in enumerate(accents):
            btn = QRadioButton(name)
            btn.setStyleSheet(f"color: {col}; font-weight: bold;")
            self.group_theme.addButton(btn)
            grid_theme.addWidget(btn, i // 2, i % 2)
            
            # Connect
            btn.clicked.connect(lambda checked, c=col: self.change_theme(c))
            
        self.content_layout.addLayout(grid_theme)
        
        # Background Theme
        lbl_bg = QLabel("BACKGROUND THEME")
        lbl_bg.setObjectName("SectionLabel")
        self.content_layout.addWidget(lbl_bg)
        
        self.combo_bg = QComboBox()
        self.combo_bg.addItems(["OLED Black", "Deep Gray", "Midnight Blue", "Cyber Dark"])
        self.combo_bg.currentTextChanged.connect(self.change_bg)
        self.content_layout.addWidget(self.combo_bg)
        
        # Audio
        lbl_audio = QLabel("AUDIO INPUT")
        lbl_audio.setObjectName("SectionLabel")
        self.content_layout.addWidget(lbl_audio)
        
        self.cb_input = QComboBox()
        self.cb_input.addItems(["Default System Input", "Microphone (USB)", "Headset"])
        self.content_layout.addWidget(self.cb_input)
        
        self.content_layout.addWidget(self.cb_input)
        
        # Manual Hotkeys
        lbl_hk = QLabel("MANUAL HOTKEYS")
        lbl_hk.setObjectName("SectionLabel")
        self.content_layout.addWidget(lbl_hk)
        
        hk_grid = QGridLayout()
        hk_grid.addWidget(QLabel("Start Recording:"), 0, 0)
        self.rec_start = HotkeyRecorder("F9")
        hk_grid.addWidget(self.rec_start, 0, 1)
        
        hk_grid.addWidget(QLabel("Stop Recording:"), 1, 0)
        self.rec_stop = HotkeyRecorder("F10")
        hk_grid.addWidget(self.rec_stop, 1, 1)
        
        self.content_layout.addLayout(hk_grid)
        
        # Behavior
        lbl_beh = QLabel("BEHAVIOR")
        lbl_beh.setObjectName("SectionLabel")
        self.content_layout.addWidget(lbl_beh)
        
        self.chk_tray = QCheckBox("Minimize to Tray")
        self.chk_tray.setChecked(True)
        self.content_layout.addWidget(self.chk_tray)
        
        self.chk_top = QCheckBox("Always on Top")
        self.chk_top.toggled.connect(self.toggle_top)
        self.content_layout.addWidget(self.chk_top)
        
        self.content_layout.addStretch()
        
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def change_theme(self, color):
        if self.parent() and self.parent().parent():
            mw = self.parent().parent().window() 
            if hasattr(mw, 'apply_theme'):
                mw.apply_theme(color)
                mw.save_config()
            
    def change_bg(self, bg_name):
        if self.parent() and self.parent().parent():
            mw = self.parent().parent().window()
            if hasattr(mw, 'apply_theme'):
                # Keep current Accent
                current_acc = getattr(mw, "current_accent", "#00C8FF")
                mw.apply_theme(current_acc, bg_name)
                mw.save_config()
                
    def toggle_top(self, checked):
        if self.parent() and self.parent().parent():
            mw = self.parent().parent().window()
            if checked: mw.setWindowFlags(mw.windowFlags() | Qt.WindowStaysOnTopHint)
            else: mw.setWindowFlags(mw.windowFlags() & ~Qt.WindowStaysOnTopHint)
            mw.show()

    def toggle_top(self, checked):
        mw = self.window()
        if mw:
            flags = mw.windowFlags()
            if checked: mw.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
            else: mw.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
            mw.show()

class HistoryWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Transcription History")
        self.resize(600, 400)
        layout = QVBoxLayout(self)
        
        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        layout.addWidget(self.text_view)
        
        self.load_history()
        
    def load_history(self):
        hist_path = os.path.join(os.path.dirname(CONFIG_PATH), "history.json")
        if os.path.exists(hist_path):
            with open(hist_path, 'r') as f:
                data = json.load(f)
                for entry in data:
                    self.text_view.append(f"[{entry['timestamp']}] {entry['text']}")
                    self.text_view.append("-" * 40)

# --- MAIN WINDOW UPDATES ---
# --- MAIN WINDOW UPDATES ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dex Dictate v3 - Starsilk Expansion")
        self.resize(1000, 750)
        
        self.current_accent = "#00C8FF"
        
        # System Tray
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon.fromTheme("audio-input-microphone"))
        self.tray_icon.setToolTip("Dex Dictate: OFFLINE")
        
        tray_menu = QMenu()
        action_show = tray_menu.addAction("Show Window")
        action_show.triggered.connect(self.showNormal)
        action_quit = tray_menu.addAction("Quit")
        action_quit.triggered.connect(self.quit_app)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
        self.daemon = DaemonClient()
        self.daemon.status_signal.connect(self.update_status)
        self.daemon.log_signal.connect(self.log)
        self.daemon.start()
        
        # Telemetry Client (New)
        self.telemetry_client = TelemetryClient(self)
        self.telemetry_client.telemetry_updated.connect(self.update_telemetry)
        
        self.history_win = None
        
        # External Top Bar
        self.topbar = TopBarWidget()
        self.topbar.mode_changed.connect(self.set_mode)
        self.topbar.show()
        
        self.init_ui()
        
        # Load Theme AFTER UI Init
        self.apply_theme(self.current_accent)
        
        self.macros = {}
        self.load_config()
        
    def quit_app(self):
        self.daemon.running = False
        self.tray_icon.hide()
        if hasattr(self, 'topbar'):
            self.topbar.close()
        QApplication.quit()

    def update_status(self, state, extra):
        try:
            # Update Top Bar
            color = "#555"
            if state == "CONNECTED":
                if extra == "REC":
                    color = "#D96F30"
                    if hasattr(self, 'topbar'):
                        self.topbar.update_status("RECORDING", color)
                    self.tray_icon.setIcon(QIcon.fromTheme("media-record"))
                else:
                    color = self.current_accent
                    if hasattr(self, 'topbar'):
                        self.topbar.update_status("IDLE", color)
                    self.tray_icon.setIcon(QIcon.fromTheme("audio-input-microphone"))
                
                # Sync Daemon Button
                if hasattr(self, 'btn_daemon'):
                    self.btn_daemon.setText("STOP DAEMON")
                    self.btn_daemon.setStyleSheet("background-color: #B33232; color: white; font-weight: bold;")
                    
            else:
                color = "#FF0000"
                if hasattr(self, 'topbar'):
                    self.topbar.update_status("OFFLINE", color)
                self.tray_icon.setIcon(QIcon.fromTheme("network-offline"))
                
                # Sync Daemon Button
                if hasattr(self, 'btn_daemon'):
                    self.btn_daemon.setText("START DAEMON")
                    self.btn_daemon.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold;")
                    
            self.tray_icon.setToolTip(f"Dex Dictate: {state} | {extra}")
        except RuntimeError:
            pass # Object deleted during shutdown

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        # Main Grid Layout
        main_layout = QGridLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        
        # --- LEFT COLUMN (Controls) ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(15)
        
        # 1. Header
        header_layout = QHBoxLayout()
        lbl_header = QLabel("DEX DICTATE V3")
        lbl_header.setObjectName("HeaderLabel")
        lbl_header.setStyleSheet("font-size: 18px; font-weight: bold; color: #00C8FF; margin-bottom: 10px;")
        header_layout.addWidget(lbl_header)
        
        btn_faq = QPushButton("HELP")
        btn_faq.setToolTip("Help & FAQ")
        btn_faq.setFixedSize(60, 30)
        btn_faq.setStyleSheet("background-color: #222; color: #FFF; border: 1px solid #555; border-radius: 4px; font-weight: bold; font-size: 12px;")
        btn_faq.clicked.connect(self.show_faq)
        header_layout.addWidget(btn_faq)
        header_layout.addStretch()
        
        left_layout.addLayout(header_layout)
        
        # 2. Operation Mode
        left_layout.addWidget(self._create_section_label("OPERATION MODE"))
        
        mode_group = QButtonGroup(self)
        self.btn_wake = QPushButton("WAKE WORD")
        self.btn_manual = QPushButton("MANUAL")
        self.btn_focus = QPushButton("FOCUS (VAD)")
        
        for btn in [self.btn_wake, self.btn_manual, self.btn_focus]:
            btn.setCheckable(True)
            btn.setObjectName("ModeButton")
            mode_group.addButton(btn)
            
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(self.btn_wake)
        mode_layout.addWidget(self.btn_manual)
        mode_layout.addWidget(self.btn_focus)
        left_layout.addLayout(mode_layout)
        
        mode_group.buttonClicked.connect(self.set_mode)
        
        # 3. Sensitivity
        left_layout.addWidget(self._create_section_label("SENSITIVITY"))
        self.slider_sens = QSlider(Qt.Horizontal)
        self.slider_sens.setRange(0, 100)
        self.slider_sens.setValue(70)
        self.slider_sens.valueChanged.connect(self.set_sens)
        left_layout.addWidget(self.slider_sens)
        
        # 4. Manual Hotkeys
        left_layout.addWidget(self._create_section_label("MANUAL HOTKEYS"))
        hk_layout = QHBoxLayout()
        hk_layout.addWidget(QLabel("Start:"))
        hk_layout.addWidget(QPushButton("Click to Set"))
        hk_layout.addWidget(QLabel("Stop:"))
        hk_layout.addWidget(QPushButton("Click to Set"))
        left_layout.addLayout(hk_layout)
        
        # 5. Subsystems (Buttons)
        left_layout.addWidget(self._create_section_label("SUBSYSTEMS"))
        
        sub_row1 = QHBoxLayout()
        btn_hist = QPushButton("HISTORY")
        btn_hist.setToolTip("View Transcription History")
        btn_cmd = QPushButton("COMMANDS")
        btn_cmd.setToolTip("Manage Voice Commands")
        btn_float = QPushButton("TOOLBAR")
        btn_float.setToolTip("Toggle Desktop Toolbar")
        
        btn_hist.clicked.connect(self.show_history)
        btn_cmd.clicked.connect(self.toggle_commands)
        btn_float.clicked.connect(self.toggle_topbar)
        
        sub_row1.addWidget(btn_hist)
        sub_row1.addWidget(btn_cmd)
        sub_row1.addWidget(btn_float)
        left_layout.addLayout(sub_row1)
        
        sub_row2 = QHBoxLayout()
        btn_clip = QPushButton("CLIPBOARD")
        btn_clip.setToolTip("View Clipboard History")
        btn_clip.clicked.connect(self.toggle_clipboard)
        btn_settings = QPushButton("SETTINGS")
        btn_settings.setToolTip("Configure Application")
        btn_settings.clicked.connect(self.toggle_settings)
        
        sub_row2.addWidget(btn_clip)
        sub_row2.addWidget(btn_settings)
        left_layout.addLayout(sub_row2)
        
        # 6. Daemon Control
        left_layout.addWidget(self._create_section_label("DAEMON CONTROL"))
        self.btn_daemon = QPushButton("STOP DAEMON")
        self.btn_daemon.setToolTip("Start/Stop Background Service")
        self.btn_daemon.setStyleSheet("background-color: #B33232; color: white; font-weight: bold;")
        self.btn_daemon.clicked.connect(self.toggle_daemon)
        left_layout.addWidget(self.btn_daemon)
        
        # 7. Test Input
        left_layout.addWidget(self._create_section_label("TEST INPUT"))
        self.test_input = QTextEdit()
        self.test_input.setMaximumHeight(60)
        self.test_input.setPlaceholderText("Type here to test injection...")
        left_layout.addWidget(self.test_input)
        
        btn_send = QPushButton("SEND TO ENGINE")
        btn_send.setToolTip("Simulate Voice Input")
        btn_send.clicked.connect(self.send_test_input)
        left_layout.addWidget(btn_send)
        
        left_layout.addStretch()
        
        # --- RIGHT COLUMN (Logs & Inspector) ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        
        # System Log
        right_layout.addWidget(self._create_section_label("SYSTEM LOG"))
        self.log_window = QTextEdit()
        self.log_window.setReadOnly(True)
        self.log_window.setStyleSheet("font-family: monospace; font-size: 11px; color: #00FF6A; background: #050505; border: 1px solid #333;")
        right_layout.addWidget(self.log_window)
        
        # Inspector
        right_layout.addWidget(self._create_section_label("INSPECTOR (TELEMETRY)"))
        
        # Audio Visualizer (Main Window)
        self.visualizer = AudioVisualizer(self, bars=40)
        right_layout.addWidget(self.visualizer)
        
        insp_grid = QGridLayout()
        insp_grid.addWidget(QLabel("VAD Energy:"), 0, 0)
        self.lbl_energy = QLabel("0.000")
        self.lbl_energy.setStyleSheet("color: #00FF6A; font-weight: bold;")
        insp_grid.addWidget(self.lbl_energy, 0, 1)
        
        insp_grid.addWidget(QLabel("VAD State:"), 1, 0)
        self.lbl_vad_state = QLabel("IDLE")
        insp_grid.addWidget(self.lbl_vad_state, 1, 1)
        
        insp_grid.addWidget(QLabel("ASR State:"), 2, 0)
        self.lbl_asr_state = QLabel("IDLE")
        insp_grid.addWidget(self.lbl_asr_state, 2, 1)
        
        right_layout.addLayout(insp_grid)
        
        self.inspector_text = QTextEdit()
        self.inspector_text.setMaximumHeight(100)
        self.inspector_text.setReadOnly(True)
        self.inspector_text.setStyleSheet("font-family: monospace; color: #555; font-size: 10px; background: #000;")
        right_layout.addWidget(self.inspector_text)
        
        # Add columns to main grid
        main_layout.addWidget(left_panel, 0, 0)
        main_layout.addWidget(right_panel, 0, 1)
        main_layout.setColumnStretch(0, 1)
        main_layout.setColumnStretch(1, 2) # Log area wider
        
        # --- Drawers (Hidden) ---
        # Settings Drawer (Right)
        self.drawer_settings = SlidingDrawer(central, "RIGHT", 400)
        self.settings_panel = SettingsPanel(self.drawer_settings)
        self.drawer_settings.layout.addWidget(self.settings_panel)
        
        # Commands Drawer (Left)
        self.drawer_commands = SlidingDrawer(central, "LEFT", 400)
        self.cmd_editor = CommandEditor(self.drawer_commands)
        self.drawer_commands.layout.addWidget(self.cmd_editor)
        
        # Clipboard Drawer (Left)
        self.drawer_clipboard = SlidingDrawer(central, "LEFT", 400)
        self.clipboard_widget = ClipboardWidget(self.drawer_clipboard)
        self.drawer_clipboard.layout.addWidget(self.clipboard_widget)

    def _create_section_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #00C8FF; font-weight: bold; margin-top: 10px; font-size: 12px;")
        return lbl

    def toggle_topbar(self):
        if hasattr(self, 'topbar'):
            if self.topbar.isVisible(): self.topbar.hide()
            else: self.topbar.show()
            
            # Sync Mode Buttons
            self.topbar.mode_changed.connect(self.set_mode)
            self.set_mode(self.current_mode if hasattr(self, 'current_mode') else "WAKE")

    def toggle_daemon(self):
        if self.daemon.connected:
            # Stop Daemon
            subprocess.run(["systemctl", "--user", "stop", "dex-dictate"])
            self.btn_daemon.setText("START DAEMON")
            self.btn_daemon.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold;")
        else:
            # Start Daemon
            subprocess.run(["systemctl", "--user", "start", "dex-dictate"])
            self.btn_daemon.setText("STOP DAEMON")
            self.btn_daemon.setStyleSheet("background-color: #B33232; color: white; font-weight: bold;")

    def toggle_clipboard(self):
        # Close others if opening
        if not self.drawer_clipboard.is_open:
            if self.drawer_settings.is_open: self.drawer_settings.toggle()
            if self.drawer_commands.is_open: self.drawer_commands.toggle()
        self.drawer_clipboard.toggle()

    def closeEvent(self, event):
        # Clean shutdown
        self.daemon.running = False
        if hasattr(self, 'topbar'):
            self.topbar.close()
        event.accept()

    def show_history(self):
        if not self.history_win:
            self.history_win = HistoryWindow(self)
        self.history_win.show()

    def send_test_input(self):
        text = self.test_input.toPlainText()
        if text:
            # Mock injection via daemon
            self.log(f"Injecting: {text}")
            self.test_input.clear()

    def toggle_settings(self):
        self.drawer_settings.toggle()
        
    def toggle_commands(self):
        # Close others if opening
        if not self.drawer_commands.is_open:
            if self.drawer_settings.is_open: self.drawer_settings.toggle()
            if self.drawer_clipboard.is_open: self.drawer_clipboard.toggle()
        self.drawer_commands.toggle()

    def apply_theme(self, accent_color, bg_theme="OLED Black"):
        self.current_accent = accent_color
        self.current_bg_theme = bg_theme
        
        # Define Background Colors
        bg_colors = {
            "OLED Black": ("#000000", "#050505"),
            "Deep Gray": ("#101010", "#181818"),
            "Midnight Blue": ("#050510", "#0A0A18"),
            "Cyber Dark": ("#000505", "#001010")
        }
        
        bg_main, bg_alt = bg_colors.get(bg_theme, ("#000000", "#050505"))
        
        try:
            with open(STYLESHEET_PATH, 'r') as f:
                qss = f.read()
                
                c = QColor(accent_color)
                accent_dim = f"rgba({c.red()}, {c.green()}, {c.blue()}, 0.2)"
                accent_bright = accent_color 
                
                qss = qss.replace("{{ACCENT}}", accent_color)
                qss = qss.replace("{{ACCENT_BRIGHT}}", accent_bright)
                qss = qss.replace("{{ACCENT_DIM}}", accent_dim)
                qss = qss.replace("{{BACKGROUND}}", bg_main)
                qss = qss.replace("{{BACKGROUND_ALT}}", bg_alt)
                
                self.setStyleSheet(qss)
                if hasattr(self, 'topbar'):
                    self.topbar.setStyleSheet(qss)
                    self.topbar.update_status("IDLE", accent_color)
                    
                self.log(f"Theme applied: {accent_color} | {bg_theme}")
        except Exception as e:
            print(f"Theme Error: {e}")

    def update_status(self, state, extra):
        try:
            # Update Top Bar
            color = "#555"
            if state == "CONNECTED":
                if extra == "REC":
                    color = "#D96F30"
                    if hasattr(self, 'topbar'):
                        self.topbar.update_status("RECORDING", color)
                    self.tray_icon.setIcon(QIcon.fromTheme("media-record"))
                else:
                    color = self.current_accent
                    if hasattr(self, 'topbar'):
                        self.topbar.update_status("IDLE", color)
                    self.tray_icon.setIcon(QIcon.fromTheme("audio-input-microphone"))
            else:
                color = "#FF0000"
                if hasattr(self, 'topbar'):
                    self.topbar.update_status("OFFLINE", color)
                self.tray_icon.setIcon(QIcon.fromTheme("network-offline"))
                
            # Sync Daemon Button
            if hasattr(self, 'btn_daemon'):
                if state == "CONNECTED":
                    self.btn_daemon.setText("STOP DAEMON")
                    self.btn_daemon.setStyleSheet("background-color: #B33232; color: white; font-weight: bold;")
                else:
                    self.btn_daemon.setText("START DAEMON")
                    self.btn_daemon.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold;")
                
            self.tray_icon.setToolTip(f"Dex Dictate: {state} | {extra}")
        except RuntimeError:
            pass # Object deleted during shutdown

    def poll_telemetry(self):
        if self.daemon.connected:
            self.daemon.send_cmd("GET_TELEMETRY")

    def update_telemetry(self, data):
        # Update Inspector Grid
        energy = data.get('vad_energy', 0.0)
        vad_state = data.get('vad_state', 'idle')
        asr_state = data.get('asr_state', 'idle')
        
        self.lbl_energy.setText(f"{energy:.3f}")
        self.lbl_vad_state.setText(vad_state.upper())
        self.lbl_asr_state.setText(asr_state.upper())
        
        # Update Visualizers
        # Normalize energy (assuming 0.0 to 0.1 range roughly, clamp to 1.0)
        level = min(1.0, energy * 10) 
        if hasattr(self, 'visualizer'):
            self.visualizer.update_level(level)
        if hasattr(self, 'topbar'):
            self.topbar.update_audio(level)
        
        # Update Text Log with details
        # (Optional: Only log if state changes to avoid spam)
        if asr_state == "injecting":
             self.inspector_text.append(f"Injecting: {data.get('last_final', '')}")
             sb = self.inspector_text.verticalScrollBar()
             sb.setValue(sb.maximum())

    def show_history(self):
        self.history_win = HistoryWindow(self)
        self.history_win.show()
        
    def show_commands(self):
        self.cmd_win = CommandListWindow(self)
        self.cmd_win.show()

    def show_faq(self):
        msg = QMessageBox()
        msg.setWindowTitle("Dex Dictate FAQ")
        msg.setText("<h3>Dex Dictate v3 Help</h3>"
                    "<p><b>Q: How do I start dictating?</b><br>"
                    "A: Use the 'Wake Word' mode and say 'Computer', or use 'Manual' mode and press the hotkey (default F9).</p>"
                    "<p><b>Q: How do I add commands?</b><br>"
                    "A: Open the 'COMMANDS' drawer and use the 'Add Command' form at the top.</p>"
                    "<p><b>Q: Why isn't it typing?</b><br>"
                    "A: Ensure the daemon is running (Green 'CONNECTED' status) and you have a text field focused.</p>"
                    "<p><b>Q: Can I change the theme?</b><br>"
                    "A: Yes, open 'SETTINGS' and select a new accent color and background.</p>")
        msg.setStyleSheet(f"QLabel {{ color: #ddd; }} QMessageBox {{ background-color: {self.current_bg_theme if hasattr(self, 'current_bg_theme') and self.current_bg_theme == 'OLED Black' else '#222'}; }}")
        msg.exec()

    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r') as f:
                    config = json.load(f)
                    accent = config.get("theme_accent", "#00C8FF")
                    bg_theme = config.get("theme_bg", "OLED Black")
                    self.apply_theme(accent, bg_theme)
                    
                    # Load Hotkeys
                    hk_start = config.get("hotkey_start", "F9")
                    hk_stop = config.get("hotkey_stop", "F10")
                    if hasattr(self, 'settings_panel'):
                        self.settings_panel.rec_start.setText(hk_start)
                        self.settings_panel.rec_stop.setText(hk_stop)
                        
                    # Load Macros
                    self.macros = config.get("macros", {})
                    self.cmd_editor.load_commands(self.macros)
                    
                self.log("Config loaded.")
            except Exception as e:
                self.log(f"Load Config Error: {e}")

    def save_config(self):
        config = {
            "mode": self.current_mode,
            "theme_accent": self.current_accent,
            "theme_bg": getattr(self, "current_bg_theme", "OLED Black"),
            "macros": self.macros,
            "hotkey_start": self.settings_panel.rec_start.text() if hasattr(self, 'settings_panel') else "F9",
            "hotkey_stop": self.settings_panel.rec_stop.text() if hasattr(self, 'settings_panel') else "F10"
        }
        try:
            with open(CONFIG_PATH, 'w') as f:
                json.dump(config, f, indent=4)
            self.log("Config saved.")
            
            # Notify Daemon to Reload
            if self.daemon.connected:
                self.daemon.send_cmd("RELOAD_CONFIG")
                
        except Exception as e:
            self.log(f"Save Config Error: {e}")

    def toggle_daemon(self):
        self.btn_daemon.setEnabled(False)
        self.btn_daemon.setText("WORKING...")
        QApplication.processEvents()
        
        if self.daemon.connected:
            # Stop Daemon
            subprocess.run(["systemctl", "--user", "stop", "dex-dictate"])
            # Wait for disconnection signal to update UI
        else:
            # Start Daemon
            subprocess.run(["systemctl", "--user", "start", "dex-dictate"])
            # Wait for connection signal to update UI
            
        # Re-enable after short delay to prevent spam
        QTimer.singleShot(2000, lambda: self.btn_daemon.setEnabled(True))

    def set_mode(self, arg):
        mode = "WAKE"
        
        # Determine Mode from Argument or State
        if isinstance(arg, str):
            mode = arg
        else:
            # Called from Local Button Click
            if self.btn_wake.isChecked(): mode = "WAKE"
            elif self.btn_manual.isChecked(): mode = "MANUAL"
            elif self.btn_focus.isChecked(): mode = "FOCUS"
            
        # Update Local Buttons (Visually)
        self.btn_wake.setChecked(mode == "WAKE")
        self.btn_manual.setChecked(mode == "MANUAL")
        self.btn_focus.setChecked(mode == "FOCUS")
            
        # Update TopBar (Visually)
        if hasattr(self, 'topbar'):
            self.topbar.set_mode(mode)
            
        self.save_config()
        self.daemon.send_cmd(f"SET_MODE:{mode}")
        self.log(f"Mode set to {mode}")

    def set_sens(self):
        val = self.slider_sens.value() / 100.0
        self.daemon.send_cmd(f"SET_SENS:{val}")
        
    def send_test_input(self):
        text = self.test_input.toPlainText()
        if text:
            # Mock injection via daemon
            self.log(f"Injecting: {text}")
            self.test_input.clear()

    def log(self, msg):
        # Dedup: Don't log if same as last message
        if not hasattr(self, 'last_log_msg'): self.last_log_msg = ""
        if msg == self.last_log_msg: return
        self.last_log_msg = msg
        
        # History
        if msg.startswith("Transcribed: "):
            text = msg.replace("Transcribed: ", "")
            if hasattr(self, 'page_history') and hasattr(self.page_history, 'add_item'):
                self.page_history.add_item(text)
        
        ts = time.strftime("%H:%M:%S")
        if hasattr(self, 'log_window'):
            self.log_window.append(f"[{ts}] {msg}")
            # Scroll to bottom
            sb = self.log_window.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _init_dashboard(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(20,20,20,20)
        
        layout.addWidget(QLabel("DASHBOARD"))
        
        # Sensitivity Slider
        layout.addWidget(QLabel("Microphone Sensitivity"))
        self.slider_sens = QSlider(Qt.Horizontal)
        self.slider_sens.setRange(1, 100)
        self.slider_sens.setValue(70)
        self.slider_sens.valueChanged.connect(self.set_sens)
        layout.addWidget(self.slider_sens)
        
        # Test Input
        layout.addWidget(QLabel("Test Input Injection"))
        input_row = QHBoxLayout()
        self.test_input = QTextEdit()
        self.test_input.setMaximumHeight(40)
        self.test_input.setPlaceholderText("Type text to inject...")
        input_row.addWidget(self.test_input)
        
        btn_send = QPushButton("SEND")
        btn_send.setFixedSize(60, 40)
        btn_send.clicked.connect(self.send_test_input)
        input_row.addWidget(btn_send)
        layout.addLayout(input_row)
        
        layout.addStretch()

    def change_page(self, index):
        self.stack.setCurrentIndex(index)

    def closeEvent(self, event):
        # Minimize to tray behavior (Hide only)
        # self.daemon.running = False # Don't stop daemon
        # self.daemon.wait()
        self.hide()
        event.ignore() # Ignore close event to keep app running

from PySide6.QtGui import QKeySequence
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QPoint

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
