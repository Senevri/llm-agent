import re
import json
import os
import math as math_lib

def grep(pattern: str, input_data: str) -> str:
    """Searches for a regex pattern within the provided input_data."""
    if os.path.isfile(input_data):
        try:
            with open(input_data, 'r') as f:
                content = f.read()
        except Exception as e:
            return f"Error reading file: {str(e)}"
    else:
        content = input_data

    matches = [m.group(0) for m in re.finditer(pattern, content, re.MULTILINE)]
    if not matches:
        return "None"
    return "\n".join(matches)

def json_get(key: str, json_string: str) -> str:
    """Extracts a value from a JSON string using a dot-notation key."""
    try:
        data = json.loads(json_string)
        keys = key.split('.')
        for k in keys:
            if isinstance(data, dict):
                data = data.get(k)
            else:
                return "None"
                
        if data is None:
            return "None"
        return str(data)
    except Exception as e:
        return f"Error: {str(e)}"

def json_validate(json_string: str, required_keys_json: str) -> str:
    """Checks if a JSON string contains all specified required keys (as a JSON array)."""
    try:
        data = json.loads(json_string)
        required_keys = json.loads(required_keys_json)
        missing = [k for k in required_keys if k not in data]
        
        if not missing:
            return "Valid"
        return f"Missing: {', '.join(missing)}"
    except Exception as e:
        return f"Error: {str(e)}"

def count(count_type: str, input_data: str) -> str:
    """Counts occurrences of count_type (lines, words, chars) in the input_data."""
    try:
        if count_type == 'lines':
            return str(len(input_data.splitlines()))
        elif count_type == 'words':
            return str(len(input_data.split()))
        elif count_type == 'chars':
            return str(len(input_data))
        else:
            return "Error: Invalid count_type. Use 'lines', 'words', or 'chars'."
    except Exception as e:
        return f"Error: {str(e)}"

def exists(path: str) -> str:
    """Checks if a file or directory exists."""
    return str(os.path.exists(path))

def math_eval(expression: str) -> str:
    """Evaluates a simple mathematical expression."""
    allowed_names = {k: getattr(math_lib, k) for k in dir(math_lib) if not k.startswith("__")}
    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"

def shell_report(stdout: str, stderr: str, exit_code: int) -> str:
    """Provides a structured summary of a shell command execution."""
    status = "SUCCESS" if exit_code == 0 else "FAILURE"
    report = [f"Status: {status}", f"Exit Code: {exit_code}"]
    
    if stderr:
        report.append("\n--- Error Output ---")
        report.append("\n".join(stderr.splitlines()[-5:])) # Last 5 lines
        
    if stdout:
        report.append("\n--- Standard Output ---")
        report.append("\n".join(stdout.splitlines()[-5:])) # Last 5 lines
        
    return "\n".join(report)

TOOL_REGISTRY = {
    "grep": grep,
    "json_get": json_get,
    "json_validate": json_validate,
    "count": count,
    "exists": exists,
    "math": math_eval,
    "shell_report": shell_report
}
