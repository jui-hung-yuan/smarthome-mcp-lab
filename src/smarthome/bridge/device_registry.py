"""Device registry for managing multiple smart home devices."""

from typing import Optional

from smarthome.devices.base import BaseDevice


class DeviceRegistry:
    """Registry for managing multiple devices by ID.

    Allows the IoT Bridge to manage multiple devices with a single MQTT connection.
    """

    def __init__(self):
        self._devices: dict[str, BaseDevice] = {}

    def register(self, device_id: str, device: BaseDevice) -> None:
        """Register a device with the given ID.

        Args:
            device_id: Unique identifier for the device
            device: Device instance implementing BaseDevice

        Raises:
            ValueError: If a device with the same ID is already registered
        """
        if device_id in self._devices:
            raise ValueError(f"Device already registered: {device_id}")
        self._devices[device_id] = device

    def unregister(self, device_id: str) -> Optional[BaseDevice]:
        """Unregister a device by ID.

        Args:
            device_id: ID of device to unregister

        Returns:
            The unregistered device, or None if not found
        """
        return self._devices.pop(device_id, None)

    def get(self, device_id: str) -> Optional[BaseDevice]:
        """Get a device by ID.

        Args:
            device_id: ID of device to retrieve

        Returns:
            Device instance or None if not found
        """
        return self._devices.get(device_id)

    def get_all(self) -> dict[str, BaseDevice]:
        """Get all registered devices.

        Returns:
            Dictionary mapping device IDs to device instances
        """
        return dict(self._devices)

    def list_device_ids(self) -> list[str]:
        """List all registered device IDs.

        Returns:
            List of device IDs
        """
        return list(self._devices.keys())

    def __len__(self) -> int:
        """Return the number of registered devices."""
        return len(self._devices)

    def __contains__(self, device_id: str) -> bool:
        """Check if a device ID is registered."""
        return device_id in self._devices
