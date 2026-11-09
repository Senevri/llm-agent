#!/usr/local/bin/python

import os
import time
import json
import yaml
import logging
import argparse
import platform
from pathlib import Path
from collections import Counter

from openai import OpenAI
from dotenv import load_dotenv


# Import internal modules from /agent
import sys
for path in "/agent", "/agent/skill_system":
    if Path(path).exists() and path not in sys.path:
        sys.path.append(path)

# Fix the import issue for skill_system internal imports
if Path(__file__).parent not in sys.path:
    sys.path.append(str(Path(__file__).parent))

from openai_error_handling import classify_api_error, Action
from llm_utils import UsageTracker, estimate_tokens, normalize_messages
from custom_logger import setup_logging
from backend import LLMBackend, BACKEND_MAP


# Skill System Integration
from skill_system.tool_registry import registry as tool_registry
from skill_system.skills_manager import SkillsManager
#
# Import legacy tools to register them into the new registry
from tools.agent_tools import (
    # read_file, read_file_lines, search_file, list_files,
    # write_file, append_file, tool_now, install_deb_package,
    # run_bash, INTERNET_TOOL_MAP, TMUX_TOOL_MAP, CONTEXT_TOOL_MAP,
    TOOL_DEFINITIONS, TOOL_MAP
)

SCRIPT_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
except ImportError:
    def _load_dotenv(dotenv_path: Path = SCRIPT_DIR / ".env") -> None:
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

load_dotenv(SCRIPT_DIR / ".env")


logger = setup_logging("RunAgent", prefix="agent_")


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

# --- Configuration Defaults ---
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_MAX_TURNS = 100
DEFAULT_CONTEXT_LIMIT = 100

from datetime import datetime


if not os.getenv("ALLOWED_PATHS"):
    # Load from yaml
    conf_path = Path.cwd() / "tool_config.yaml"
    if conf_path.is_file():
        with open(conf_path, "r", encoding="utf-8") as f:
            conf = yaml.safe_load(f)
        logger.info(conf)
        os.environ["ALLOWED_PATHS"] = ",".join(conf.get("allowed_paths",[]))
    else:
        os.environ["ALLOWED_PATHS"] = str(Path.cwd().resolve())
try:
    from prompt_generator import PromptGenerator, find_prompt_dir
    # Find prompt directory
    PROMPT_DIR = find_prompt_dir()

    prompt_gen = PromptGenerator(prompts_dir=str(PROMPT_DIR))
    prompt_gen.platform = platform.system().lower()
    current_role = "general"
except ImportError as e:
    logging.warning(f"Failed to import prompt_generator: {e}")
    prompt_gen = None


def _trim_messages(messages:list, limit: int) -> dict:
    if len(messages) <= limit + 2:
        return {"messages": messages}  # no trimming needed, return original messages
    head = messages[:2]  # system + original task
    tail = messages[-limit:]
    tokens_in_msg = estimate_tokens(messages)
    # more aggressive trimming
    while (
        len(tail) > 2
        and tail and _role(tail[0]) == "tool"
        or tokens_in_msg > limit
        ):
        tail = tail[1:]
        tokens_in_msg = estimate_tokens(messages)
    new_message_list = head + tail
    removed_count = len(messages) - len(new_message_list) + 2
    trimmed_msgs = messages[2:removed_count+2]
    logger.info(f"trimmed {removed_count} messages")
    def format_for_compression(msg: dict) -> str:
        if msg.get("role") == "tool":
            return f"[TOOL RESULT: {msg.get('name', 'unknown')} (ID: {msg.get('tool_call_id')})]\n{msg.get('content')}"
        return f"{msg['role']}: {msg.get('content', '')}"

    sections = [format_for_compression(c) for c in trimmed_msgs]

    logger.info(f"Messages:\m\n{trimmed_msgs}")

    return {
        "messages": new_message_list,
        "removed_sections": sections
        }

def _role(m) -> str:
    return m["role"] if isinstance(m, dict) else getattr(m, "role", "")



from collections import deque
MAX_IDENTICAL_CALLS = 3
MAX_TOOL_CHARS = 12000

class LLMAgent:
    def __init__(self, client, api, max_turns=DEFAULT_MAX_TURNS, logger=None, sleep_time=0):
        self.client = client
        self.api = api
        self.max_turns = max_turns
        self.sleep_time = sleep_time
        self.logger = setup_logging("LLMAgent")
        self.recent_calls = deque(maxlen=6)

    def run_turns (self, messages: list, **kwargs):
        return self._run_turns(self.client, self.api, messages, **kwargs)

    def ai_compress(self, sections, max_tokens=2000):
        task_message = [
            {"role": "system",
             "content": f"You are a helpful assistant. Provide a concise, condensed version of the prompt below. Aim for max {max_tokens} tokens."},
            {"role": "user", "content": "\n\n".join(sections[:-1])}]

        response =  self.client.chat.completions.create(
                model=self.api.model,
                messages=normalize_messages(task_message, self.api.backend)
            )
        return response.choices[0].message.content



    def check_tool_call(self, name, arguments):
        key = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
        self.recent_calls.append(key)
        if self.recent_calls.count(key) > MAX_IDENTICAL_CALLS:
            return (False,
                    f"Loop detected: {name} repeated with the same arguments. "
                    "Do not repeat this call. Use a different approach or answer "
                    "from the evidence already gathered.")
        return True, None



    def _run_turns(self,
            client, api, messages: list,
            max_turns: int = DEFAULT_MAX_TURNS, logger=None, sleep_time=0):
        """Run one user-facing assistant turn, executing safe tools as needed."""
        empty_streak = 0

        logger = logger or self.logger

        for turn in range(max_turns):
            if sleep_time > 0:
                time.sleep(sleep_time)

            limit = 75.0
            if api.usage.context_pct > limit:
                logger.warning(f"context > {limit}% — trimming to {int(api.context_limit*0.8)} messages")
                # fixed bug: was args.context_limit.
                trimmed = _trim_messages(messages, int(api.context_limit*0.8))

                messages = trimmed.get("messages", [])
                # Could compress and insert...
                compress_target = trimmed.get("removed_sections", None)
                if compress_target:
                    message = self.ai_compress(compress_target)
                    messages.insert(2, {"role": "system", "content": message})

            try:
                response = client.chat.completions.create(
                    model=api.model,
                    messages=messages,
                    tools=tool_registry.get_all_schemas(),
                    tool_choice="auto"
                )
                api.usage.record(response.usage, turn=len(messages))
                logger.info(f"usage: {api.usage.summary()}")
            except KeyboardInterrupt:
                clarification = input("User: > ")
                if clarification in ("q", "quit", "exit"):
                    break
                messages.append({"role": "user", "content": str(clarification)})
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
                    # TODO: refactor
                    func_name = tool_call.function.name
                    try:
                        tool_args = json.loads(tool_call.function.arguments)
                        tool_check = self.check_tool_call(func_name, tool_args)
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
                        if len(result) > MAX_TOOL_CHARS:
                            result = (result[:MAX_TOOL_CHARS]
                                    + f"\n[truncated {len(result) - MAX_TOOL_CHARS} chars; "
                                    "use read_file_lines or search_file for specific ranges]")

                        logger.info("Tool %s output: %s...", func_name, result)

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
        return messages

def main():
    parser = argparse.ArgumentParser(description="Unified LLM Agent with Skill System")
    parser.add_argument("--backend", choices=BACKEND_MAP.keys(), required=True, help="LLM backend to use")
    parser.add_argument("--system-prompt", default="", help="Path to system prompt file")
    parser.add_argument("--user-prompt", default="user_prompt.md", help="Path to user prompt file")
    parser.add_argument("--model", help="Override model name")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help="Maximum agent turns")
    parser.add_argument("--context-limit", type=int, default=DEFAULT_CONTEXT_LIMIT, help="Context window limit")
    parser.add_argument("--log-level", default=os.getenv("AGENT_LOG_LEVEL", DEFAULT_LOG_LEVEL), help="Logging level")
    parser.add_argument("--role", default="agent", help="Role of the agent")
    parser.add_argument("--task", default=None, help="Task to perform")
    parser.add_argument("--port", default=None, type=int, help="port override for backend")
    parser.add_argument("--test", action="store_true", help="Run in test mode")
    parser.add_argument("--skills", default=None, help="Path to skills directory")
    parser.add_argument("--notools", action="store_true", help="Disable tools")
    parser.add_argument("--project", default=None, help="Project name")

    args = parser.parse_args()

    # logger = setup_logging(args.log_level, log_dir=Path(
    #     os.getenv("AGENT_LOG_DIR", "./log/")))


    if args.project:
        logger.info(f"Project: {args.project}")
        config = Path.cwd() / "agent_config.yaml"
        if config.exists():
            with open(config, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
            # if config_data.get("project") != args.project:
            #     logger.warning(f"Project mismatch: {config_data.get('project')} vs {args.project}")
            for key in ["role", "system_prompt", "user_prompt", "backend", "model", "port", "max_turns", "context_limit", "task"]:
                if key in config_data:
                    setattr(args, key, config_data[key])


    # Initialize Skill System
    if args.notools:
        logger.info("Disabling tools")
    else:
        register_core_tools()
    if args.skills:
        logger.info(f"Loading skills from {args.skills}")
        SKILLS_ROOT = args.skills

    else:
        from skill_system.integration import SKILLS_ROOT

    logger.info(f"Registered tools: {tool_registry.list_tools()}")

    skills_summary = ""

    logger.info(SKILLS_ROOT)
    if SKILLS_ROOT:
        skills_mgr = SkillsManager(SKILLS_ROOT)
        skills_mgr.discover_skills()
        logger.info(f"Discovered skills: {list(skills_mgr.catalog.keys())}")
        skills_summary = skills_mgr.get_catalog_summary()

    api = LLMBackend(backend=args.backend)
    if args.model:
        api.model = args.model

    if args.context_limit:
        api.context_limit = args.context_limit

    try:
        if args.port and args.port != -1:

            logger.info(f"Using port override: {args.port}")
            api.port = int(args.port)
        client, default_model = api.get_client()
    except Exception as e:
        logger.error(f"Client initialization failed: {e}")
        return

    # Load Prompts
    try:
        current_role = args.role or "agent"
        prompt_gen = PromptGenerator(prompts_dir=str(PROMPT_DIR))
        prompt_gen.platform = platform.system().lower()
        assert prompt_gen
        if args.system_prompt == "" and prompt_gen:
            system_prompt = prompt_gen.generate_prompt(current_role)
            enabled_skills = prompt_gen.enabled_skills
            if not enabled_skills:
                SKILLS_ROOT = None
        elif args.system_prompt: # fallback to hardcoded prompts
            with open(args.system_prompt, "r", encoding="utf-8") as f:
                system_prompt = f.read()

        if args.user_prompt and not args.task:
            with open(args.user_prompt, "r", encoding="utf-8") as f:
                user_prompt = f.read()
        elif args.task:
            logger.info(f"Using task: {args.task}")
            user_prompt = args.task
        system_prompt = "\n\n".join([system_prompt, skills_summary]).strip()
    except FileNotFoundError as e:
        logger.error(f"Required prompt file missing: {e}")
        return

    allowed_paths = tool_registry.get_allowed_paths()
    if allowed_paths:
        system_prompt += (
            "### Allowed Paths\n"
            f"{allowed_paths}"
        )


    logger.info(f"Using system prompt: \n{system_prompt[:320]}")
    logger.info(f"current role: {current_role}")



    # raise Exception("debug")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    sleep_time = 1 if api.backend == "mistral" else 0

    if args.test:
        logger.info("Test run mode enabled. Exiting...")
        exit(0)

    agent = LLMAgent(client, api, max_turns=args.max_turns, logger=logger, sleep_time=sleep_time)
    logger.info(f"--- Starting Agent Loop via {args.backend} ({api.model}) ---")
    messages = agent.run_turns(messages)
    with open("agent_messages.yaml", "w", encoding="utf-8") as f:
        yaml.dump(messages, f, default_flow_style=False, allow_unicode=True)
    logger.info("--- Agent Loop Complete ---")
    path = Path.cwd() / "agent_config.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump({
            "project": args.project,
            "role": current_role,
            "system_prompt": args.system_prompt,
            "user_prompt": args.user_prompt,
            "task": args.task,
            "backend": args.backend,
            "model": api.model,
            "port": api.port,
            "max_turns": args.max_turns,
            "context_limit": args.context_limit,
        }, f, default_flow_style=False, allow_unicode=True)
    logger.info(f"Config saved to {path}")


if __name__ == "__main__":
    main()
