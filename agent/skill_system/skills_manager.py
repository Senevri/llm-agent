import logging
import os
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("SkillsManager")

@dataclass
class SkillMetadata:
    name: str
    description: str
    version: str
    author: str
    category: str
    dependencies: List[str]

class SkillsManager:
    """Manages discovery and loading of Agent Skills (SKILL.md)."""
    def __init__(self, skills_root: str):
        self.skills_root = skills_root
        self.catalog: Dict[str, SkillMetadata] = {}
        self.active_skills: List[str] = []

    def discover_skills(self):
        """Scan the skills root directory for directories containing SKILL.md."""
        logger.info(f"Discovering skills in {self.skills_root}...")
        if not os.path.exists(self.skills_root):
            logger.error(f"Skills root {self.skills_root} does not exist.")
            return

        for entry in os.scandir(self.skills_root):
            if entry.is_dir():
                skill_md_path = os.path.join(entry.path, "SKILL.md")
                if os.path.exists(skill_md_path):
                    try:
                        metadata = self._parse_skill_md(skill_md_path)
                        if metadata:
                            self.catalog[entry.name] = metadata
                            logger.info(f"Discovered skill: {entry.name}")
                    except Exception as e:
                        logger.error(f"Error parsing skill {entry.name}: {e}")

    def _parse_skill_md(self, path: str) -> Optional[SkillMetadata]:
        """Parse the SKILL.md file for basic metadata."""
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        metadata = {}
        for line in content.splitlines():
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                if key in ['name', 'description', 'version', 'author', 'category', 'dependencies']:
                    metadata[key] = value.strip()
        
        if 'name' not in metadata or 'description' not in metadata:
            return None
            
        return SkillMetadata(
            name=metadata.get('name'),
            description=metadata.get('description'),
            version=metadata.get('version', '0.1.0'),
            author=metadata.get('author', 'unknown'),
            category=metadata.get('category', 'general'),
            dependencies=[d.strip() for d in metadata.get('dependencies', '').split(',') if d.strip()]
        )

    def get_skill_instructions(self, skill_id: str) -> Optional[str]:
        """Load the full instructions from the SKILL.md file."""
        skill_path = os.path.join(self.skills_root, skill_id, "SKILL.md")
        if not os.path.exists(skill_path):
            return None
        
        with open(skill_path, 'r', encoding='utf-8') as f:
            return f.read()

    def get_skill_resource(self, skill_id: str, resource_path: str) -> Optional[str]:
        """Load a resource relative to the skill directory."""
        full_path = os.path.normpath(os.path.join(self.skills_root, skill_id, resource_path))
        if not full_path.startswith(os.path.join(self.skills_root, skill_id)):
            logger.warning(f"Attempted out-of-bounds resource access: {full_path}")
            return None
            
        if not os.path.exists(full_path):
            return None
            
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading resource {full_path}: {e}")
            return None

    def get_catalog_summary(self) -> str:
        """Return a summary of available skills for the LLM."""
        if not self.catalog:
            return "No skills discovered."
        
        summary = ["Available Agent Skills:"]
        for skill_id, meta in self.catalog.items():
            summary.append(f"- {skill_id} ({meta.name}): {meta.description} (Category: {meta.category})")
        return "\n".join(summary)
