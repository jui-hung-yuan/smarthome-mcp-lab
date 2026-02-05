"""Tests for the IoTBridge class."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from smarthome.bridge.config import IoTConfig
from smarthome.bridge.device_registry import DeviceRegistry
from smarthome.bridge.iot_bridge import IoTBridge
from smarthome.devices.tapo_bulb import MockTapoBulb

# Import mocks directly to avoid module path issues
sys.path.insert(0, str(Path(__file__).parent))
from mocks.mock_iot_client import MockMqttConnection


@pytest.fixture
def iot_config(tmp_path):
    """Create a test IoT configuration."""
    cert_dir = tmp_path / "certs"
    cert_dir.mkdir()

    # Create dummy certificate files
    (cert_dir / "certificate.pem").write_text("dummy cert")
    (cert_dir / "private.key").write_text("dummy key")
    (cert_dir / "AmazonRootCA1.pem").write_text("dummy ca")

    return IoTConfig(
        endpoint="test-endpoint.iot.region.amazonaws.com",
        thing_name="test-thing",
        cert_path=cert_dir / "certificate.pem",
        key_path=cert_dir / "private.key",
        root_ca_path=cert_dir / "AmazonRootCA1.pem",
        device_id="test-device",
    )


@pytest.fixture
def mock_bulb(tmp_path):
    """Create a mock bulb for testing."""
    state_file = tmp_path / "bulb_state.json"
    return MockTapoBulb(state_file)


@pytest.fixture
def mock_connection():
    """Create a mock MQTT connection."""
    return MockMqttConnection()


@pytest.fixture
def mock_shadow_manager():
    """Create a mock shadow manager."""
    manager = MagicMock()
    manager.update_reported = AsyncMock(return_value=True)
    manager.subscribe_to_delta = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def registry(mock_bulb, iot_config):
    """Create a device registry with the mock bulb registered."""
    reg = DeviceRegistry()
    reg.register(iot_config.device_id, mock_bulb)
    return reg


@pytest.fixture
def bridge(iot_config, registry):
    """Create an IoTBridge instance for testing."""
    return IoTBridge(iot_config, registry)


class TestIoTBridgeInit:
    """Tests for IoTBridge initialization."""

    def test_init_sets_config(self, iot_config, registry):
        """Test that config is properly stored."""
        bridge = IoTBridge(iot_config, registry)
        assert bridge._config == iot_config

    def test_init_sets_registry(self, iot_config, registry):
        """Test that registry is properly stored."""
        bridge = IoTBridge(iot_config, registry)
        assert bridge._registry is registry

    def test_init_not_running(self, bridge):
        """Test that bridge is not running after init."""
        assert bridge.is_running is False
        assert bridge.is_disabled is False


class TestIoTBridgeCommandHandling:
    """Tests for command handling via _handle_command.

    Note: Command execution logic is now in the device's execute() method.
    See test_base_device.py for comprehensive execute() tests.
    These tests verify the bridge correctly routes commands to the device.
    """

    @pytest.mark.asyncio
    async def test_handle_command_turn_on(
        self, bridge, mock_bulb, mock_connection, mock_shadow_manager
    ):
        """Test turn_on command via _handle_command."""
        bridge._connection = mock_connection
        bridge._shadow_manager = mock_shadow_manager

        topic = "smarthome/test-device/commands/turn_on"
        payload = json.dumps({"request_id": "test-on", "parameters": {}}).encode()

        await bridge._handle_command(topic, payload)

        status = await mock_bulb.get_status()
        assert status["is_on"] is True

        responses = mock_connection.get_published_to("smarthome/test-device/responses/")
        assert len(responses) == 1
        response_data = json.loads(responses[0].payload.decode())
        assert response_data["success"] is True

    @pytest.mark.asyncio
    async def test_handle_command_turn_off(
        self, bridge, mock_bulb, mock_connection, mock_shadow_manager
    ):
        """Test turn_off command via _handle_command."""
        bridge._connection = mock_connection
        bridge._shadow_manager = mock_shadow_manager
        await mock_bulb.turn_on()

        topic = "smarthome/test-device/commands/turn_off"
        payload = json.dumps({"request_id": "test-off", "parameters": {}}).encode()

        await bridge._handle_command(topic, payload)

        status = await mock_bulb.get_status()
        assert status["is_on"] is False

    @pytest.mark.asyncio
    async def test_handle_command_set_brightness(
        self, bridge, mock_bulb, mock_connection, mock_shadow_manager
    ):
        """Test set_brightness command via _handle_command."""
        bridge._connection = mock_connection
        bridge._shadow_manager = mock_shadow_manager

        topic = "smarthome/test-device/commands/set_brightness"
        payload = json.dumps(
            {"request_id": "test-brightness", "parameters": {"brightness": 75}}
        ).encode()

        await bridge._handle_command(topic, payload)

        status = await mock_bulb.get_status()
        assert status["brightness"] == 75

    @pytest.mark.asyncio
    async def test_handle_command_set_brightness_missing_param(
        self, bridge, mock_connection, mock_shadow_manager
    ):
        """Test set_brightness with missing brightness parameter."""
        bridge._connection = mock_connection
        bridge._shadow_manager = mock_shadow_manager

        topic = "smarthome/test-device/commands/set_brightness"
        payload = json.dumps(
            {"request_id": "test-missing", "parameters": {}}
        ).encode()

        await bridge._handle_command(topic, payload)

        responses = mock_connection.get_published_to("smarthome/test-device/responses/")
        assert len(responses) == 1
        response_data = json.loads(responses[0].payload.decode())
        assert response_data["success"] is False
        assert "required" in response_data["message"].lower()


class TestIoTBridgeMessageParsing:
    """Tests for MQTT message parsing and routing."""

    @pytest.mark.asyncio
    async def test_handle_command_with_valid_json(
        self, bridge, mock_connection, mock_shadow_manager
    ):
        """Test handling a command with valid JSON payload."""
        bridge._connection = mock_connection
        bridge._shadow_manager = mock_shadow_manager

        topic = "smarthome/test-device/commands/turn_on"
        payload = json.dumps(
            {"request_id": "test-123", "parameters": {}}
        ).encode()

        await bridge._handle_command(topic, payload)

        # Check that a response was published
        responses = mock_connection.get_published_to(
            "smarthome/test-device/responses/"
        )
        assert len(responses) == 1

        response_data = json.loads(responses[0].payload.decode())
        assert response_data["request_id"] == "test-123"
        assert response_data["success"] is True

    @pytest.mark.asyncio
    async def test_handle_command_with_empty_payload(
        self, bridge, mock_connection, mock_shadow_manager
    ):
        """Test handling a command with empty payload."""
        bridge._connection = mock_connection
        bridge._shadow_manager = mock_shadow_manager

        topic = "smarthome/test-device/commands/get_status"
        payload = b""

        await bridge._handle_command(topic, payload)

        responses = mock_connection.get_published_to(
            "smarthome/test-device/responses/"
        )
        assert len(responses) == 1

        response_data = json.loads(responses[0].payload.decode())
        assert response_data["success"] is True

    @pytest.mark.asyncio
    async def test_handle_command_unknown_action(
        self, bridge, mock_connection, mock_shadow_manager
    ):
        """Test handling a command with unknown action."""
        bridge._connection = mock_connection
        bridge._shadow_manager = mock_shadow_manager

        topic = "smarthome/test-device/commands/unknown_action"
        payload = json.dumps({"request_id": "test-456"}).encode()

        await bridge._handle_command(topic, payload)

        responses = mock_connection.get_published_to(
            "smarthome/test-device/responses/"
        )
        assert len(responses) == 1

        response_data = json.loads(responses[0].payload.decode())
        assert response_data["success"] is False
        assert "unknown" in response_data["message"].lower()

    @pytest.mark.asyncio
    async def test_handle_command_unknown_device(
        self, bridge, mock_connection, mock_shadow_manager
    ):
        """Test handling a command for an unknown device."""
        bridge._connection = mock_connection
        bridge._shadow_manager = mock_shadow_manager

        topic = "smarthome/unknown-device/commands/turn_on"
        payload = json.dumps({"request_id": "test-unknown"}).encode()

        await bridge._handle_command(topic, payload)

        responses = mock_connection.get_published_to(
            "smarthome/unknown-device/responses/"
        )
        assert len(responses) == 1

        response_data = json.loads(responses[0].payload.decode())
        assert response_data["success"] is False
        assert "unknown device" in response_data["message"].lower()


class TestIoTBridgeShadowDelta:
    """Tests for shadow delta handling."""

    @pytest.mark.asyncio
    async def test_apply_desired_state_turn_on(self, bridge, mock_bulb):
        """Test applying desired state to turn on bulb."""
        await bridge._apply_desired_state({"is_on": True})

        status = await mock_bulb.get_status()
        assert status["is_on"] is True

    @pytest.mark.asyncio
    async def test_apply_desired_state_turn_off(self, bridge, mock_bulb):
        """Test applying desired state to turn off bulb."""
        await mock_bulb.turn_on()

        await bridge._apply_desired_state({"is_on": False})

        status = await mock_bulb.get_status()
        assert status["is_on"] is False

    @pytest.mark.asyncio
    async def test_apply_desired_state_brightness(self, bridge, mock_bulb):
        """Test applying desired brightness from shadow delta."""
        await bridge._apply_desired_state({"brightness": 50})

        status = await mock_bulb.get_status()
        assert status["brightness"] == 50

    @pytest.mark.asyncio
    async def test_apply_desired_state_multiple_fields(self, bridge, mock_bulb):
        """Test applying multiple desired state fields."""
        await bridge._apply_desired_state({"is_on": True, "brightness": 75})

        status = await mock_bulb.get_status()
        assert status["is_on"] is True
        assert status["brightness"] == 75


class TestIoTBridgeConnection:
    """Tests for connection management."""

    def test_connection_failure_increases_count(self, bridge):
        """Test that connection failure increases failure count."""
        assert bridge._failure_count == 0

        bridge._handle_connection_failure()

        assert bridge._failure_count == 1

    def test_max_failures_disables_bridge(self, bridge):
        """Test that max failures disables the bridge."""
        # Simulate multiple failures until disabled
        while not bridge._disabled:
            bridge._handle_connection_failure()

        assert bridge.is_disabled is True

    @pytest.mark.asyncio
    async def test_on_connection_resumed_resets_failure_count(self, bridge):
        """Test that successful reconnection resets failure count."""
        # Simulate some failures first
        bridge._handle_connection_failure()
        bridge._handle_connection_failure()
        assert bridge._failure_count == 2

        # Create mock shadow manager to avoid errors in state report
        bridge._shadow_manager = MagicMock()
        bridge._shadow_manager.update_reported = AsyncMock()

        # Simulate reconnection - this creates a task to report state
        bridge._on_connection_resumed(None, 0, False)

        # Give the async task a chance to run
        import asyncio
        await asyncio.sleep(0.01)

        assert bridge._failure_count == 0


class TestIoTBridgeResponsePublishing:
    """Tests for response publishing."""

    @pytest.mark.asyncio
    async def test_publish_response_format(self, bridge, mock_connection):
        """Test that response is published in correct format."""
        bridge._connection = mock_connection

        await bridge._publish_response(
            device_id="test-device",
            request_id="req-123",
            success=True,
            message="Test message",
            state={"is_on": True, "brightness": 100},
        )

        assert len(mock_connection.published_messages) == 1

        msg = mock_connection.published_messages[0]
        assert msg.topic == "smarthome/test-device/responses/req-123"

        data = json.loads(msg.payload.decode())
        assert data["request_id"] == "req-123"
        assert data["device_id"] == "test-device"
        assert data["success"] is True
        assert data["message"] == "Test message"
        assert data["state"]["is_on"] is True
        assert data["state"]["brightness"] == 100
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_publish_response_no_connection(self, bridge):
        """Test that publish does nothing when not connected."""
        bridge._connection = None

        # Should not raise
        await bridge._publish_response(
            device_id="test-device",
            request_id="req-123",
            success=True,
            message="Test",
            state={},
        )
