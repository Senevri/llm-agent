Installation: run build.bat (it should trivially convert to .sh)

You need an OpenAI compatible API endpoint somewhere.

You can export OLLAMA_BASE_URL and OLLAMA_PORT


run podman compose run --rm sandbox
edit prompts as desired
run python /agent/run_ollama_agent_v3.py