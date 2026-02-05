"""Base device interface for smart home devices."""

from abc import ABC, abstractmethod
from typing import Any


class BaseDevice(ABC):
    """Abstract base class for all smart home devices.

    All devices must implement this interface to work with the IoT Bridge.
    This allows the bridge to be device-agnostic and support multiple device types.
    """

    @property
    @abstractmethod
    def device_type(self) -> str:
        """Return device type identifier (e.g., 'bulb', 'plug', 'thermostat')."""
        pass

    @property
    @abstractmethod
    def supported_actions(self) -> list[str]:
        """Return list of action names this device supports."""
        pass

    @abstractmethod
    async def execute(self, action: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Execute an action on the device.

        Args:
            action: The action name (e.g., 'turn_on', 'set_brightness')
            parameters: Action parameters as a dictionary

        Returns:
            dict with keys:
                - success: bool indicating if action succeeded
                - message: str describing the result
                - state: dict with current device state after action
        """
        pass

    @abstractmethod
    async def apply_desired_state(self, desired: dict[str, Any]) -> None:
        """Apply desired state from shadow delta.

        Each device knows its own state fields and how to apply them.

        Args:
            desired: Dictionary of desired state fields to apply
        """
        pass

    @abstractmethod
    async def get_shadow_state(self) -> dict[str, Any]:
        """Get current state for shadow reporting.

        Returns:
            dict with device-specific state fields for AWS IoT Shadow
        """
        pass
