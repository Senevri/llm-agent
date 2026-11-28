import re
import json
import os
import math as math_lib
from typing import Tuple

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

    #print (expression)
    # how many closing parens
    opening_count = expression.count("(")

    def handle_mid_parens(expr: str) -> str:
        closing_index = expr.find(")")
        assert isinstance(expr, str)
        if (closing_index != -1
            and ")" == expr[-1]):
            expr = math_eval(str(expr[:-1].rstrip(")")))
        elif closing_index != -1: #un-parenthesized content in split.
            expr_sides = [e for e in expr.split(")") if e.strip()]
            while len(expr_sides) > 1:

                result = _math_eval(expr_sides[0])
                expr_sides[1] = f"{result}{expr_sides[1]}"
                expr_sides = expr_sides[1:]

            expr =  "".join(expr_sides)

     #   print(expr)
        return expr



    if opening_count > 1:
        # Test and fix for implicit multiplication:
        for r in re.findall(r"[0-9,\)]\(", expression):

            expression = expression.replace(r, f"{r.rstrip('(')} * (", 1)
            # Deal with implicit multiplication first

        split_expression = list(e.strip() for e in expression.split("(") if e.strip())
        for i in range(len(split_expression)-1, 0, -1):

            # prefix=""
            # split_expression = [s for s in split_expression if s.strip()]

            # if split_expression[0].find(")"):
            #     prefix = "("

      #      print(f"{i}: {prefix}{' ('.join(split_expression)})")


            expr = split_expression[i].strip()
            if expr == "":
                continue
            operators = ["+", "-", "*", "/"]
            if ")" not in expr:
                if expr[0] not in operators:
                    expr = _math_eval(expr)
                split_expression[i-1] = f"{split_expression[i-1]}{expr}"
                split_expression[i] = ""
                continue
            prev_expr = ""

            if i>0:
                prev_expr = split_expression[i-1]

            if (prev_expr
                and len(expr) > 1
                and (
                    expr[0] in  operators
                    or prev_expr[-1] in operators
                )
            ):
                #there was parens there.
                #split_expression[i-1] = f"{prev_expr}{_math_eval(expr.rstrip(')'))}"
                expr = f"{handle_mid_parens(expr.rstrip(')'))}"
                assert(expr.find(")") == -1)
                split_expression[i-1] = f"{prev_expr}{expr}"
                split_expression[i] = ""
                continue

       #     print(expr)
            split_expression[i] = handle_mid_parens(expr)

            assert(split_expression[i].find(")") == -1)

            #split_expression[i] = math.evalf"({split_expression[i]})"

        expression = "".join(split_expression)

        expression = _math_eval(handle_mid_parens(expression))
    else:
        expression = _math_eval(expression)
    return expression


def _math_eval(expression: str) -> str:
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

if __name__=="__main__": # For testing
    import sys
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("tool", choices=TOOL_REGISTRY.keys())
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    try:
        print(TOOL_REGISTRY[sys.argv[1]](*sys.argv[2:]))
    except TypeError as e:
        print(f"Error: {e}")
        print("Usage: python implementation.py <tool> <args>")
        sys.exit(1)
