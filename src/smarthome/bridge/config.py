"""Configuration loader for IoT Bridge."""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "~/.smarthome/iot/config.json"
DEFAULT_THING_NAME = "tapo-bulb-default"


@dataclass
class IoTConfig:
    """IoT Core connection configuration."""

    endpoint: str
    thing_name: str
    cert_path: Path
    key_path: Path
    root_ca_path: Path
    device_id: str

    def validate(self) -> None:
        """Validate that all certificate files exist."""
        for path, name in [
            (self.cert_path, "certificate"),
            (self.key_path, "private key"),
            (self.root_ca_path, "root CA"),
        ]:
            if not path.exists():
                raise FileNotFoundError(f"{name} not found at {path}")


def load_config(config_path: Optional[str] = None) -> IoTConfig:
    """Load IoT configuration from file with environment variable overrides.

    Environment variables:
        IOT_ENDPOINT: Override AWS IoT Core endpoint
        IOT_THING_NAME: Override IoT Thing name
        IOT_CONFIG_PATH: Override config file location

    Args:
        config_path: Path to config JSON file. Defaults to ~/.smarthome/iot/config.json

    Returns:
        IoTConfig with validated paths
    """
    # Determine config file path
    path_str = config_path or os.environ.get("IOT_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    config_file = Path(path_str).expanduser()

    if not config_file.exists():
        raise FileNotFoundError(
            f"IoT config not found at {config_file}. "
            f"Run 'uv run python scripts/create_iot_thing.py' to provision."
        )

    with open(config_file) as f:
        data = json.load(f)

    # Apply environment variable overrides
    endpoint = os.environ.get("IOT_ENDPOINT", data.get("endpoint", ""))
    thing_name = os.environ.get("IOT_THING_NAME", data.get("thing_name", DEFAULT_THING_NAME))
    device_id = data.get("device_id", thing_name)

    # Expand paths relative to config file directory
    config_dir = config_file.parent
    cert_dir = config_dir / thing_name

    cert_path = Path(data.get("cert_path", cert_dir / "certificate.pem")).expanduser()
    key_path = Path(data.get("key_path", cert_dir / "private.key")).expanduser()
    root_ca_path = Path(data.get("root_ca_path", cert_dir / "AmazonRootCA1.pem")).expanduser()

    config = IoTConfig(
        endpoint=endpoint,
        thing_name=thing_name,
        cert_path=cert_path,
        key_path=key_path,
        root_ca_path=root_ca_path,
        device_id=device_id,
    )

    logger.info(f"Loaded IoT config: endpoint={endpoint}, thing={thing_name}")
    return config
