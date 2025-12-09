import socket
import json
import time
import os
import sys

SOCK_FILE = f"/run/user/{os.getuid()}/dex3.sock"

def send_cmd(cmd, mode=None, state=None):
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(SOCK_FILE)
        msg = {"cmd": cmd}
        if mode: msg["mode"] = mode
        if state: msg["state"] = state
        client.send(json.dumps(msg).encode())
        
        # Wait for response if GET_STATUS
        if cmd == "GET_STATUS":
            data = client.recv(1024).decode()
            print(f"STATUS: {data}")
            return json.loads(data)
        client.close()
        print(f"Sent: {cmd} {mode if mode else ''} {state if state else ''}")
        time.sleep(0.5)
    except Exception as e:
        print(f"Error: {e}")

def run_diagnostics():
    print("--- DIAGNOSTIC TEST START ---")
    
    # 1. Check Initial Status
    status = send_cmd("GET_STATUS")
    if not status:
        print("FAIL: Daemon not reachable")
        return

    print(f"Initial Mode: {status.get('status')} (Config: {status.get('config_mode')})")

    # 2. Test Focus Mode Entry
    print("\n--- Test A: Focus Mode Entry & Failure Reset ---")
    send_cmd("SET_CONFIG_MODE", mode="FOCUS")
    status = send_cmd("GET_STATUS")
    if status.get('config_mode') != "FOCUS":
        print("FAIL: Could not set FOCUS mode")
    else:
        print("PASS: FOCUS mode set")

    # Simulate Focus Gained
    send_cmd("FOCUS_GAINED")
    status = send_cmd("GET_STATUS")
    if status.get('status') == "LISTENING":
        print("PASS: Focus Gained -> LISTENING")
    else:
        print(f"FAIL: Focus Gained -> {status.get('status')}")

    # Simulate Focus Lost (Failure Case)
    send_cmd("FOCUS_LOST")
    status = send_cmd("GET_STATUS")
    if status.get('status') == "WAKE" and status.get('config_mode') == "WAKE":
        print("PASS: Focus Lost -> Reset to WAKE (Clean Reset)")
    else:
        print(f"FAIL: Focus Lost -> {status.get('status')} / {status.get('config_mode')}")

    # 3. Test Audio Feedback
    print("\n--- Test B: Audio Feedback (Check Logs for 'done') ---")
    # We can't easily verify sound output programmatically without complex audio capture,
    # but we can trigger the flow that should play it.
    # Simulate a transcription flow
    send_cmd("SET_MODE", mode="LISTENING")
    time.sleep(1)
    # We can't force 'transcribe' via IPC easily without sending audio, 
    # but we can verify the state transition logic in the daemon logs.
    print("Check daemon logs for 'Playing sound: done'")

    print("\n--- DIAGNOSTIC TEST COMPLETE ---")

if __name__ == "__main__":
    run_diagnostics()
