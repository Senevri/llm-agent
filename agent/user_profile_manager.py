import json
import os
from pathlib import Path
from typing import Dict, Any, List
import logging
import threading
import time
from dataclasses import dataclass, field

DEFAULT_PROFILE_PATH=Path(".llm_user_profile.json")

# --- Helper classes ---------------------------------------------------------------
@dataclass
class ContextSnapshot:
    """State packaging for the profiling worker."""
    user_input: str
    assistant_response: str
    history: List[Any]
    timestamp: float = field(default_factory=time.time)
    event_type: str = "turn_complete"


class UserProfileManager:
    """Thread-safe manager for user preferences and profile data."""

    def __init__(self, profile_path: Path = DEFAULT_PROFILE_PATH):
        self.profile_path = Path(profile_path)
        self._lock = threading.RLock()
        with self._lock:
            self._profile_data: Dict[str, Any] = self._load_profile()

    def _load_profile(self) -> Dict[str, Any]:
        if self.profile_path.exists():
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
                logging.error("Profile file did not contain a JSON object; ignoring.")
                return {}
            except Exception as e:
                logging.error(f"Failed to load profile: {e}")
                return {}
        return {}

    def save_profile(self) -> None:
        with self._lock:
            try:
                self.profile_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.profile_path, "w", encoding="utf-8") as f:
                    json.dump(self._profile_data, f, indent=2)
            except Exception as e:
                logging.error(f"Error saving profile: {e}")

    def get_profile_string(self) -> str:
        with self._lock:
            if not self._profile_data:
                return "No user profile available."
            return json.dumps(self._profile_data, indent=2)

    def update_profile(self, updates: Dict[str, Any]) -> None:
        with self._lock:
            self._profile_data.update(updates)
            self.save_profile()

    def set_profile_data(self, data: Dict[str, Any]) -> None:
        with self._lock:
            if not isinstance(data, dict):
                raise ProfileError(f"Expected dict for profile data, got {type(data)}")
            self._profile_data = data
            self.save_profile()

    @property
    def profile_data(self) -> Dict[str, Any]:
        with self._lock:
            return self._profile_data.copy()

    def __enter__(self) -> "UserProfileManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.save_profile()
        return False