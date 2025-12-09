import pvporcupine
import os

ACCESS_KEY = os.environ.get("PICOVOICE_ACCESS_KEY", "CpyLypXl9zpcJzppA6W70VwqTDr2+d2XYa6AhExQYPryoIwbt2h6DA==")

try:
    print(f"Testing Porcupine with key: {ACCESS_KEY[:5]}...")
    pp = pvporcupine.create(access_key=ACCESS_KEY, keywords=['porcupine'])
    print("Porcupine Initialized Successfully!")
    print(f"Sample Rate: {pp.sample_rate}")
    print(f"Frame Length: {pp.frame_length}")
except Exception as e:
    print(f"Porcupine Failed: {e}")
