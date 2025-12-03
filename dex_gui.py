#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, scrolledtext
import socket
import os
import json
import threading
import time
import subprocess
import sys
import pystray
from PIL import Image, ImageDraw

# --- CONSTANTS & CONFIG ---
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
SOCK_PATH = os.path.join(RUNTIME, "dex3.sock")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# Colors
COLOR_BG = "#111111"
COLOR_FG = "#00FFFF"
COLOR_ACCENT = "#008888"
COLOR_LOG_BG = "#000000"
COLOR_LOG_FG = "#00FF00"

# Status Colors
STATUS_RED = "#FF0000"      # Offline
STATUS_YELLOW = "#FFFF00"   # Connecting
STATUS_GREEN = "#00FF00"    # Online/Ready
STATUS_FLASH = "#CCFFCC"    # Recording (Bright Green)

class DexGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Dex Dictate v3")
        self.root.geometry("500x600")
        self.root.configure(bg=COLOR_BG)
        
        self.load_config()
        self.connected = False
        self.recording = False
        self.last_pong = 0
        
        # --- STYLES ---
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_FG, font=("Monospace", 10))
        style.configure("TButton", background="#333", foreground="white", borderwidth=1)
        style.map("TButton", background=[("active", "#555")])
        style.configure("TRadiobutton", background=COLOR_BG, foreground=COLOR_FG)
        style.configure("TFrame", background=COLOR_BG)
        
        # --- UI LAYOUT ---
        
        # 1. Header & Status
        header_frame = ttk.Frame(root)
        header_frame.pack(fill=tk.X, pady=15, padx=15)
        
        ttk.Label(header_frame, text="DEX DICTATE V3", font=("Monospace", 14, "bold")).pack(side=tk.LEFT)
        
        # Status Canvas (LED)
        self.status_canvas = tk.Canvas(header_frame, width=30, height=30, bg=COLOR_BG, highlightthickness=0)
        self.status_canvas.pack(side=tk.RIGHT)
        self.led = self.status_canvas.create_oval(5, 5, 25, 25, fill=STATUS_RED, outline="")
        
        # 2. Mode Selection
        mode_frame = ttk.LabelFrame(root, text=" Operation Mode ", padding=10)
        mode_frame.pack(fill=tk.X, padx=15, pady=5)
        
        self.mode_var = tk.StringVar(value=self.config.get("mode", "WAKE"))
        modes = [("Wake Word", "WAKE"), ("Manual", "MANUAL"), ("Focus", "FOCUS")]
        
        for text, val in modes:
            rb = ttk.Radiobutton(mode_frame, text=text, variable=self.mode_var, value=val, command=self.set_mode)
            rb.pack(side=tk.LEFT, expand=True)

        # 3. Sensitivity
        sens_frame = ttk.LabelFrame(root, text=" Sensitivity ", padding=10)
        sens_frame.pack(fill=tk.X, padx=15, pady=5)
        
        self.scale_sens = tk.Scale(sens_frame, from_=0, to=1, resolution=0.1, orient=tk.HORIZONTAL, 
                                   bg=COLOR_BG, fg=COLOR_FG, highlightthickness=0, command=self.on_sens_change)
        self.scale_sens.set(self.config.get("sensitivity", 0.7))
        self.scale_sens.pack(fill=tk.X)

        # 4. Hotkey Config
        hk_frame = ttk.LabelFrame(root, text=" Hotkeys (Manual Mode) ", padding=10)
        hk_frame.pack(fill=tk.X, padx=15, pady=5)
        
        ttk.Label(hk_frame, text="Start Key:").grid(row=0, column=0, padx=5)
        self.entry_start = ttk.Entry(hk_frame, width=10)
        self.entry_start.insert(0, self.config.get("hotkey_start", "F9"))
        self.entry_start.grid(row=0, column=1, padx=5)
        
        ttk.Label(hk_frame, text="Stop Key:").grid(row=0, column=2, padx=5)
        self.entry_stop = ttk.Entry(hk_frame, width=10)
        self.entry_stop.insert(0, self.config.get("hotkey_stop", "F10"))
        self.entry_stop.grid(row=0, column=3, padx=5)
        
        btn_save_hk = ttk.Button(hk_frame, text="Save", command=self.save_config)
        btn_save_hk.grid(row=0, column=4, padx=10)

        # 5. Controls
        ctrl_frame = ttk.Frame(root)
        ctrl_frame.pack(fill=tk.X, padx=15, pady=10)
        
        self.btn_toggle = tk.Button(ctrl_frame, text="TOGGLE RECORDING", bg="#222", fg=COLOR_FG, 
                                    font=("Monospace", 10, "bold"), command=self.toggle_recording)
        self.btn_toggle.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        btn_kill = tk.Button(ctrl_frame, text="RESTART DAEMON", bg="#500", fg="white", command=self.restart_daemon)
        btn_kill.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))

        # 6. Transcription Log
        log_frame = ttk.LabelFrame(root, text=" System Log ", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))
        
        self.log_text = scrolledtext.ScrolledText(log_frame, bg=COLOR_LOG_BG, fg=COLOR_LOG_FG, 
                                                  font=("Monospace", 9), height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log("GUI Started. Initializing Watchdog...")

        # --- THREADS ---
        self.stop_event = threading.Event()
        
        # Watchdog Thread
        self.wd_thread = threading.Thread(target=self.watchdog_loop, daemon=True)
        self.wd_thread.start()
        
        # Tray Icon
        threading.Thread(target=self.setup_tray, daemon=True).start()

    # --- LOGIC ---

    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.log_text.see(tk.END)

    def set_led(self, color):
        self.status_canvas.itemconfig(self.led, fill=color)

    def load_config(self):
        try:
            with open(CONFIG_PATH, 'r') as f: self.config = json.load(f)
        except:
            self.config = {"mode": "WAKE", "sensitivity": 0.7, "hotkey_start": "F9", "hotkey_stop": "F10"}

    def save_config(self):
        self.config["mode"] = self.mode_var.get()
        self.config["sensitivity"] = self.scale_sens.get()
        self.config["hotkey_start"] = self.entry_start.get()
        self.config["hotkey_stop"] = self.entry_stop.get()
        try:
            with open(CONFIG_PATH, 'w') as f: json.dump(self.config, f)
            self.log("Configuration saved.")
            self.send_cmd("RELOAD_CONFIG")
        except Exception as e:
            self.log(f"Error saving config: {e}")

    def send_cmd(self, cmd):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(1.0)
            client.connect(SOCK_PATH)
            client.send(cmd.encode())
            resp = client.recv(1024).decode()
            client.close()
            return resp
        except Exception as e:
            return None

    def set_mode(self):
        mode = self.mode_var.get()
        self.log(f"Setting Mode: {mode}")
        self.send_cmd(f"SET_MODE:{mode}")
        self.save_config()

    def on_sens_change(self, val):
        # Debounce could be added here, but direct send is okay for local socket
        self.send_cmd(f"SET_SENS:{val}")

    def toggle_recording(self):
        self.send_cmd("TOGGLE")
        self.log("Sent TOGGLE command.")

    def restart_daemon(self):
        self.log("⚠️ Restarting Daemon Service...")
        self.set_led(STATUS_RED)
        try:
            subprocess.Popen(['systemctl', '--user', 'restart', 'dex-dictate'])
            self.log("Service restart command sent.")
        except Exception as e:
            self.log(f"Failed to restart service: {e}")

    # --- WATCHDOG ---

    def watchdog_loop(self):
        # Startup Grace Period
        self.log("Waiting for daemon (Startup Grace Period)...")
        self.set_led(STATUS_YELLOW)
        
        # Aggressive Connect Logic
        while not self.stop_event.is_set():
            resp = self.send_cmd("PING")
            
            if resp and resp.startswith("PONG"):
                if not self.connected:
                    self.connected = True
                    self.log("✅ Daemon Connected!")
                    # Sync initial state
                    self.set_mode()
                
                # Parse Status (PONG:REC or PONG:IDLE)
                parts = resp.split(":")
                status = parts[1] if len(parts) > 1 else "IDLE"
                
                if status == "REC":
                    self.recording = True
                    # Flash Effect
                    cur_col = self.status_canvas.itemcget(self.led, "fill")
                    new_col = STATUS_FLASH if cur_col == STATUS_GREEN else STATUS_GREEN
                    self.root.after(0, self.set_led, new_col)
                else:
                    self.recording = False
                    self.root.after(0, self.set_led, STATUS_GREEN)
                
            else:
                if self.connected:
                    self.connected = False
                    self.log("❌ Daemon Disconnected.")
                    self.root.after(0, self.set_led, STATUS_RED)
                
                # Retry Logic
                self.log("Daemon Offline. Attempting restart...")
                self.restart_daemon()
                time.sleep(5) # Wait for restart
            
            time.sleep(2) # Heartbeat interval

    # --- TRAY ---
    def setup_tray(self):
        image = Image.new('RGB', (64, 64), color = (0, 128, 128))
        d = ImageDraw.Draw(image)
        d.text((10,10), "D", fill=(255,255,255))
        
        def on_quit(icon, item):
            icon.stop()
            self.stop_event.set()
            self.root.quit()
            sys.exit(0)
            
        def on_show(icon, item):
            self.root.deiconify()

        icon = pystray.Icon("DexDictate", image, menu=pystray.Menu(
            pystray.MenuItem("Show", on_show),
            pystray.MenuItem("Quit", on_quit)
        ))
        icon.run()

if __name__ == "__main__":
    root = tk.Tk()
    app = DexGUI(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)
