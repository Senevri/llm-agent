import json
import os
from pathlib import Path
from typing import Dict, Any, List
import logging
import threading
import time
from dataclasses import dataclass, field
from custom_logger import setup_logging


DEFAULT_PROFILE_PATH=Path(".llm_user_profile.json")
DEFAULT_PROFILE_GIST=Path("llm_user_profile_gist.json")
logger = setup_logging("UserProfileManager")
logger.setLevel(logging.WARNING)


# --- Helper classes ---------------------------------------------------------------
@dataclass
class ContextSnapshot:
    """State packaging for the profiling worker."""
    user_input: str
    assistant_response: str
    history: List[Any]
    timestamp: float = field(default_factory=time.time)
    event_type: str = "turn_complete"


from collections.abc import Mapping
from typing import Any


def profile_to_prompt(
    data: Any,
    *,
    indent: int = 0,
    omit_keys: set[str] | None = None,
) -> str:
    """Render structured profile data as compact, readable prompt text."""
    if omit_keys is None:
        omit_keys = {
            "id", "source", "confidence", "retention",
            "created_at", "updated_at",
        }

    lines: list[str] = []
    prefix = "  " * indent

    if isinstance(data, Mapping):
        for key, value in data.items():
            if key in omit_keys or value is None or value == "" or value == []:
                continue

            label = str(key).replace("_", " ").capitalize()

            if isinstance(value, (Mapping, list)):
                nested = profile_to_prompt(
                    value, indent=indent + 1, omit_keys=omit_keys
                )
                if nested:
                    lines.append(f"{prefix}{label}:")
                    lines.append(nested)
            else:
                lines.append(f"{prefix}{label}: {value}")

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (Mapping, list)):
                nested = profile_to_prompt(
                    item, indent=indent + 1, omit_keys=omit_keys
                )
                if nested:
                    lines.append(f"{prefix}- {nested.lstrip()}")
            else:
                lines.append(f"{prefix}- {item}")

    else:
        return f"{prefix}{data}"

    return "\n".join(lines)


def render_profile(profile: dict) -> str:
    """Render a complete user profile for system-prompt inclusion."""
    return profile_to_prompt(profile)


class UserProfileManager:
    """Thread-safe manager for user preferences and profile data."""

    def __init__(self, profile_path: Path = DEFAULT_PROFILE_PATH):
        self.gist_path = Path(DEFAULT_PROFILE_GIST)
        self.profile_path = Path(profile_path)
        #logger.set_log_path(str(self.profile_path.parent))
        self._lock = threading.RLock()
        with self._lock:
            self._profile_data: Dict[str, Any] = self._load_profile()
            self._gist_data: Dict[str, Any] = self._load_gist()

    def _load_gist(self) -> Dict[str, Any]:
        try:
            json_str = self._load_json(self.gist_path)
        except Exception as e:
            logging.error(f"Failed to load gist: {e}")
            return {}
        if json_str:
            return json_str
        else:
            logging.error("Gist file did not contain a JSON object; ignoring.")
        return {}

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
        return {}

    def _load_profile(self) -> Dict[str, Any]:
        try:
            json_str = self._load_json(self.profile_path)
        except Exception as e:
            logging.error(f"Failed to load profile: {e}")
            return {}
        if json_str:
            return json_str
        else:
            logging.error("Profile file did not contain a JSON object; ignoring.")
        return {}

    def save_gist(self) -> None:
        # backs up gist changes, too.
        logger.info("Saving gist", self.get_gist_json_string())
        with self._lock:
            try:
                self.gist_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.gist_path, "w", encoding="utf-8") as f:
                    json.dump(self._gist_data, f, indent=2)
            except Exception as e:
                logging.error(f"Error saving gist: {e}")

    def save_profile(self) -> None:
        # backs up profile changes, too.
        logger.info("Saving profile", self.get_profile_json_string())
        with self._lock:
            try:
                self.profile_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.profile_path, "w", encoding="utf-8") as f:
                    json.dump(self._profile_data, f, indent=2)
                with open(self.profile_path.with_suffix(".bak.json"), "w", encoding="utf-8") as f:
                    json.dump(self._profile_data, f, indent=2)
            except Exception as e:
                logging.error(f"Error saving profile: {e}")

    def _get_json_string(self, data: Dict[str, Any]) -> str:
        with self._lock:
            if not data:
                return ""
            return json.dumps(data, indent    =2)

    def get_gist_json_string(self) -> str:
        json_str = self._get_json_string(self._gist_data)
        if not json_str:
            return "No gist available."
        return json.dumps(self._profile_data, indent    =2)


    def get_profile_json_string(self) -> str:
        json_str = self._get_json_string(self._profile_data)
        if not json_str:
            return "No user profile available."
        return json.dumps(self._profile_data, indent    =2)

    def get_profile_string(self) -> str:
        with self._lock:
            if not self._profile_data:
                return "No user profile available."
            return render_profile(self._profile_data)

    def update_profile(self, updates: Dict[str, Any]) -> None:
        with self._lock:
            self._profile_data.update(updates)
            self.save_profile()

    def needs_consolidation(self) -> bool:
        with self._lock:
            return len(str(self.get_profile_string())) > 5000

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

if __name__ == "__main__":
    # test
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--profile_path", type=str, default=DEFAULT_PROFILE_PATH)
    args = parser.parse_args()

    profile_path = Path(args.profile_path)


    manager = UserProfileManager(profile_path=profile_path)
    print(manager.get_profile_string())
    print(len(str(manager.profile_data)))
    print(manager.needs_consolidation())
