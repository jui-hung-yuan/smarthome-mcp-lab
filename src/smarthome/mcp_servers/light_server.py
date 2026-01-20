"""MCP server for controlling TAPO smart light bulb."""

import logging
from pathlib import Path
from fastmcp import FastMCP

from smarthome.devices import TapoBulb

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
app = FastMCP("TAPO Light Control")

# Path for bulb state persistence
STATE_FILE = Path.home() / ".smarthome" / "tapo_bulb_state.json"

# Initialize the mock bulb
bulb = TapoBulb(state_file=STATE_FILE)

logger.info(f"MCP Server initialized. State file: {STATE_FILE}")


@app.tool()
def turn_on() -> str:
    """Turn on the TAPO smart light bulb.
    
    Returns:
        A message confirming the bulb was turned on
    """
    logger.info("Tool called: turn_on")
    result = bulb.turn_on()
    
    if result["success"]:
        return f"✓ {result['message']}. Current state: {'ON' if result['state']['is_on'] else 'OFF'}"
    else:
        return f"✗ Failed to turn on bulb"


@app.tool()
def turn_off() -> str:
    """Turn off the TAPO smart light bulb.
    
    Returns:
        A message confirming the bulb was turned off
    """
    logger.info("Tool called: turn_off")
    result = bulb.turn_off()
    
    if result["success"]:
        return f"✓ {result['message']}. Current state: {'ON' if result['state']['is_on'] else 'OFF'}"
    else:
        return f"✗ Failed to turn off bulb"


@app.tool()
def get_status() -> str:
    """Get the current status of the TAPO smart light bulb.
    
    Returns:
        Current bulb status including on/off state, brightness, and color temperature
    """
    logger.info("Tool called: get_status")
    status = bulb.get_status()
    
    state_emoji = "💡" if status["is_on"] else "⚫"
    state_text = "ON" if status["is_on"] else "OFF"
    
    return (
        f"{state_emoji} Bulb is {state_text}\n"
        f"Brightness: {status['brightness']}%\n"
        f"Color Temperature: {status['color_temp']}K\n"
        f"Last Updated: {status['last_updated']}"
    )


if __name__ == "__main__":
    # This allows running the server directly for testing
    app.run()