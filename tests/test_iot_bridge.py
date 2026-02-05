"""Tests for the IoTBridge class."""

import json
import pytest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from smarthome.bridge.config import IoTConfig
from smarthome.bridge.iot_bridge import IoTBridge
from smarthome.devices.tapo_bulb import MockTapoBulb

# Import mocks directly to avoid module path issues
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mocks.mock_iot_client import MockMqttConnection, MockShadowClient


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
def bridge(iot_config, mock_bulb):
    """Create an IoTBridge instance for testing."""
    return IoTBridge(iot_config, mock_bulb)


class TestIoTBridgeInit:
    """Tests for IoTBridge initialization."""

    def test_init_sets_config(self, iot_config, mock_bulb):
        """Test that config is properly stored."""
        bridge = IoTBridge(iot_config, mock_bulb)
        assert bridge._config == iot_config

    def test_init_sets_topic_prefixes(self, iot_config, mock_bulb):
        """Test that topic prefixes are correctly set."""
        bridge = IoTBridge(iot_config, mock_bulb)
        assert bridge._command_topic_prefix == "smarthome/test-device/commands/"
        assert bridge._response_topic_prefix == "smarthome/test-device/responses/"

    def test_init_not_running(self, bridge):
        """Test that bridge is not running after init."""
        assert bridge.is_running is False
        assert bridge.is_disabled is False


class TestIoTBridgeCommandHandling:
    """Tests for command handling."""

    @pytest.mark.asyncio
    async def test_handle_turn_on(self, bridge, mock_bulb):
        """Test turn_on command handling."""
        result = await bridge._handle_turn_on({})

        assert result["success"] is True
        assert "turned on" in result["message"].lower()

        status = await mock_bulb.get_status()
        assert status["is_on"] is True

    @pytest.mark.asyncio
    async def test_handle_turn_off(self, bridge, mock_bulb):
        """Test turn_off command handling."""
        # First turn on
        await mock_bulb.turn_on()

        result = await bridge._handle_turn_off({})

        assert result["success"] is True
        assert "turned off" in result["message"].lower()

        status = await mock_bulb.get_status()
        assert status["is_on"] is False

    @pytest.mark.asyncio
    async def test_handle_get_status(self, bridge, mock_bulb):
        """Test get_status command handling."""
        result = await bridge._handle_get_status({})

        assert result["success"] is True
        assert "state" in result
        assert "is_on" in result["state"]
        assert "brightness" in result["state"]

    @pytest.mark.asyncio
    async def test_handle_set_brightness(self, bridge, mock_bulb):
        """Test set_brightness command handling."""
        result = await bridge._handle_set_brightness({"brightness": 75})

        assert result["success"] is True

        status = await mock_bulb.get_status()
        assert status["brightness"] == 75

    @pytest.mark.asyncio
    async def test_handle_set_brightness_missing_param(self, bridge):
        """Test set_brightness with missing brightness parameter."""
        result = await bridge._handle_set_brightness({})

        assert result["success"] is False
        assert "required" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_handle_set_brightness_invalid_value(self, bridge):
        """Test set_brightness with invalid brightness value."""
        result = await bridge._handle_set_brightness({"brightness": 150})

        assert result["success"] is False


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

    def test_connection_failure_increases_delay(self, bridge):
        """Test that connection failure increases reconnect delay."""
        initial_delay = bridge._reconnect_delay

        bridge._handle_connection_failure()

        assert bridge._reconnect_delay == initial_delay * 2

    def test_max_failures_disables_bridge(self, bridge):
        """Test that max failures disables the bridge."""
        # Simulate multiple failures until disabled
        while not bridge._disabled:
            bridge._handle_connection_failure()

        assert bridge.is_disabled is True

    @pytest.mark.asyncio
    async def test_on_connection_resumed_resets_delay(self, bridge):
        """Test that successful reconnection resets the delay."""
        # Simulate some failures first
        bridge._handle_connection_failure()
        bridge._handle_connection_failure()

        # Create mock shadow manager to avoid errors in state report
        bridge._shadow_manager = MagicMock()
        bridge._shadow_manager.update_reported = AsyncMock()

        # Simulate reconnection - this creates a task to report state
        bridge._on_connection_resumed(None, 0, False)

        # Give the async task a chance to run
        import asyncio
        await asyncio.sleep(0.01)

        assert bridge._reconnect_delay == 1  # MIN_RECONNECT_DELAY_SEC


class TestIoTBridgeResponsePublishing:
    """Tests for response publishing."""

    @pytest.mark.asyncio
    async def test_publish_response_format(self, bridge, mock_connection):
        """Test that response is published in correct format."""
        bridge._connection = mock_connection

        await bridge._publish_response(
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
            request_id="req-123",
            success=True,
            message="Test",
            state={},
        )
