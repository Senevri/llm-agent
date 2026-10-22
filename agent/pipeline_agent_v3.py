#!/usr/bin/env python3
import os
import sys
import json
import time
import argparse
import logging
import requests
from typing import Dict, Any, List, Tuple

try:
    from get_ip import get_gateway_ip
except ImportError:
    def get_gateway_ip() -> str:
        return "localhost"

# --- Configuration ---
#PORT = int(os.getenv("PIPELINE_PORT", "11434")) # Ollama
PORT = int(os.getenv("PIPELINE_PORT", "5001")) # Kobold
MODEL = os.getenv("PIPELINE_MODEL", "gemma4:e4b")
BASE_URL = os.getenv("PIPELINE_BASE_URL", f"http://{get_gateway_ip()}:{PORT}/v1")
MAX_TURNS = int(os.getenv("PIPELINE_MAX_TURNS", "6"))
PHASE_LIMIT = int(os.getenv("PIPELINE_PHASE_LIMIT", "4000"))
RUN_DIR = os.getenv("PIPELINE_RUN_DIR", os.path.join(os.getcwd(), "pipeline_run"))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PipelineAgent")

# --- Tools ---
def tool_run_bash(command: str) -> str:
    try:
        import subprocess
        res = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.getcwd(),
            errors="replace"
        )
        out = (res.stdout or "") + (res.stderr or "")
        if not out:
            return "Success (no output)"
        if len(out) > 3000:
            return out[:1500] + "\n... [TRUNCATED] ...\n" + out[-1500:]
        return out
    except Exception as e:
        return f"Error executing command: {e}"

def tool_read_file(path: str) -> str:
    try:
        safe_path = os.path.normpath(path)
        with open(safe_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        if len(content) > 3000:
            return content[:1500] + "\n... [TRUNCATED] ...\n" + content[-1500:]
        return content
    except Exception as e:
        return f"Error reading file: {e}"

def tool_write_file(path: str, content: str) -> str:
    try:
        safe_path = os.path.normpath(path)
        os.makedirs(os.path.dirname(safe_path) or ".", exist_ok=True)
        with open(safe_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Wrote {len(content)} chars to {safe_path}"
    except Exception as e:
        return f"Error writing file: {e}"

def tool_list_files(path: str = ".") -> str:
    try:
        safe_path = os.path.normpath(path)
        items = os.listdir(safe_path)
        return "\n".join(items) if items else "(empty)"
    except Exception as e:
        return f"Error listing directory: {e}"

TOOL_MAP = {
    "run_bash": tool_run_bash,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_files": tool_list_files,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "Execute bash command",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file content",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write file content",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in directory",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}
        }
    },
]

REQUIRED_ARGS = {
    "run_bash":     ["command"],
    "read_file":    ["path"],
    "write_file":   ["path", "content"],
    "list_files":   [],
}

FAILURE_MARKERS = [
    "PHASE FAILED",
    "No such file",
    "cannot access",
    "Cannot perform analysis",
    "Result: Cannot",
    "Result: Error: [Errno",
]

def artifact_failed(path: str) -> bool:
    if not os.path.exists(path):
        return True
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()

        # Check primary failure indicators explicitly
        if any(marker in text for marker in FAILURE_MARKERS):
            return True

        # Count minor failure occurrences
        err_count = sum(text.count(m) for m in FAILURE_MARKERS[1:])
        return err_count >= 3
    except Exception:
        return True

# --- LLM call with retries ---
def call_llm(messages: List[Dict[str, Any]], retries: int = 2) -> dict | None:
    payload = {"model": MODEL, "messages": messages, "tools": TOOL_SCHEMAS, "tool_choice": "auto"}
    for attempt in range(retries + 1):
        try:
            resp = requests.post(f"{BASE_URL}/chat/completions", json=payload, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]
        except Exception as e:
            logger.warning(f"LLM call failed (attempt {attempt+1}/{retries+1}): {e}")
            if attempt < retries:
                time.sleep(2)
    return None

# --- Phase definitions ---
PHASE_FILES = {
    "analysis": "01_analysis.md",
    "plan": "02_plan.md",
    "execute": "03_findings.md",
    "draft": "04_draft.md",
    "review": "05_review.md",
    "revise": "06_final.md",
}

PHASES = [
    (
        "analysis",
        "You are in ANALYSIS phase. Your job is to analyze what the task REQUIRES — "
        "you are NOT solving it. Do NOT produce the deliverable (no haiku, no poem, no code, "
        "no final prose answer) in this phase.\n\n"
        "Write your analysis by filling in this exact template:\n\n"
        "# Analysis\n\n"
        "## Deliverable\n[one sentence: what must be produced]\n\n"
        "## Constraints\n- [any constraints from the task]\n\n"
        "## Format\n[expected output format]\n\n"
        "## Unknowns\n- [anything unclear]\n",
        []
    ),
    (
        "plan",
        "You are in PLAN phase. Write a concrete step-by-step plan for solving the task, "
        "based on the analysis. Do NOT execute yet. Use this template:\n\n"
        "# Plan\n1. [step]\n2. [step]\n...\n",
        ["analysis"]
    ),
    (
        "execute",
        "You are in EXECUTE phase. Follow the plan and record findings. "
        "If a tool call fails with 'No such file' or 'Permission denied': do NOT proceed. "
        "First list_files the directory you're in, then list_files any subdirectory that looks relevant, "
        "then read_file using the path you found. "
        "Only conclude a file is inaccessible after you've tried at least two different locations. Record every attempt, "
        "what the results were, what remains. Use this template:\n\n"
        "# Findings\n\n## Step 1: [title]\n- Action:\n- Result:\n\n## Step 2: ...\n",
        ["plan"]
    ),
    (
        "draft",
        "You are in DRAFT phase. Using the analysis and findings, produce a complete first "
        "draft of the final answer. This is your candidate deliverable — write it fully.",
        ["analysis", "execute"]
    ),
    (
        "review",
        "You are in REVIEW phase. Compare the draft against the original task. Be specific and critical. "
        "Use this template:\n\n"
        "# Review\n\n## Satisfies task?\n[yes/no + brief reason]\n\n"
        "## Defects\n- [defect] or NONE\n\n## Suggestions\n- \n",
        ["analysis", "draft"]
    ),
    (
        "revise",
        "You are in REVISE phase. Using the draft and review, produce the FINAL answer. "
        "If review found defects, fix them. If review said NONE, copy the draft forward.",
        ["draft", "review"]
    ),
]

def run_phase(name: str, instruction: str, deps: List[str], task_content: str) -> Dict[str, Any]:
    logger.info(f"=== Phase: {name} ===")
    start_time = time.time()
    target_path = os.path.join(RUN_DIR, PHASE_FILES[name])

    if os.path.exists(target_path):
        os.remove(target_path)

    # Build system prompt
    sys_prompt = instruction + "\n"
    for dep_name in deps:
        dep_path = os.path.join(RUN_DIR, PHASE_FILES[dep_name])
        if os.path.exists(dep_path):
            with open(dep_path, 'r', encoding='utf-8', errors='replace') as f:
                sys_prompt += f"\n<<<BEGIN {dep_name} OUTPUT>>>\n{f.read()}\n<<<END {dep_name}>>>\n"
        else:
            sys_prompt += f"\n<<<{dep_name} OUTPUT MISSING>>>\n"
    sys_prompt += f"\n<<<BEGIN TASK>>>\n{task_content}\n<<<END TASK>>>\n"
    sys_prompt += (
        f"\nIMPORTANT: When this phase's output is ready, call the write_file tool with "
        f"path='{target_path}' and the full output as content. Do not skip this step. "
        f"Only after the write succeeds, reply DONE."
    )

    messages = [
        {"role": "system", "content": sys_prompt},
        {
            "role": "user",
            "content": f"Begin the {name} phase now. Write your output to {target_path} using write_file, then reply DONE."
        },
    ]

    turns = 0
    last_text = ""

    while turns < MAX_TURNS:
        turns += 1
        choice = call_llm(messages)
        if choice is None:
            break

        msg = choice.get("message", {})
        fr = choice.get("finish_reason")

        # Guard against empty responses
        if not msg.get("tool_calls") and not msg.get("content"):
            logger.warning(f"  turn {turns}: empty response (finish_reason={fr})")
            messages.append({
                "role": "user",
                "content": f"Use the write_file tool to save your output to {target_path}."
            })
            continue

        # Format message cleanly for message history inclusion
        clean_msg = {"role": "assistant", "content": msg.get("content")}
        if msg.get("tool_calls"):
            clean_msg["tool_calls"] = msg["tool_calls"]

        messages.append(clean_msg)
        logger.info(
            f"  turn {turns}: finish_reason={fr}, tool_calls={bool(msg.get('tool_calls'))}, "
            f"content_len={len(msg.get('content') or '')}"
        )

        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc["id"]
                fn = tc["function"]["name"]

                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError as e:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"Error: malformed JSON ({e}). Retry with valid arguments."
                    })
                    continue

                if fn not in TOOL_MAP:
                    res = f"Error: unknown tool '{fn}'"
                else:
                    missing = [k for k in REQUIRED_ARGS[fn] if k not in args]
                    if missing:
                        res = (
                            f"Error: {fn} is missing required argument(s): {missing}. "
                            f"Required: {REQUIRED_ARGS[fn]}. You must supply all of them."
                        )
                    elif fn == "write_file":
                        content = args.get("content", "")
                        truncated = False
                        if len(content) > PHASE_LIMIT:
                            args["content"] = content[:PHASE_LIMIT] + "\n... [TRUNCATED]"
                            truncated = True
                        res = TOOL_MAP[fn](**args)
                        if truncated:
                            res += f" (was truncated from {len(content)} to {PHASE_LIMIT} chars)"
                    else:
                        try:
                            res = TOOL_MAP[fn](**args)
                        except Exception as e:
                            res = f"Error executing {fn}: {e}"

                messages.append({"role": "tool", "tool_call_id": tc_id, "content": res})

            # Check if target artifact has been successfully written
            if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                logger.info(f"  artifact written successfully, exiting loop")
                break

        elif msg.get("content"):
            content_text = msg["content"]
            if len(content_text) > len(last_text):
                last_text = content_text

            if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                break

            messages.append({
                "role": "user",
                "content": f"Now save that response text to {target_path} using write_file."
            })

    # Fallback mechanism if target artifact wasn't written via tool calls
    if not os.path.exists(target_path) or os.path.getsize(target_path) == 0:
        cleaned_last = last_text.strip()
        if cleaned_last.upper() in ("DONE", "OK", "COMPLETED", ""):
            cleaned_last = ""

        os.makedirs(RUN_DIR, exist_ok=True)
        if cleaned_last and len(cleaned_last) > 30:
            logger.warning(f"  falling back to last text response ({len(cleaned_last)} chars)")
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(cleaned_last)
        else:
            logger.error(f"  no usable output produced for phase {name}")
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write("PHASE FAILED TO PRODUCE OUTPUT")

    elapsed = time.time() - start_time
    is_failed = artifact_failed(target_path)

    if is_failed:
        logger.warning(f"  phase {name} produced a failure artifact")

    return {
        "turns": turns,
        "elapsed_s": round(elapsed, 2),
        "output_chars": os.path.getsize(target_path) if os.path.exists(target_path) else 0,
        "ok": not is_failed,
        "failed_artifact": is_failed,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="TASK.md")
    args = parser.parse_args()

    if not os.path.exists(args.task):
        logger.error(f"Task file {args.task} not found")
        sys.exit(1)

    with open(args.task, 'r', encoding='utf-8', errors='replace') as f:
        task_content = f.read()

    os.makedirs(RUN_DIR, exist_ok=True)
    logger.info(f"Model: {MODEL} | Base URL: {BASE_URL} | Run dir: {RUN_DIR}")

    summary = {}
    try:
        for name, inst, deps in PHASES:
            summary[name] = run_phase(name, inst, deps, task_content)
            if summary.get(name, {}).get("failed_artifact"):
                logger.warning(f"Phase '{name}' flagged a failure; downstream phases will see warnings.")
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
    except Exception as e:
        logger.exception(f"Pipeline crashed unexpectedly: {e}")
    finally:
        summary_path = os.path.join(RUN_DIR, "summary.json")
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2)
        logger.info(f"Summary saved to {summary_path}:\n{json.dumps(summary, indent=2)}")

if __name__ == "__main__":
    main()