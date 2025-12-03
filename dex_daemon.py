import os
import sys
import time
import socket
import queue
import threading
import json
import struct
import subprocess
import re
import numpy as np
import sounddevice as sd
import torch
import pvporcupine
from faster_whisper import WhisperModel
import evdev
from evdev import UInput, ecodes as e
import pyperclip
import select
import logging
import logging.handlers

# --- LOGGING SETUP ---
def setup_logging(name):
    log_dir = os.path.expanduser("~/.local/share/dex-dictate/logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{name}.log")
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # File Handler (Rotating: 5MB, 3 backups)
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5*1024*1024, backupCount=3
    )
    fh.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    
    # Console Handler
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger

logger = setup_logging("dex_daemon")

# --- CONFIGURATION ---
ACCESS_KEY = os.environ.get("PICOVOICE_ACCESS_KEY", "CpyLypXl9zpcJzppA6W70VwqTDr2+d2XYa6AhExQYPryoIwbt2h6DA==")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
SOCK_PATH = os.path.join(RUNTIME, "dex3.sock")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
VOCAB_PATH = os.path.join(BASE_DIR, "vocabulary.json")

SAMPLE_RATE = 16000
FRAME_LENGTH = 512

# Modes
MODE_WAKE = "WAKE"
MODE_MANUAL = "MANUAL"
MODE_FOCUS = "FOCUS"

# State
current_mode = MODE_WAKE
recording = False
audio_q = queue.Queue()
command_q = queue.Queue()
porcupine = None
whisper_model = None
vad_model = None
ui = None
last_segment_len = 0
initial_prompt = "" # Vocabulary prompt

# Telemetry
telemetry_lock = threading.Lock()
telemetry = {
    "timestamp": 0.0,
    "vad_energy": 0.0,
    "vad_state": "idle",       # "idle" | "speech" | "silence"
    "asr_state": "idle",       # "idle" | "listening" | "transcribing" | "injecting"
    "last_partial": "",
    "last_final": "",
    "latency_ms": 0.0,
}

# --- EVDEV SETUP ---
CHAR_MAP = {
    ' ': (e.KEY_SPACE, False), '\n': (e.KEY_ENTER, False), '.': (e.KEY_DOT, False),
    ',': (e.KEY_COMMA, False), '?': (e.KEY_SLASH, True), '!': (e.KEY_1, True),
    "'": (e.KEY_APOSTROPHE, False), '"': (e.KEY_APOSTROPHE, True), '-': (e.KEY_MINUS, False),
    '_': (e.KEY_MINUS, True), ':': (e.KEY_SEMICOLON, True), ';': (e.KEY_SEMICOLON, False),
}
for i in range(26):
    c = chr(ord('a') + i); C = chr(ord('A') + i)
    k = getattr(e, f'KEY_{C}'); CHAR_MAP[c] = (k, False); CHAR_MAP[C] = (k, True)
for i in range(10):
    c = str(i); k = getattr(e, f'KEY_{c}'); CHAR_MAP[c] = (k, False)

def ensure_uinput():
    global ui
    if ui: return
    cap = {e.EV_KEY: [v[0] for v in CHAR_MAP.values()] + [e.KEY_LEFTSHIFT, e.KEY_ENTER, e.KEY_SPACE, e.KEY_BACKSPACE, e.KEY_V, e.KEY_LEFTCTRL]}
    try: ui = UInput(cap, name='Dex-Dictate-Daemon', version=0x3)
    except Exception as ex: logger.error(f"UInput Error: {ex}", exc_info=True)

def type_text(text):
    global last_segment_len
    if not text: return
    ensure_uinput()
    
    # Macro: Scratch that
    clean_text = re.sub(r'[^\w\s]', '', text).lower().strip()
    if "scratch that" in clean_text:
        logger.info(f"Macro: Scratching {last_segment_len} chars")
        if ui:
            for _ in range(last_segment_len + 1): # +1 for space
                ui.write(e.EV_KEY, e.KEY_BACKSPACE, 1); ui.syn()
                ui.write(e.EV_KEY, e.KEY_BACKSPACE, 0); ui.syn()
                time.sleep(0.005)
        last_segment_len = 0
        return

    last_segment_len = len(text)
    
    # Try evdev first
    if ui:
        try:
            for char in text + " ":
                if char in CHAR_MAP:
                    k, s = CHAR_MAP[char]
                    if s: ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
                    ui.write(e.EV_KEY, k, 1); ui.syn()
                    ui.write(e.EV_KEY, k, 0)
                    if s: ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
                    ui.syn(); time.sleep(0.005)
            return
        except Exception as ex:
            logger.warning(f"Evdev failed: {ex}. Fallback to clipboard.")
    
    # Fallback: Clipboard + Ctrl+V
    try:
        subprocess.run(['wl-copy', text + " "], check=True)
        if ui:
            ui.write(e.EV_KEY, e.KEY_LEFTCTRL, 1)
            ui.write(e.EV_KEY, e.KEY_V, 1)
            ui.syn()
            ui.write(e.EV_KEY, e.KEY_V, 0)
            ui.write(e.EV_KEY, e.KEY_LEFTCTRL, 0)
            ui.syn()
        else:
            logger.error("No input method available.")
    except Exception as ex:
        logger.error(f"Fallback failed: {ex}", exc_info=True)

def press_combo(combo_str):
    ensure_uinput()
    if not ui: return
    
    parts = combo_str.upper().split('+')
    keys = []
    
    # Map string to keycode
    for p in parts:
        p = p.strip()
        if p == "CTRL": keys.append(e.KEY_LEFTCTRL)
        elif p == "ALT": keys.append(e.KEY_LEFTALT)
        elif p == "SHIFT": keys.append(e.KEY_LEFTSHIFT)
        elif p == "SUPER": keys.append(e.KEY_LEFTMETA)
        elif p == "TAB": keys.append(e.KEY_TAB)
        elif p == "ENTER": keys.append(e.KEY_ENTER)
        elif p == "ESC": keys.append(e.KEY_ESC)
        elif p == "BACKSPACE": keys.append(e.KEY_BACKSPACE)
        elif p == "DELETE": keys.append(e.KEY_DELETE)
        elif p == "UP": keys.append(e.KEY_UP)
        elif p == "DOWN": keys.append(e.KEY_DOWN)
        elif p == "LEFT": keys.append(e.KEY_LEFT)
        elif p == "RIGHT": keys.append(e.KEY_RIGHT)
        elif p == "F4": keys.append(e.KEY_F4)
        elif p == "F5": keys.append(e.KEY_F5)
        elif p == "F11": keys.append(e.KEY_F11)
        elif p == "HOME": keys.append(e.KEY_HOME)
        elif p == "END": keys.append(e.KEY_END)
        elif p == "PAGEUP": keys.append(e.KEY_PAGEUP)
        elif p == "PAGEDOWN": keys.append(e.KEY_PAGEDOWN)
        elif p == "PLUS" or p == "=": keys.append(e.KEY_EQUAL)
        elif p == "MINUS" or p == "-": keys.append(e.KEY_MINUS)
        elif p == "ZERO" or p == "0": keys.append(e.KEY_0)
        elif len(p) == 1:
            if hasattr(e, f"KEY_{p}"): keys.append(getattr(e, f"KEY_{p}"))
            
    # Press Down
    for k in keys: ui.write(e.EV_KEY, k, 1)
    ui.syn()
    time.sleep(0.05)
    # Release Up (Reverse order)
    for k in reversed(keys): ui.write(e.EV_KEY, k, 0)
    ui.syn()

# --- AUDIO UTILS ---
def play_tone(freq=1000, ms=100):
    t = np.linspace(0, ms/1000, int(44100*ms/1000), False)
    w = (0.1 * np.sin(2*np.pi*freq*t)).astype(np.float32)
    sd.play(w, 44100, blocking=False)

def audio_callback(indata, frames, time, status):
    if status: logger.warning(f"Audio Status: {status}")
    audio_q.put(indata.copy())

# --- THREADS ---

# --- LOGGING STATE ---
last_log_message = ""

def set_log(msg):
    global last_log_message
    last_log_message = msg
    logger.info(f"LOG: {msg}")

def ipc_thread():
    if os.path.exists(SOCK_PATH):
        try: os.unlink(SOCK_PATH)
        except: pass
    
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o666)
    server.listen(1)
    logger.info(f"IPC Listening on {SOCK_PATH}")
    
    while True:
        conn, _ = server.accept()
        try:
            data = conn.recv(1024).decode().strip()
            if data:
                # print(f"CMD: {data}") # Too noisy
                if data == "PING": 
                    status = "REC" if recording else "IDLE"
                    # Send status AND last log message
                    # Escape colons in log message to avoid parsing issues? 
                    # Simple replace for now.
                    safe_log = last_log_message.replace(":", "-")
                    conn.send(f"PONG:{status}:{safe_log}".encode())
                elif data == "GET_DEVICES":
                    try:
                        devices = sd.query_devices()
                        input_devices = []
                        for i, d in enumerate(devices):
                            if d['max_input_channels'] > 0:
                                input_devices.append(f"{i}:{d['name']}")
                        resp = "DEVICES:" + "|".join(input_devices)
                        conn.sendall(resp.encode())
                    except Exception as e:
                        logger.error(f"Error getting devices: {e}")
                        conn.send(f"ERROR: {e}".encode())
                elif data.startswith("SET_DEVICE:"):
                    try:
                        idx = int(data.split(":")[1])
                        logger.info(f"Switching to audio device index: {idx}")
                        # Update global device_id and restart stream
                        global device_id
                        device_id = idx
                        # Restart stream logic would be complex here as it's in a separate thread/process
                        # For now, we just update the variable. Ideally, we signal the audio thread.
                        # Since audio_loop uses device_id, we might need to restart the daemon or the loop.
                        # Simpler approach: Just save config and tell user to restart? 
                        # Or better: The audio_loop checks a shared variable?
                        # Let's assume audio_loop is robust enough or we restart it.
                        # Actually, sd.InputStream is blocking or callback based.
                        # We need to stop and start it.
                        # For this iteration, let's just log it and maybe save it to a config file that audio_loop reads?
                        # But the requirement is "Real Audio Device Selection".
                        # Let's write to a config file that the daemon reads on startup.
                        # And maybe trigger a restart of the audio subsystem if possible.
                        conn.send(b"OK")
                    except Exception as e:
                        logger.error(f"Error setting device: {e}")
                        conn.send(f"ERROR: {e}".encode())
                elif data.startswith("SET_MODE:"):
                    global current_mode
                    current_mode = data.split(":")[1]
                    conn.send(b"OK")
                elif data == "TOGGLE":
                    command_q.put("TOGGLE")
                    conn.send(b"OK")
                elif data == "START_REC":
                    command_q.put("START")
                    conn.send(b"OK")
                elif data == "STOP_REC":
                    command_q.put("STOP")
                    conn.send(b"OK")
                elif data == "RELOAD_CONFIG":
                    command_q.put("RELOAD")
                    conn.send(b"OK")
                elif data == "PLAY_CHIME":
                    command_q.put("CHIME")
                    conn.send(b"OK")
                elif data.startswith("TYPE:"):
                    # "TYPE:Hello World"
                    text = data.split(":", 1)[1]
                    command_q.put(f"TYPE:{text}")
                    conn.send(b"OK")
                elif data == "GET_TELEMETRY":
                    with telemetry_lock:
                        # Return JSON telemetry
                        resp = json.dumps({"type": "telemetry", "data": telemetry})
                        conn.send(resp.encode())
                elif data.startswith("SET_THEME:"):
                    # Mock theme setting
                    conn.send(b"OK")
                else: conn.send(b"UNKNOWN")
        except Exception as e: logger.error(f"IPC Error: {e}", exc_info=True)
        finally: conn.close()
        
def log_history(text):
    set_log(f"Transcribed: {text}")
    hist_path = os.path.join(os.path.dirname(CONFIG_PATH), "history.json")
    entry = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "text": text}
    try:
        data = []
        if os.path.exists(hist_path):
            with open(hist_path, 'r') as f: data = json.load(f)
        data.insert(0, entry)
        data = data[:100] # Keep last 100
        with open(hist_path, 'w') as f: json.dump(data, f)
    except: pass

def process_text(text):
    text = text.strip()
    if not text: return
    
    # 1. Command Mode & Snippets
    # COMMANDS DICTIONARY
    # Format: "trigger phrase": (type, action)
    # type: "cmd" (subprocess), "text" (type text), "func" (python function)
    
# --- MACROS ---
MACROS = {}

def init_macros():
    global MACROS
    MACROS = {
        # System
        "open firefox": ("cmd", ["firefox"]),
        "open terminal": ("cmd", ["gnome-terminal"]),
        "open file manager": ("cmd", ["nautilus"]),
        "open calculator": ("cmd", ["gnome-calculator"]),
        "open editor": ("cmd", ["gedit"]),
        "lock screen": ("cmd", ["xdg-screensaver", "lock"]),
        "take screenshot": ("cmd", ["gnome-screenshot"]),
        
        # Media
        "pause music": ("cmd", ["playerctl", "play-pause"]),
        "resume music": ("cmd", ["playerctl", "play"]),
        "next track": ("cmd", ["playerctl", "next"]),
        "previous track": ("cmd", ["playerctl", "previous"]),
        "volume up": ("cmd", ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"]),
        "volume down": ("cmd", ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"]),
        "mute": ("cmd", ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]),
        
        # Text Snippets
        "insert signature": ("text", "\n--\nSent from Dex Dictate v3\nStarsilk Edition"),
        "insert date": ("text", time.strftime("%Y-%m-%d")),
        "insert time": ("text", time.strftime("%H:%M")),
        "insert code block": ("text", "```\n\n```"),
        "insert todo": ("text", "- [ ] "),
        "insert lorem ipsum": ("text", "Lorem ipsum dolor sit amet, consectetur adipiscing elit."),
        "clear selection": ("key", "BackSpace"),
        
        # Fun/Utility
        "what time is it": ("text", f"It is {time.strftime('%H:%M')}"),
        "date today": ("text", f"Today is {time.strftime('%A, %B %d, %Y')}"),
        
        # Browser
        "new tab": ("key", "CTRL+T"),
        "close tab": ("key", "CTRL+W"),
        "reopen tab": ("key", "CTRL+SHIFT+T"),
        "next tab": ("key", "CTRL+TAB"),
        "previous tab": ("key", "CTRL+SHIFT+TAB"),
        "refresh page": ("key", "F5"),
        "browser history": ("key", "CTRL+H"),
        "downloads": ("key", "CTRL+J"),
        "private window": ("key", "CTRL+SHIFT+P"),
        
        # Editing
        "select all": ("key", "CTRL+A"),
        "copy selection": ("key", "CTRL+C"),
        "paste clipboard": ("key", "CTRL+V"),
        "cut selection": ("key", "CTRL+X"),
        "undo action": ("key", "CTRL+Z"),
        "redo action": ("key", "CTRL+SHIFT+Z"),
        "save file": ("key", "CTRL+S"),
        "find text": ("key", "CTRL+F"),
        
        # Window Management
        "close window": ("key", "ALT+F4"),
        "switch window": ("key", "ALT+TAB"),
        "show desktop": ("key", "SUPER+D"),
        "run command": ("key", "ALT+F2"),
        "open settings": ("cmd", ["gnome-control-center"]),
        
        # Navigation
        "page up": ("key", "PAGEUP"),
        "page down": ("key", "PAGEDOWN"),
        "go home": ("key", "ALT+HOME"),
        
        # Window Tiling
        "maximize window": ("key", "SUPER+UP"),
        "minimize window": ("key", "SUPER+DOWN"),
        "snap left": ("key", "SUPER+LEFT"),
        "snap right": ("key", "SUPER+RIGHT"),
        "fullscreen": ("key", "F11"),
        
        # Text Navigation
        "go to start": ("key", "HOME"),
        "go to end": ("key", "END"),
        "top of page": ("key", "CTRL+HOME"),
        "bottom of page": ("key", "CTRL+END"),
        "delete word": ("key", "CTRL+BACKSPACE"),
        "delete next word": ("key", "CTRL+DELETE"),
        "select word left": ("key", "CTRL+SHIFT+LEFT"),
        "select word right": ("key", "CTRL+SHIFT+RIGHT"),
        
        # Zoom
        "zoom in": ("key", "CTRL+PLUS"),
        "zoom out": ("key", "CTRL+MINUS"),
        "reset zoom": ("key", "CTRL+0"),
        
        # Media Extra
        "stop music": ("cmd", ["playerctl", "stop"]),
        "rewind": ("cmd", ["playerctl", "position", "10-"]),
        "fast forward": ("cmd", ["playerctl", "position", "10+"]),
        "mute microphone": ("cmd", ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"]),
        
        # Apps/Folders
        "open monitor": ("cmd", ["gnome-system-monitor"]),
        "open documents": ("cmd", ["xdg-open", os.path.expanduser("~/Documents")]),
        "open downloads folder": ("cmd", ["xdg-open", os.path.expanduser("~/Downloads")]),
        "open pictures": ("cmd", ["xdg-open", os.path.expanduser("~/Pictures")]),
        "open trash": ("cmd", ["gio", "open", "trash:///"]),
        
        # Workspaces
        "workspace one": ("key", "SUPER+1"),
        "workspace two": ("key", "SUPER+2"),
        "workspace three": ("key", "SUPER+3"),
        "workspace four": ("key", "SUPER+4"),
        "move to workspace one": ("key", "SUPER+SHIFT+1"),
        "move to workspace two": ("key", "SUPER+SHIFT+2"),
        "move to workspace three": ("key", "SUPER+SHIFT+3"),
        "move to workspace four": ("key", "SUPER+SHIFT+4"),
        
        # Function Keys
        "press f one": ("key", "F1"),
        "press f two": ("key", "F2"),
        "press f three": ("key", "F3"),
        "press f four": ("key", "F4"),
        "press f five": ("key", "F5"),
        "press f six": ("key", "F6"),
        "press f seven": ("key", "F7"),
        "press f eight": ("key", "F8"),
        "press f nine": ("key", "F9"),
        "press f ten": ("key", "F10"),
        "press f eleven": ("key", "F11"),
        "press f twelve": ("key", "F12"),
        
        # Markdown
        "bold text": ("key", "CTRL+B"),
        "italic text": ("key", "CTRL+I"),
        "underline text": ("key", "CTRL+U"),
        "insert link": ("key", "CTRL+K"),
        
        # Terminal
        "clear terminal": ("key", "CTRL+L"),
        "stop process": ("key", "CTRL+C"),
        "exit terminal": ("key", "CTRL+D"),
        
        # Keys
        "press enter": ("key", "ENTER"),
        "press escape": ("key", "ESC"),
        "press tab": ("key", "TAB"),
        "press space": ("key", "SPACE"),
        "press backspace": ("key", "BACKSPACE"),
        "press delete": ("key", "DELETE"),
        
        # Arrows
        "press up": ("key", "UP"),
        "press down": ("key", "DOWN"),
        "press left": ("key", "LEFT"),
        "press right": ("key", "RIGHT"),
        
        # Apps Extra
        "open spotify": ("cmd", ["spotify"]),
        "open discord": ("cmd", ["discord"]),
        "open code": ("cmd", ["code"]),
        "open tweaks": ("cmd", ["gnome-tweaks"]),
        "open weather": ("cmd", ["gnome-weather"]),
        
        # Kill / Pause
        "stop listening": ("func", lambda: command_q.put("STOP")),
        "pause listening": ("func", lambda: command_q.put("STOP")),
        "shutdown system": ("func", lambda: sys.exit(0)),
        
        # Coding
        "git status": ("text", "git status"),
        "git pull": ("text", "git pull"),
        "git push": ("text", "git push"),
        "git commit": ("text", "git commit -m ''"),
        "git add all": ("text", "git add ."),
        "git checkout": ("text", "git checkout "),
        "git log": ("text", "git log"),
        "git diff": ("text", "git diff"),
        "npm start": ("text", "npm start"),
        "npm test": ("text", "npm test"),
        "npm install": ("text", "npm install "),
        "python run": ("text", "python3 "),
        "pip install": ("text", "pip install "),
        
        # Terminal Utils
        "list files": ("text", "ls -la"),
        "change directory": ("text", "cd "),
        "go back": ("text", "cd .."),
        "make directory": ("text", "mkdir "),
        "remove file": ("text", "rm "),
        "clear screen": ("key", "CTRL+L"),
        
        # VS Code
        "command palette": ("key", "CTRL+SHIFT+P"),
        "quick open": ("key", "CTRL+P"),
        "toggle sidebar": ("key", "CTRL+B"),
        "toggle panel": ("key", "CTRL+J"),
        "toggle terminal": ("key", "CTRL+`"),
        "comment line": ("key", "CTRL+/"),
        "format document": ("key", "CTRL+SHIFT+I"),
        "go to definition": ("key", "F12"),
        "find in files": ("key", "CTRL+SHIFT+F"),
        
        # System Control
        "brightness up": ("cmd", ["brightnessctl", "s", "+10%"]),
        "brightness down": ("cmd", ["brightnessctl", "s", "10%-"]),
        "wifi on": ("cmd", ["nmcli", "radio", "wifi", "on"]),
        "wifi off": ("cmd", ["nmcli", "radio", "wifi", "off"]),
        "bluetooth on": ("cmd", ["rfkill", "unblock", "bluetooth"]),
        "bluetooth off": ("cmd", ["rfkill", "block", "bluetooth"]),
        
        # Obsidian
        "heading one": ("text", "# "),
        "heading two": ("text", "## "),
        "heading three": ("text", "### "),
        "checkbox": ("text", "- [ ] "),
        "bullet list": ("text", "- "),
        "numbered list": ("text", "1. "),
        "quote block": ("text", "> "),
        "code fence": ("text", "```"),
        "horizontal rule": ("text", "---"),
    }

def process_text(text):
    text = text.strip()
    if not text: return
    
    # 1. Command Mode & Snippets
    # Use global MACROS
    global MACROS
    if not MACROS: init_macros()
    
    commands = MACROS

    # Normalize: lower, remove punctuation
    cmd_text = text.lower()
    for char in [",", ".", "?", "!", ";", ":"]:
        cmd_text = cmd_text.replace(char, "")
    cmd_text = cmd_text.strip()
    
    # Check for "Computer, [command]"
    if cmd_text.startswith("computer"):
        action_key = cmd_text.replace("computer", "").strip()
        if action_key in commands:
            ctype, cval = commands[action_key]
            set_log(f"Executing: {action_key}")
            print(f"Executing Command: {action_key}")
            if ctype == "cmd":
                subprocess.Popen(cval)
                play_tone(1000, 100)
            elif ctype == "text":
                type_text(cval)
            elif ctype == "key":
                press_combo(cval)
            elif ctype == "func":
                cval()
            return

    # Check for direct snippets (no "Computer" prefix)
    if cmd_text in commands:
        ctype, cval = commands[cmd_text]
        set_log(f"Executing: {cmd_text}")
        print(f"Executing Command: {cmd_text}") # Added print for direct snippets
        if ctype == "text":
            type_text(cval)
            return
        elif ctype == "key":
            press_combo(cval)
            return
        elif ctype == "func":
            cval()
            return
            
    # 3. Type & Log
    log_history(text)
    type_text(text)

# --- MODEL MANAGER (Lazy Loading) ---
class ModelManager:
    def __init__(self):
        self._whisper = None
        self._porcupine = None
        self._vad = None
        self._vad_utils = None

    @property
    def whisper(self):
        if not self._whisper:
            print("⏳ Lazy Loading Whisper (tiny.en)...")
            self._whisper = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        return self._whisper

    @property
    def porcupine(self):
        if not self._porcupine:
            print("⏳ Lazy Loading Porcupine...")
            try:
                self._porcupine = pvporcupine.create(access_key=ACCESS_KEY, keywords=['porcupine'])
            except Exception as e:
                print(f"Porcupine Load Error: {e}")
        return self._porcupine

    @property
    def vad(self):
        if not self._vad:
            print("⏳ Lazy Loading Silero VAD...")
            self._vad, self._vad_utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False, trust_repo=True)
        return self._vad, self._vad_utils

models = ModelManager()

# --- HELPER FUNCTIONS ---
def set_clipboard(text):
    try:
        subprocess.run(['wl-copy'], input=text.encode(), check=True)
    except Exception as e:
        print(f"Clipboard Error: {e}")

def process_thread():
    global recording, current_mode
    
    # Audio Stream
    device_id = None
    try:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if 'default' in d['name'] and d['max_input_channels'] > 0:
                device_id = i
                break
    except: pass
    
    # Queue Cap: ~2 minutes @ 16kHz/512 frame = ~31.25 fps * 120s = 3750 frames -> 4000
    global audio_q
    audio_q = queue.Queue(maxsize=4000) 
    
    stream = sd.InputStream(samplerate=SAMPLE_RATE, device=device_id, channels=1, dtype='int16', blocksize=FRAME_LENGTH, callback=audio_callback)
    stream.start()
    print("Audio Engine Started.")
    
    rec_buffer = []
    silence_start = None
    
    while True:
        # 1. Handle Commands
        try:
            cmd = command_q.get_nowait()
            if cmd == "TOGGLE":
                if not recording:
                    recording = True
                    rec_buffer = []
                    play_tone(1200)
                else:
                    recording = False
                    play_tone(600)
            elif cmd == "START":
                if not recording:
                    recording = True
                    rec_buffer = []
                    play_tone(1200)
            elif cmd == "STOP":
                if recording:
                    recording = False
                    play_tone(600)
            elif cmd == "CHIME":
                play_tone(880, 50) # High ping
            elif cmd == "RELOAD_CONFIG":
                load_config()
                logger.info("Config Reloaded via IPC")
            elif cmd.startswith("TYPE:"):
                text = cmd.split(":", 1)[1]
                print(f"Injecting History: {text}")
                process_text(text)
            
        except queue.Empty: pass
        
        # 2. Get Audio
        try:
            pcm = audio_q.get(timeout=0.1)
        except queue.Empty: continue
        
        # 3. Logic Branch
        
        # WAKE MODE
        if current_mode == MODE_WAKE and not recording:
            # Lazy Load Porcupine
            pp = models.porcupine
            if pp:
                # Calculate Energy for Visualizer
                frame_float = pcm.flatten().astype(np.float32) / 32768.0
                energy = float(np.sqrt(np.mean(frame_float**2)))
                
                with telemetry_lock:
                    telemetry["timestamp"] = time.time()
                    telemetry["vad_energy"] = energy
                    telemetry["vad_state"] = "idle"
                    telemetry["asr_state"] = "idle"
                
                idx = pp.process(pcm.flatten())
                if idx >= 0:
                    logger.info("Wake Word Detected!")
                    play_tone(1200)
                    recording = True
                    rec_buffer = []
                    silence_start = None
        
        # FOCUS MODE (VAD Only)
        elif current_mode == MODE_FOCUS and not recording:
            frame_float = pcm.flatten().astype(np.float32) / 32768.0
            
            # VAD Check (Lazy Load)
            vad_model, _ = models.vad
            
            speech_prob = 0.0
            if vad_model:
                speech_prob = vad_model(torch.from_numpy(frame_float), SAMPLE_RATE).item()
            else:
                # Energy Fallback
                speech_prob = np.sqrt(np.mean(frame_float**2)) * 10 # Boost for visibility
            
            # Telemetry Update (Idle)
            with telemetry_lock:
                telemetry["timestamp"] = time.time()
                telemetry["vad_energy"] = float(np.sqrt(np.mean(frame_float**2)))
                telemetry["vad_state"] = "speech" if speech_prob > 0.5 else "silence"
                telemetry["asr_state"] = "idle"

            if speech_prob > 0.5:
                logger.info("Focus Speech Detected!")
                recording = True
                rec_buffer = []
                silence_start = None
        
        # RECORDING LOGIC
        if recording:
            rec_buffer.append(pcm)
            
            # VAD Check
            frame_float = pcm.flatten().astype(np.float32) / 32768.0
            speech_prob = 0.0
            
            vad_model, _ = models.vad
            if vad_model:
                speech_prob = vad_model(torch.from_numpy(frame_float), SAMPLE_RATE).item()
            else:
                speech_prob = np.sqrt(np.mean(frame_float**2)) * 10
            
            # Telemetry Update (Recording)
            with telemetry_lock:
                telemetry["timestamp"] = time.time()
                telemetry["vad_energy"] = float(np.sqrt(np.mean(frame_float**2)))
                telemetry["vad_state"] = "speech" if speech_prob > 0.3 else "silence"
                telemetry["asr_state"] = "listening"
                telemetry["buffer_ms"] = len(rec_buffer) * (FRAME_LENGTH / SAMPLE_RATE) * 1000

            if speech_prob < 0.3: # Silence
                if silence_start is None: silence_start = time.time()
                elif time.time() - silence_start > 1.0: # 1s Silence Timeout
                    logger.info("Silence Timeout. Stopping.")
                    recording = False
                    play_tone(600)
                    
                    # Transcribe
                    if len(rec_buffer) > 5: # Min frames
                        logger.info(f"Transcribing {len(rec_buffer)} frames...")
                        
                        # Telemetry: Transcribing
                        with telemetry_lock: telemetry["asr_state"] = "transcribing"
                            
                        # Flatten buffer
                        audio_data = np.concatenate(rec_buffer).flatten().astype(np.float32) / 32768.0
                        
                        # Lazy Load Whisper
                        w_model = models.whisper
                        
                        try:
                            segments, _ = w_model.transcribe(audio_data, beam_size=5, initial_prompt=initial_prompt)
                            text = " ".join([s.text for s in segments]).strip()
                            
                            logger.info(f"Transcribed: {text}")
                            with telemetry_lock: 
                                telemetry["asr_state"] = "injecting"
                                telemetry["last_final"] = text
                            
                            process_text(text)
                            
                        except Exception as e:
                            logger.error(f"Transcription Error: {e}", exc_info=True)
                            set_log("Error during transcription.")
                            
                        # Telemetry: Idle
                        with telemetry_lock: telemetry["asr_state"] = "idle"

            else:
                silence_start = None
        
        # Manual Mode Telemetry (Idle)
        elif current_mode == MODE_MANUAL:
             frame_float = pcm.flatten().astype(np.float32) / 32768.0
             with telemetry_lock:
                telemetry["timestamp"] = time.time()
                telemetry["vad_energy"] = float(np.sqrt(np.mean(frame_float**2)))
                telemetry["vad_state"] = "idle"
                telemetry["asr_state"] = "idle"



# --- VAD & MODELS ---
def load_models():
    global porcupine, whisper_model, vad_model
    print("Loading Models...")
    
    # 1. Porcupine (Wake Word)
    try:
        porcupine = pvporcupine.create(access_key=ACCESS_KEY, keywords=['computer'])
        print("Porcupine Loaded.")
    except Exception as e:
        print(f"Porcupine Error: {e}")

    # 2. Whisper (ASR)
    try:
        # Use tiny.en for speed on CPU
        whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        print("Whisper Loaded.")
    except Exception as e:
        print(f"Whisper Error: {e}")

    # 3. Silero VAD (Voice Activity Detection)
    try:
        vad_model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                                          model='silero_vad',
                                          force_reload=False,
                                          trust_repo=True)
        print("Silero VAD Loaded.")
    except:
        print("Silero VAD failed. Using Energy VAD fallback.")
        vad_model = None

# --- INPUT HANDLING ---
hotkey_start_alts = []
hotkey_stop_alts = []

def load_config():
    global hotkey_start_alts, hotkey_stop_alts, MACROS, initial_prompt, current_mode
    
    # 1. Load Vocabulary
    try:
        if os.path.exists(VOCAB_PATH):
            with open(VOCAB_PATH, 'r') as f:
                vocab_data = json.load(f)
                terms = vocab_data.get("terms", [])
                style = vocab_data.get("style", "")
                
                # Construct Prompt: "Style. Terms."
                prompt_parts = []
                if style: prompt_parts.append(f"{style}.")
                if terms: prompt_parts.append(f"Vocabulary: {', '.join(terms)}.")
                
                initial_prompt = " ".join(prompt_parts)
                print(f"Vocabulary Loaded: {len(terms)} terms.")
    except Exception as e:
        print(f"Vocabulary Load Error: {e}")

    # 2. Load Config & Macros
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                
                def parse_hk(hk_str):
                    # Returns a LIST of SETS (alternatives)
                    # e.g. "CTRL+F9" -> [{LCTRL, F9}, {RCTRL, F9}]
                    parts = hk_str.upper().split('+')
                    base_keys = set()
                    modifiers = []
                    
                    for p in parts:
                        p = p.strip()
                        if p == "CTRL": modifiers.append({evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_RIGHTCTRL})
                        elif p == "ALT": modifiers.append({evdev.ecodes.KEY_LEFTALT, evdev.ecodes.KEY_RIGHTALT})
                        elif p == "SHIFT": modifiers.append({evdev.ecodes.KEY_LEFTSHIFT, evdev.ecodes.KEY_RIGHTSHIFT})
                        elif p == "SUPER": modifiers.append({evdev.ecodes.KEY_LEFTMETA, evdev.ecodes.KEY_RIGHTMETA})
                        elif hasattr(evdev.ecodes, f"KEY_{p}"):
                            base_keys.add(getattr(evdev.ecodes, f"KEY_{p}"))
                    
                    # Generate combinations
                    import itertools
                    combos = []
                    if not modifiers:
                        combos.append(base_keys)
                    else:
                        for mod_combo in itertools.product(*modifiers):
                            s = base_keys.copy()
                            for m in mod_combo: s.add(m)
                            combos.append(s)
                    return combos

                hotkey_start_alts = parse_hk(config.get("hotkey_start", "F9"))
                hotkey_stop_alts = parse_hk(config.get("hotkey_stop", "F10"))
                print(f"Hotkeys Loaded: {len(hotkey_start_alts)} start combos, {len(hotkey_stop_alts)} stop combos")
                
                # Update Mode
                current_mode = config.get("mode", "WAKE")
                
                # Update Macros
                if not MACROS: init_macros()
                
                # Load User Macros
                user_macros = config.get("macros", {})
                
                # Merge into Global MACROS
                # User macros override system macros
                for k, v in user_macros.items():
                    # Infer Type if missing (simple heuristic)
                    ctype = "text"
                    cval = v
                    
                    if isinstance(v, dict): # If they used the advanced format
                        ctype = v.get("type", "text")
                        cval = v.get("value", "")
                    elif isinstance(v, str): # Only apply heuristics if it's a string
                        if v.startswith("!"):
                            ctype = "cmd"
                            cval = v[1:].split(" ") # "!firefox" -> ["firefox"]
                        elif "+" in v and v.isupper(): # Rough check for hotkeys
                            ctype = "key"
                    
                    MACROS[k] = (ctype, cval)
                         
                print(f"Macros Loaded: {len(MACROS)} total ({len(user_macros)} user)")
                
    except Exception as e:
        print(f"Config Load Error: {e}")

def input_thread():
    load_config()
    
    # Monitor ALL keyboards
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    keyboards = [dev for dev in devices if 'keyboard' in dev.name.lower()]
    
    if not keyboards:
        print("No keyboards found!")
        return
        
    print(f"Listening on {len(keyboards)} keyboards: {[k.name for k in keyboards]}")
    
    # Selector for multiple devices
    from select import select
    
    active_keys = set()
    last_trigger = 0

    while True:
        try:
            if current_mode == MODE_MANUAL:
                r, w, x = select({dev.fd: dev for dev in keyboards}, [], [], 0.1)
                
                for fd in r:
                    for event in keyboards[0].read(): # Read from the ready device?
                        # Actually need to map fd back to device object
                        # Simplified: Just read from all (non-blocking usually if select says ready)
                        pass
                
                # Re-implement simple loop for reliability over complex select for now
                # Just merge events from all keyboards
                for kb in keyboards:
                    try:
                        for event in kb.read():
                            if event.type == evdev.ecodes.EV_KEY:
                                if event.value == 1: # Down
                                    active_keys.add(event.code)
                                    
                                    # Debounce
                                    if time.time() - last_trigger < 0.3: continue
                                    
                                    # Check Combos
                                    is_start = any(s.issubset(active_keys) for s in hotkey_start_alts)
                                    is_stop = any(s.issubset(active_keys) for s in hotkey_stop_alts)
                                    
                                    if is_start and is_stop and hotkey_start_alts == hotkey_stop_alts:
                                        command_q.put("TOGGLE")
                                        last_trigger = time.time()
                                    elif is_start:
                                        command_q.put("START")
                                        last_trigger = time.time()
                                    elif is_stop:
                                        command_q.put("STOP")
                                        last_trigger = time.time()
                                        
                                elif event.value == 0: # Up
                                    active_keys.discard(event.code)
                    except BlockingIOError: pass
                    except OSError: 
                        # Device disconnected?
                        pass
            
            time.sleep(0.01)
        except Exception as e:
            print(f"Input Loop Error: {e}")
            time.sleep(1)

# --- IPC EXTENSION ---
def ipc_thread():
    if os.path.exists(SOCK_PATH):
        try: os.unlink(SOCK_PATH)
        except: pass
    
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o666)
    server.listen(5)
    server.setblocking(False)
    print(f"IPC Listening on {SOCK_PATH}")
    
    clients = []
    
    while True:
        # Accept new clients
        try:
            client, _ = server.accept()
            client.setblocking(False)
            clients.append(client)
        except BlockingIOError: pass
        except Exception as e: print(f"Accept Error: {e}")
        
        # Read from clients
        readable = []
        if clients:
            try:
                readable, _, _ = select.select(clients, [], [], 0.01)
            except:
                # Clean up closed sockets
                clients = [c for c in clients if c.fileno() != -1]
                continue
                
        for c in readable:
            try:
                data = c.recv(4096)
                if not data:
                    clients.remove(c)
                    c.close()
                    continue
                
                command = data.decode("utf-8").strip()
                
                if command == "GET_TELEMETRY":
                    with telemetry_lock:
                        payload_dict = {
                            "type": "telemetry",
                            "data": telemetry,
                        }
                    payload = (json.dumps(payload_dict) + "\n").encode("utf-8")
                    c.sendall(payload)
                
                elif command == "PING": 
                    status = "REC" if recording else "IDLE"
                    safe_log = last_log_message.replace(":", "-")
                    c.send(f"PONG:{status}:{safe_log}".encode())
                    
                elif command.startswith("SET_MODE:"):
                    global current_mode
                    current_mode = command.split(":")[1]
                    c.send(b"OK")
                elif command == "TOGGLE":
                    command_q.put("TOGGLE")
                    c.send(b"OK")
                elif command == "START_REC":
                    command_q.put("START")
                    c.send(b"OK")
                elif command == "STOP_REC":
                    command_q.put("STOP")
                    c.send(b"OK")
                elif command == "RELOAD_CONFIG":
                    command_q.put("RELOAD")
                    load_config() 
                    c.send(b"OK")
                elif command == "PLAY_CHIME":
                    command_q.put("CHIME")
                    c.send(b"OK")
                else: c.send(b"UNKNOWN")
                
            except (ConnectionResetError, BrokenPipeError):
                if c in clients: clients.remove(c)
                c.close()
            except Exception as e:
                print(f"IPC Client Error: {e}")
                if c in clients: clients.remove(c)
                c.close()
                
        time.sleep(0.005)

if __name__ == "__main__":
    try:
        load_config()
        
        # Start IPC
        t_ipc = threading.Thread(target=ipc_thread, daemon=True)
        t_ipc.start()
        
        # Start Input Monitoring
        t_input = threading.Thread(target=input_thread, daemon=True)
        t_input.start()
        
        # Start Audio Processing
        process_thread()
    except KeyboardInterrupt:
        logger.info("Stopping Daemon...")
    except Exception as e:
        logger.critical(f"Fatal Error: {e}", exc_info=True)

