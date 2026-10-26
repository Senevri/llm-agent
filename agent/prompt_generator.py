import os
import yaml
import sys
from pathlib import Path
from typing import Dict, List, Optional

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

    def _load_profiles(self) -> Dict:
        if not self.profiles_path.exists():
            raise FileNotFoundError(f"Profiles file not found: {self.profiles_path}")
        with open(self.profiles_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("roles", {})

    def reload_profiles(self):
        self._profiles = self._load_profiles()

    def get_role_names(self) -> List[str]:
        return list(self._profiles.keys())

    def generate_prompt(self, role_name: str) -> str:
        if role_name not in self._profiles:
            raise ValueError(f"Unknown role: {role_name}")

        profile = self._profiles[role_name]
        snippets = profile.get("snippets", [])

        prompt_parts = []
        for snippet_name in snippets:
            snippet_path = self.snippets_dir / f"{snippet_name}.md"
            if not snippet_path.exists():
                raise FileNotFoundError(f"Snippet file not found: {snippet_path}")
            content = snippet_path.read_text(encoding="utf-8").strip()
            prompt_parts.append(content)

        prompt = "\n\n".join(prompt_parts).strip()

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
