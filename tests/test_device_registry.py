"""Tests for DeviceRegistry."""

import pytest
from smarthome.bridge.device_registry import DeviceRegistry
from smarthome.devices.tapo_bulb import MockTapoBulb


@pytest.fixture
def registry():
    """Create an empty device registry."""
    return DeviceRegistry()


@pytest.fixture
def mock_bulb(tmp_path):
    """Create a mock bulb for testing."""
    state_file = tmp_path / "bulb_state.json"
    return MockTapoBulb(state_file)


@pytest.fixture
def mock_bulb2(tmp_path):
    """Create a second mock bulb for testing."""
    state_file = tmp_path / "bulb_state2.json"
    return MockTapoBulb(state_file)


class TestDeviceRegistryBasics:
    """Tests for basic registry operations."""

    def test_empty_registry(self, registry):
        """Test that new registry is empty."""
        assert len(registry) == 0
        assert registry.list_device_ids() == []

    def test_register_device(self, registry, mock_bulb):
        """Test registering a device."""
        registry.register("bulb-1", mock_bulb)

        assert len(registry) == 1
        assert "bulb-1" in registry
        assert registry.get("bulb-1") is mock_bulb

    def test_register_multiple_devices(self, registry, mock_bulb, mock_bulb2):
        """Test registering multiple devices."""
        registry.register("bulb-1", mock_bulb)
        registry.register("bulb-2", mock_bulb2)

        assert len(registry) == 2
        assert "bulb-1" in registry
        assert "bulb-2" in registry

    def test_register_duplicate_raises(self, registry, mock_bulb, mock_bulb2):
        """Test that registering duplicate ID raises ValueError."""
        registry.register("bulb-1", mock_bulb)

        with pytest.raises(ValueError) as exc_info:
            registry.register("bulb-1", mock_bulb2)

        assert "already registered" in str(exc_info.value).lower()


class TestDeviceRetrieval:
    """Tests for device retrieval operations."""

    def test_get_device(self, registry, mock_bulb):
        """Test getting a device by ID."""
        registry.register("bulb-1", mock_bulb)

        device = registry.get("bulb-1")

        assert device is mock_bulb

    def test_get_unknown_returns_none(self, registry):
        """Test that getting unknown device returns None."""
        device = registry.get("unknown-device")

        assert device is None

    def test_get_all_empty(self, registry):
        """Test get_all on empty registry."""
        devices = registry.get_all()

        assert devices == {}

    def test_get_all_returns_copy(self, registry, mock_bulb):
        """Test that get_all returns a copy, not the internal dict."""
        registry.register("bulb-1", mock_bulb)

        devices = registry.get_all()
        devices["bulb-2"] = mock_bulb  # Modify the returned dict

        assert "bulb-2" not in registry

    def test_list_device_ids(self, registry, mock_bulb, mock_bulb2):
        """Test listing device IDs."""
        registry.register("bulb-1", mock_bulb)
        registry.register("bulb-2", mock_bulb2)

        ids = registry.list_device_ids()

        assert set(ids) == {"bulb-1", "bulb-2"}


class TestDeviceUnregister:
    """Tests for device unregistration."""

    def test_unregister_device(self, registry, mock_bulb):
        """Test unregistering a device."""
        registry.register("bulb-1", mock_bulb)

        removed = registry.unregister("bulb-1")

        assert removed is mock_bulb
        assert "bulb-1" not in registry
        assert len(registry) == 0

    def test_unregister_unknown_returns_none(self, registry):
        """Test that unregistering unknown device returns None."""
        removed = registry.unregister("unknown-device")

        assert removed is None

    def test_unregister_allows_reregister(self, registry, mock_bulb, mock_bulb2):
        """Test that after unregister, the ID can be reused."""
        registry.register("bulb-1", mock_bulb)
        registry.unregister("bulb-1")

        # Should not raise
        registry.register("bulb-1", mock_bulb2)

        assert registry.get("bulb-1") is mock_bulb2


class TestDeviceRegistryContains:
    """Tests for __contains__ (in) operator."""

    def test_contains_registered_device(self, registry, mock_bulb):
        """Test that registered device is found with 'in'."""
        registry.register("bulb-1", mock_bulb)

        assert "bulb-1" in registry

    def test_not_contains_unregistered_device(self, registry):
        """Test that unregistered device is not found with 'in'."""
        assert "unknown" not in registry
