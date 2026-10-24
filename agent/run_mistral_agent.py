import os
import time
import json
import logging
from openai import OpenAI
from ollama_agent_tools import tools, TOOL_MAP
from openai_error_handling import classify_api_error, Action

from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

PROMPT_DIR = Path(os.getenv("AGENT_PROMPT_DIR", ".")).resolve()

# --- Tiny .env loader (no extra dependency) ---
def _load_dotenv(path: Path = SCRIPT_DIR / ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(
                key.strip(), value.strip().strip('"').strip("'")
            )


_load_dotenv()


# --- Configuration ---
LOG_LEVEL = os.getenv("AGENT_LOG_LEVEL", "INFO")
MODEL_NAME = os.getenv("AGENT_MODEL", "ministral-14b-latest")
MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "100"))
CONTEXT_WINDOW_LIMIT = int(os.getenv("AGENT_CONTEXT_LIMIT", "50"))

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
if not MISTRAL_API_KEY:
    raise RuntimeError("MISTRAL_API_KEY not set. Add it to .env")

BASE_URL = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")

# Setup Logging
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("MistralAgentV3")


logger.info(f"Prompt dir: {PROMPT_DIR}")

for name in ("system_prompt.md", "user_prompt.md"):
    if not (PROMPT_DIR / name).exists():
        logger.error(f"Missing {PROMPT_DIR / name}")
        raise SystemExit(1)


# Connect to Mistral (OpenAI-compatible endpoint)
client = OpenAI(
    base_url=BASE_URL,
    api_key=MISTRAL_API_KEY,
)

def _role(m) -> str:
    return m["role"] if isinstance(m, dict) else getattr(m, "role", "")

def _trim_messages(messages, limit: int):
    if len(messages) <= limit + 1:
        return messages
    system = messages[0]
    tail = messages[-limit:]
    # drop orphaned tool results until we start on a legal message
    while tail and _role(tail[0]) == "tool":
        tail = tail[1:]
    return [system] + tail


def main():
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
        {"role": "user", "content": user_prompt},
    ]

    logger.info(f"--- Starting Agent Loop v3 via Mistral ({MODEL_NAME}) ---")

    empty_streak = 0

    for turn in range(MAX_TURNS):
        time.sleep(1) # Avoid hitting rate limits
        messages = _trim_messages(messages, CONTEXT_WINDOW_LIMIT)

        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
        except Exception as e:
            action, delay = classify_api_error(e)
            if action is Action.ABORT:
                logger.error(f"Aborting on: {e}")
                raise SystemExit(1)
            logger.warning(f"{action.name} in {delay}s: {e}")
            time.sleep(delay)
            continue
        choice = response.choices[0]
        msg = choice.message
        finish_reason = choice.finish_reason

        if not msg.tool_calls and not msg.content:
            empty_streak += 1
            logger.warning(
                f"Empty response (finish_reason={finish_reason}, streak={empty_streak})"
            )
            if empty_streak >= 4:
                logger.error("Model stuck returning empty responses; aborting.")
                break
            messages.append(
                {
                    "role": "user",
                    "content": "Continue the task, or if it is complete, respond with your final summary.",
                }
            )
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

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": func_name,
                                "content": result,
                            }
                        )
                    except Exception as e:
                        logger.error(f"Tool execution failed: {e}")
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": func_name,
                                "content": f"Error executing tool: {str(e)}",
                            }
                        )
                else:
                    logger.warning(f"Unknown tool requested: {func_name}")
        elif msg.content:
            logger.info(f"\n[Agent Final Response]:\n{msg.content}")
            break


if __name__ == "__main__":
    main()