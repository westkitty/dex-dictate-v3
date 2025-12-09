import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi, GLib
import time
import socket
import json
import os
import sys

SOCK_FILE = f"/run/user/{os.getuid()}/dex3.sock"

def on_focus_changed(event):
    try:
        acc = event.source
        try:
            role = acc.get_role()
        except:
            # Stale object or error getting role
            return

        # Debounce: Ignore if same object focused within 0.1s
        current_time = time.time()
        if hasattr(on_focus_changed, "last_focus_time"):
            if current_time - on_focus_changed.last_focus_time < 0.1:
                return
        on_focus_changed.last_focus_time = current_time
        
        # Expanded roles for better compatibility
        TEXT_ROLES = [
            Atspi.Role.TEXT, 
            Atspi.Role.ENTRY, 
            Atspi.Role.TERMINAL, 
            Atspi.Role.DOCUMENT_TEXT,
            Atspi.Role.PASSWORD_TEXT,
            Atspi.Role.PARAGRAPH,
            Atspi.Role.SECTION,
            Atspi.Role.HEADING,
            Atspi.Role.PAGE_TAB
        ]
        
        if role in TEXT_ROLES:
            print(f"Focused: {acc.get_name()} ({role})")
            send_cmd("FOCUS_GAINED")
        else:
            print(f"Focus Lost: {acc.get_name()} ({role})")
            send_cmd("FOCUS_LOST")
            
    except Exception as e:
        print(f"Focus Error: {e}")

def send_cmd(cmd, mode=None):
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(SOCK_FILE)
        msg = {"cmd": cmd}
        if mode: msg["mode"] = mode
        client.send(json.dumps(msg).encode())
        client.close()
    except: pass

def main():
    print("Starting Wayland Focus Listener (Atspi via GI)...")
    
    # Initialize Atspi
    ret = Atspi.init()
    if ret != 0:
        print(f"CRITICAL ERROR: Atspi.init() failed with code {ret}. Is the registry daemon running?")
        sys.exit(1)
    print("Atspi initialized successfully.")
    
    # Register Event Listener
    listener = Atspi.EventListener.new(on_focus_changed)
    listener.register("object:state-changed:focused")
    
    # Main Loop
    loop = GLib.MainLoop()
    print("Focus Listener Main Loop Starting...")
    try:
        loop.run()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
