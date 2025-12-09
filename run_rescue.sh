#!/bin/bash
# Rescue script to run Dex Dictate v3 from the repo using the temp venv

VENV=/tmp/dex_venv
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Export Keys
export PICOVOICE_ACCESS_KEY="CpyLypXl9zpcJzppA6W70VwqTDr2+d2XYa6AhExQYPryoIwbt2h6DA=="
export PYTHONUNBUFFERED=1

# Ensure Venv exists
if [ ! -d "$VENV" ]; then
    echo "Virtual Environment not found at $VENV"
    exit 1
fi

# Kill old instances
pkill -f "dex_daemon.py"
pkill -f "dex_gui_qt.py"
pkill -f "dex_focus.py"

# Start Daemon
echo "Starting v3 Daemon..."
$VENV/bin/python3 $DIR/dex_daemon.py > $DIR/logs/daemon_rescue.log 2>&1 &
DAEMON_PID=$!

# Start Focus Listener (Now Safe)
echo "Starting Focus Listener... (DISABLED FOR NIGHTTIME)"
# $VENV/bin/python3 $DIR/dex_focus.py > $DIR/logs/focus_rescue.log 2>&1 &
# FOCUS_PID=$!

# Start GUI
echo "Starting v3 GUI..."
$VENV/bin/python3 $DIR/dex_gui_qt.py > $DIR/logs/gui_rescue.log 2>&1

# Cleanup
kill $DAEMON_PID
# kill $FOCUS_PID
