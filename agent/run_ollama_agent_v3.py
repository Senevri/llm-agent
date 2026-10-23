import os
import time
import json
import subprocess
import logging
from openai import OpenAI
from get_ip import get_gateway_ip
from ollama_agent_tools import tools, TOOL_MAP
from openai_error_handling import handle_api_error

# --- Configuration ---
LOG_LEVEL = os.getenv("AGENT_LOG_LEVEL", "INFO")
MODEL_NAME = os.getenv("AGENT_MODEL", "gemma4:31b-cloud")
MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "100"))
# TOOL_TIMEOUT and MAX_OUTPUT_LENGTH are now handled in ollama_agent_tools.py
CONTEXT_WINDOW_LIMIT = int(os.getenv("AGENT_CONTEXT_LIMIT", "50"))

# Setup Logging
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("OllamaAgentV3")

# Connect to Ollama
HOST_IP = get_gateway_ip()

PORT = os.getenv("OLLAMA_PORT", "11434")
#PORT = os.getenv("OLLAMA_PORT", "5001") # Kobold
BASE_URL = os.getenv("OLLAMA_BASE_URL", f"http://{HOST_IP}:{PORT}/v1")
client = OpenAI(
    base_url=BASE_URL,
    api_key="ollama"
)

def main():
    # Load Prompts
    try:
        with open("system_prompt.md", "r", encoding="utf-8") as f:
            system_prompt = f.read()
        with open("user_prompt.md", "r", encoding="utf-8") as f:
            user_prompt = f.read()
    except FileNotFoundError as e:
        logger.error(f"Required prompt file missing: {e}")
        return

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    logger.info(f"--- Starting Agent Loop v3 via Ollama ({MODEL_NAME}) ---")

    empty_streak = 0

    for turn in range(MAX_TURNS):
        # simple context trimming: keep system prompt and the last N messages
        if len(messages) > CONTEXT_WINDOW_LIMIT + 1:
            messages = [messages[0]] + messages[-(CONTEXT_WINDOW_LIMIT):]

        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
        except Exception as e:
            handle_api_error(e)
            continue

        choice = response.choices[0]
        msg = choice.message
        finish_reason = choice.finish_reason

        if not msg.tool_calls and not msg.content:
            empty_streak += 1
            logger.warning(f"Empty response (finish_reason={finish_reason}, streak={empty_streak})")
            if empty_streak >= 4:
                logger.error("Model stuck returning empty responses; aborting.")
                break
            messages.append({
                "role": "user",
                "content": "Continue the task, or if it is complete, respond with your final summary."
            })
            continue

        empty_streak = 0
        messages.append(msg)

        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                if func_name in TOOL_MAP:
                    try:
                        args = json.loads(tool_call.function.arguments)
                        result = TOOL_MAP[func_name](**args)
                        logger.info(f"Tool {func_name} output: {result[:100]}...")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": func_name,
                            "content": result
                        })
                    except Exception as e:
                        logger.error(f"Tool execution failed: {e}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": func_name,
                            "content": f"Error executing tool: {str(e)}"
                        })
                else:
                    logger.warning(f"Unknown tool requested: {func_name}")
        elif msg.content:
            logger.info(f"\n[Agent Final Response]:\n{msg.content}")
            break

if __name__ == "__main__":
    main()
