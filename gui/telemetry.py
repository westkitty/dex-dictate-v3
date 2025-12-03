import sounddevice as sd
import numpy as np
from PySide6.QtCore import QThread, Signal, QObject
import time

class TelemetryService(QThread):
    def __init__(self, state_manager):
        super().__init__()
        self.state_manager = state_manager
        self.running = True
        self.device_index = None

    def run(self):
        # Get device from config
        self.device_index = self.state_manager.get_config("audio_device", None)
        
        def callback(indata, frames, time, status):
            if status:
                print(status)
            if not self.running:
                raise sd.CallbackStop()
            
            # Compute RMS
            rms = np.sqrt(np.mean(indata**2))
            # Normalize somewhat (assuming 16-bit input usually, but float32 here)
            # float32 is -1.0 to 1.0. 
            # Let's boost it a bit for visualization
            level = min(rms * 5, 1.0) 
            
            # Update State
            self.state_manager.update_audio(level)

        try:
            with sd.InputStream(device=self.device_index, channels=1, callback=callback, blocksize=2048):
                while self.running:
                    self.msleep(100) # Keep thread alive, callback does the work
        except Exception as e:
            print(f"Telemetry Error: {e}")
            self.state_manager.set_status("ERROR", "MIC")

    def stop(self):
        self.running = False
        self.wait()
