# Dex Dictate v3 - Starsilk Expansion

A local, privacy-focused voice dictation and command system for Linux (Wayland/GNOME).

![Dex Dictate Logo](https://via.placeholder.com/150x150.png?text=Dex+Dictate)

## 🌟 Features

*   **Local Processing**: Uses VOSK for offline speech recognition. No data leaves your machine.
*   **Wayland Support**: Uses `ydotool` or `uinput` for text injection on modern Linux desktops.
*   **Modes**:
    *   **Wake Word**: "Computer, [command]" (Powered by Porcupine).
    *   **Manual**: Push-to-Talk (F9 Start / F10 Stop).
    *   **Focus**: Voice Activity Detection (VAD) for continuous dictation.
*   **Custom Commands**: Define macros for launching apps, controlling media, or inserting snippets.
*   **Modern GUI**: A sleek, dark-themed Qt interface with accessibility support.

## 🚀 Installation

### Prerequisites
*   Python 3.10+
*   `pip` and `venv`
*   `ydotool` (for Wayland input simulation)
*   `portaudio` (for audio input)

### Setup

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/yourusername/dex-dictate-v3.git
    cd dex-dictate-v3
    ```

2.  **Create a virtual environment**:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Download VOSK Model**:
    Download a model from [alphacephei.com](https://alphacephei.com/vosk/models) (e.g., `vosk-model-small-en-us-0.15`) and extract it to `~/.cache/vosk/`.

5.  **Configure ydotool**:
    Ensure `ydotoold` is running. You may need to start it as a user service.

## 🖥️ Usage

### Running the Daemon
The daemon handles audio processing and input simulation.
```bash
./run_daemon.sh
```
*Or install as a systemd user service (recommended).*

### Running the GUI
```bash
./run_gui.sh
```

### Hotkeys
*   **F9**: Start Recording (Manual Mode)
*   **F10**: Stop Recording (Manual Mode)
*   **Ctrl+Alt+D**: Toggle GUI (if configured)

## ⚙️ Configuration

Settings are stored in `~/.config/dex-dictate/config.json`.
You can configure:
*   **Macros**: Custom voice triggers.
*   **Theme**: Accent colors and background styles.
*   **Audio Device**: Select specific input device.
*   **Sensitivity**: VAD threshold.

## 🤝 Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
