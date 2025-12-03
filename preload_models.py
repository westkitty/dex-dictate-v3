import torch
from faster_whisper import WhisperModel
import os

print("--- PRELOADING MODELS ---")

# 1. Preload Silero VAD
print("Downloading Silero VAD...")
torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=True, trust_repo=True)

# 2. Preload Whisper
print("Downloading Faster-Whisper (small.en)...")
model = WhisperModel("small.en", device="cpu", compute_type="int8", download_root=os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub"))

print("--- PRELOAD COMPLETE ---")
