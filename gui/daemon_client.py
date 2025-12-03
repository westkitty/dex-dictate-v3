from PySide6.QtCore import QThread, Signal
import socket
import time
import os

SOCKET_PATH = f"/run/user/{os.getuid()}/dex3.sock"

class DaemonClient(QThread):
    status_signal = Signal(str, str) # state, extra
    log_signal = Signal(str)
    data_signal = Signal(str) # New signal for raw data like devices
    
    def __init__(self, state_manager):
        super().__init__()
        self.state_manager = state_manager
        self.running = True
        self.sock = None
        
    def run(self):
        while self.running:
            try:
                if not os.path.exists(SOCKET_PATH):
                    self.state_manager.set_status("OFFLINE", "")
                    time.sleep(2)
                    continue
                    
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(SOCKET_PATH)
                self.state_manager.set_status("CONNECTED", "IDLE")
                
                while self.running:
                    data = self.sock.recv(1024).decode()
                    if not data: break
                    
                    if data.startswith("STATUS:"):
                        parts = data.split(":", 2)
                        state = parts[1]
                        extra = parts[2] if len(parts) > 2 else ""
                        self.state_manager.set_status(state, extra)
                    elif data.startswith("LOG:"):
                        # self.log_signal.emit(data[4:]) 
                        # Log signal might still be useful for UI log window?
                        # Or StateManager handles logs? 
                        # Let's keep log_signal for now, but maybe StateManager should have a log signal?
                        # For simplicity, let's emit to StateManager if we add a log signal there, 
                        # or just keep it here and connect MainWindow to it?
                        # The prompt says "All UI updates must be driven from this state."
                        # But logs are a stream.
                        # Let's emit it and let orchestrator connect it.
                        self.log_signal.emit(data[4:])
                    elif data.startswith("DEVICES:"):
                        self.data_signal.emit(data)
                        
            except Exception as e:
                self.state_manager.set_status("OFFLINE", "")
                time.sleep(2)
            finally:
                if self.sock: self.sock.close()
                
    def send_cmd(self, cmd):
        if self.sock:
            try:
                self.sock.sendall(cmd.encode())
            except:
                pass
                
    def stop(self):
        self.running = False
        self.wait()
