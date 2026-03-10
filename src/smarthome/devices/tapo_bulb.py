"""TAPO L530E smart bulb implementations (real + mock fallback)."""

import json
import logging
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from tapo import ApiClient
from tapo.requests import Color

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
        "set_color_temp": ["color_temp"],
        "set_color": ["color_name"],
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
            "hue": 0,
            "saturation": 0,
            "color_mode": "color_temp",
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

    def _get_status(self) -> Dict[str, Any]:
        return {
            "is_on": self.state["is_on"],
            "brightness": self.state["brightness"],
            "color_temp": self.state.get("color_temp", 0),
            "hue": self.state.get("hue", 0),
            "saturation": self.state.get("saturation", 0),
            "color_mode": self.state.get("color_mode", "color_temp"),
            "last_updated": self.state["last_updated"]
        }

    # BaseDevice interface implementation

    @property
    def device_type(self) -> str:
        return "bulb"

    @property
    def supported_actions(self) -> list[str]:
        return ["turn_on", "turn_off", "set_brightness", "set_color_temp", "set_color", "get_status"]

    async def execute(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if action not in self.supported_actions:
            return {
                "success": False,
                "message": f"Unknown action: {action}",
                "state": await self.get_shadow_state(),
            }

        if action == "turn_on":
            logger.info("Turning bulb ON (mock)")
            self.state["is_on"] = True
            self._save_state()
            return {"success": True, "message": "Bulb turned on", "state": self._get_status()}

        if action == "turn_off":
            logger.info("Turning bulb OFF (mock)")
            self.state["is_on"] = False
            self._save_state()
            return {"success": True, "message": "Bulb turned off", "state": self._get_status()}

        if action == "set_brightness":
            brightness = parameters.get("brightness")
            if brightness is None:
                return {
                    "success": False,
                    "message": "brightness parameter required",
                    "state": await self.get_shadow_state(),
                }
            brightness = int(brightness)
            if not 0 <= brightness <= 100:
                return {
                    "success": False,
                    "message": f"Brightness must be 0-100, got {brightness}",
                }
            logger.info(f"Setting brightness to {brightness} (mock)")
            self.state["brightness"] = brightness
            self._save_state()
            return {"success": True, "message": f"Brightness set to {brightness}", "state": self._get_status()}

        if action == "set_color_temp":
            color_temp = parameters.get("color_temp")
            if color_temp is None:
                return {
                    "success": False,
                    "message": "color_temp parameter required",
                    "state": await self.get_shadow_state(),
                }
            color_temp = int(color_temp)
            if not (2500 <= color_temp <= 6500):
                return {
                    "success": False,
                    "message": f"color_temp must be 2500-6500 K, got {color_temp}",
                }
            logger.info(f"Setting color temperature to {color_temp} K (mock)")
            self.state["color_temp"] = color_temp
            self.state["hue"] = 0
            self.state["saturation"] = 0
            self.state["color_mode"] = "color_temp"
            self._save_state()
            return {
                "success": True,
                "message": f"Color temperature set to {color_temp} K",
                "state": self._get_status(),
            }

        if action == "set_color":
            color_name = parameters.get("color_name")
            if not color_name:
                return {"success": False, "message": "color_name parameter required"}
            color_obj = getattr(Color, color_name, None)
            if color_obj is None:
                return {
                    "success": False,
                    "message": f"Unknown color: {color_name}. Valid names are in the Color enum (e.g. Lime, BlueViolet, Candlelight).",
                }
            hue, saturation, _ = color_obj.get_color_config()
            logger.info(f"Setting color to {color_name} (hue={hue}, sat={saturation}) (mock)")
            self.state["hue"] = hue
            self.state["saturation"] = saturation
            self.state["color_temp"] = 0
            self.state["color_mode"] = "color"
            self._save_state()
            return {
                "success": True,
                "message": f"Color set to {color_name}",
                "state": self._get_status(),
            }

        if action == "get_status":
            return {"success": True, "message": "Status retrieved", "state": self._get_status()}

    async def apply_desired_state(self, desired: Dict[str, Any]) -> None:
        if "is_on" in desired:
            await self.execute("turn_on" if desired["is_on"] else "turn_off", {})
        if "brightness" in desired:
            await self.execute("set_brightness", {"brightness": int(desired["brightness"])})

    async def get_shadow_state(self) -> Dict[str, Any]:
        return {
            "is_on": self.state["is_on"],
            "brightness": self.state["brightness"],
            "color_temp": self.state.get("color_temp", 0),
            "hue": self.state.get("hue", 0),
            "saturation": self.state.get("saturation", 0),
            "color_mode": self.state.get("color_mode", "color_temp"),
        }


class TapoBulb(BaseDevice):
    """Real Tapo L530E control via the tapo library."""

    ACTION_PARAMS = {
        "turn_on": [],
        "turn_off": [],
        "set_brightness": ["brightness"],
        "set_color_temp": ["color_temp"],
        "set_color": ["color_name"],
        "get_status": [],
    }

    def __init__(self, device, username: str, password: str, ip_address: str):
        self._device = device
        self._username = username
        self._password = password
        self._ip_address = ip_address

    @classmethod
    async def connect(cls, username: str, password: str, ip_address: str) -> "TapoBulb":
        client = ApiClient(username, password)
        device = await client.l530(ip_address)
        return cls(device, username, password, ip_address)

    async def _reconnect(self) -> None:
        logger.warning("TapoBulb session expired — reconnecting to %s", self._ip_address)
        client = ApiClient(self._username, self._password)
        self._device = await client.l530(self._ip_address)
        logger.info("TapoBulb reconnected successfully")

    async def _get_status(self) -> Dict[str, Any]:
        info = await self._device.get_device_info()
        hue = getattr(info, "hue", 0) or 0
        saturation = getattr(info, "saturation", 0) or 0
        color_temp = info.color_temp or 0
        color_mode = "color" if hue != 0 or saturation != 0 else "color_temp"
        return {
            "is_on": info.device_on,
            "brightness": info.brightness,
            "color_temp": color_temp,
            "hue": hue,
            "saturation": saturation,
            "color_mode": color_mode,
            "last_updated": datetime.now().isoformat()
        }

    # BaseDevice interface implementation

    @property
    def device_type(self) -> str:
        return "bulb"

    @property
    def supported_actions(self) -> list[str]:
        return ["turn_on", "turn_off", "set_brightness", "set_color_temp", "set_color", "get_status"]

    async def execute(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await self._execute_once(action, parameters)
        except Exception as e:
            if "SessionTimeout" in str(e):
                await self._reconnect()
                return await self._execute_once(action, parameters)
            raise

    async def _execute_once(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if action not in self.supported_actions:
            return {
                "success": False,
                "message": f"Unknown action: {action}",
                "state": await self.get_shadow_state(),
            }

        if action == "turn_on":
            logger.info("Turning bulb ON (real)")
            await self._device.on()
            return {"success": True, "message": "Bulb turned on", "state": await self._get_status()}

        if action == "turn_off":
            logger.info("Turning bulb OFF (real)")
            await self._device.off()
            return {"success": True, "message": "Bulb turned off", "state": await self._get_status()}

        if action == "set_brightness":
            brightness = parameters.get("brightness")
            if brightness is None:
                return {
                    "success": False,
                    "message": "brightness parameter required",
                    "state": await self.get_shadow_state(),
                }
            brightness = int(brightness)
            if not 0 <= brightness <= 100:
                return {
                    "success": False,
                    "message": f"Brightness must be 0-100, got {brightness}",
                }
            logger.info(f"Setting brightness to {brightness} (real)")
            await self._device.set_brightness(brightness)
            return {"success": True, "message": f"Brightness set to {brightness}", "state": await self._get_status()}

        if action == "set_color_temp":
            color_temp = parameters.get("color_temp")
            if color_temp is None:
                return {
                    "success": False,
                    "message": "color_temp parameter required",
                    "state": await self.get_shadow_state(),
                }
            color_temp = int(color_temp)
            if not (2500 <= color_temp <= 6500):
                return {
                    "success": False,
                    "message": f"color_temp must be 2500-6500 K, got {color_temp}",
                }
            logger.info(f"Setting color temperature to {color_temp} K (real)")
            try:
                await self._device.set_color_temperature(color_temp)
            except AttributeError:
                return {
                    "success": False,
                    "message": "set_color_temperature not available on this device",
                }
            return {
                "success": True,
                "message": f"Color temperature set to {color_temp} K",
                "state": await self._get_status(),
            }

        if action == "set_color":
            color_name = parameters.get("color_name")
            if not color_name:
                return {"success": False, "message": "color_name parameter required"}
            color_obj = getattr(Color, color_name, None)
            if color_obj is None:
                return {
                    "success": False,
                    "message": f"Unknown color: {color_name}. Valid names are in the Color enum (e.g. Lime, BlueViolet, Candlelight).",
                }
            logger.info(f"Setting color to {color_name} (real)")
            await self._device.set_color(color_obj)
            return {
                "success": True,
                "message": f"Color set to {color_name}",
                "state": await self._get_status(),
            }

        if action == "get_status":
            return {"success": True, "message": "Status retrieved", "state": await self._get_status()}

    async def apply_desired_state(self, desired: Dict[str, Any]) -> None:
        if "is_on" in desired:
            await self.execute("turn_on" if desired["is_on"] else "turn_off", {})
        if "brightness" in desired:
            await self.execute("set_brightness", {"brightness": int(desired["brightness"])})

    async def get_shadow_state(self) -> Dict[str, Any]:
        status = await self._get_status()
        return {
            "is_on": status["is_on"],
            "brightness": status["brightness"],
            "color_temp": status["color_temp"],
            "hue": status["hue"],
            "saturation": status["saturation"],
            "color_mode": status["color_mode"],
        }
