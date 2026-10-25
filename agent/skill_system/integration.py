import logging
import os
import sys
from pathlib import Path

# Add /agent to path to import harness components

sys.path.append('/agent')
# Add /workspace/agent_skills to path
sys.path.append('/workspace/agent_skills')

from skill_system.tool_registry import registry as tool_registry
from skill_system.skills_manager import SkillsManager

# Configuration
SKILLS_ROOT = '/workspace/.skills'
os.makedirs(SKILLS_ROOT, exist_ok=True)

# Initialize Skills Manager
skills_manager = SkillsManager(SKILLS_ROOT)
skills_manager.discover_skills()

def get_all_tools_schema():
    """Return all registered tools as OpenAI schemas."""
    return tool_registry.get_all_schemas()

def execute_tool(name: str, **kwargs):
    """Execute a tool through the registry."""
    return tool_registry.execute(name, **kwargs)

def get_skills_summary():
    """Get a summary of available skills."""
    return skills_manager.get_catalog_summary()

def activate_skill(skill_id: str):
    """Load and return instructions for a skill."""
    return skills_manager.get_skill_instructions(skill_id)

def get_skill_resource(skill_id: str, resource_path: str):
    """Get a resource for a skill."""
    return skills_manager.get_skill_resource(skill_id, resource_path)

# To integrate with the actual /agent harness, we would normally
# modify the dispatcher in /agent/pipeline_agent_v3.py or similar.
# Since /agent is read-only, we provide this as a library to be used by a
# runner that we can control.
