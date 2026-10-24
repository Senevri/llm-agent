import os
import time
import json
import logging
import argparse
from pathlib import Path
from openai import OpenAI
# from dotenv import load_dotenv

# load_dotenv()

# Import internal modules from /agent
import sys
sys.path.append('/agent')
from get_ip import get_gateway_ip
from ollama_agent_tools import tools, TOOL_MAP
from openai_error_handling import classify_api_error, Action
from llm_utils import UsageTracker, discover_context_window

usage = UsageTracker()

# --- Configuration Defaults ---
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_MAX_TURNS = 100
DEFAULT_CONTEXT_LIMIT = 50

# Setup Logging
from datetime import datetime

def setup_logging(level, log_dir: Path | None = None) -> logging.Logger:
    log_dir = log_dir or Path.cwd()
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"agent_{stamp}.log"

    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    fileh = logging.FileHandler(log_path, encoding="utf-8")
    fileh.setFormatter(fmt)

    logging.basicConfig(level=level, handlers=[stream, fileh], force=True)
    logger = logging.getLogger("UnifiedAgent")
    logger.info(f"Logging to {log_path}")
    return logger


SCRIPT_DIR = Path(__file__).resolve().parent

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


PROMPT_DIR = Path(os.getenv("AGENT_PROMPT_DIR", ".")).resolve()


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

def get_client(backend):
    logger = setup_logging(DEFAULT_LOG_LEVEL)
    logger.info(f"context window: {usage.context_limit} (model max may be larger)")
    if backend == "ollama":
        #model = os.getenv("AGENT_MODEL", "gemma4:31b-cloud")
        model = os.getenv("AGENT_MODEL", "beam:cloud")

        host_ip = get_gateway_ip()
        port = os.getenv("OLLAMA_PORT", "11434")
        base_url = os.getenv("OLLAMA_BASE_URL", f"http://{host_ip}:{port}/v1")
        usage.context_limit = discover_context_window(base_url, model)
        return OpenAI(base_url=base_url, api_key="ollama"), model

    elif backend == "mistral":
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY not set. Please set it in environment variables.")
        model = os.getenv("AGENT_MODEL", "ministral-14b-latest")
        base_url = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
        return OpenAI(base_url=base_url, api_key=api_key), model

    else:
        raise ValueError(f"Unsupported backend: {backend}")

def main():
    parser = argparse.ArgumentParser(description="Unified LLM Agent")
    parser.add_argument("--backend", choices=["ollama", "mistral"], required=True, help="LLM backend to use")
    parser.add_argument("--system-prompt", default="system_prompt.md", help="Path to system prompt file")
    parser.add_argument("--user-prompt", default="user_prompt.md", help="Path to user prompt file")
    parser.add_argument("--model", help="Override model name")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help="Maximum agent turns")
    parser.add_argument("--context-limit", type=int, default=DEFAULT_CONTEXT_LIMIT, help="Context window limit")
    parser.add_argument("--log-level", default=os.getenv("AGENT_LOG_LEVEL", DEFAULT_LOG_LEVEL), help="Logging level")

    args = parser.parse_args()
    logger = setup_logging(args.log_level)

    try:
        client, default_model = get_client(args.backend)
        model_name = args.model or default_model
    except Exception as e:
        logger.error(f"Client initialization failed: {e}")
        return

    # Load Prompts
    try:
        with open(args.system_prompt, "r", encoding="utf-8") as f:
            system_prompt = f.read()
        with open(args.user_prompt, "r", encoding="utf-8") as f:
            user_prompt = f.read()
    except FileNotFoundError as e:
        logger.error(f"Required prompt file missing: {e}")
        return

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    logger.info(f"--- Starting Agent Loop via {args.backend} ({model_name}) ---")

    empty_streak = 0

    for turn in range(args.max_turns):
        if args.backend == "mistral":
            time.sleep(1) # Avoid rate limits for Mistral

        if usage.context_pct > 90:
            logger.warning("context >90% — trimming or summarizing before next turn")
            messages = _trim_messages(messages, args.context_limit)

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
            usage.record(response.usage, turn=len(messages))
            logger.info(f"usage: {usage.summary()}")
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
        if msg.content:
            logger.info(msg.content)
        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                if func_name in TOOL_MAP:
                    try:
                        args_json = json.loads(tool_call.function.arguments)
                        result = TOOL_MAP[func_name](**args_json)
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
            # logger.info(f"\n[Agent Final Response]:\n{msg.content}")
            break
    # Max turns reached
    else:
        logger.error("Max turns reached. Aborting.")

if __name__ == "__main__":
    main()
