import wave
import math
import struct
import os

def generate_beep(filename, frequency, duration_ms, volume=0.5):
    sample_rate = 44100
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    
    with wave.open(filename, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        for i in range(num_samples):
            value = int(volume * 32767.0 * math.sin(2.0 * math.pi * frequency * i / sample_rate))
            data = struct.pack('<h', value)
            wav_file.writeframes(data)
    print(f"Generated {filename}: {frequency}Hz, {duration_ms}ms")

OUTPUT_DIR = "/home/andrew-dolby/DAO_Linux_Workspace/dex-dictate-v3-repo/assets/sounds"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# High Beep (Ready) - 880Hz (A5), Short
generate_beep(os.path.join(OUTPUT_DIR, "high_beep.wav"), 880, 150)

# Low Beep (Done) - 440Hz (A4), Short
generate_beep(os.path.join(OUTPUT_DIR, "low_beep.wav"), 440, 150)

# Mid Tone (Transcribed) - 660Hz (E5), Slightly longer
generate_beep(os.path.join(OUTPUT_DIR, "mid_beep.wav"), 660, 200)

# Reset Tone - Descending Slide (Simulated by two tones)
# For simplicity, just a very low tone
generate_beep(os.path.join(OUTPUT_DIR, "reset_beep.wav"), 220, 300)
