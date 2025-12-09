import socket
import json
import time
import os
import sys
import subprocess

SOCK_FILE = f"/run/user/{os.getuid()}/dex3.sock"

def check_process(name):
    try:
        res = subprocess.run(["pgrep", "-f", name], capture_output=True, text=True)
        if res.returncode == 0:
            pids = res.stdout.strip().split('\n')
            print(f"PASS: {name} is running (PIDs: {pids})")
            return True
        else:
            print(f"FAIL: {name} is NOT running")
            return False
    except Exception as e:
        print(f"Error checking process {name}: {e}")
        return False

def send_cmd(cmd, mode=None, state=None):
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(SOCK_FILE)
        msg = {"cmd": cmd}
        if mode: msg["mode"] = mode
        if state: msg["state"] = state
        client.send(json.dumps(msg).encode())
        
        if cmd == "GET_STATUS":
            data = client.recv(1024).decode()
            print(f"STATUS: {data}")
            return json.loads(data)
        client.close()
        print(f"Sent: {cmd} {mode if mode else ''} {state if state else ''}")
        time.sleep(0.5)
    except Exception as e:
        print(f"IPC Error: {e}")
        return None

def run_deep_diagnostics():
    print("--- DEEP DIAGNOSTIC START ---")
    
    # 1. Process Check
    d_ok = check_process("dex_daemon.py")
    f_ok = check_process("dex_focus.py")
    
    if not d_ok:
        print("CRITICAL: Daemon is down. Aborting.")
        return

    # 2. State Machine Check
    print("\n--- State Machine Check ---")
    status = send_cmd("GET_STATUS")
    if not status:
        print("CRITICAL: Daemon IPC unresponsive.")
        return

    print(f"Current State: {status}")

    # 3. Focus Mode Simulation
    print("\n--- Focus Mode Simulation ---")
    # Force WAKE first
    send_cmd("SET_CONFIG_MODE", mode="WAKE")
    time.sleep(0.5)
    
    # Switch to FOCUS
    send_cmd("SET_CONFIG_MODE", mode="FOCUS")
    status = send_cmd("GET_STATUS")
    if status.get("config_mode") != "FOCUS":
        print("FAIL: Failed to set FOCUS mode via IPC")
    else:
        print("PASS: FOCUS mode set via IPC")

    # Simulate Focus Gained
    send_cmd("FOCUS_GAINED")
    status = send_cmd("GET_STATUS")
    if status.get("status") == "LISTENING":
        print("PASS: Focus Gained -> LISTENING")
    else:
        print(f"FAIL: Focus Gained -> {status.get('status')} (Expected LISTENING)")

    # Simulate Focus Lost (Clean Reset Check)
    send_cmd("FOCUS_LOST")
    status = send_cmd("GET_STATUS")
    if status.get("status") == "FOCUS":
        print("PASS: Focus Lost -> FOCUS (Persistent Focus Mode)")
    else:
        print(f"FAIL: Focus Lost -> {status.get('status')} (Expected FOCUS)")

    print("\n--- DEEP DIAGNOSTIC COMPLETE ---")

if __name__ == "__main__":
    run_deep_diagnostics()
