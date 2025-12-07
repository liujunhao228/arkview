"""
Configuration service implementation for Arkview.
Handles application configuration management.
"""

import json
import os
from typing import Any, Dict
from pathlib import Path


class ConfigService:
    """Service for managing application configuration."""
    
    def __init__(self, config_file: str = None):
        self.config_file = config_file or self._get_default_config_path()
        self.settings = {}
        self._load_settings()
        
    def _get_default_config_path(self) -> str:
        """Get the default configuration file path."""
        # Try to get user config directory
        config_dir = Path.home() / ".config"
        if not config_dir.exists():
            config_dir = Path.home()
            
        return str(config_dir / "arkview" / "settings.json")
        
    def _load_settings(self):
        """Load settings from the configuration file."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.settings = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load settings from {self.config_file}: {e}")
            self.settings = {}
            
    def _save_settings(self):
        """Save settings to the configuration file."""
        try:
            # Create directory if it doesn't exist
            config_path = Path(self.config_file)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save settings to {self.config_file}: {e}")
            
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a configuration setting."""
        return self.settings.get(key, default)
        
    def set_setting(self, key: str, value: Any):
        """Set a configuration setting."""
        self.settings[key] = value
        
    def save_settings(self):
        """Save all settings to persistent storage."""
        self._save_settings()
        
    def get_all_settings(self) -> Dict[str, Any]:
        """Get all configuration settings."""
        return self.settings.copy()
        
    def update_settings(self, settings: Dict[str, Any]):
        """Update multiple settings at once."""
        self.settings.update(settings)