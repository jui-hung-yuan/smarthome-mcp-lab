"""Mock TAPO L530E smart bulb for testing and development."""

import json
import logging
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class TapoBulb:
    """Mock implementation of TAPO L530E smart bulb.
    
    This simulates a real TAPO bulb's behavior for development and testing.
    State is persisted to a JSON file so it survives server restarts.
    """
    
    def __init__(self, state_file: Path):
        """Initialize the mock bulb.
        
        Args:
            state_file: Path to JSON file for persisting bulb state
        """
        self.state_file = state_file
        self.state = self._load_state()
        logger.info(f"TapoBulb initialized. Current state: {self.state}")
    
    def _load_state(self) -> Dict[str, Any]:
        """Load bulb state from JSON file or create default state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    logger.info(f"Loaded state from {self.state_file}")
                    return state
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load state file: {e}. Using default state.")
        
        # Default state
        return {
            "is_on": False,
            "brightness": 100,  # 0-100
            "color_temp": 2700,  # Kelvin (will add RGB later)
            "last_updated": datetime.now().isoformat()
        }
    
    def _save_state(self) -> None:
        """Persist current state to JSON file."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state["last_updated"] = datetime.now().isoformat()
            
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            
            logger.debug(f"State saved to {self.state_file}")
        except IOError as e:
            logger.error(f"Failed to save state: {e}")
    
    def turn_on(self) -> Dict[str, Any]:
        """Turn the bulb on.
        
        Returns:
            Dict with operation result and current state
        """
        logger.info("Turning bulb ON")
        self.state["is_on"] = True
        self._save_state()
        
        return {
            "success": True,
            "message": "Bulb turned on",
            "state": self.get_status()
        }
    
    def turn_off(self) -> Dict[str, Any]:
        """Turn the bulb off.
        
        Returns:
            Dict with operation result and current state
        """
        logger.info("Turning bulb OFF")
        self.state["is_on"] = False
        self._save_state()
        
        return {
            "success": True,
            "message": "Bulb turned off",
            "state": self.get_status()
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get current bulb status.
        
        Returns:
            Dict with current bulb state
        """
        return {
            "is_on": self.state["is_on"],
            "brightness": self.state["brightness"],
            "color_temp": self.state["color_temp"],
            "last_updated": self.state["last_updated"]
        }
    
    def set_brightness(self, brightness: int) -> Dict[str, Any]:
        """Set bulb brightness (for future use).
        
        Args:
            brightness: Brightness level 0-100
            
        Returns:
            Dict with operation result and current state
        """
        if not 0 <= brightness <= 100:
            return {
                "success": False,
                "message": f"Brightness must be 0-100, got {brightness}"
            }
        
        logger.info(f"Setting brightness to {brightness}")
        self.state["brightness"] = brightness
        self._save_state()
        
        return {
            "success": True,
            "message": f"Brightness set to {brightness}",
            "state": self.get_status()
        }