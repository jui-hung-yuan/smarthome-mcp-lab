"""IoT Bridge module for AWS IoT Core integration."""

from smarthome.devices.device_registry import DeviceRegistry
from smarthome.aws_mcp.bridge.iot_bridge import IoTBridge
from smarthome.aws_mcp.bridge.shadow_manager import ShadowManager
from smarthome.aws_mcp.bridge.config import IoTConfig, load_config

__all__ = ["DeviceRegistry", "IoTBridge", "ShadowManager", "IoTConfig", "load_config"]
