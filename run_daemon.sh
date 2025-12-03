#!/bin/bash
# run_daemon.sh

# Placeholder for Access Key - User should replace this if not set in environment
export PICOVOICE_ACCESS_KEY="CpyLypXl9zpcJzppA6W70VwqTDr2+d2XYa6AhExQYPryoIwbt2h6DA=="
export PYTHONUNBUFFERED=1

# Absolute path to Python in the Runtime Environment
PYTHON_BIN="/home/andrew-dolby/.cache/vibe_venv/dex-dictate-v3/bin/python3"
# Updated Path for EXT4 Workspace
DAEMON_SCRIPT="/home/andrew-dolby/DAO_Linux_Workspace/Projects/dex-dictate-v3/dex_daemon.py"

# Define VENV_PYTHON and PROJECT_DIR based on existing variables
VENV_PYTHON="$PYTHON_BIN"
PROJECT_DIR=$(dirname "$DAEMON_SCRIPT")

# Launch Focus Listener
"$VENV_PYTHON" "$PROJECT_DIR/dex_focus.py" &

# Launch Daemon
exec "$VENV_PYTHON" "$DAEMON_SCRIPT"
