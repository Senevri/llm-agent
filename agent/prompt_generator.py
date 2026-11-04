import os
import json
import yaml
import sys
from pathlib import Path
from typing import Dict, List, Optional, Union, Any

import logging
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent

def find_prompt_dir(paths:Optional[List[Path]] = None) -> Path:
    PROMPT_DIR = Path(os.getenv("AGENT_PROMPT_DIR", ".")) / "prompts"
    if not PROMPT_DIR.exists():

        potential_paths = [
            Path.cwd() / "prompts",
            Path(SCRIPT_DIR) /"prompts",
            Path("/workspace/prompts")
            ]

        potential_paths.extend(paths or [])
        for path in potential_paths:
            if path.exists():
                PROMPT_DIR = path
                break
        else:
            raise FileNotFoundError(
                "Failed to find prompts directory. "
                "Please set the AGENT_PROMPT_DIR environment variable or "
                "create a 'prompts' directory in the current working directory.")

    return PROMPT_DIR.resolve()


class PromptGenerator:
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = Path(prompts_dir).resolve()
        self.profiles_path = self.prompts_dir / "profiles.yaml"
        self.snippets_dir = self.prompts_dir / "snippets"
        self._profiles = self._load_profiles()
        self.enabled_skills = ["all"]
        self.platform = "linux"

    def _load_profiles(self) -> Dict:
        if not self.profiles_path.exists():
            raise FileNotFoundError(f"Profiles file not found: {self.profiles_path}")
        with open(self.profiles_path, "r", encoding="utf-8") as f:
            self.data = yaml.safe_load(f)
            logger.debug("Profiles data: %s", self.data)
            return self.data.get("roles", {})


    def _get_platform_patches(self, platform_name: str):
        return self.data.get("platforms", {}).get(platform_name, {}).get("patches", {})



    def reload_profiles(self):
        self._profiles = self._load_profiles()

    def _get_enabled_skills(self, role_name: str) -> List[str]:
        if role_name not in self._profiles:
            raise ValueError(f"Unknown role: {role_name}")

        profile = self._profiles[role_name]
        return profile.get("skills", [])

    def get_role_names(self) -> List[str]:
        return list(self._profiles.keys())

    def _get_prompt_parts(self, profile):
        snippets = profile.get("snippets", [])
        patches = self._get_platform_patches(self.platform)
        logger.debug("platform patches: %s, snippets: %s", patches, snippets)
        if patches:
            logger.debug("platform patches found:", patches)
        for i, snippet_name in enumerate(snippets):
            if snippet_name in patches:
                #index matters
                snippets.remove(snippet_name)
                snippets.insert(i, patches[snippet_name])
                logger.info (f"patched {snippet_name} with {patches[snippet_name]}")
        logger.debug("snippets: %s", snippets)
        prompt_parts = []
        for snippet_name in snippets:
            snippet_path = self.snippets_dir / f"{snippet_name}.md"
            if not snippet_path.exists():
                raise FileNotFoundError(f"Snippet file not found: {snippet_path}")
            content = snippet_path.read_text(encoding="utf-8").strip()
            prompt_parts.append(content)

        return prompt_parts

    def generate_prompt(self, role_name: str, profile: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        logger.debug("--------", role_name, "------")
        if profile:
            json.dumps(profile) # validate lite
            if role_name in profile.keys():
                self._profiles.update(profile)
        elif role_name not in self._profiles:
            raise ValueError(f"Unknown role: {role_name}")
        profile = profile or self._profiles[role_name]

        prompt_parts = self._get_prompt_parts(profile)

        prompt = "\n\n".join(prompt_parts).strip()
        for k, v in kwargs.items():
            prompt = prompt.replace(f"<{k}>", str(v))
        # self.enabled_skills = self._get_enabled_skills(role_name)

        return f"{prompt}\n" ##make sure we end in newline

def main():
    if len(sys.argv) < 2:
        print("Usage: python prompt_generator.py [role_name]")
        sys.exit(1)

    role = sys.argv[1]
    try:
        gen = PromptGenerator()
        print(gen.generate_prompt(role))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
