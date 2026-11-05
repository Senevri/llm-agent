# Environment

- run_bash operates probably in cmd;
- not running on /workspace, so use relative paths.
- installed cli tools: git, curl, wget, awk, sed, rg(ripgrep), jq, tree, less, file,
  vi and more
- You are restricted to set directories; Typically current working directory.
- Never hardcode `localhost` or `127.0.0.1` in generated code. The host may be
  reachable only via the gateway IP; programs you write run in the same
  container as you, so they need the same endpoint discovery you use.
- Programs that call the LLM should read `LLM_BASE_URL` or `OPENAI_BASE_URL`
  from the environment, falling back to `f"http://{get_gateway_ip()}:11434
