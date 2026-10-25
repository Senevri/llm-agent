import json
import os
from pathlib import Path
from typing import Dict, Any

class UserProfileManager:
    def __init__(self, profile_path: Path = Path.cwd() / ".llm_user_profile.json"):
        self.profile_path = profile_path
        self.profile_data: Dict[str, Any] = self._load_profile()

    def _load_profile(self) -> Dict[str, Any]:
        if self.profile_path.exists():
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_profile(self):
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(self.profile_data, f, indent=2)
        except Exception as e:
            print(f"Error saving profile: {e}")

    def get_profile_string(self) -> str:
        if not self.profile_data:
            return "No user profile available."
        return json.dumps(self.profile_data, indent=2)

    def update_profile(self, updates: Dict[str, Any]):
        self.profile_data.update(updates)
        self.save_profile()

    def set_profile_data(self, data: Dict[str, Any]):
        self.profile_data = data
        self.save_profile()
