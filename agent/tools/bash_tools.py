#bash_tools.py
import platform
import subprocess
import shlex
from pathlib import Path
from typing import List, Union

import subprocess
import logging
import os
import platform
from pathlib import Path
from tools import WORKSPACE_DIR
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BashAgentTools")

TOOL_TIMEOUT = int(os.getenv("AGENT_TOOL_TIMEOUT", "60"))
MAX_OUTPUT_LENGTH = int(os.getenv("AGENT_MAX_OUTPUT_LENGTH", "20000"))

EXECUTABLE = "/bin/bash"
if platform.system() == "Windows":
    #EXECUTABLE = "C:\\Windows\\System32\\bash.exe"
    # userprofile = os.getenv('USERPROFILE')
    # EXECUTABLE = f"{userprofile}\\scoop\\shims\\bash.exe"
    EXECUTABLE = None

def find_bash():
    candidates = [
        EXECUTABLE
    ]
    userprofile = os.getenv("USERPROFILE")
    if userprofile and Path(userprofile).exists():
        candidates.append(str(Path(userprofile) / "scoop" / "shims" / "bash.exe"))

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ""

def run_cmd(command: str, executable=EXECUTABLE, cwd=str(WORKSPACE_DIR)) -> str:
    return run_command(command, cwd=cwd)

def run_bash(command: str, executable=EXECUTABLE, cwd=str(WORKSPACE_DIR)) -> str:
    return _run_bash(command,  cwd=cwd)

def _run_bash(command: str, cwd: Union[str, Path] = WORKSPACE_DIR) -> str:
    """Execute a bash command inside the container environment."""
    logger.info(f"Executing bash: {command}")
    bash = find_bash()

    if not bash:
        return "Error: bash executable not found."

    # THE FIX: Build a list of arguments.
    # subprocess will handle all OS-specific escaping and quoting for you.
    args: List[str] = [bash, "-c", command]

    return run_command(args, cwd=cwd)


# Regex to detect shell metacharacters that require a shell to interpret
SHELL_META_REGEX = re.compile(r'(&&|\|\||\||>|<|;)')

def _format_subprocess_result(result: subprocess.CompletedProcess) -> str:
    """Helper to keep output formatting DRY (Don't Repeat Yourself)."""
    returncode_str = f"[exit={result.returncode}]"
    output_tuple = (result.stdout or "", result.stderr or "")

    if result.returncode != 0 and not any(output_tuple):
        return f"{returncode_str} (no output)"

    output = "".join(output_tuple)

    if len(output) > MAX_OUTPUT_LENGTH:
        return (f"Output truncated to {MAX_OUTPUT_LENGTH} characters:\n\n"
                f"{output[:MAX_OUTPUT_LENGTH]} [...]\n{returncode_str}")

    return f"{output}\n{returncode_str}"

def run_command(
        command: Union[str, List[str]],
        cwd: Union[str, Path] = WORKSPACE_DIR,
        executable=None) -> str:
    try:
        if isinstance(command, str):
            command = command.strip()

            # WINDOWS SAFEGUARD: If it's a shell script, force it through bash
            # because Windows doesn't natively understand shebangs (#!/bin/bash)
            if platform.system() == "Windows" and (command.endswith(".sh") or command.startswith("./")):
                bash = find_bash()
                if bash:
                    logger.info("Windows detected: Routing .sh script through bash for compatibility.")
                    command = [bash, "-c", command]
                else:
                    return "Error: bash not found, cannot execute shell script on Windows."

            # SHELL OPERATOR CHECK
            elif SHELL_META_REGEX.search(command):
                bash = find_bash()
                if platform.system() == "Windows" and bash:
                    logger.info("Detected shell operators. Routing through bash -c.")
                    command = [bash, "-c", command]
                else:
                    logger.info("Detected shell operators. Using shell=True.")
                    return _run_with_shell(command, cwd)
            else:
                # Safe, simple command
                command = shlex.split(command)

        # 2. Execute (command is now guaranteed to be a List[str])
        result = subprocess.run(
            command,
            shell=False,  # CRITICAL: Keep this False for list execution
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
            cwd=str(cwd)
        )
        return _format_subprocess_result(result)

    except subprocess.TimeoutExpired:
        return "Error: Command timed out."
    except FileNotFoundError as e:
        return f"Execution error: Executable not found. Details: {str(e)}"
    except Exception as e:
        return f"Execution error: {str(e)}"


def _run_with_shell(command: str, cwd: Union[str, Path], executable=None) -> str:
    """Fallback for when shell operators are used but bash isn't available."""
    try:
        result = subprocess.run(
            command,
            shell=True,  # Uses cmd.exe on Windows, /bin/sh on Linux
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
            cwd=str(cwd)
        )
        return _format_subprocess_result(result)
    except subprocess.TimeoutExpired:
        return "Error: Command timed out."
    except Exception as e:
        return f"Execution error: {str(e)}"