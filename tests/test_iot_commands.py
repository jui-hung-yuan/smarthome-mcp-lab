"""Tests for cloud.iot_commands using mocked boto3 iot-data client."""

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from smarthome.cloud.iot_commands import send_command, get_device_state

DEVICE_ID = "tapo-bulb-default"
THING_NAME = "smarthome-bridge-home"


def _make_shadow_payload(
    is_on=True, brightness=80, color_temp=4000, bridge_connected=True
):
    """Build a shadow response payload matching the bridge's format."""
    shadow = {
        "state": {
            "reported": {
                "bridge_connected": bridge_connected,
                "devices": {
                    DEVICE_ID: {
                        "is_on": is_on,
                        "brightness": brightness,
                        "color_temp": color_temp,
                        "device_reachable": True,
                    }
                },
            }
        }
    }
    payload = io.BytesIO(json.dumps(shadow).encode("utf-8"))
    return {"payload": payload}


@pytest.fixture
def mock_iot_client():
    """Return a mocked boto3 iot-data client."""
    client = MagicMock()
    client.publish.return_value = {}
    client.get_thing_shadow.return_value = _make_shadow_payload()
    return client


class TestGetDeviceState:
    def test_returns_device_state(self, mock_iot_client):
        state = get_device_state(DEVICE_ID, THING_NAME, mock_iot_client)

        assert state is not None
        assert state["is_on"] is True
        assert state["brightness"] == 80
        assert state["color_temp"] == 4000
        assert state["bridge_connected"] is True

        mock_iot_client.get_thing_shadow.assert_called_once_with(
            thingName=THING_NAME
        )

    def test_returns_none_for_unknown_device(self, mock_iot_client):
        state = get_device_state("unknown-device", THING_NAME, mock_iot_client)
        assert state is None

    def test_returns_none_on_api_error(self, mock_iot_client):
        mock_iot_client.get_thing_shadow.side_effect = Exception("API error")
        state = get_device_state(DEVICE_ID, THING_NAME, mock_iot_client)
        assert state is None


class TestSendCommand:
    @patch("smarthome.cloud.iot_commands.time.sleep")
    def test_publishes_and_reads_state(self, mock_sleep, mock_iot_client):
        result = send_command(
            device_id=DEVICE_ID,
            action="turn_on",
            parameters={},
            thing_name=THING_NAME,
            iot_client=mock_iot_client,
            command_wait=0.0,
        )

        assert result["success"] is True
        assert "turn_on" in result["message"]
        assert result["state"]["is_on"] is True

        # Verify MQTT publish was called
        mock_iot_client.publish.assert_called_once()
        call_kwargs = mock_iot_client.publish.call_args[1]
        assert call_kwargs["topic"] == f"smarthome/{DEVICE_ID}/commands/turn_on"
        assert call_kwargs["qos"] == 1

        # Verify payload contains request_id
        payload = json.loads(call_kwargs["payload"].decode("utf-8"))
        assert "request_id" in payload
        assert "timestamp" in payload
        assert payload["parameters"] == {}

    @patch("smarthome.cloud.iot_commands.time.sleep")
    def test_passes_parameters(self, mock_sleep, mock_iot_client):
        result = send_command(
            device_id=DEVICE_ID,
            action="set_brightness",
            parameters={"level": 50},
            thing_name=THING_NAME,
            iot_client=mock_iot_client,
            command_wait=0.0,
        )

        call_kwargs = mock_iot_client.publish.call_args[1]
        payload = json.loads(call_kwargs["payload"].decode("utf-8"))
        assert payload["parameters"] == {"level": 50}

    @patch("smarthome.cloud.iot_commands.time.sleep")
    def test_returns_failure_on_publish_error(self, mock_sleep, mock_iot_client):
        mock_iot_client.publish.side_effect = Exception("Connection refused")

        result = send_command(
            device_id=DEVICE_ID,
            action="turn_on",
            parameters={},
            thing_name=THING_NAME,
            iot_client=mock_iot_client,
            command_wait=0.0,
        )

        assert result["success"] is False
        assert "Failed to publish" in result["message"]

    @patch("smarthome.cloud.iot_commands.time.sleep")
    def test_returns_failure_when_shadow_unreadable(self, mock_sleep, mock_iot_client):
        mock_iot_client.get_thing_shadow.side_effect = Exception("Shadow error")

        result = send_command(
            device_id=DEVICE_ID,
            action="turn_on",
            parameters={},
            thing_name=THING_NAME,
            iot_client=mock_iot_client,
            command_wait=0.0,
        )

        assert result["success"] is False
        assert "failed to read back state" in result["message"].lower()

    @patch("smarthome.cloud.iot_commands.time.sleep")
    def test_waits_for_command_processing(self, mock_sleep, mock_iot_client):
        send_command(
            device_id=DEVICE_ID,
            action="turn_off",
            parameters={},
            thing_name=THING_NAME,
            iot_client=mock_iot_client,
            command_wait=3.0,
        )

        mock_sleep.assert_called_once_with(3.0)
