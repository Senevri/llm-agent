"""
edit_tools.py — Agentic in-memory file editing toolkit.

Concept
-------
Files exist in RAM until explicitly saved.  The LLM can:
  • Load a file from disk into memory (or create a new one)
  • Read arbitrary line segments (by line number range or by description)
  • Apply edits (replace, insert, delete) to the in-memory version
  • Evaluate code snippets safely before committing
  • Save the in-memory state back to disk

All changes are tracked.  Nothing touches the filesystem until `save_file` is called.
"""

from __future__ import annotations

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parent.parent.resolve()
if SOURCE_DIR not in sys.path or Path("/agent") not in sys.path:
    sys.path.append(str(SOURCE_DIR))


from tools import WORKSPACE_DIR


import ast
import textwrap
import traceback as tb_mod
from dataclasses import dataclass, field

from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EditOp:
    """An atomic edit recorded in the edit log."""
    op: str          # 'replace', 'insert_after', 'delete', 'append'
    target_line: int  # 1-indexed line number (relevant for replace/delete/insert)
    old_lines: list[str] | None
    new_lines: list[str]

    def summary(self) -> str:
        if self.op == "replace":
            return f"Replace lines {self.target_line}–{self.target_line + len(self.old_lines) - 1}: {len(self.new_lines)} new line(s)"
        elif self.op == "insert_after":
            return f"Insert after line {self.target_line}: {len(self.new_lines)} line(s)"
        elif self.op == "delete":
            return f"Delete lines {self.target_line}–{self.target_line + len(self.old_lines) - 1}"
        elif self.op == "append":
            return f"Append: {len(self.new_lines)} line(s)"
        return f"{self.op}: {len(self.new_lines)} new line(s)"


@dataclass
class InMemoryFile:
    """A file that lives in RAM until saved."""

    path: str                        # filesystem path (string)
    lines: list[str] = field(default_factory=list)   # raw text, one element per line (no trailing \n)
    original_lines: list[str] | None = None  # snapshot at load time for diff tracking
    edit_log: list[EditOp] = field(default_factory=list)
    _dirty: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str) -> InMemoryFile:
        """Load file contents from disk."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"[edit_tools] {path} does not exist")
        raw = p.read_text(encoding="utf-8")
        lines = raw.splitlines() if raw else []
        return cls(
            path=str(p.resolve()),
            lines=lines,
            original_lines=list(lines),
        )

    @classmethod
    def create(cls, path: str) -> InMemoryFile:
        """Create a new empty in-memory file."""
        return cls(path=str(Path(path).resolve()))

    # ------------------------------------------------------------------
    # Reading segments
    # ------------------------------------------------------------------

    def read_lines(self, start: int = 1, end: int | None = None) -> list[str]:
        """Read lines by 1-indexed range. *end* is inclusive."""
        if not self.lines:
            return []
        s = max(0, start - 1)          # convert to 0-indexed
        e = len(self.lines) if end is None else min(len(self.lines), end)
        return list(self.lines[s:e])

    def read_segment_description(self, pattern: str, context_lines: int = 5) -> str:
        """Read lines around the *first* occurrence of *pattern* (case-insensitive)."""
        for i, line in enumerate(self.lines):
            if pattern.lower() in line.lower():
                lo = max(0, i - context_lines)
                hi = min(len(self.lines), i + context_lines + 1)
                snippet = "\n".join(f"{j + 1}: {self.lines[j]}" for j in range(lo, hi))
                return f"Context around '{pattern}' (lines {lo+1}–{hi}):\n{snippet}"
        return f"[edit_tools] Pattern '{pattern}' not found."

    def read_all(self) -> str:
        """Return the entire file content."""
        return "\n".join(self.lines) if self.lines else ""

    def line_count(self) -> int:
        return len(self.lines)

    # ------------------------------------------------------------------
    # Editing (in-memory only)
    # ------------------------------------------------------------------

    def replace_lines(
        self,
        start: int,
        end: int | None = None,
        replacement: str | list[str] = "",
    ) -> EditOp:
        """Replace lines *start*–*end* (1-indexed, inclusive) with new text."""
        s_idx = max(0, start - 1)
        e_idx = len(self.lines) if end is None else min(len(self.lines), end)
        old_slice = list(self.lines[s_idx:e_idx])

        if isinstance(replacement, str):
            new = replacement.splitlines()
        else:
            new = list(replacement)

        # Handle single-line text without trailing newline in representation
        if not new and replacement == "":
            new = [""]

        self.lines[s_idx:e_idx] = new
        op = EditOp(op="replace", target_line=start, old_lines=old_slice or None, new_lines=new)
        self.edit_log.append(op)
        self._dirty = True
        return op

    def insert_after(self, after_line: int, text: str | list[str]) -> EditOp:
        """Insert *text* after line *after_line* (1-indexed)."""
        idx = after_line            # 0-indexed position to insert at
        if isinstance(text, str):
            new = text.splitlines()
        else:
            new = list(text)

        self.lines[idx:idx] = new
        op = EditOp(op="insert_after", target_line=after_line, old_lines=None, new_lines=new)
        self.edit_log.append(op)
        self._dirty = True
        return op

    def delete_lines(self, start: int, end: int | None = None) -> EditOp:
        """Delete lines *start*–*end* (1-indexed, inclusive)."""
        s_idx = max(0, start - 1)
        e_idx = len(self.lines) if end is None else min(len(self.lines), end)
        old_slice = list(self.lines[s_idx:e_idx])

        del self.lines[s_idx:e_idx]
        op = EditOp(op="delete", target_line=start, old_lines=old_slice, new_lines=[])
        self.edit_log.append(op)
        self._dirty = True
        return op

    def append(self, text: str | list[str]) -> EditOp:
        """Append *text* to the end of the file."""
        if isinstance(text, str):
            new = text.splitlines()
        else:
            new = list(text)

        self.lines.extend(new)
        op = EditOp(op="append", target_line=0, old_lines=None, new_lines=new)
        self.edit_log.append(op)
        self._dirty = True
        return op

    # ------------------------------------------------------------------
    # Diff & status helpers
    # ------------------------------------------------------------------

    def diff(self) -> str:
        """Return a unified-diff-like view between original and current."""
        if not self.original_lines:
            return "[edit_tools] No original snapshot to compare against."
        orig = self.original_lines
        cur = self.lines
        result: list[str] = []
        mi, ni = 0, 0
        while mi < len(orig) and ni < len(cur):
            if orig[mi] == cur[ni]:
                mi += 1
                ni += 1
                continue
            result.append(f"-{orig[mi]}")
            result.append(f"+{cur[ni]}")
            mi += 1
            ni += 1
        for line in orig[mi:]:
            result.append(f"-{line}")
        for line in cur[ni:]:
            result.append(f"+{line}")
        return "\n".join(result) if result else "[edit_tools] No differences from original."

    def is_dirty(self) -> bool:
        return self._dirty or (self.lines != self.original_lines) if self.original_lines else False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | None = None) -> str:
        """Write in-memory lines to disk."""
        target = Path(path) if path else Path(self.path)
        target.write_text("\n".join(self.lines) + "\n" if self.lines else "", encoding="utf-8")
        self._dirty = False
        self.original_lines = list(self.lines)  # snapshot after save
        return f"[edit_tools] Saved {self.line_count()} lines to {target}"

    def discard(self) -> str:
        """Discard all edits, restoring the original."""
        if not self.original_lines:
            return "[edit_tools] Nothing to discard."
        self.lines = list(self.original_lines)
        self.edit_log.clear()
        self._dirty = False
        return "[edit_tools] Edits discarded; file restored to loaded state."

    def reset(self) -> str:
        """Forget all edits (including the save point)."""
        self.lines = []
        self.original_lines = None
        self.edit_log.clear()
        self._dirty = False
        return "[edit_tools] File memory cleared."


# ---------------------------------------------------------------------------
# Safe code evaluation
# ---------------------------------------------------------------------------

SAFE_EVAL_BUILTINS = {
    "__builtins__": {
        "abs": abs,
        "any": any,
        "bool": bool,
        "bytes": bytes,
        "chr": chr,
        "dict": dict,
        "divmod": divmod,
        "enumerate": enumerate,
        "eval": eval,
        "filter": filter,
        "float": float,
        "frozenset": frozenset,
        "getattr": getattr,
        "hasattr": hasattr,
        "hash": hash,
        "hex": hex,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "oct": oct,
        "open": None,  # block file opens in eval
        "ord": ord,
        "pow": pow,
        "range": range,
        "repr": repr,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "type": type,
        "zip": zip,
    }
}


def safe_eval_code(source: str, timeout: int = 5) -> dict[str, str]:
    """
    Safely evaluate *source* as Python code.

    Returns a dict with keys:
      - 'success': bool
      - 'output': str   (printed output or result repr)
      - 'error': str    (empty on success)
    """
    try:
        # Parse to check for obviously unsafe constructs
        tree = ast.parse(source, mode="eval")
        _check_ast(tree)

        # SAFE_EVAL_BUILTINS has the correct shape: {builtin_name: func, ...}
        globals_dict: dict[str, object] = dict(SAFE_EVAL_BUILTINS)
        result = eval(
            compile(tree, "<safe_eval>", "eval"),
            globals_dict,
            {},
        )
        return {
            "success": True,
            "output": repr(result) if result is not None else "",
            "error": "",
        }
    except SyntaxError:
        # Multi-statement source — compile in exec mode
        _check_ast(ast.parse(source))  # same AST safety check for statements
        globals_dict: dict[str, object] = dict(SAFE_EVAL_BUILTINS)
        compiled = compile(source, "<safe_exec>", "exec")
        ns: dict = {}
        exec(compiled, globals_dict, ns)
        if ns:
            last_key = list(ns.keys())[-1]
            return {
                "success": True,
                "output": repr(ns[last_key]) if ns[last_key] is not None else "",
                "error": "",
            }
        return {"success": True, "output": "", "error": ""}
    except TimeoutError:
        return {"success": False, "output": "", "error": "Evaluation timed out."}
    except Exception as exc:
        return {"success": False, "output": "", "error": str(exc)}


def _check_ast(node: ast.AST) -> None:
    """Reject AST nodes that are unsafe to eval."""
    # Whitelist only safe expression-level AST node types.
    allowed = {
        ast.Expression,              # top-level eval wrapper
        ast.Constant,                # strings, ints, floats, bools, None
        ast.Name, ast.Load, ast.Store, ast.Param,  # var names + contexts
        ast.Module,              # top-level stmt wrapper for exec mode
        ast.FunctionDef,         # function definitions
        # ---- statement-level (exec-mode) nodes ----
        ast.Assign,                # x = 1
        ast.AugAssign,             # x += 1
        ast.Expr,                  # standalone expression stmt
        ast.Return,                # return value in functions
        ast.arguments,             # func param list: (a, b)
        ast.arg,                   # individual arg: def f(a, b):
        ast.If,                    # if/else statements
        ast.For,                   # for loops
        ast.While,                 # while loops
        ast.Try,                   # try/except blocks
        ast.With,                  # with statements
        ast.Import,                # import x
        ast.ImportFrom,            # from x import y
        ast.ClassDef,              # class definitions
        ast.Attribute,               # attr access: foo.bar
        ast.Call,                    # function calls: foo()
        ast.keyword,                 # keyword args: foo(a=1)
        ast.BinOp,                   # binary ops: a + b
        ast.Add, ast.Sub, ast.Mult,
        ast.Div, ast.Mod, ast.Pow,
        ast.LShift, ast.RShift,
        ast.BitOr, ast.BitXor,
        ast.BitAnd, ast.FloorDiv,
        ast.MatMult,
        ast.UnaryOp,                 # unary ops: -x
        ast.USub, ast.UAdd,         # -, + (unary)
        ast.Not, ast.Invert,
        ast.Compare,                # comparisons: a == b
        ast.Eq, ast.NotEq, ast.Lt,
        ast.LtE, ast.Gt, ast.GtE,
        ast.Is, ast.IsNot,
        ast.In, ast.NotIn,
        ast.BoolOp,
        ast.And, ast.Or,
        ast.IfExp,                  # ternary: x if cond else y
        ast.Lambda,                 # lambdas (use cautiously)
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
        ast.comprehension,          # for x in y parts of comprehensions
        ast.List, ast.Tuple, ast.Set,
        ast.Dict,                   # literals: [...], (...), {...}
        ast.FormattedValue,          # f-string parts
        ast.JoinedStr,              # f-strings
    }
    for child in ast.walk(node):
        if type(child) not in allowed:
            raise ValueError(f"Unsafe AST node: {type(child).__name__}")


# ---------------------------------------------------------------------------
# Tool registry (for the agentic dispatcher)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict = {}

TOOL_SCHEMAS = {
    "load_file": {
        "name": "load_file",
        "description": (
            "Load a file from disk into in-memory storage. "
            "All subsequent edits happen in RAM until `save_file` is called."
        ),
        "parameters": {
            "path": {"type": "string", "description": "Absolute or relative path to the file."},
        },
    },
    "create_file": {
        "name": "create_file",
        "description": (
            "Create a new empty in-memory file at *path*. "
            "No disk I/O until `save_file` is called."
        ),
        "parameters": {
            "path": {"type": "string", "description": "Path where the new file will be saved."},
        },
    },
    "read_all_lines": {
        "name": "read_all_lines",
        "description": (
            "Return all lines of the currently loaded in-memory file as a single string."
        ),
        "parameters": {},
    },
    "read_line_range": {
        "name": "read_line_range",
        "description": (
            "Read a specific range of lines (1-indexed, inclusive). "
            "Useful for examining function bodies, imports, etc."
        ),
        "parameters": {
            "start": {"type": "integer", "description": "Start line (inclusive)."},
            "end": {"type": "integer", "description": "End line (inclusive). If omitted, reads to end of file."},
        },
    },
    "read_around_pattern": {
        "name": "read_around_pattern",
        "description": (
            "Find the first occurrence of *pattern* (case-insensitive) and return "
            "context lines around it. Useful for locating specific code sections."
        ),
        "parameters": {
            "pattern": {"type": "string", "description": "Text to search for in any line."},
            "context_lines": {"type": "integer", "description": "Number of lines before and after the match (default 5)."},
        },
    },
    "replace_lines": {
        "name": "replace_lines",
        "description": (
            "Replace lines *start*–*end* (1-indexed, inclusive) with new text. "
            "Changes are in-memory only until `save_file`."
        ),
        "parameters": {
            "start": {"type": "integer", "description": "First line to replace (inclusive)."},
            "end": {"type": "integer", "description": "Last line to replace (inclusive). If omitted, replaces from *start* to end."},
            "replacement": {"type": "string", "description": "Text to insert in place of the old lines. Use \\n for line breaks."},
        },
    },
    "insert_after_line": {
        "name": "insert_after_line",
        "description": (
            "Insert *text* after a given 1-indexed line number. "
            "Useful for adding new functions or imports."
        ),
        "parameters": {
            "after_line": {"type": "integer", "description": "Line number after which to insert."},
            "text": {"type": "string", "description": "Text to insert. Use \\n for line breaks."},
        },
    },
    "delete_lines": {
        "name": "delete_lines",
        "description": (
            "Delete lines *start*–*end* (1-indexed, inclusive). "
            "Changes are in-memory only until `save_file`."
        ),
        "parameters": {
            "start": {"type": "integer", "description": "First line to delete."},
            "end": {"type": "integer | null", "description": "Last line to delete. If omitted, deletes a single line."},
        },
    },
    "append_text": {
        "name": "append_text",
        "description": (
            "Append *text* to the end of the in-memory file."
        ),
        "parameters": {
            "text": {"type": "string", "description": "Text to append. Use \\n for line breaks."},
        },
    },
    "save_file": {
        "name": "save_file",
        "description": (
            "Write the current in-memory file contents to disk. "
            "If a *path* is provided, saves to that path; otherwise overwrites the originally loaded file."
        ),
        "parameters": {
            "path": {"type": "string | null", "description": "Optional destination path. If omitted, overwrites the original."},
        },
    },
    "diff_file": {
        "name": "diff_file",
        "description": (
            "Show a diff between the loaded/created state and the current in-memory version."
        ),
        "parameters": {},
    },
    "discard_edits": {
        "name": "discard_edits",
        "description": (
            "Discard all edits and restore the file to its originally loaded state."
        ),
        "parameters": {},
    },
    "line_count": {
        "name": "line_count",
        "description": "Return the number of lines in the current in-memory file.",
        "parameters": {},
    },
    "evaluate_code": {
        "name": "evaluate_code",
        "description": (
            "Safely evaluate a Python code snippet. "
            "Returns success status, output/result, and any error message."
        ),
        "parameters": {
            "source": {"type": "string", "description": "Python source code to evaluate."},
        },
    },
}




def tool_implementations() -> dict:
    """ !!!! FFFFFF """

    def _load_file(path: str) -> str:
        mem = InMemoryFile.load(path)
        TOOL_REGISTRY["_current"] = mem
        return f"[edit_tools] Loaded {mem.path} ({mem.line_count()} lines)"

    def _create_file(path: str) -> str:
        mem = InMemoryFile.create(path)
        TOOL_REGISTRY["_current"] = mem
        return f"[edit_tools] Created empty file at {path}"

    def _read_all_lines() -> str:
        mem = TOOL_REGISTRY.get("_current")
        if not mem:
            return "[edit_tools] No file loaded. Use `load_file` or `create_file` first."
        return mem.read_all() or "[edit_tools] File is empty."

    def _read_line_range(start: int, end: int | None = None) -> str:
        mem = TOOL_REGISTRY.get("_current")
        if not mem:
            return "[edit_tools] No file loaded."
        lines = mem.read_lines(start, end)
        numbered = "\n".join(f"{i + start}: {l}" for i, l in enumerate(lines))
        return f"[Lines {start}–{end or '*'}]\n{numbered}"

    def _read_around_pattern(pattern: str, context_lines: int = 5) -> str:
        mem = TOOL_REGISTRY.get("_current")
        if not mem:
            return "[edit_tools] No file loaded."
        return mem.read_segment_description(pattern, context_lines)

    def _replace_lines(start: int, end: int | None, replacement: str) -> str:
        mem = TOOL_REGISTRY.get("_current")
        if not mem:
            return "[edit_tools] No file loaded."
        op = mem.replace_lines(start, end, replacement)
        return f"[edit_tools] {op.summary()}"

    def _insert_after_line(after_line: int, text: str) -> str:
        mem = TOOL_REGISTRY.get("_current")
        if not mem:
            return "[edit_tools] No file loaded."
        op = mem.insert_after(after_line, text)
        return f"[edit_tools] {op.summary()}"

    def _delete_lines(start: int, end: int | None = None) -> str:
        mem = TOOL_REGISTRY.get("_current")
        if not mem:
            return "[edit_tools] No file loaded."
        op = mem.delete_lines(start, end)
        return f"[edit_tools] {op.summary()}"

    def _append_text(text: str) -> str:
        mem = TOOL_REGISTRY.get("_current")
        if not mem:
            return "[edit_tools] No file loaded."
        op = mem.append(text)
        return f"[edit_tools] {op.summary()}"

    def _save_file(path: str | None = None) -> str:
        mem = TOOL_REGISTRY.get("_current")
        if not mem:
            return "[edit_tools] No file loaded."
        if path is None or path == "":
            path = None  # let save() use the stored path
        return mem.save(path)

    def _diff_file() -> str:
        mem = TOOL_REGISTRY.get("_current")
        if not mem:
            return "[edit_tools] No file loaded."
        return f"[Diff]\n{mem.diff()}"

    def _discard_edits() -> str:
        mem = TOOL_REGISTRY.get("_current")
        if not mem:
            return "[edit_tools] No file loaded."
        return mem.discard()

    def _line_count() -> int:
        mem = TOOL_REGISTRY.get("_current")
        if not mem:
            return 0
        return mem.line_count()

    def _evaluate_code(source: str) -> dict:
        return safe_eval_code(source)

    # Map names to implementations
    tool_impls = {
        "load_file": _load_file,
        "create_file": _create_file,
        "read_all_lines": _read_all_lines,
        "read_line_range": _read_line_range,
        "read_around_pattern": _read_around_pattern,
        "replace_lines": _replace_lines,
        "insert_after_line": _insert_after_line,
        "delete_lines": _delete_lines,
        "append_text": _append_text,
        "save_file": _save_file,
        "diff_file": _diff_file,
        "discard_edits": _discard_edits,
        "line_count": _line_count,
        "evaluate_code": _evaluate_code,
    }

    return tool_impls


# Compat with existing code

tool_defs = {}
for k, v in TOOL_SCHEMAS.items():
    v.update({"name": f"edit_{v['name']}"})
    tool_defs[k] = v # Might be unnecessary if ref.

EDIT_TOOL_DEFINITIONS = [
        {"type": "function",
        "function": {**spec, "name": f"edit_{name}"}}
    for name, spec in TOOL_SCHEMAS.items()
]

EDIT_TOOL_MAP = {f"edit_{name}": impl for name, impl in tool_implementations().items()}




# ---------------------------------------------------------------------------
# Quick CLI demo / self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json, sys

    print("=" * 60)
    print("edit_tools.py — Self-test")
    print("=" * 60)

    # Create a test file on disk
    test_path = "test_edit_tools_demo.py"
    demo_code = '''"""Demo file for edit_tools self-test."""

import os
from pathlib import Path


def greet(name: str) -> str:
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    print(greet("World"))
    print(add(2, 3))
'''
    Path(test_path).write_text(demo_code, encoding="utf-8")
    print(f"[setup] Created {test_path}")

    # Load into memory
    mem = InMemoryFile.load(test_path)
    print(f"\n[load] Loaded {mem.line_count()} lines")
    print(f"  First 3 lines:")
    for i, l in enumerate(mem.read_lines(1, 3)):
        print(f"    {i + 1}: {l}")

    # Edit: replace the greet function
    old_greet = mem.read_lines(7, 9)
    new_greet = 'def greet(name: str, shout: bool = False) -> str:\n    msg = f"Hello, {name}!"\n    return msg.upper() if shout else msg'
    op = mem.replace_lines(7, 9, new_greet)
    print(f"\n[edit] {op.summary()}")

    # Insert a new function after line 10
    insert_text = '''def multiply(a: float, b: float) -> float:
    return a * b'''
    op = mem.insert_after(10, insert_text)
    print(f"[edit] {op.summary()}")

    # Evaluate the updated greet function
    updated_greet = "\n".join(mem.read_lines(7, 9))
    eval_result = safe_eval_code(updated_greet)
    print(f"\n[eval] Parsed greet: success={eval_result['success']}")

    # Now evaluate a call to it
    eval_call = safe_eval_code('greet("test", shout=True)')
    print(f"[eval] greet('test', shout=True): {eval_call}")

    # Diff
    print(f"\n[diff]\n{mem.diff()[:500]}")

    # Save
    save_msg = mem.save()
    print(f"\n{save_msg}")

    # Reload and verify
    mem2 = InMemoryFile.load(test_path)
    assert mem2.read_lines(7, 9) == new_greet.splitlines(), "Save+reload mismatch!"
    print("\n[verify] Save + reload passed ✓")

    # Clean up
    Path(test_path).unlink(missing_ok=True)
    print(f"\n[cleanup] Removed {test_path}")

    print("\n" + "=" * 60)
    print("All self-tests passed ✓")
    print("=" * 60)
