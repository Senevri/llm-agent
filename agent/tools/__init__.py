# coding=utf-8
import os
import sys
from pathlib import Path

AGENT_DIR=os.getenv("AGENT_DIR", "/agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

TOOLS_DIR = Path(__file__).resolve().parent

from tools import *