import unittest
import json
from pathlib import Path
from user_profile_manager import UserProfileManager

class TestUserProfileManager(unittest.TestCase):
    def setUp(self):
        self.test_profile_path = Path("test_profile.json")
        self.manager = UserProfileManager(profile_path=self.test_profile_path)

    def tearDown(self):
        if self.test_profile_path.exists():
            self.test_profile_path.unlink()

    def test_initialization(self):
        self.assertEqual(self.manager.profile_data, {})
        self.assertEqual(self.manager.get_profile_string(), "No user profile available.")

    def test_update_profile(self):
        self.manager.update_profile({"name": "Alice", "pref": "dark mode"})
        self.assertEqual(self.manager.profile_data["name"], "Alice")
        self.assertEqual(self.manager.profile_data["pref"], "dark mode")
        
        with open(self.test_profile_path, "r") as f:
            data = json.load(f)
            self.assertEqual(data["name"], "Alice")

    def test_set_profile_data(self):
        self.manager.set_profile_data({"hobby": "coding"})
        self.assertEqual(self.manager.profile_data["hobby"], "coding")
        
        with open(self.test_profile_path, "r") as f:
            data = json.load(f)
            self.assertEqual(data["hobby"], "coding")

    def test_load_existing_profile(self):
        with open(self.test_profile_path, "w") as f:
            json.dump({"city": "New York"}, f)
        
        new_manager = UserProfileManager(profile_path=self.test_profile_path)
        self.assertEqual(new_manager.profile_data["city"], "New York")

if __name__ == "__main__":
    unittest.main()
