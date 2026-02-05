"""Entry point to start the IoT Bridge.

Usage:
    uv run python scripts/run_bridge.py           # Use real bulb if credentials available
    uv run python scripts/run_bridge.py --mock    # Force mock bulb mode

The bridge connects to AWS IoT Core and waits for commands on:
    smarthome/{device_id}/commands/{action}

Responds on:
    smarthome/{device_id}/responses/{request_id}
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from smarthome.bridge.config import load_config
from smarthome.bridge.device_registry import DeviceRegistry
from smarthome.bridge.iot_bridge import IoTBridge
from smarthome.devices.tapo_bulb import MockTapoBulb, TapoBulb

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# State file for mock bulb
SMARTHOME_DIR = Path.home() / ".smarthome"
STATE_FILE = SMARTHOME_DIR / "tapo_bulb_state.json"
ENV_FILE = SMARTHOME_DIR / ".env"


async def create_bulb(force_mock: bool) -> MockTapoBulb | TapoBulb:
    """Create bulb instance (real or mock based on credentials and flag)."""
    if force_mock:
        logger.info("Using mock bulb (--mock flag)")
        return MockTapoBulb(STATE_FILE)

    # Try to load credentials
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)

    username = os.environ.get("TAPO_USERNAME")
    password = os.environ.get("TAPO_PASSWORD")
    ip_address = os.environ.get("TAPO_IP_ADDRESS")

    if username and password and ip_address:
        try:
            logger.info(f"Connecting to real Tapo bulb at {ip_address}...")
            bulb = await TapoBulb.connect(username, password, ip_address)
            logger.info("Connected to real Tapo bulb")
            return bulb
        except Exception as e:
            logger.warning(f"Failed to connect to real bulb: {e}")
            logger.info("Falling back to mock bulb")

    logger.info("Using mock bulb (no credentials or connection failed)")
    return MockTapoBulb(STATE_FILE)


async def main(args: argparse.Namespace) -> int:
    """Main entry point."""
    # Load IoT configuration
    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    # Validate certificates exist
    try:
        config.validate()
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    # Create bulb and register it
    bulb = await create_bulb(args.mock)

    # Create registry and register the device
    registry = DeviceRegistry()
    registry.register(config.device_id, bulb)

    # Create and start bridge with registry
    bridge = IoTBridge(config, registry)

    # Set up graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    # Start bridge
    logger.info("Starting IoT Bridge...")
    if not await bridge.start():
        logger.error("Failed to start bridge")
        return 1

    logger.info(f"Bridge running. Device ID: {config.device_id}")
    logger.info(f"Listening on: smarthome/{config.device_id}/commands/+")
    logger.info("Press Ctrl+C to stop")

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Clean shutdown
    logger.info("Stopping bridge...")
    await bridge.stop()
    logger.info("Bridge stopped")

    return 0


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Start the IoT Bridge for smart home control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force mock bulb mode (ignore real credentials)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to IoT config file (default: ~/.smarthome/iot/config.json)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    sys.exit(asyncio.run(main(args)))
