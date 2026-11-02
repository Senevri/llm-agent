import logging
import os
import sys
from pathlib import Path

# Add /agent to path to import harness components
for path in ["/agent", "/workspace/agent_skills"]:
    if Path(path).exists() and path not in sys.path:
        sys.path.append(path)
    else:
        sys.path.append(Path(__file__).parent.parent.as_posix())

from skill_system.tool_registry import registry as tool_registry
from skill_system.skills_manager import SkillsManager

# Configuration

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SkillSystem")

def get_skills_root():
    """Determine the root directory for skills."""
    # Check environment variable first
    potential_paths = [
        os.getenv("SKILLS_ROOT"),
        Path.cwd() / ".skills",
        Path("/workspace/.skills")
    ]

    for path in potential_paths:
        if path and Path(path).exists():
            path = Path(path)
            break
    else:
        path = Path.cwd() / ".skills"
    logger.info(f"Using skills root: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return str(path)

SKILLS_ROOT = get_skills_root()

# assert SKILLS_ROOT
# print(f"Using skills root: {SKILLS_ROOT}")

skills_manager = None

def initialize():
    # Initialize Skills Manager
    global skills_manager
    skills_manager = SkillsManager(SKILLS_ROOT)
    skills_manager.discover_skills()
    return skills_manager

def get_all_tools_schema():
    """Return all registered tools as OpenAI schemas."""
    return tool_registry.get_all_schemas()

def execute_tool(name: str, **kwargs):
    """Execute a tool through the registry."""
    return tool_registry.execute(name, **kwargs)

def get_skills_summary():
    """Get a summary of available skills."""
    global skills_manager
    if not skills_manager:
        skills_manager = initialize()
    return skills_manager.get_catalog_summary()

def activate_skill(skill_id: str):
    """Load and return instructions for a skill."""
    global skills_manager
    if not skills_manager:
        skills_manager = initialize()
    return skills_manager.get_skill_instructions(skill_id)

def get_skill_resource(skill_id: str, resource_path: str):
    """Get a resource for a skill."""
    global skills_manager
    if not skills_manager:
        skills_manager = initialize()
    return skills_manager.get_skill_resource(skill_id, resource_path)

# To integrate with the actual /agent harness, we would normally
# modify the dispatcher in /agent/pipeline_agent_v3.py or similar.
# Since /agent is read-only, we provide this as a library to be used by a
# runner that we can control.

if __name__ == "__main__":

    print("Initializing skill system...")
    print(f"Skills root: {SKILLS_ROOT}")