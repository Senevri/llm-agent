#!/usr/local/bin/python

import os
import time
import json
import logging
import argparse
from pathlib import Path
from collections import Counter

from openai import OpenAI
from dotenv import load_dotenv


# Import internal modules from /agent
import sys
sys.path.append('/agent')
sys.path.append('/agent/skill_system') # Fix the import issue for skill_system internal imports

from get_ip import get_gateway_ip
from openai_error_handling import classify_api_error, Action
from llm_utils import UsageTracker, discover_context_window

# Skill System Integration
from skill_system.tool_registry import registry as tool_registry
from skill_system.skills_manager import SkillsManager
from skill_system.integration import SKILLS_ROOT

# Import legacy tools to register them into the new registry
from agent_tools import (
    read_file, read_file_lines, search_file, list_files,
    write_file, append_file, tool_now, install_deb_package,
    run_bash, INTERNET_TOOL_MAP, TMUX_TOOL_MAP, CONTEXT_TOOL_MAP,
    TOOL_DEFINITIONS, TOOL_MAP
)

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

# --- Tool Registration ---
def register_core_tools():
    """Registers the base tools into the ToolRegistry."""
    # Map tool definitions to their implementations
    for tool_def in TOOL_DEFINITIONS:
        name = tool_def["function"]["name"]
        func = TOOL_MAP.get(name)
        if func is None:
            logging.warning(f"No implementation found for tool '{name}'. Skipping registration.")
            continue

        if name not in tool_registry.list_tools():
            description = tool_def["function"].get("description", f"Tool {name}")
            parameters = tool_def["function"].get("parameters", {})
            tool_registry.register(name, description, func, parameters)
        else:
            logging.info(f"Tool '{name}' is already registered. Skipping.")

usage = UsageTracker()

# --- Configuration Defaults ---
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_MAX_TURNS = 100
DEFAULT_CONTEXT_LIMIT = 100

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

PROMPT_DIR = Path(os.getenv("AGENT_PROMPT_DIR", ".")) / "prompts"
if not PROMPT_DIR.exists():
    PROMPT_DIR = Path(SCRIPT_DIR) /"prompts"

# Todo: Use both /agent/prompts and curdir/prompts


PROMPT_DIR = PROMPT_DIR.resolve()

try:
    from prompt_generator import PromptGenerator
    prompt_gen = PromptGenerator(prompts_dir=str(PROMPT_DIR))
    current_role = "general"
except ImportError:
    prompt_gen = None


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
    logger = setup_logging(DEFAULT_LOG_LEVEL, log_dir=Path(
        os.getenv("AGENT_LOG_DIR", "./log/")))
    logger.info(f"context window: {usage.context_limit} (model max may be larger)")
    if backend == "ollama":
        model = os.getenv("AGENT_MODEL", "gemma4:31b-cloud")
        #model = os.getenv("AGENT_MODEL", "beam:cloud")

        host_ip = get_gateway_ip()
        port = os.getenv("OLLAMA_PORT", "11434")
        base_url = os.getenv("OLLAMA_BASE_URL", f"http://{host_ip}:{port}/v1")
        usage.context_limit = discover_context_window(base_url, model)
        return OpenAI(base_url=base_url, api_key="ollama"), model
    elif backend == "mistral":
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY not set.")
        model = os.getenv("AGENT_MODEL", "ministral-14b-latest")
        base_url = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
        return OpenAI(base_url=base_url, api_key=api_key), model
    else:
        raise ValueError(f"Unsupported backend: {backend}")

tool_call_counts = Counter()
MAX_IDENTICAL_CALLS = 3

def check_tool_call(name, arguments):
    key = (name, json.dumps(
        arguments, sort_keys=True, ensure_ascii=False
    ))

    tool_call_counts[key] += 1

    if tool_call_counts[key] > MAX_IDENTICAL_CALLS:
        return (
            False,
            f"Loop detected: {name} has been called with "
            f"the same arguments {tool_call_counts[key]} times. "
            "Do not repeat this call. Use a different approach "
            "or provide the answer from the evidence already gathered."
        )

    return True, None

def main():
    parser = argparse.ArgumentParser(description="Unified LLM Agent with Skill System")
    parser.add_argument("--backend", choices=["ollama", "mistral"], required=True, help="LLM backend to use")
    parser.add_argument("--system-prompt", default="system_prompt.md", help="Path to system prompt file")
    parser.add_argument("--user-prompt", default="user_prompt.md", help="Path to user prompt file")
    parser.add_argument("--model", help="Override model name")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help="Maximum agent turns")
    parser.add_argument("--context-limit", type=int, default=DEFAULT_CONTEXT_LIMIT, help="Context window limit")
    parser.add_argument("--log-level", default=os.getenv("AGENT_LOG_LEVEL", DEFAULT_LOG_LEVEL), help="Logging level")
    parser.add_argument("--role", default="general", help="Role of the agent")

    args = parser.parse_args()
    logger = setup_logging(args.log_level, log_dir=Path(
        os.getenv("AGENT_LOG_DIR", "./log/")))

    # Initialize Skill System
    register_core_tools()
    skills_mgr = SkillsManager(SKILLS_ROOT)
    skills_mgr.discover_skills()

    logger.info(f"Registered tools: {tool_registry.list_tools()}")
    logger.info(f"Discovered skills: {list(skills_mgr.catalog.keys())}")

    try:
        client, default_model = get_client(args.backend)
        model_name = args.model or default_model
    except Exception as e:
        logger.error(f"Client initialization failed: {e}")
        return

    # Load Prompts
    try:
        current_role = args.role or "general"
        if prompt_gen and not args.system_prompt:
            system_prompt = prompt_gen.generate_prompt(current_role)
        else: # fallback to hardcoded prompts
            with open(args.system_prompt, "r", encoding="utf-8") as f:
                system_prompt = f.read()
        with open(args.user_prompt, "r", encoding="utf-8") as f:
            user_prompt = f.read()
    except FileNotFoundError as e:
        logger.error(f"Required prompt file missing: {e}")
        return

    skills_summary = skills_mgr.get_catalog_summary()
    system_prompt += "\n\n" + skills_summary

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    logger.info(f"--- Starting Agent Loop via {args.backend} ({model_name}) ---")
    empty_streak = 0

    for turn in range(args.max_turns):
        if args.backend == "mistral":
            time.sleep(1)

        if usage.context_pct > 90:
            logger.warning("context >90% — trimming")
            messages = _trim_messages(messages, args.context_limit)

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=tool_registry.get_all_schemas(),
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
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                    tool_check = check_tool_call(func_name, tool_args)
                    if tool_check[0] is False:
                        logger.error(tool_check[1])
                        result = tool_check[1]
                    else:
                        result = tool_registry.execute(func_name, **tool_args)

                    if result is None:
                        logger.error("Tool %s returned None", func_name)
                        result = "Error: tool returned no result (None)."
                    elif not isinstance(result, str):
                        result = str(result)

                    logger.info("Tool %s output: %.100s...", func_name, result)

                except Exception as e:
                    logger.exception("Tool %s failed", func_name)
                    result = f"Error executing tool {func_name}: {e}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": result
                })

        elif msg.content:
            break
    else:
        logger.error("Max turns reached. Aborting.")
    logger.info("--- Agent Loop Complete ---")



if __name__ == "__main__":
    main()
