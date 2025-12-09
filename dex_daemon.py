import os
import sys
import time
import json
import queue
import socket
import struct
import threading
import logging
import subprocess
import numpy as np
import sounddevice as sd
import pvporcupine
from faster_whisper import WhisperModel
from evdev import UInput, ecodes as e

# --- CONFIGURATION ---
SAMPLE_RATE = 16000
FRAME_LENGTH = 512
VAD_THRESHOLD = 0.005
SILENCE_LIMIT = 1.5
SOCK_FILE = f"/run/user/{os.getuid()}/dex3.sock"
MODEL_SIZE = "tiny.en"
ACCESS_KEY = os.environ.get("PICOVOICE_ACCESS_KEY", "CpyLypXl9zpcJzppA6W70VwqTDr2+d2XYa6AhExQYPryoIwbt2h6DA==")

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DexDaemon")

# --- INPUT SIMULATION ---
try:
    ui = UInput()
    logger.info("UInput initialized successfully.")
except Exception as ex:
    logger.warning(f"UInput failed: {ex}. Will use fallback methods.")
    ui = None

CHAR_MAP = {
    'a': (e.KEY_A, 0), 'b': (e.KEY_B, 0), 'c': (e.KEY_C, 0), 'd': (e.KEY_D, 0), 'e': (e.KEY_E, 0),
    'f': (e.KEY_F, 0), 'g': (e.KEY_G, 0), 'h': (e.KEY_H, 0), 'i': (e.KEY_I, 0), 'j': (e.KEY_J, 0),
    'k': (e.KEY_K, 0), 'l': (e.KEY_L, 0), 'm': (e.KEY_M, 0), 'n': (e.KEY_N, 0), 'o': (e.KEY_O, 0),
    'p': (e.KEY_P, 0), 'q': (e.KEY_Q, 0), 'r': (e.KEY_R, 0), 's': (e.KEY_S, 0), 't': (e.KEY_T, 0),
    'u': (e.KEY_U, 0), 'v': (e.KEY_V, 0), 'w': (e.KEY_W, 0), 'x': (e.KEY_X, 0), 'y': (e.KEY_Y, 0),
    'z': (e.KEY_Z, 0), ' ': (e.KEY_SPACE, 0), '.': (e.KEY_DOT, 0), ',': (e.KEY_COMMA, 0),
    '?': (e.KEY_SLASH, 1), '!': (e.KEY_1, 1), '\n': (e.KEY_ENTER, 0)
}

def type_text(text):
    logger.info(f"Typing: {text}")
    if ui:
        try:
            for char in text + " ":
                if char.lower() in CHAR_MAP:
                    k, s = CHAR_MAP[char.lower()]
                    if char.isupper() or s: ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
                    ui.write(e.EV_KEY, k, 1); ui.syn()
                    ui.write(e.EV_KEY, k, 0)
                    if char.isupper() or s: ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
                    ui.syn(); time.sleep(0.002)
            return
        except: pass

    try:
        subprocess.run(['wl-copy', text + " "], check=True)
        if ui:
            ui.write(e.EV_KEY, e.KEY_LEFTCTRL, 1)
            ui.write(e.EV_KEY, e.KEY_V, 1); ui.syn()
            ui.write(e.EV_KEY, e.KEY_V, 0)
            ui.write(e.EV_KEY, e.KEY_LEFTCTRL, 0); ui.syn()
            return
    except: pass
    
    try: subprocess.run(['xdotool', 'type', text + " "], check=True)
    except: pass

# --- AUDIO THREAD ---
class AudioThread(threading.Thread):
    def __init__(self, callback, shutdown_event):
        super().__init__()
        self.callback = callback
        self.shutdown_event = shutdown_event

    def run(self):
        while not self.shutdown_event.is_set():
            try:
                device_id = None
                devices = sd.query_devices()
                for name in ['pulse', 'pipewire', 'default']:
                    for i, d in enumerate(devices):
                        if name in d['name'].lower() and d['max_input_channels'] > 0:
                            device_id = i
                            logger.info(f"Selected Audio Device: {d['name']} (Index {i})")
                            break
                    if device_id is not None: break
                
                if device_id is None:
                    logger.error("No suitable audio device found!")
                    time.sleep(2)
                    continue

                with sd.InputStream(samplerate=SAMPLE_RATE, device=device_id, channels=1, dtype='int16', 
                                  blocksize=FRAME_LENGTH, callback=self._audio_callback):
                    logger.info("Audio Stream Started")
                    while not self.shutdown_event.is_set():
                        time.sleep(0.1)
            except Exception as e:
                logger.error(f"Audio Stream Error: {e}. Retrying in 2s...")
                time.sleep(2)

    def _audio_callback(self, indata, frames, time, status):
        if status: logger.warning(f"Audio Status: {status}")
        self.callback(indata.copy())

    def stop(self):
        self.running = False

# --- DAEMON CLASS ---
class DexDaemon:
    def __init__(self):
        # Singleton Check
        self.lock_file = "/tmp/dex_daemon.lock"
        if os.path.exists(self.lock_file):
            try:
                pid = int(open(self.lock_file).read())
                os.kill(pid, 0)
                logger.error(f"Daemon already running (PID {pid}). Exiting.")
                sys.exit(1)
            except:
                pass # Stale lock
        with open(self.lock_file, 'w') as f: f.write(str(os.getpid()))

        self.mode = "WAKE"
        self.config_mode = "WAKE"
        self.audio_q = queue.Queue()
        self.rec_buffer = []
        self.silence_start = None
        
        logger.info("Loading Porcupine...")
        self.pp = pvporcupine.create(access_key=ACCESS_KEY, keywords=['porcupine'])
        logger.info("Loading Whisper...")
        # Optimize for low-resource: Limit threads
        self.whisper = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8", cpu_threads=4)
        
        self.load_macros()
        
        self.shutdown_event = threading.Event()
        self.audio_thread = AudioThread(self.audio_q.put, self.shutdown_event)
        self.audio_thread.start()
        
        threading.Thread(target=self.ipc_loop, daemon=True).start()

    def cleanup(self):
        if os.path.exists(self.lock_file): os.remove(self.lock_file)
        self.shutdown_event.set()
        self.audio_thread.join(timeout=2)

    def load_macros(self):
        self.macros = {}
        try:
            config_path = os.path.expanduser("~/.config/dex-dictate/config.json")
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    self.macros = config.get("macros", {})
                    logger.info(f"Loaded {len(self.macros)} macros.")
        except Exception as e:
            logger.error(f"Macro Load Error: {e}")

    def process_audio(self):
        logger.info("Daemon Ready. Waiting for audio...")
        while True:
            try:
                # Non-blocking get with timeout to allow loop to breathe
                try:
                    pcm = self.audio_q.get(timeout=0.05)
                except queue.Empty:
                    continue

                # Optimize: Only calc energy if needed (LISTENING mode) or periodically
                energy = 0.0
                if self.mode == "LISTENING" or int(time.time() * 10) % 5 == 0:
                     energy = np.sqrt(np.mean(pcm.astype(float)**2)) / 32768.0
                
                # Debug Energy occasionally
                if int(time.time()) % 5 == 0 and int(time.time() * 10) % 10 == 0:
                    logger.debug(f"Energy: {energy:.4f}")

                if self.mode == "WAKE":
                    idx = self.pp.process(pcm.flatten())
                    if idx >= 0:
                        logger.info("Wake Word Detected!")
                        self.set_mode("LISTENING")
                        self.play_sound("listening")

                elif self.mode == "LISTENING":
                    if energy > VAD_THRESHOLD:
                        self.rec_buffer.append(pcm)
                        self.silence_start = None
                    else:
                        if self.silence_start is None:
                            self.silence_start = time.time()
                        elif time.time() - self.silence_start > SILENCE_LIMIT:
                            if len(self.rec_buffer) > 0:
                                self.transcribe()
                            else:
                                self.set_mode("WAKE")
                                self.play_sound("sleeping")

            except Exception as e:
                logger.error(f"Processing Error: {e}")

    def transcribe(self):
        self.set_mode("PROCESSING")
        self.play_sound("done") # "I'm Done" Beep
        
        audio_data = np.concatenate(self.rec_buffer).flatten().astype(np.float32) / 32768.0
        self.rec_buffer = []
        self.silence_start = None
        
        segments, _ = self.whisper.transcribe(audio_data, beam_size=5)
        text = " ".join([s.text for s in segments]).strip()
        
        if text:
            logger.info(f"Transcribed: {text}")
            self.last_text = text
            
            # Macro Check
            lower_text = text.lower().strip().rstrip('.').rstrip('!')
            if lower_text in self.macros:
                cmd = self.macros[lower_text]
                logger.info(f"Executing Macro: {cmd}")
                subprocess.Popen(cmd, shell=True)
            else:
                type_text(text)
        
        self.set_mode(self.config_mode)
        self.play_sound("transcribed")

    def reset_state(self, keep_config=False):
        """Clean State Machine Reset"""
        logger.info(f"Resetting State Machine (Keep Config: {keep_config})...")
        self.mode = "WAKE"
        if not keep_config:
            self.config_mode = "WAKE"
        self.rec_buffer = []
        self.silence_start = None
        self.send_ipc_update()
        self.play_sound("sleeping")
        if not keep_config:
            self.play_sound("reset") # Hard reset sound

    def set_mode(self, mode):
        # If setting a primary mode, update config_mode
        if mode in ["WAKE", "MANUAL", "FOCUS"]:
            self.config_mode = mode
            self.mode = mode
        else:
            # Transient modes (LISTENING, PROCESSING)
            self.mode = mode
            
        logger.info(f"Mode set to: {self.mode} (Config: {getattr(self, 'config_mode', 'WAKE')})")
        self.send_ipc_update()
        # self.play_sound("sleeping") # Removed, sounds are now handled more explicitly

    def play_sound(self, sound_type):
        # New Audio Protocol: High (Ready), Low (Done), Mid (Transcribed)
        # Using generated simple sine waves for clarity
        base_path = "/home/andrew-dolby/DAO_Linux_Workspace/dex-dictate-v3-repo/assets/sounds"
        sounds = {
            "listening": os.path.join(base_path, "high_beep.wav"), # High Beep (Ready)
            "done": os.path.join(base_path, "low_beep.wav"), # Low Beep (Done Listening)
            "transcribed": os.path.join(base_path, "low_beep.wav"), # Low Beep (Done/Transcribed) - Keep simple
            "reset": os.path.join(base_path, "reset_beep.wav") # Reset/Sleep
        }
        path = sounds.get(sound_type)
        if path and os.path.exists(path):
            subprocess.Popen(['paplay', path], stderr=subprocess.DEVNULL)

    def ipc_loop(self):
        if os.path.exists(SOCK_FILE): os.remove(SOCK_FILE)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCK_FILE)
        server.listen(1)
        logger.info(f"IPC Listening on {SOCK_FILE}")
        
        while True:
            conn, _ = server.accept()
            try:
                data = conn.recv(1024).decode()
                if not data: continue
                
                cmd = json.loads(data)
                if cmd['cmd'] == "SET_MODE":
                    self.set_mode(cmd['mode'])
                elif cmd['cmd'] == "GET_STATUS":
                    self.send_ipc_update(conn)
                elif cmd['cmd'] == "TOGGLE":
                    new_mode = "LISTENING" if self.mode == "WAKE" else "WAKE"
                    self.set_mode(new_mode)
                    if new_mode == "LISTENING": self.play_sound("listening")
                    # Toggle between WAKE and MANUAL config modes
                    new_config_mode = "MANUAL" if self.config_mode == "WAKE" else "WAKE"
                    self.set_mode(new_config_mode)
                    if new_config_mode == "MANUAL": self.play_sound("listening")
                    else: self.play_sound("sleeping")
                elif cmd['cmd'] == "SET_CONFIG_MODE": # New command to set primary mode
                    if cmd['mode'] in ["WAKE", "MANUAL", "FOCUS"]:
                        self.set_mode(cmd['mode'])
                        if cmd['mode'] == "MANUAL": self.play_sound("listening")
                        else: self.play_sound("sleeping")
                    else:
                        logger.warning(f"Invalid config mode received: {cmd['mode']}")
                elif cmd['cmd'] == "FOCUS_STATE": # New command for focus events
                    pass # self.handle_focus(cmd['state'])
                elif cmd['cmd'] == "FOCUS_GAINED":
                    pass # self.handle_focus("GAINED")
                elif cmd['cmd'] == "FOCUS_LOST":
                    pass
                    # On focus lost, we don't just set mode, we ensure a clean reset if we were listening
                    # if self.mode == "LISTENING":
                    #     # Soft reset: Stop listening, but keep FOCUS config if active
                    #     self.reset_state(keep_config=(self.config_mode == "FOCUS"))
                    #     if self.config_mode == "FOCUS":
                    #          self.set_mode("FOCUS") # Explicitly set back to FOCUS state
                    # else:
                    #     self.handle_focus("LOST")
                elif cmd['cmd'] == "STOP":
                    logger.info("Received STOP command. Shutting down...")
                    self.cleanup()
                    sys.exit(0)
            except Exception as e:
                logger.error(f"IPC Error: {e}")
            finally:
                conn.close()

    def handle_focus(self, state):
        # Only act if user selected FOCUS mode
        # NIGHTTIME STABILIZATION: FOCUS MODE DISABLED
        pass
        # if getattr(self, 'config_mode', 'WAKE') == "FOCUS":
        #     if state == "GAINED":
        #         logger.info("Focus Gained -> LISTENING")
        #         self.set_mode("LISTENING")
        #         self.play_sound("listening")
        #     elif state == "LOST":
        #         logger.info("Focus Lost -> FOCUS (Idle)")
        #         self.set_mode("FOCUS")
        #         self.play_sound("sleeping")

    def send_ipc_update(self, conn=None):
        msg = json.dumps({
            "status": self.mode,
            "config_mode": getattr(self, 'config_mode', 'WAKE'),
            "last_text": getattr(self, 'last_text', "")
        }).encode()
        if conn:
            conn.send(msg)
        else:
            pass

if __name__ == "__main__":
    daemon = DexDaemon()
    daemon.process_audio()
