from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                               QListWidget, QListWidgetItem, QMenu, QTextEdit, QGridLayout, 
                               QRadioButton, QComboBox, QCheckBox, QLineEdit, QApplication, QButtonGroup)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from gui.widgets import HotkeyRecorder
from strings import Strings
import os
import json
import time
import logging

logger = logging.getLogger("dex_gui")

class HistoryPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10,10,10,10)
        
        layout.addWidget(QLabel("TRANSCRIPT HISTORY"))
        
        self.list = QListWidget()
        self.list.setObjectName("HistoryList")
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.list)
        
        btn_clear = QPushButton(Strings.BTN_CLEAR_HIST)
        btn_clear.setAccessibleName(Strings.A11Y_CLEAR_HIST)
        btn_clear.clicked.connect(self.list.clear)
        layout.addWidget(btn_clear)
        
    def add_entry(self, text):
        ts = time.strftime("%H:%M:%S")
        item = QListWidgetItem(f"[{ts}] {text}")
        self.list.insertItem(0, item)
        # Limit history
        if self.list.count() > 50:
            self.list.takeItem(50)
            
    def show_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item: return
        
        menu = QMenu()
        action_copy = menu.addAction("Copy")
        action_type = menu.addAction("Re-type")
        action_del = menu.addAction("Delete")
        
        action = menu.exec(self.list.mapToGlobal(pos))
        
        if action == action_copy:
            text = item.text().split("] ", 1)[1]
            QApplication.clipboard().setText(text)
        elif action == action_type:
            text = item.text().split("] ", 1)[1]
            # Clean text
            clean_text = text.replace('"', '\\"').replace("'", "\\'")
            mw = QApplication.instance().activeWindow()
            if hasattr(mw, 'daemon'):
                mw.daemon.send_cmd(f"TYPE:{clean_text}")
                mw.show_toast(Strings.TOAST_REINJECT)
        elif action == action_del:
            self.list.takeItem(self.list.row(item))

class ClipboardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10,10,10,10)
        
        # Close Button
        btn_close = QPushButton(Strings.BTN_CLOSE_DRAWER)
        btn_close.setAccessibleName(Strings.A11Y_CLOSE_CLIP)
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
        btn_cap = QPushButton(Strings.BTN_CAPTURE)
        btn_cap.setAccessibleName(Strings.A11Y_CAP_CLIP)
        btn_cap.clicked.connect(self.capture_clipboard)
        btn_copy_last = QPushButton(Strings.BTN_COPY)
        btn_copy_last.setAccessibleName(Strings.A11Y_COPY_LAST)
        btn_copy_last.clicked.connect(lambda: QApplication.clipboard().setText(self.txt_last.toPlainText()))
        hbox1.addWidget(btn_cap)
        hbox1.addWidget(btn_copy_last)
        layout.addLayout(hbox1)
        
        # Pinned Note
        layout.addWidget(QLabel("PINNED NOTE (PERSISTENT)"))
        self.txt_pinned = QTextEdit()
        layout.addWidget(self.txt_pinned)
        
        hbox2 = QHBoxLayout()
        btn_save = QPushButton(Strings.BTN_SAVE_PINNED) # Auto-save on change? Yes, but button for reassurance
        btn_save.setAccessibleName(Strings.A11Y_SAVE_PIN)
        btn_save.clicked.connect(self.save_pinned)
        btn_copy_pinned = QPushButton(Strings.BTN_COPY)
        btn_copy_pinned.setAccessibleName(Strings.A11Y_COPY_PIN)
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

class CommandEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10,10,10,10)
        
        # Close Button
        btn_close = QPushButton(Strings.BTN_CLOSE_DRAWER)
        btn_close.setAccessibleName(Strings.A11Y_CLOSE_CMD)
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
        self.inp_trigger.setAccessibleName(Strings.A11Y_NEW_TRIG)
        form.addWidget(self.inp_trigger, 0, 1)
        
        form.addWidget(QLabel("Action:"), 1, 0)
        self.inp_action = QTextEdit()
        self.inp_action.setMaximumHeight(30)
        self.inp_action.setPlaceholderText("e.g. '!nautilus /home' or 'CTRL+C'")
        self.inp_action.setAccessibleName(Strings.A11Y_NEW_ACT)
        form.addWidget(self.inp_action, 1, 1)
        
        layout.addLayout(form)
        
        # Add Button (Top)
        btn_add = QPushButton(Strings.BTN_ADD_CMD)
        btn_add.setAccessibleName(Strings.A11Y_ADD_CMD)
        btn_add.setStyleSheet("background-color: #00C8FF; color: black; font-weight: bold; padding: 5px;")
        btn_add.clicked.connect(self.add_command)
        layout.addWidget(btn_add)
        
        # Search Bar
        self.inp_search = QLineEdit()
        self.inp_search.setPlaceholderText("Search commands...")
        self.inp_search.setAccessibleName(Strings.A11Y_SEARCH_CMD)
        self.inp_search.textChanged.connect(self.filter_commands)
        self.inp_search.setStyleSheet("background-color: #222; color: #EEE; border: 1px solid #444; padding: 5px;")
        layout.addWidget(self.inp_search)
        
        # List
        self.table = QListWidget()
        self.table.setStyleSheet("background-color: #111; border: 1px solid #333;")
        layout.addWidget(self.table)
        
        # Remove Button (Bottom)
        btn_del = QPushButton(Strings.BTN_REMOVE_CMD)
        btn_del.setAccessibleName(Strings.A11Y_REM_CMD)
        btn_del.clicked.connect(self.remove_command)
        layout.addWidget(btn_del)
        
        self.commands = {}
        self.system_commands = {} # Non-editable
        
    def load_commands(self, macros):
        self.commands = macros
        self.table.clear()
        
        # Load System Commands (Mock for now, or pass in)
        # For now, just load user macros
        for trig, act in self.commands.items():
            item = QListWidgetItem(f"{trig}  ➔  {act}")
            item.setData(Qt.UserRole, trig)
            self.table.addItem(item)
            
    def filter_commands(self, text):
        for i in range(self.table.count()):
            item = self.table.item(i)
            item.setHidden(text.lower() not in item.text().lower())
            
    def add_command(self):
        trig = self.inp_trigger.toPlainText().strip()
        act = self.inp_action.toPlainText().strip()
        
        if trig and act:
            self.commands[trig] = act
            self.load_commands(self.commands)
            self.inp_trigger.clear()
            self.inp_action.clear()
            
            # Save via parent
            if self.parent() and hasattr(self.parent(), 'save_macros'):
                self.parent().save_macros()
                mw = QApplication.instance().activeWindow()
                if hasattr(mw, 'show_toast'):
                    mw.show_toast(Strings.TOAST_CMD_ADDED)

    def remove_command(self):
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row)
            trig = item.data(Qt.UserRole)
            
            if trig in self.commands:
                del self.commands[trig]
                self.load_commands(self.commands)
                
                if self.parent() and hasattr(self.parent(), 'save_macros'):
                    self.parent().save_macros()
                    mw = QApplication.instance().activeWindow()
                    if hasattr(mw, 'show_toast'):
                        mw.show_toast(Strings.TOAST_CMD_REMOVED)
                
    def get_macros(self):
        macros = {}
        for trig, act in self.commands.items():
            macros[trig] = act
        return macros

class SettingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Scroll Area
        from PySide6.QtWidgets import QScrollArea
        
        # Header
        header_layout = QHBoxLayout()
        lbl_head = QLabel(Strings.TITLE_SETTINGS)
        lbl_head.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px; background: #111;")
        header_layout.addWidget(lbl_head)
        
        btn_close = QPushButton("X")
        btn_close.setFixedSize(30, 30)
        btn_close.setAccessibleName(Strings.A11Y_CLOSE_SET)
        btn_close.setStyleSheet("background-color: #333; color: #FFF; border: 1px solid #555; border-radius: 4px;")
        btn_close.clicked.connect(lambda: self.parent().toggle() if hasattr(self.parent(), 'toggle') else None)
        header_layout.addWidget(btn_close)
        
        # Main Layout
        main_layout = QVBoxLayout(self)
        main_layout.addLayout(header_layout)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        
        # --- GENERAL SETTINGS ---
        lbl_gen = QLabel(Strings.HDR_GEN_SETTINGS)
        lbl_gen.setStyleSheet("color: #888; font-weight: bold; margin-top: 10px;")
        self.content_layout.addWidget(lbl_gen)
        
        # Theme Accent
        lbl_theme = QLabel(Strings.HDR_THEME_ACCENT)
        lbl_theme.setObjectName("SectionLabel")
        self.content_layout.addWidget(lbl_theme)
        
        accents = [
            ("Cyan", "#00C8FF"),
            ("Amber", "#FFCC00"),
            ("Crimson", "#FF0055"),
            ("Lime", "#00FF6A"),
            ("Violet", "#AA00FF"),
            ("White", "#FFFFFF")
        ]
        
        self.group_theme = QButtonGroup(self)
        self.group_theme.setExclusive(True)
        
        grid_theme = QGridLayout()
        for i, (name, col) in enumerate(accents):
            btn = QRadioButton(name)
            btn.setAccessibleName(f"{Strings.A11Y_THEME_ACCENT}{name}")
            btn.setStyleSheet(f"color: {col}; font-weight: bold;")
            self.group_theme.addButton(btn)
            grid_theme.addWidget(btn, i // 2, i % 2)
            
            # Connect
            btn.clicked.connect(lambda checked, c=col: self.change_theme(c))
            
        self.content_layout.addLayout(grid_theme)
        
        # Background Theme
        lbl_bg = QLabel(Strings.HDR_BG_THEME)
        lbl_bg.setObjectName("SectionLabel")
        self.content_layout.addWidget(lbl_bg)
        
        self.combo_bg = QComboBox()
        self.combo_bg.setAccessibleName(Strings.A11Y_BG_THEME)
        self.combo_bg.addItems(["OLED Black", "Deep Gray", "Midnight Blue", "Cyber Dark"])
        self.combo_bg.currentTextChanged.connect(self.change_bg)
        self.content_layout.addWidget(self.combo_bg)
        
        # Audio
        lbl_audio = QLabel(Strings.HDR_AUDIO_INPUT)
        lbl_audio.setObjectName("SectionLabel")
        self.content_layout.addWidget(lbl_audio)
        
        self.cb_input = QComboBox()
        self.cb_input.setAccessibleName(Strings.A11Y_AUDIO_IN)
        # self.cb_input.addItems(["Default System Input", "Microphone (USB)", "Headset"]) # Removed placeholder
        self.cb_input.currentIndexChanged.connect(self.change_audio_device)
        self.content_layout.addWidget(self.cb_input)
        
        # Fetch devices
        QTimer.singleShot(1000, self.fetch_audio_devices)
        
        # Manual Hotkeys
        lbl_hk = QLabel(Strings.HDR_MANUAL_HK)
        lbl_hk.setObjectName("SectionLabel")
        self.content_layout.addWidget(lbl_hk)
        
        hk_grid = QGridLayout()
        hk_grid.addWidget(QLabel("Start Recording:"), 0, 0)
        self.rec_start = HotkeyRecorder("F9")
        self.rec_start.setAccessibleName(Strings.A11Y_REC_START)
        hk_grid.addWidget(self.rec_start, 0, 1)
        
        hk_grid.addWidget(QLabel("Stop Recording:"), 1, 0)
        self.rec_stop = HotkeyRecorder("F10")
        self.rec_stop.setAccessibleName(Strings.A11Y_REC_STOP)
        hk_grid.addWidget(self.rec_stop, 1, 1)
        
        self.content_layout.addLayout(hk_grid)
        
        # Config Management
        lbl_cfg = QLabel(Strings.HDR_CONFIG)
        lbl_cfg.setObjectName("SectionLabel")
        self.content_layout.addWidget(lbl_cfg)
        
        cfg_layout = QHBoxLayout()
        btn_export = QPushButton(Strings.BTN_EXPORT_CFG)
        btn_export.setAccessibleName(Strings.A11Y_EXPORT)
        btn_export.clicked.connect(self.export_config)
        cfg_layout.addWidget(btn_export)
        
        btn_import = QPushButton(Strings.BTN_IMPORT_CFG)
        btn_import.setAccessibleName(Strings.A11Y_IMPORT)
        btn_import.clicked.connect(self.import_config)
        cfg_layout.addWidget(btn_import)
        
        self.content_layout.addLayout(cfg_layout)
        
        # Behavior
        lbl_beh = QLabel(Strings.HDR_BEHAVIOR)
        lbl_beh.setObjectName("SectionLabel")
        self.content_layout.addWidget(lbl_beh)
        
        self.chk_tray = QCheckBox("Minimize to Tray")
        self.chk_tray.setAccessibleName(Strings.A11Y_TRAY)
        self.chk_tray.setChecked(True)
        self.content_layout.addWidget(self.chk_tray)
        
        self.content_layout.addStretch()
        
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def change_theme(self, color):
        mw = QApplication.instance().activeWindow()
        if hasattr(mw, 'apply_theme'):
            # Pass current bg theme if available
            bg = self.combo_bg.currentText()
            mw.apply_theme(color, bg)
            
    def change_bg(self, bg_name):
        mw = QApplication.instance().activeWindow()
        if hasattr(mw, 'apply_theme'):
            # Pass current accent
            accent = mw.current_accent if hasattr(mw, 'current_accent') else "#00C8FF"
            mw.apply_theme(accent, bg_name)

    def fetch_audio_devices(self):
        mw = QApplication.instance().activeWindow()
        if hasattr(mw, 'daemon'):
            # We need a way to get response. DaemonClient emits signals.
            # But here we are in a panel.
            # Ideally, we ask daemon to fetch, and daemon emits a signal that we listen to.
            # Or we use a direct socket call if we want it synchronous (blocking UI).
            # Let's use the signal approach if possible, or just send command and expect a log/status update?
            # Actually, DaemonClient in MainWindow handles receiving.
            # We need to hook into that.
            # For now, let's implement a simple direct socket query here for simplicity, 
            # or better: add a signal to MainWindow that we connect to.
            pass # TODO: Implement response handling
            
            # Alternative: Just send command and let MainWindow handle the "DEVICES:..." response
            mw.daemon.send_cmd("GET_DEVICES")

    def change_audio_device(self, index):
        if index < 0: return
        # Get device ID from user data
        dev_id = self.cb_input.itemData(index)
        if dev_id is not None:
            mw = QApplication.instance().activeWindow()
            if hasattr(mw, 'daemon'):
                mw.daemon.send_cmd(f"SET_DEVICE:{dev_id}")

    def update_device_list(self, devices_str):
        # devices_str format: "0:Name|1:Name2"
        self.cb_input.blockSignals(True)
        self.cb_input.clear()
        try:
            parts = devices_str.split("|")
            for p in parts:
                if ":" in p:
                    idx, name = p.split(":", 1)
                    self.cb_input.addItem(name, int(idx))
        except Exception as e:
            logger.error(f"Error parsing devices: {e}")
        self.cb_input.blockSignals(False)

    def export_config(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export Config", "", "JSON Files (*.json)")
        if path:
            try:
                # Mock export logic for refactor
                # In real app, gather data from parent/config
                config = {"exported": True} # Placeholder
                with open(path, 'w') as f:
                    json.dump(config, f, indent=4)
                
                if self.parent() and self.parent().parent():
                    mw = self.parent().parent().window()
                    if hasattr(mw, 'show_toast'):
                        mw.show_toast(Strings.TOAST_EXPORT.format(os.path.basename(path)))
            except Exception as e:
                logger.error(f"Export Error: {e}", exc_info=True)

    def import_config(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Import Config", "", "JSON Files (*.json)")
        if path:
            try:
                with open(path, 'r') as f:
                    config = json.load(f)
                # Mock import logic
                
                if self.parent() and self.parent().parent():
                    mw = self.parent().parent().window()
                    if hasattr(mw, 'show_toast'):
                        mw.show_toast(Strings.TOAST_IMPORT)
                    # Trigger reload
                    QTimer.singleShot(1000, mw.load_config)
            except Exception as e:
                logger.error(f"Import Error: {e}", exc_info=True)
