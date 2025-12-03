#!/usr/bin/env python3
import pyatspi
import socket
import os
import json
import time
import threading
from gi.repository import GLib

# --- CONFIG ---
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
SOCK_PATH = os.path.join(RUNTIME, "dex3.sock")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# State
current_mode = "WAKE"

def load_config():
    global current_mode
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
            current_mode = config.get("mode", "WAKE")
    except: pass

def send_cmd(cmd):
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.5)
        client.connect(SOCK_PATH)
        client.send(cmd.encode())
        client.close()
    except Exception as e:
        # print(f"Socket Error: {e}")
        pass

def log(msg):
    with open("/tmp/dex_focus.log", "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} - {msg}\n")

def on_focus_changed(event):
    if current_mode != "FOCUS": return
    
    try:
        accessible = event.source
        role = accessible.get_role()
        # log(f"Event: {accessible.name} ({role})")
        
        # Check if it's a text entry field
        # ROLE_TEXT, ROLE_ENTRY, ROLE_TERMINAL, ROLE_DOCUMENT_TEXT, ROLE_PARAGRAPH
        if role in [pyatspi.ROLE_TEXT, pyatspi.ROLE_ENTRY, pyatspi.ROLE_DOCUMENT_TEXT, pyatspi.ROLE_TERMINAL, pyatspi.ROLE_PARAGRAPH]:
            if event.detail1 == 1: # Focus Gained
                log(f"Focus Gained: {accessible.name} ({role})")
                send_cmd("PLAY_CHIME")
                send_cmd("START_REC")
            else: # Focus Lost
                log(f"Focus Lost: {accessible.name}")
                send_cmd("STOP_REC")
    except Exception as e:
        log(f"Focus Handler Error: {e}")

def config_watcher():
    while True:
        load_config()
        time.sleep(2)

def main():
    log("Dex Focus Listener Started.")
    print("Dex Focus Listener Started.")
    
    # Start Config Watcher
    t = threading.Thread(target=config_watcher, daemon=True)
    t.start()
    
    # Register Registry
    pyatspi.Registry.registerEventListener(on_focus_changed, "object:state-changed:focused")
    
    # Main Loop
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
