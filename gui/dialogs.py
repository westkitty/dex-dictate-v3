from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, 
                               QHeaderView, QTextEdit)
from strings import Strings
import os
import json

class HistoryWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(Strings.TITLE_HISTORY)
        self.resize(500, 600)
        layout = QVBoxLayout(self)
        
        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        layout.addWidget(self.text_view)
        
        self.load_history()
        
    def load_history(self):
        # Assuming config path is available or passed. For now, using relative or hardcoded for simplicity in refactor.
        # Ideally, config path should be managed by a ConfigManager or passed in.
        # Using standard path for now.
        config_path = os.path.expanduser("~/.config/dex-dictate/config.json")
        hist_path = os.path.join(os.path.dirname(config_path), "history.json")
        if os.path.exists(hist_path):
            with open(hist_path, 'r') as f:
                data = json.load(f)
                for entry in data:
                    self.text_view.append(f"[{entry['timestamp']}] {entry['text']}")
                    self.text_view.append("-" * 40)

class CommandListWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(Strings.TITLE_COMMANDS)
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
