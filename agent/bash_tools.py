import subprocess
import logging
import os

logger = logging.getLogger("BashAgentTools")

TOOL_TIMEOUT = int(os.getenv("AGENT_TOOL_TIMEOUT", "60"))
MAX_OUTPUT_LENGTH = int(os.getenv("AGENT_MAX_OUTPUT_LENGTH", "20000"))

def run_bash(command: str) -> str:
    """Execute a bash command inside the container environment."""
    logger.info(f"Executing bash: {command}")
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
            cwd="/workspace"
        )
        output = (result.stdout or "") + (result.stderr or "")
        if not output:
            return "Command executed successfully with no output."

        if len(output) > MAX_OUTPUT_LENGTH:
            return f"Output truncated to {MAX_OUTPUT_LENGTH} characters:\n\n{output[:MAX_OUTPUT_LENGTH]}..."
        return output
    except subprocess.TimeoutExpired:
        return "Error: Command timed out."
    except Exception as e:
        return f"Execution error: {str(e)}"