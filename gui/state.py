from PySide6.QtCore import QObject, Signal, QTimer
import json
import os
import socket

SOCK_FILE = f"/run/user/{os.getuid()}/dex3.sock"

class StateManager(QObject):
    # Signals
    status_changed = Signal(str, str) # state, extra
    mode_changed = Signal(str)
    audio_level_changed = Signal(float)
    transcription_received = Signal(str)
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
        
        self.status = "OFFLINE"
        self.extra_status = ""
        self.mode = "WAKE"
        self.audio_level = 0.0
        self.config = {}
        self.config_path = os.path.expanduser("~/.config/dex-dictate/config.json")
        self.load_config()
        
        # Polling Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_daemon)
        self.timer.start(500)

    def poll_daemon(self):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(0.05)
            client.connect(SOCK_FILE)
            client.send(json.dumps({"cmd": "GET_STATUS"}).encode())
            data = client.recv(1024).decode()
            client.close()
            
            if data:
                resp = json.loads(data)
                self.set_status("CONNECTED", resp.get("status", "IDLE"))
                
                # Sync Mode (User Preference)
                config_mode = resp.get("config_mode", "WAKE")
                if config_mode != self.mode:
                    self.mode = config_mode
                    self.mode_changed.emit(self.mode)
                
                last_text = resp.get("last_text", "")
                if last_text and last_text != getattr(self, 'last_seen_text', ""):
                    self.last_seen_text = last_text
                    self.transcription_received.emit(last_text)
        except:
            self.set_status("OFFLINE", "")

    def send_cmd(self, cmd, mode=None):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(SOCK_FILE)
            msg = {"cmd": cmd}
            if mode: msg["mode"] = mode
            client.send(json.dumps(msg).encode())
            client.close()
        except Exception as e:
            print(f"Command Failed: {e}")

    def set_status(self, status, extra=""):
        if self.status != status or self.extra_status != extra:
            self.status = status
            self.extra_status = extra
            self.status_changed.emit(status, extra)

    def set_mode(self, mode):
        if self.mode != mode:
            self.mode = mode
            self.mode_changed.emit(mode)
            self.send_cmd("SET_MODE", mode)

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    self.config = json.load(f)
        except: pass

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
            self.config_changed.emit(self.config)
        except: pass
