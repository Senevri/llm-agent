import os
import json
import subprocess
from openai import OpenAI
from dotenv import load_dotenv
import time

load_dotenv()

# Point OpenAI client directly to Google AI Studio's compatibility endpoint
client = OpenAI(
    api_key=os.environ["GEMINI_API_KEY"],
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

# Tool definition giving Gemini permission to execute commands
tools = [
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "Execute a bash command inside the container environment. Remember that root is read-only, so use /tmp or /workspace for files/packages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The exact bash command to run."
                    }
                },
                "required": ["command"]
            }
        }
    }
]

def execute_bash(command):
    """Executes the command in the sandbox and returns combined output."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/workspace"
        )
        out = result.stdout + result.stderr
        return out if out else "Command executed cleanly with no stdout/stderr."
    except Exception as e:
        return f"Execution failed: {str(e)}"

# Initial instruction to prep the container
messages = [
    {
        "role": "system",
        "content": (
            "You are an autonomous setup agent operating in a restricted Linux container sandbox.\n"
            "System layout:\n"
            "- Root filesystem (`/`) is READ-ONLY.\n"
            "- Writeable directories: `/workspace` (persistent mount) and `/tmp` (tmpfs).\n"
            "Your task is to inspect the system, set up any necessary developer utilities or Python packages "
            "you like in `/workspace` or `/tmp`, and initialize a workspace environment."
        )
    },
    {
        "role": "user",
        "content": "Explore the container, set up a virtual environment in /workspace/.venv, install ripgrep or useful utilities if needed, and leave a workspace summary in /workspace/README.md."
    }
]

# Agent Autonomous Execution Loop
print("--- Starting Gemini Setup Agent ---")
while True:
    time.sleep(2)  # Optional: slow down loop for free tier rate limits
    response = client.chat.completions.create(
        model="gemini-3.8-flash",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )

    msg = response.choices[0].message
    messages.append(msg)

    # If Gemini wants to execute a tool:
    if msg.tool_calls:
        for tool_call in msg.tool_calls:
            if tool_call.function.name == "run_bash":
                args = json.loads(tool_call.function.arguments)
                cmd = args.get("command")
                print(f"\n[Gemini Executing]: {cmd}")

                output = execute_bash(cmd)
                print(f"[Result]:\n{output[:300]}..." if len(output) > 300 else f"[Result]:\n{output}")

                # Feed execution result back into conversation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": output
                })
    else:
        # Agent finished its task
        print("\n[Agent Completed Setup]:")
        print(msg.content)
        break