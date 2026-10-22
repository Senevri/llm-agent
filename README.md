# LLM Agent Project

This project provides tools for interacting with Large Language Models (LLMs) via an Ollama-compatible API, featuring both an autonomous agent loop and an interactive REPL.

# Installation

run build.bat (it should trivially convert to .sh)

You need an OpenAI compatible API endpoint somewhere.

You can export OLLAMA_BASE_URL and OLLAMA_PORT

run
    podman compose run --rm sandbox

This starts a BASH shell inside the container.

edit prompts as desired; They can be edited in the host filesystem.

run
    python /agent/run_ollama_agent_v3.py


## Components

### 1. Autonomous Agent (`run_ollama_agent_v3.py`)
An autonomous agent that follows a set of instructions provided in prompt files to complete a task, utilizing tool calling to interact with the system.

**Usage:**
The agent expects two prompt files in the current working directory:
- `system_prompt.md`: Defines the agent's persona and rules.
- `user_prompt.md`: Defines the specific task to be performed.

**Run the agent:**
```bash
python3 /agent/run_ollama_agent_v3.py
```

**Configuration (Environment Variables):**
- `AGENT_MODEL`: Model to use (default: `gemma4:31b-cloud`).
- `AGENT_MAX_TURNS`: Maximum number of iterations (default: `100`).
- `AGENT_CONTEXT_LIMIT`: Number of messages to keep in history (default: `50`).
- `AGENT_LOG_LEVEL`: Logging level (`INFO`, `DEBUG`, etc.).
- `OLLAMA_PORT`: Port for Ollama API (default: `11434`).
- `OLLAMA_BASE_URL`: Custom base URL for the API.

---

### 2. LLM REPL (`llm_repl.py`)
An interactive Read-Eval-Print Loop (REPL) that allows you to chat with an LLM and let it use local tools (bash, file I/O, internet search) to assist you.

**Usage:**
```bash
python3 /agent/llm_repl.py
```

**Commands:**
- `/q`: Quit the REPL.

**Configuration (Environment Variables):**
- `LLM_REPL_MODEL`: Model to use (default: `gemma4:e4b`).
- `LLM_REPL_BASE_URL`: Custom base URL for the API.
- `LLM_REPL_API_KEY`: API key (default: `ollama`).

**Available Tools in REPL:**
- `run_bash`: Executes shell commands.
- `read_file`: Reads contents of a file.
- `write_file`: Writes content to a file.
- `list_files`: Lists files in a directory.
- `search_internet`: Performs web searches (if `internet_tools.py` is available).
- `get_weather`: Fetches weather data (if `internet_tools.py` is available).

The tools automatically discover the host gateway IP to connect to Ollama running on the host.
