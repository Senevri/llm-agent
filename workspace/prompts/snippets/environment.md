>
# Environment (stable facts — verified at build time)

- User: sandboxuser. Home: /home/sandboxuser (writable, exec-allowed).
- Working directory: /workspace (persistent volume; 9p mount; SLOW for
  many-small-file I/O like pip installs; do not build
  venvs here).
- Root filesystem `/` is READ-ONLY. apt-get will fail at runtime.
- /tmp is tmpfs with `noexec`: scripts run (shebang is read by the interpreter),
  but compiled extensions in /tmp fail to import. Do not install packages there.
- Your own source code: /agent.
- Python: `python3` and `pip` on PATH. `pip install --user` installs to
  ~/.local/lib/python3.X/site-packages, which IS on PATH via
  ~/.local/bin — use this for runtime deps. Prefer `uv` if available.
- Installed CLI tools: git, curl, wget, w3m, jq, rg (ripgrep), procps, iproute2 fd, bat, tree, less,
  file, rsync, build-essential, pkg-config, vi, tmux.
- If a tool you want is not in
  this list, install a static binary into ~/.local/bin rather than using apt.
- Your own source code is at /agent. `get_ip.py` exposes `get_gateway_ip()` which
  returns the host gateway IP — use it in any program you write that needs to
  reach the host's Ollama or other services.
- Never hardcode `localhost` or `127.0.0.1` in generated code. The host may be
  reachable only via the gateway IP; programs you write run in the same
  container as you, so they need the same endpoint discovery you use.
- Programs that call the LLM should read `LLM_BASE_URL` or `OPENAI_BASE_URL`
  from the environment, falling back to `f"http://{get_gateway_ip()}:11434/v1"`.
