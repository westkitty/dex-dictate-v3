import sys
from PySide6.QtWidgets import QApplication
from gui.dex_bar import DexBar
from gui.main_window import MainWindow
from gui.state import StateManager

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Initialize State Manager (Singleton)
    state_manager = StateManager()
    
    # Create Main Window (The Relic)
    main_window = MainWindow(state_manager)
    
    # Geometry Fix: Push down by 32px (Toolbar Height)
    screen = QApplication.primaryScreen().geometry()
    main_window.setGeometry(0, 32, screen.width(), screen.height() - 32)
    main_window.show()
    
    # Create Toolbar (DexBar)
    # Pass main_window to allow toggling? Or just let them coexist via StateManager?
    # DexBar uses StateManager, so they are synced.
    bar = DexBar(state_manager)
    bar.show()
    
    # Connect signals if needed (e.g. toggle bar from main window)
    # Connect signals
    main_window.request_toggle_bar.connect(lambda: bar.setVisible(not bar.isVisible()))
    
    # Connect Daemon Commands
    def handle_cmd(cmd_str):
        if ":" in cmd_str:
            cmd, arg = cmd_str.split(":", 1)
            state_manager.send_cmd(cmd, arg)
        else:
            state_manager.send_cmd(cmd_str)
            
    main_window.request_daemon_cmd.connect(handle_cmd)
    
    # Connect Bar Signals
    bar.request_open_gui.connect(main_window.show)
    bar.request_quit.connect(app.quit)
    
    sys.exit(app.exec())
