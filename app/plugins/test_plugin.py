from typing import Dict, Any
from .base import MetadataPlugin

class TestPlugin(MetadataPlugin):
    id = "test_plugin"
    name = "Debug / Test Plugin"
    
    # NEW: Define fields so the Settings UI generates input boxes
    config_fields = [
        {"key": "test_username", "label": "Test Username"},
        {"key": "test_api_key", "label": "Dummy API Key"}
    ]

    def scrape(self, url: str, config: Dict[str, str]) -> Dict[str, Any]:
        """
        Returns hardcoded data, but injects the config values into the 
        description/tags so you can verify they were saved correctly.
        """
        # Retrieve values from the config dictionary (loaded from DB)
        user = config.get("test_username", "Guest")
        key = config.get("test_api_key", "No Key Found")
        
        return {
            "title": "Test Title",
            "artist": "Test Artist",
            # We add the username to tags to prove it worked
            "tags": ["Test Tag", "Debug Mode", f"User: {user}"], 
            "description": f"This is a test scrape.\nURL: {url}\nAPI Key used: {key}"
        }