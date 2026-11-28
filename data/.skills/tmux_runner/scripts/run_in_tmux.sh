#!/bin/bash

# run_in_tmux.sh
# A wrapper script to execute commands in a managed, detached tmux session.
# Usage: ./run_in_tmux.sh "command_to_run" [session_name]

set -e

COMMAND=$1
SESSION_NAME=$2

if [ -z "$COMMAND" ]; then
    echo "Error: No command provided."
    echo "Usage: $0 \"command\" [session_name]"
    exit 1
fi

# Generate a default session name if none is provided
if [ -z "$SESSION_NAME" ]; then
    SESSION_NAME="agent_exec_$(date +%s)_$RANDOM"
fi

# Check if tmux is installed
if ! command -v tmux >/dev/null 2>&1; then
    echo "Error: tmux is not installed."
    exit 1
fi

# Create a new detached session and run the command
# -d: detached
# -s: session name
# The command is wrapped in a shell to ensure it handles pipes/redirects correctly
tmux new-session -d -s "$SESSION_NAME" "bash -c \"$COMMAND; read -p 'Press enter to exit'\""

echo "Started session: $SESSION_NAME"
echo "Command: $COMMAND"
echo "----------------------------------------------------------------"
echo "To observe the output, use: tmux capture-pane -t $SESSION_NAME"
echo "To send input, use: tmux send-keys -t $SESSION_NAME \"input\" ENTER"
echo "To kill the session, use: tmux kill-session -t $SESSION_NAME"
echo "----------------------------------------------------------------"

echo "$SESSION_NAME" # Output session name for the agent to capture
