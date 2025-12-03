from PySide6.QtCore import QObject, Signal
import json
import os

class StateManager(QObject):
    # Signals
    status_changed = Signal(str, str) # state, extra (e.g. "CONNECTED", "REC")
    mode_changed = Signal(str)        # "WAKE", "MANUAL", "FOCUS"
    audio_level_changed = Signal(float) # 0.0 to 1.0
    config_changed = Signal(dict)
    
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(StateManager, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'): return
        super().__init__()
        self._initialized = True
        
        # Default State
        self.status = "OFFLINE"
        self.extra_status = ""
        self.mode = "WAKE"
        self.audio_level = 0.0
        self.config = {}
        self.config_path = os.path.expanduser("~/.config/dex-dictate/config.json")
        
        self.load_config()

    def set_status(self, status, extra=""):
        if self.status != status or self.extra_status != extra:
            self.status = status
            self.extra_status = extra
            self.status_changed.emit(status, extra)

    def set_mode(self, mode):
        if self.mode != mode:
            self.mode = mode
            self.mode_changed.emit(mode)
            # Also update config? Or wait for explicit save?
            # Usually mode is session-based, but we might want to persist it.
            # Let's persist it.
            self.config['mode'] = mode
            self.save_config()

    def update_audio(self, level):
        # Throttle? Or just emit.
        # Let UI handle throttling if needed.
        self.audio_level = level
        self.audio_level_changed.emit(level)

    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    self.config = json.load(f)
            else:
                self.config = {
                    "mode": "WAKE",
                    "theme": "OLED Black",
                    "accent": "#00C8FF",
                    "sensitivity": 50,
                    "macros": {},
                    "audio_device": 0
                }
            
            # Apply loaded mode
            self.mode = self.config.get("mode", "WAKE")
            
        except Exception as e:
            print(f"Error loading config: {e}")

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
            self.config_changed.emit(self.config)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def set_config(self, key, value):
        self.config[key] = value
        self.save_config()
