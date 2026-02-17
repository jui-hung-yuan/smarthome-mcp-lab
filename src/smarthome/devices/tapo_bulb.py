"""TAPO L530E smart bulb implementations (real + mock fallback)."""

import json
import logging
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from tapo import ApiClient

from smarthome.devices.base import BaseDevice

logger = logging.getLogger(__name__)


class MockTapoBulb(BaseDevice):
    """Mock implementation of TAPO L530E smart bulb.

    Simulates a real TAPO bulb for development and testing.
    State is persisted to a JSON file so it survives server restarts.
    """

    ACTION_PARAMS = {
        "turn_on": [],
        "turn_off": [],
        "set_brightness": ["brightness"],
        "get_status": [],
    }

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state = self._load_state()
        logger.info(f"MockTapoBulb initialized. Current state: {self.state}")

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    logger.info(f"Loaded state from {self.state_file}")
                    return state
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load state file: {e}. Using default state.")

        return {
            "is_on": False,
            "brightness": 100,
            "color_temp": 2700,
            "last_updated": datetime.now().isoformat()
        }

    def _save_state(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state["last_updated"] = datetime.now().isoformat()
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            logger.debug(f"State saved to {self.state_file}")
        except IOError as e:
            logger.error(f"Failed to save state: {e}")

    async def turn_on(self) -> Dict[str, Any]:
        logger.info("Turning bulb ON (mock)")
        self.state["is_on"] = True
        self._save_state()
        return {
            "success": True,
            "message": "Bulb turned on",
            "state": await self.get_status()
        }

    async def turn_off(self) -> Dict[str, Any]:
        logger.info("Turning bulb OFF (mock)")
        self.state["is_on"] = False
        self._save_state()
        return {
            "success": True,
            "message": "Bulb turned off",
            "state": await self.get_status()
        }

    async def get_status(self) -> Dict[str, Any]:
        return {
            "is_on": self.state["is_on"],
            "brightness": self.state["brightness"],
            "color_temp": self.state["color_temp"],
            "last_updated": self.state["last_updated"]
        }

    async def set_brightness(self, brightness: int) -> Dict[str, Any]:
        if not 0 <= brightness <= 100:
            return {
                "success": False,
                "message": f"Brightness must be 0-100, got {brightness}"
            }
        logger.info(f"Setting brightness to {brightness} (mock)")
        self.state["brightness"] = brightness
        self._save_state()
        return {
            "success": True,
            "message": f"Brightness set to {brightness}",
            "state": await self.get_status()
        }

    # BaseDevice interface implementation

    @property
    def device_type(self) -> str:
        return "bulb"

    @property
    def supported_actions(self) -> list[str]:
        return ["turn_on", "turn_off", "set_brightness", "get_status"]

    async def execute(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if action not in self.supported_actions:
            return {
                "success": False,
                "message": f"Unknown action: {action}",
                "state": await self.get_shadow_state(),
            }

        if action == "turn_on":
            return await self.turn_on()
        elif action == "turn_off":
            return await self.turn_off()
        elif action == "set_brightness":
            brightness = parameters.get("brightness")
            if brightness is None:
                return {
                    "success": False,
                    "message": "brightness parameter required",
                    "state": await self.get_shadow_state(),
                }
            return await self.set_brightness(int(brightness))
        elif action == "get_status":
            return {
                "success": True,
                "message": "Status retrieved",
                "state": await self.get_status(),
            }

    async def apply_desired_state(self, desired: Dict[str, Any]) -> None:
        if "is_on" in desired:
            if desired["is_on"]:
                await self.turn_on()
            else:
                await self.turn_off()
        if "brightness" in desired:
            await self.set_brightness(int(desired["brightness"]))

    async def get_shadow_state(self) -> Dict[str, Any]:
        return {
            "is_on": self.state["is_on"],
            "brightness": self.state["brightness"],
            "color_temp": self.state["color_temp"],
        }


class TapoBulb(BaseDevice):
    """Real Tapo L530E control via the tapo library."""

    ACTION_PARAMS = {
        "turn_on": [],
        "turn_off": [],
        "set_brightness": ["brightness"],
        "get_status": [],
    }

    def __init__(self, device):
        self._device = device

    @classmethod
    async def connect(cls, username: str, password: str, ip_address: str) -> "TapoBulb":
        client = ApiClient(username, password)
        device = await client.l530(ip_address)
        return cls(device)

    async def turn_on(self) -> Dict[str, Any]:
        logger.info("Turning bulb ON (real)")
        await self._device.on()
        return {
            "success": True,
            "message": "Bulb turned on",
            "state": await self.get_status()
        }

    async def turn_off(self) -> Dict[str, Any]:
        logger.info("Turning bulb OFF (real)")
        await self._device.off()
        return {
            "success": True,
            "message": "Bulb turned off",
            "state": await self.get_status()
        }

    async def get_status(self) -> Dict[str, Any]:
        info = await self._device.get_device_info()
        return {
            "is_on": info.device_on,
            "brightness": info.brightness,
            "color_temp": info.color_temp,
            "last_updated": datetime.now().isoformat()
        }

    async def set_brightness(self, brightness: int) -> Dict[str, Any]:
        if not 0 <= brightness <= 100:
            return {
                "success": False,
                "message": f"Brightness must be 0-100, got {brightness}"
            }
        logger.info(f"Setting brightness to {brightness} (real)")
        await self._device.set_brightness(brightness)
        return {
            "success": True,
            "message": f"Brightness set to {brightness}",
            "state": await self.get_status()
        }

    # BaseDevice interface implementation

    @property
    def device_type(self) -> str:
        return "bulb"

    @property
    def supported_actions(self) -> list[str]:
        return ["turn_on", "turn_off", "set_brightness", "get_status"]

    async def execute(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if action not in self.supported_actions:
            return {
                "success": False,
                "message": f"Unknown action: {action}",
                "state": await self.get_shadow_state(),
            }

        if action == "turn_on":
            return await self.turn_on()
        elif action == "turn_off":
            return await self.turn_off()
        elif action == "set_brightness":
            brightness = parameters.get("brightness")
            if brightness is None:
                return {
                    "success": False,
                    "message": "brightness parameter required",
                    "state": await self.get_shadow_state(),
                }
            return await self.set_brightness(int(brightness))
        elif action == "get_status":
            return {
                "success": True,
                "message": "Status retrieved",
                "state": await self.get_status(),
            }

    async def apply_desired_state(self, desired: Dict[str, Any]) -> None:
        if "is_on" in desired:
            if desired["is_on"]:
                await self.turn_on()
            else:
                await self.turn_off()
        if "brightness" in desired:
            await self.set_brightness(int(desired["brightness"]))

    async def get_shadow_state(self) -> Dict[str, Any]:
        status = await self.get_status()
        return {
            "is_on": status["is_on"],
            "brightness": status["brightness"],
            "color_temp": status["color_temp"],
        }
