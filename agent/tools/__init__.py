# coding=utf-8
import os
import sys
from pathlib import Path

AGENT_DIR=os.getenv("AGENT_DIR", "/agent")
if Path(AGENT_DIR).exists() and AGENT_DIR not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TOOLS_DIR = Path(__file__).resolve().parent

# if TOOLS_DIR not in sys.path:
#     sys.path.insert(0, str(TOOLS_DIR))

def resolve_workspace_dir():
    potential_paths = [
        os.getenv("AGENT_WORKSPACE_DIR", "/workspace"),
        Path.cwd() / "workspace",
        Path("/workspace")
    ]

    for path in potential_paths:
        if path and Path(path).exists():
            path = Path(path)
            break
    else:
        path = Path.cwd()

    return path

WORKSPACE_DIR = resolve_workspace_dir()

from tools import *