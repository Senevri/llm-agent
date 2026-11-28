---
Name: Tmux Runner
Description: A skill to execute long-running commands in a detached tmux session, allowing the agent to monitor progress and interact with the process over time.
Version: 1.0.0
Author: Agent
Category: execution
Dependencies: tmux
---

# Instructions
1. Use `tmux_create_session(name, command, cwd)` to start a process.
2. Ensure the session name starts with `agent-`.
3. Use `tmux_capture(session, lines)` to check the output.
4. Use `tmux_send(session, input)` to provide input to the running process.
5. Use `tmux_list()` to see all active agent sessions.
6. Use `tmux_kill(session)` to terminate the process when done.
