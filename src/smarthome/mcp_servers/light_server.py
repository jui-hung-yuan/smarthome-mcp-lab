"""MCP server for controlling TAPO smart light bulb."""

import logging
from pathlib import Path
from fastmcp import FastMCP
from dotenv import dotenv_values

from smarthome.devices import TapoBulb, MockTapoBulb
from smarthome.logging import DynamoStateLogger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
app = FastMCP("TAPO Light Control")

# Paths
STATE_FILE = Path.home() / ".smarthome" / "tapo_bulb_state.json"
ENV_FILE = Path.home() / ".smarthome" / ".env"

# Lazily initialized bulb instance
bulb = None

# State logger (fire-and-forget)
state_logger = DynamoStateLogger()
DEVICE_ID = "tapo-bulb-default"


async def get_bulb():
    """Get or initialize the bulb instance.

    Tries to connect to a real Tapo bulb using credentials from ~/.smarthome/.env.
    Falls back to MockTapoBulb if credentials are missing or connection fails.
    """
    global bulb
    if bulb is not None:
        return bulb

    config = dotenv_values(ENV_FILE)
    required_keys = ("TAPO_USERNAME", "TAPO_PASSWORD", "TAPO_IP_ADDRESS")

    if all(k in config for k in required_keys):
        try:
            bulb = await TapoBulb.connect(
                config["TAPO_USERNAME"],
                config["TAPO_PASSWORD"],
                config["TAPO_IP_ADDRESS"],
            )
            logger.info("Connected to real Tapo bulb at %s", config["TAPO_IP_ADDRESS"])
            return bulb
        except Exception as e:
            logger.warning("Failed to connect to real bulb: %s. Falling back to mock.", e)

    bulb = MockTapoBulb(state_file=STATE_FILE)
    logger.info("Using mock bulb (no .env or connection failed)")
    return bulb


@app.tool()
async def turn_on() -> str:
    """Turn on the TAPO smart light bulb.

    Returns:
        A message confirming the bulb was turned on
    """
    logger.info("Tool called: turn_on")
    b = await get_bulb()
    result = await b.turn_on()
    if not isinstance(b, MockTapoBulb):
        await state_logger.log_state_change(DEVICE_ID, "turn_on", result)

    if result["success"]:
        return f"✓ {result['message']}. Current state: {'ON' if result['state']['is_on'] else 'OFF'}"
    else:
        return "✗ Failed to turn on bulb"


@app.tool()
async def turn_off() -> str:
    """Turn off the TAPO smart light bulb.

    Returns:
        A message confirming the bulb was turned off
    """
    logger.info("Tool called: turn_off")
    b = await get_bulb()
    result = await b.turn_off()
    if not isinstance(b, MockTapoBulb):
        await state_logger.log_state_change(DEVICE_ID, "turn_off", result)

    if result["success"]:
        return f"✓ {result['message']}. Current state: {'ON' if result['state']['is_on'] else 'OFF'}"
    else:
        return "✗ Failed to turn off bulb"


@app.tool()
async def get_status() -> str:
    """Get the current status of the TAPO smart light bulb.

    Returns:
        Current bulb status including on/off state, brightness, and color temperature
    """
    logger.info("Tool called: get_status")
    b = await get_bulb()
    status = await b.get_status()

    state_emoji = "💡" if status["is_on"] else "⚫"
    state_text = "ON" if status["is_on"] else "OFF"
    mode = "mock" if isinstance(b, MockTapoBulb) else "real"

    return (
        f"{state_emoji} Bulb is {state_text}\n"
        f"Mode: {mode}\n"
        f"Brightness: {status['brightness']}%\n"
        f"Color Temperature: {status['color_temp']}K\n"
        f"Last Updated: {status['last_updated']}"
    )


@app.tool()
async def set_brightness(level: int) -> str:
    """Set the brightness level of the TAPO smart light bulb.

    Args:
        level: Brightness level from 0 to 100

    Returns:
        A message confirming the brightness was set
    """
    logger.info("Tool called: set_brightness(%d)", level)
    b = await get_bulb()
    result = await b.set_brightness(level)
    if not isinstance(b, MockTapoBulb):
        await state_logger.log_state_change(DEVICE_ID, "set_brightness", result)

    if result["success"]:
        return f"✓ {result['message']}. Current state: brightness={result['state']['brightness']}%"
    else:
        return f"✗ {result['message']}"


if __name__ == "__main__":
    app.run()
