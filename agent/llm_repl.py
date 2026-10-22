import os
import sys
import json
import logging
from typing import Dict, Any, List, Callable, Optional
from openai import OpenAI

# Import get_gateway_ip from /agent
sys.path.append("/agent")
try:
    from get_ip import get_gateway_ip
except ImportError:
    def get_gateway_ip():
        return "127.0.0.1"

# Import internet tools
try:
    from internet_tools import (
        search_internet, get_weather, internet_tool_definition, weather_tool_definition,
        INTERNET_TOOL_MAP)
except ImportError:
    def search_internet(query: str, max_results: int = 5) -> str:
        return "Internet search is not available."
    def get_weather(location: str) -> str:
        return "Weather lookup is not available."
    internet_tool_definition = None
    weather_tool_definition = None

# --- Configuration ---
DEFAULT_MODEL = "gemma4:e4b"
# Use environment variables first, then fall back to gateway IP discovery
DEFAULT_BASE_URL = os.getenv("OPENAI_BASE_URL", os.getenv("LLM_BASE_URL", f"http://{get_gateway_ip()}:11434/v1"))
DEFAULT_API_KEY = "ollama"



# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("LLMRepl")

# --- Tool Definitions ---
def tool_run_bash(command: str) -> str:
    """Execute a bash command and return the output."""
    try:
        import subprocess
        res = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            errors="replace"
        )
        out = (res.stdout or "") + (res.stderr or "")
        return out if out else "Success (no output)"
    except Exception as e:
        return f"Error executing command: {e}"

def tool_read_file(path: str) -> str:
    """Read a file's content."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

def tool_write_file(path: str, content: str) -> str:
    """Write content to a file."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing file: {e}"

def tool_list_files(path: str = ".") -> str:
    """List files in a directory."""
    try:
        items = os.listdir(path)
        return "\n".join(items) if items else "(empty)"
    except Exception as e:
        return f"Error listing directory: {e}"

# Tool Mapping
TOOL_MAP: Dict[str, Callable] = {
    "run_bash": tool_run_bash,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_files": tool_list_files,
    "search_internet": search_internet,
    "get_weather": get_weather,
}

# Tool Schemas for OpenAI API
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

if internet_tool_definition:
    TOOL_SCHEMAS.append(internet_tool_definition)

if weather_tool_definition:
    TOOL_SCHEMAS.append(weather_tool_definition)

class LLMRepl:
    def __init__(self, model=DEFAULT_MODEL, base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.messages: List[Dict[str, str]] = [
            {"role": "system", "content":
             "You are a helpful assistant with access to local tools. "
             "Use tools when necessary to complete the user's request."}
        ]

    def send_message(self, user_input: str):
        self.messages.append({"role": "user", "content": user_input})

        while True:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto"
                )
            except Exception as e:
                print(f"API Error: {e}")
                self.messages.pop()
                break

            msg = response.choices[0].message
            self.messages.append(msg)

            if not msg.tool_calls:
                if msg.content:
                    print(f"\nAssistant: {msg.content}")
                else:
                    print("\nAssistant: (No response)")
                break

            # Handle tool calls
            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as e:
                    result = f"Error: malformed JSON arguments ({e}). Retry with valid JSON."
                    self.messages.append({
                        "role": "tool", "tool_call_id": tool_call.id,
                        "name": tool_call.function.name, "content": result
                    })
                    continue

                print(f"[*] Calling tool: {fn_name}({args})")

                if fn_name in TOOL_MAP:
                    try:
                        result = TOOL_MAP[fn_name](**args)
                    except Exception as e:
                        result = f"Error executing tool: {e}"
                else:
                    result = f"Error: Tool {fn_name} not found."

                print(f"[*] Tool result: {result[:100]}...")

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": fn_name,
                    "content": result
                })

    def run(self):
        print("LLM REPL Started. Type '/q' to quit.")
        print(f"Model: {self.model} | Base URL: {self.client.base_url}")
        while True:
            try:
                user_input = input("\nUser > ").strip()
                if not user_input:
                    continue
                if user_input == "/q":
                    print("Goodbye!")
                    break
                self.send_message(user_input)
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Unexpected error: {e}")

if __name__ == "__main__":
    # Allow overrides via env vars
    model = os.getenv("LLM_REPL_MODEL", DEFAULT_MODEL)
    base_url = os.getenv("LLM_REPL_BASE_URL", DEFAULT_BASE_URL)
    api_key = os.getenv("LLM_REPL_API_KEY", DEFAULT_API_KEY)

    repl = LLMRepl(model=model, base_url=base_url, api_key=api_key)
    repl.run()
