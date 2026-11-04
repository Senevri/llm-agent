#bash_tools.py
import subprocess
import logging
import os
import platform
from pathlib import Path
from tools import WORKSPACE_DIR

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
    return run_command(command, executable=executable, cwd=cwd)

def run_bash(command: str, executable=EXECUTABLE, cwd=str(WORKSPACE_DIR)) -> str:
    return _run_bash(command, executable=executable, cwd=cwd)

def _run_bash(command: str, executable=EXECUTABLE, cwd=str(WORKSPACE_DIR)) -> str:
    """Execute a bash command inside the container environment."""
    logger.info(f"Executing bash: {command}")
    bash = find_bash()
    if platform.system() == "Windows" and bash:
        command = bash + " -c " + fr'"{command}"'
        executable = None
    else:
        executable = bash
    return run_command(command, executable=executable, cwd=cwd)
def run_command(command: str, executable=EXECUTABLE, cwd=str(WORKSPACE_DIR)) -> str:
    try:
        result = subprocess.run(
            command,
            shell=False,
            executable=executable,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
            cwd=cwd
        )
        returncode_str=f"[exit={result.returncode}]"
        output_tuple = (result.stdout or "", result.stderr or "")
        if result.returncode != 0 and not output_tuple:
            return f"{returncode_str} (no output)"

        output = "".join(output_tuple)

        if len(output_tuple[0]) > MAX_OUTPUT_LENGTH:
            return (f"Output truncated to {MAX_OUTPUT_LENGTH} characters:\n\n"
                    f"{output[:MAX_OUTPUT_LENGTH]} [...]\n{returncode_str}")
        # return output
        return f"{output}\n{returncode_str}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out."
    except Exception as e:
        return f"Execution error: {str(e)}"