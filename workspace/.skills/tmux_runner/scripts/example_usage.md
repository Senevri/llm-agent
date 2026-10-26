# Example Usage: Non-Blocking TUI Execution

This document demonstrates how to use the `run_in_tmux.sh` wrapper to handle a TUI application like `ddgr` (a command-line Google search tool) or any other interactive program.

## Scenario: Using `ddgr` for a search

### 1. Launching the Application
Instead of running `ddgr` directly, the agent calls the wrapper:

```bash
SESSION=$(/workspace/run_in_tmux.sh "ddgr" "google_search")
echo "Session created: $SESSION"
```

**Result:** The `ddgr` process starts in the background. The agent's shell returns immediately.

### 2. Interacting with the TUI
To perform a search, the agent sends keys to the tmux session:

```bash
# Send the search query "tmux tutorial" and press Enter
tmux send-keys -t "google_search" "tmux tutorial" ENTER
```

### 3. Observing the Result
The agent captures the screen to read the search results:

```bash
# Capture the current view of the terminal
tmux capture-pane -t "google_search"
```

### 4. Handling Navigation
To move down the list of results:

```bash
# Send the 'down' arrow key
tmux send-keys -t "google_search" "Down"
# Recapture to see the updated screen
tmux capture-pane -t "google_search"
```

### 5. Cleaning Up
Once the information is gathered, the agent terminates the session:

```bash
tmux kill-session -t "google_search"
```

## Summary of Tooling Chain

| Action | Command | Blocking? |
| :--- | :--- | :--- |
| **Start** | `/workspace/run_in_tmux.sh "cmd"` | No |
| **Inspect** | `tmux capture-pane -t <session>` | No |
| **Interact** | `tmux send-keys -t <session> <input> ENTER` | No |
| **Stop** | `tmux kill-session -t <session>` | No |
