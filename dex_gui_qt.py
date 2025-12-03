import sys
import logging
import logging.handlers
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Slot

from gui.state import StateManager
from gui.telemetry import TelemetryService
from gui.daemon_client import DaemonClient
from gui.dex_bar import DexBar
from gui.main_window import MainWindow

# --- LOGGING SETUP ---
def setup_logging(name):
    log_dir = os.path.expanduser("~/.local/share/dex-dictate/logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{name}.log")
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # File Handler (Rotating)
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=1024*1024, backupCount=3
    )
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    # Console Handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    
    logger.addHandler(handler)
    logger.addHandler(console)
    return logger

logger = setup_logging("dex_gui")

class Orchestrator:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("Dex Dictate")
        
        # 1. State Manager
        self.state_manager = StateManager()
        
        # 2. Services
        self.telemetry = TelemetryService(self.state_manager)
        self.telemetry.start()
        
        self.daemon_client = DaemonClient(self.state_manager)
        self.daemon_client.start()
        
        # 3. UI Components
        self.dex_bar = DexBar(self.state_manager)
        self.main_window = MainWindow(self.state_manager)
        
        # 4. Wiring
        self._connect_signals()
        
        # 5. Initial Launch
        self.dex_bar.show()
        # Main window starts hidden or shown? 
        # Requirement: "Clicking the bar must open (or focus) the main GUI window."
        # Usually starts hidden if bar is primary? Or show both on launch?
        # Let's show both on launch for clarity, user can close main.
        self.main_window.show()

    def _connect_signals(self):
        # DexBar -> Main Window
        self.dex_bar.request_open_gui.connect(self.show_main_window)
        self.dex_bar.request_quit.connect(self.quit_app)
        
        # Main Window -> Orchestrator
        self.main_window.request_daemon_cmd.connect(self.daemon_client.send_cmd)
        self.main_window.request_toggle_bar.connect(self.toggle_dex_bar)
        
        # State Manager -> Daemon (Mode Sync)
        self.state_manager.mode_changed.connect(self.on_mode_changed)
        
        # Daemon -> Logs (Optional, if we want to log daemon msgs to file)
        self.daemon_client.log_signal.connect(lambda msg: logger.info(f"DAEMON: {msg}"))

    @Slot()
    def show_main_window(self):
        self.main_window.show()
        self.main_window.activateWindow()
        self.main_window.raise_()

    @Slot()
    def toggle_dex_bar(self):
        if self.dex_bar.isVisible():
            self.dex_bar.hide()
        else:
            self.dex_bar.show()

    @Slot(str)
    def on_mode_changed(self, mode):
        # Send to daemon
        self.daemon_client.send_cmd(f"SET_MODE:{mode}")

    @Slot()
    def quit_app(self):
        logger.info("Quitting application...")
        self.telemetry.stop()
        self.daemon_client.stop()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec())

if __name__ == "__main__":
    orch = Orchestrator()
    orch.run()
