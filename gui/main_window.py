import sys
import os
import json
import time
import socket
import logging
import logging.handlers
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QSystemTrayIcon, QMenu, QSlider, QButtonGroup, 
                               QTextEdit, QApplication, QStackedWidget, QGridLayout)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject, QUrl
from PySide6.QtGui import QIcon, QDesktopServices, QColor

from gui.widgets import SlidingDrawer, AudioVisualizer, ToastOverlay
from gui.panels import HistoryPanel, ClipboardWidget, CommandEditor, SettingsPanel
from gui.dialogs import HistoryWindow, CommandListWindow
from strings import Strings

# --- CONSTANTS ---
CONFIG_PATH = os.path.expanduser("~/.config/dex-dictate/config.json")
STYLESHEET_PATH = os.path.join(os.path.dirname(__file__), "..", "starsilk.qss")
SOCKET_PATH = f"/run/user/{os.getuid()}/dex3.sock"

logger = logging.getLogger("dex_gui")



class MainWindow(QMainWindow):
    request_daemon_cmd = Signal(str) # Request orchestrator to send cmd
    request_toggle_bar = Signal() # Request orchestrator to toggle DexBar

    def __init__(self, state_manager):
        super().__init__()
        self.state_manager = state_manager
        self.setWindowTitle(Strings.APP_TITLE)
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
        
        self.history_win = None
        
        self.init_ui()
        
        # Connect State Manager
        self.state_manager.status_changed.connect(self.update_status)
        self.state_manager.mode_changed.connect(self.on_mode_changed)
        self.state_manager.audio_level_changed.connect(self.update_audio)
        self.state_manager.config_changed.connect(self.on_config_changed)
        
        # Initial State
        self.load_config()
        self.apply_theme(self.current_accent)
        
        # Toast Overlay
        self.toast = ToastOverlay(self)

    def closeEvent(self, event):
        # Persistence: Hide instead of close if enabled
        # For now, always hide as per requirement "Main GUI window is closed... Dex Bar must remain visible"
        # Unless we explicitly quit.
        self.hide()
        event.ignore()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        # Main Container Layout (Vertical)
        container_layout = QVBoxLayout(central)
        container_layout.setContentsMargins(0,0,0,0)
        container_layout.setSpacing(0)
        
        # 1. Top Bar (Header) removed - using DexBar
        # container_layout.addWidget(self.topbar)
        
        # 2. Main Content Layout (Horizontal split: Sidebar | Content)
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0,0,0,0)
        main_layout.setSpacing(0)
        container_layout.addLayout(main_layout)
        
        # --- LEFT SIDEBAR (Navigation & Controls) ---
        sidebar = QWidget()
        sidebar.setObjectName("NavSidebar")
        sidebar.setFixedWidth(320) # Increased from 300 to 320
        left_layout = QVBoxLayout(sidebar)
        left_layout.setContentsMargins(10, 20, 10, 20) # Reduced side margins
        left_layout.setSpacing(15)
        
        # 1. Header
        header_layout = QHBoxLayout()
        lbl_header = QLabel(Strings.APP_TITLE)
        lbl_header.setObjectName("HeaderLabel")
        lbl_header.setStyleSheet("font-size: 18px; font-weight: bold; color: #00C8FF; margin-bottom: 10px;")
        header_layout.addWidget(lbl_header)
        
        btn_faq = QPushButton(Strings.BTN_HELP)
        btn_faq.setToolTip(Strings.TT_HELP)
        btn_faq.setAccessibleName(Strings.A11Y_HELP)
        btn_faq.setFixedSize(60, 30)
        btn_faq.setStyleSheet("background-color: #222; color: #FFF; border: 1px solid #555; border-radius: 4px; font-weight: bold; font-size: 12px;")
        btn_faq.clicked.connect(self.show_faq)
        header_layout.addWidget(btn_faq)
        
        left_layout.addLayout(header_layout)
        
        # 2. Operation Mode
        left_layout.addWidget(self._create_section_label(Strings.HDR_OP_MODE))
        
        mode_group = QButtonGroup(self)
        mode_group.setObjectName("mode_group") # For finding by child
        self.btn_wake = QPushButton(Strings.MODE_WAKE)
        self.btn_manual = QPushButton(Strings.MODE_MANUAL)
        self.btn_focus = QPushButton(Strings.MODE_FOCUS)
        
        for btn in [self.btn_wake, self.btn_manual, self.btn_focus]:
            btn.setCheckable(True)
            btn.setObjectName("ModeButton")
            btn.setCursor(Qt.PointingHandCursor)
            mode_group.addButton(btn)
            left_layout.addWidget(btn)
            
        self.btn_wake.setChecked(True)
        
        # Connect signals
        mode_group.buttonClicked.connect(self.set_mode)
        
        # 3. Sensitivity
        left_layout.addWidget(self._create_section_label(Strings.HDR_SENSITIVITY))
        self.slider_sens = QSlider(Qt.Horizontal)
        self.slider_sens.setRange(0, 100)
        self.slider_sens.setValue(70)
        self.slider_sens.setAccessibleName(Strings.A11Y_SENSITIVITY)
        self.slider_sens.setAccessibleDescription(Strings.A11Y_DESC_SENSITIVITY)
        self.slider_sens.valueChanged.connect(self.set_sens)
        left_layout.addWidget(self.slider_sens)
        
        # 4. Manual Hotkeys
        left_layout.addWidget(self._create_section_label(Strings.HDR_MANUAL_HK))
        hk_layout = QHBoxLayout()
        hk_layout.addWidget(QLabel("Start:"))
        hk_layout.addWidget(QPushButton("Click to Set")) # Placeholder for now, logic in SettingsPanel
        left_layout.addLayout(hk_layout)
        
        # 5. Subsystems (Buttons) - Using Grid for better fit
        left_layout.addWidget(self._create_section_label(Strings.HDR_SUBSYSTEMS))
        
        sub_grid = QGridLayout()
        sub_grid.setSpacing(8)
        
        btn_hist = QPushButton(Strings.BTN_HISTORY)
        btn_hist.setToolTip(Strings.TT_HISTORY)
        btn_hist.setAccessibleName(Strings.A11Y_OPEN_HIST)
        
        btn_cmd = QPushButton(Strings.BTN_COMMANDS)
        btn_cmd.setToolTip(Strings.TT_COMMANDS)
        btn_cmd.setAccessibleName(Strings.A11Y_OPEN_CMD)
        
        btn_float = QPushButton(Strings.BTN_TOOLBAR)
        btn_float.setToolTip(Strings.TT_TOOLBAR)
        btn_float.setAccessibleName(Strings.A11Y_TOGGLE_BAR)
        
        btn_clip = QPushButton(Strings.BTN_CLIPBOARD)
        btn_clip.setToolTip(Strings.TT_CLIPBOARD)
        btn_clip.setAccessibleName(Strings.A11Y_OPEN_CLIP)
        
        btn_settings = QPushButton(Strings.BTN_SETTINGS)
        btn_settings.setToolTip(Strings.TT_SETTINGS)
        btn_settings.setAccessibleName(Strings.A11Y_OPEN_SETTINGS)
        
        # Connect
        btn_hist.clicked.connect(self.show_history)
        btn_cmd.clicked.connect(self.toggle_commands)
        btn_float.clicked.connect(self.request_toggle_bar.emit)
        btn_clip.clicked.connect(self.toggle_clipboard)
        btn_settings.clicked.connect(self.toggle_settings)
        
        # Add to Grid (Row, Col)
        # Row 0: History, Commands
        sub_grid.addWidget(btn_hist, 0, 0)
        sub_grid.addWidget(btn_cmd, 0, 1)
        
        # Row 1: Clipboard, Settings
        sub_grid.addWidget(btn_clip, 1, 0)
        sub_grid.addWidget(btn_settings, 1, 1)
        
        # Row 2: Toolbar (Full Width)
        sub_grid.addWidget(btn_float, 2, 0, 1, 2)
        
        left_layout.addLayout(sub_grid)
        
        # 6. Daemon Control
        left_layout.addWidget(self._create_section_label(Strings.HDR_DAEMON_CTRL))
        self.btn_daemon = QPushButton(Strings.BTN_STOP_DAEMON)
        self.btn_daemon.setToolTip(Strings.TT_DAEMON)
        self.btn_daemon.setAccessibleName(Strings.A11Y_TOGGLE_DAEMON)
        self.btn_daemon.setStyleSheet("background-color: #B33232; color: white; font-weight: bold;")
        self.btn_daemon.clicked.connect(self.toggle_daemon)
        left_layout.addWidget(self.btn_daemon)
        
        # 7. Test Input
        left_layout.addWidget(self._create_section_label(Strings.HDR_TEST_INPUT))
        self.test_input = QTextEdit()
        self.test_input.setMaximumHeight(60)
        self.test_input.setPlaceholderText("Type here to test injection...")
        self.test_input.setAccessibleName(Strings.A11Y_TEST_INPUT)
        left_layout.addWidget(self.test_input)
        
        btn_send = QPushButton(Strings.BTN_SEND_TEST)
        btn_send.setToolTip(Strings.TT_SEND_TEST)
        btn_send.setAccessibleName(Strings.A11Y_SEND_TEST)
        btn_send.clicked.connect(self.send_test_input)
        left_layout.addWidget(btn_send)
        
        left_layout.addStretch()
        
        # Add Sidebar to Main Layout
        main_layout.addWidget(sidebar)
        
        # --- RIGHT CONTENT AREA ---
        content_area = QWidget()
        right_layout = QVBoxLayout(content_area)
        right_layout.setContentsMargins(20, 20, 20, 20)
        right_layout.setSpacing(10)
        
        # System Log
        right_layout.addWidget(self._create_section_label(Strings.HDR_SYS_LOG))
        self.log_window = QTextEdit()
        self.log_window.setReadOnly(True)
        self.log_window.setAccessibleName(Strings.A11Y_LOG_OUT)
        self.log_window.setStyleSheet("font-family: monospace; font-size: 11px; color: #00FF6A; background: #050505; border: 1px solid #333;")
        right_layout.addWidget(self.log_window)
        
        # Inspector
        right_layout.addWidget(self._create_section_label(Strings.HDR_INSPECTOR))
        
        # Audio Visualizer (Main Window)
        self.visualizer = AudioVisualizer(self, bars=40)
        self.visualizer.setFixedHeight(100)
        right_layout.addWidget(self.visualizer)
        
        main_layout.addWidget(content_area)
        
        # --- DRAWERS (Overlays) ---
        # Stacked on top of right content? Or sliding from right?
        # In original code, they were added to the main layout or a stack.
        # Let's use the SlidingDrawer approach from original code.
        
        # Container for drawers (Overlay on top of content_area)
        # For simplicity in this refactor, we'll add them to the main_layout and let them animate width.
        
        self.drawer_history = SlidingDrawer(self, width=350)
        self.hist_panel = HistoryPanel(self.drawer_history)
        QVBoxLayout(self.drawer_history).addWidget(self.hist_panel)
        main_layout.addWidget(self.drawer_history)
        
        self.drawer_commands = SlidingDrawer(self, width=400)
        self.cmd_editor = CommandEditor(self.drawer_commands)
        QVBoxLayout(self.drawer_commands).addWidget(self.cmd_editor)
        main_layout.addWidget(self.drawer_commands)
        
        self.drawer_clipboard = SlidingDrawer(self, width=350)
        self.clip_widget = ClipboardWidget(self.drawer_clipboard)
        QVBoxLayout(self.drawer_clipboard).addWidget(self.clip_widget)
        main_layout.addWidget(self.drawer_clipboard)
        
        self.drawer_settings = SlidingDrawer(self, width=350)
        self.settings_panel = SettingsPanel(self.drawer_settings)
        QVBoxLayout(self.drawer_settings).addWidget(self.settings_panel)
        main_layout.addWidget(self.drawer_settings)

    def _create_section_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("SectionLabel")
        return lbl

    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.log_window.append(f"[{ts}] {msg}")
        # Also log to file via logger
        logger.info(msg)
        
        # Auto-scroll
        sb = self.log_window.verticalScrollBar()
        sb.setValue(sb.maximum())

    def handle_daemon_data(self, data):
        if data.startswith("DEVICES:"):
            devices_str = data[8:]
            if hasattr(self, 'settings_panel'):
                self.settings_panel.update_device_list(devices_str)

    def update_status(self, state, extra):
        try:
            # Update Top Bar
            color = "#555"
            if state == "CONNECTED":
                if extra == "REC":
                    color = "#D96F30"
                    if hasattr(self, 'topbar'):
                        self.topbar.update_status(Strings.STATUS_RECORDING, color)
                    self.tray_icon.setIcon(QIcon.fromTheme("media-record"))
                else:
                    color = self.current_accent
                    if hasattr(self, 'topbar'):
                        # Only show IDLE if not processing
                        if getattr(self, 'last_asr_state', 'idle') in ['idle', 'listening', 'silence']:
                            self.topbar.update_status(Strings.STATUS_IDLE, color)
                    self.tray_icon.setIcon(QIcon.fromTheme("audio-input-microphone"))
                
                # Sync Daemon Button
                if hasattr(self, 'btn_daemon'):
                    self.btn_daemon.setText(Strings.BTN_STOP_DAEMON)
                    self.btn_daemon.setStyleSheet("background-color: #B33232; color: white; font-weight: bold;")
                    
            else:
                color = "#FF0000"
                if hasattr(self, 'topbar'):
                    self.topbar.update_status(Strings.STATUS_OFFLINE, color)
                self.tray_icon.setIcon(QIcon.fromTheme("network-offline"))
                
                # Sync Daemon Button
                if hasattr(self, 'btn_daemon'):
                    self.btn_daemon.setText(Strings.BTN_START_DAEMON)
                    self.btn_daemon.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold;")
                    
            self.tray_icon.setToolTip(f"Dex Dictate: {state} | {extra}")
            self.last_asr_state = extra.lower()
            
        except RuntimeError:
            pass # Window closed

    def update_audio(self, level):
        self.visualizer.update_level(level)

    def on_mode_changed(self, mode):
        # Update UI to reflect mode
        self.btn_wake.setChecked(mode == "WAKE")
        self.btn_manual.setChecked(mode == "MANUAL")
        self.btn_focus.setChecked(mode == "FOCUS")

    def on_config_changed(self, config):
        # Reload relevant parts if needed
        pass

    def set_mode(self, btn):
        mode = "WAKE"
        if btn == self.btn_manual: mode = "MANUAL"
        elif btn == self.btn_focus: mode = "FOCUS"
        
        self.state_manager.set_mode(mode)
        self.request_daemon_cmd.emit(f"SET_MODE:{mode}")
        self.log(Strings.LOG_MODE_SET.format(mode))

    def set_sens(self):
        val = self.slider_sens.value() / 100.0
        self.request_daemon_cmd.emit(f"SET_SENS:{val:.2f}")

    def toggle_daemon(self):
        if self.btn_daemon.text() == Strings.BTN_STOP_DAEMON:
            self.request_daemon_cmd.emit("STOP")
        else:
            import subprocess
            subprocess.Popen(["systemctl", "--user", "start", "dex-dictate"])

    def send_test_input(self):
        text = self.test_input.toPlainText()
        if text:
            # Mock injection via daemon
            self.log(Strings.LOG_INJECTING.format(text))
            self.test_input.clear()

    def toggle_settings(self):
        self.drawer_settings.toggle()
        
    def toggle_settings(self):
        self.drawer_settings.toggle()
        
    # toggle_topbar removed (DexBar is always on or managed by orchestrator)
        
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
                    
                self.log(Strings.LOG_THEME.format(accent_color, bg_theme))
        except Exception as e:
            print(f"Theme Error: {e}")

    def show_history(self):
        if not self.history_win:
            self.history_win = HistoryWindow(self)
        self.history_win.show()
        
    def toggle_clipboard(self):
        # Close others
        if not self.drawer_clipboard.is_open:
            if self.drawer_settings.is_open: self.drawer_settings.toggle()
            if self.drawer_commands.is_open: self.drawer_commands.toggle()
        self.drawer_clipboard.toggle()

    def save_clipboard(self, last, pinned):
        # Save to config/state
        self.clipboard_data = {"last": last, "pinned": pinned}
        self.save_config()

    def save_macros(self):
        self.macros = self.cmd_editor.get_macros()
        self.save_config()

    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r') as f:
                    config = json.load(f)
                    
                self.macros = config.get("macros", {})
                self.cmd_editor.load_commands(self.macros)
                
                clip_data = config.get("clipboard", {"last": "", "pinned": ""})
                self.clip_widget.set_data(clip_data.get("last", ""), clip_data.get("pinned", ""))
                
                # Theme
                theme = config.get("theme", "#00C8FF")
                bg = config.get("bg_theme", "OLED Black")
                self.apply_theme(theme, bg)
                
                # Mode
                mode = config.get("mode", "WAKE")
                self.set_mode(self.btn_wake if mode == "WAKE" else self.btn_manual if mode == "MANUAL" else self.btn_focus)
                
            except Exception as e:
                logger.error(f"Config Load Error: {e}")

    def save_config(self):
        config = {
            "macros": getattr(self, 'macros', {}),
            "clipboard": getattr(self, 'clipboard_data', {}),
            "theme": self.current_accent,
            "bg_theme": getattr(self, 'current_bg_theme', "OLED Black"),
            "mode": self.state_manager.mode
        }
        try:
            # StateManager handles saving, but we might have extra UI state
            # For now, let's just update StateManager config
            self.state_manager.config.update(config)
            self.state_manager.save_config()
        except Exception as e:
            logger.error(f"Config Save Error: {e}")

    def show_faq(self):
        # Simple dialog
        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Help & FAQ")
        msg.setText("Dex Dictate v3\n\n- Wake Word: 'Computer'\n- Manual: F9 to Start, F10 to Stop\n- Focus: Auto-records speech")
        msg.setStyleSheet(self.styleSheet()) # Inherit theme
        msg.exec()

    def show_toast(self, msg):
        self.toast.show_message(msg)

    def quit_app(self):
        # Request orchestrator to quit
        QApplication.quit()
