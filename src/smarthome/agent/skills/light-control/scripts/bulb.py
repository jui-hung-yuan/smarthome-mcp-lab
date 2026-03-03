"""Light control skill — wraps smarthome.devices.TapoBulb / MockTapoBulb.

Exposes:
    execute(action: str, params: dict) -> dict
    configure(mock: bool, config: AgentConfig)  # optional, called by SkillLoader
"""

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path.home() / ".smarthome" / ".env")

logger = logging.getLogger(__name__)

# Module-level device instance (initialized on first execute or configure call)
_device = None
_mock: bool = False
_mock_state_file: Path = Path.home() / ".smarthome" / "tapo_bulb_state.json"


def configure(mock: bool = False, config: Any = None, **kwargs: Any) -> None:
    """Called by SkillLoader to inject runtime config before first use."""
    global _mock, _mock_state_file, _device
    _mock = mock
    if config is not None and hasattr(config, "mock_state_file"):
        _mock_state_file = config.mock_state_file
    # Reset device so it is re-created with new config
    _device = None


async def _get_device():
    """Lazy-init the bulb (real or mock)."""
    global _device

    if _device is not None:
        return _device

    if _mock:
        from smarthome.devices.tapo_bulb import MockTapoBulb
        _mock_state_file.parent.mkdir(parents=True, exist_ok=True)
        _device = MockTapoBulb(state_file=_mock_state_file)
        logger.info("Light-control skill using MockTapoBulb (state: %s)", _mock_state_file)
    else:
        tapo_user = os.environ.get("TAPO_USERNAME")
        tapo_pass = os.environ.get("TAPO_PASSWORD")
        tapo_ip = os.environ.get("TAPO_IP_ADDRESS")
        if not (tapo_user and tapo_pass and tapo_ip):
            raise RuntimeError(
                "Real bulb requires TAPO_USERNAME, TAPO_PASSWORD, and TAPO_IP_ADDRESS. "
                "Add them to ~/.smarthome/.env or run with --mock for testing."
            )
        from smarthome.devices.tapo_bulb import TapoBulb
        _device = await TapoBulb.connect(tapo_user, tapo_pass, tapo_ip)
        logger.info("Light-control skill connected to real TapoBulb at %s", tapo_ip)

    return _device


async def execute(action: str, params: dict) -> dict:
    """Execute a light-control action.

    Supported actions: turn_on, turn_off, set_brightness, set_color_temp, get_status
    """
    try:
        device = await _get_device()
    except RuntimeError as e:
        return {"success": False, "message": str(e)}

    # set_color_temp is handled here since MockTapoBulb doesn't expose it separately
    if action == "set_color_temp":
        color_temp = params.get("color_temp")
        if color_temp is None:
            return {"success": False, "message": "color_temp parameter required"}
        color_temp = int(color_temp)
        if not (2500 <= color_temp <= 6500):
            return {
                "success": False,
                "message": f"color_temp must be 2500-6500 K, got {color_temp}",
            }
        # MockTapoBulb: update state directly; TapoBulb: use device API if available
        if hasattr(device, "state"):
            device.state["color_temp"] = color_temp
            device._save_state()  # noqa: SLF001
            return {
                "success": True,
                "message": f"Color temperature set to {color_temp} K",
                "state": await device.get_status(),
            }
        elif hasattr(device, "_device"):
            # Real TapoBulb — try set_color_temperature if available
            try:
                await device._device.set_color_temperature(color_temp)  # noqa: SLF001
                return {
                    "success": True,
                    "message": f"Color temperature set to {color_temp} K",
                    "state": await device.get_status(),
                }
            except AttributeError:
                return {
                    "success": False,
                    "message": "set_color_temperature not available on this device",
                }
        return {"success": False, "message": "Cannot set color temperature on this device"}

    # Delegate all other actions to the BaseDevice.execute() interface
    return await device.execute(action, params)
