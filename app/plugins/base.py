from typing import List, Dict, Any

class MetadataPlugin:
    """
    The Template that all plugins must inherit from.
    This enforces the standard data format we agreed upon.
    """
    # Unique ID for the system (e.g., 'fakku', 'mangaupdates')
    id: str = "base"
    
    # Human-readable name for the UI (e.g., 'Fakku Scraper')
    name: str = "Base Plugin"
    
    # Define what settings this plugin needs from the user in the Settings page.
    # Format: [{"key": "cookie", "label": "Session Cookie"}, {"key": "user", "label": "Username"}]
    config_fields: List[Dict[str, str]] = []

    def scrape(self, url: str, config: Dict[str, str]) -> Dict[str, Any]:
        """
        The main function that runs when you click "Fetch".
        
        Inputs:
            url (str): The URL entered in the Import page.
            config (dict): The saved settings (cookies/keys) from the database.
            
        Returns:
            A dictionary matching this EXACT structure:
            {
                "title": str,
                "artist": str,
                "tags": List[str],
                "description": str
            }
        """
        raise NotImplementedError("Plugin must implement the scrape method")