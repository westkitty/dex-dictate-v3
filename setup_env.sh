#!/bin/bash
# setup_env.sh

echo "--- DEX DICTATE V3 SETUP (EXT4 WORKSPACE) ---"

# 1. System Deps
echo "Installing System Dependencies..."
sudo apt update
sudo apt install -y python3-tk libgirepository1.0-dev libcairo2-dev python3-dev libasound2-dev wl-clipboard ffmpeg

# 2. Accessibility
echo "Enabling Accessibility..."
gsettings set org.gnome.desktop.interface toolkit-accessibility true

# 3. User Groups
echo "Adding user to input group..."
sudo usermod -aG input $USER

# 4. Python Deps
echo "Installing Python Dependencies..."
/home/andrew-dolby/.cache/vibe_venv/dex-dictate-v3/bin/pip install sounddevice numpy torch pvporcupine faster-whisper evdev pyperclip pyatspi2 pystray pillow simpleaudio

# 5. Preload Models
echo "Preloading Models..."
/home/andrew-dolby/.cache/vibe_venv/dex-dictate-v3/bin/python3 /home/andrew-dolby/DAO_Linux_Workspace/Projects/dex-dictate-v3/preload_models.py

echo "--- SETUP COMPLETE ---"
echo "Please REBOOT your system to apply group changes."
