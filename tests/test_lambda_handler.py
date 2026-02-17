"""Tests for lambda_handler with mocked IoT commands and Lambda context."""

from unittest.mock import MagicMock, patch

import pytest

from smarthome.lambda_handler import lambda_handler, _extract_tool_name


def _make_context(tool_name: str) -> MagicMock:
    """Build a mock Lambda context with AgentCore tool name."""
    context = MagicMock()
    context.client_context.custom = {
        "bedrockAgentCoreToolName": f"smarthome-light___{tool_name}"
    }
    return context


def _make_context_raw(raw_name: str) -> MagicMock:
    """Build a mock Lambda context with a raw tool name (no prefix stripping)."""
    context = MagicMock()
    context.client_context.custom = {"bedrockAgentCoreToolName": raw_name}
    return context


class TestExtractToolName:
    def test_strips_target_prefix(self):
        context = _make_context("turn_on")
        assert _extract_tool_name(context) == "turn_on"

    def test_handles_no_prefix(self):
        context = _make_context_raw("get_status")
        assert _extract_tool_name(context) == "get_status"

    def test_handles_missing_client_context(self):
        context = MagicMock()
        context.client_context = None
        assert _extract_tool_name(context) == ""

    def test_handles_missing_custom_key(self):
        context = MagicMock()
        context.client_context.custom = {}
        assert _extract_tool_name(context) == ""


class TestLambdaHandlerCommands:
    @patch("smarthome.lambda_handler._log_state_change")
    @patch("smarthome.lambda_handler.send_command")
    def test_turn_on(self, mock_send, mock_log):
        mock_send.return_value = {
            "success": True,
            "message": "Command 'turn_on' sent",
            "state": {"is_on": True, "brightness": 80, "color_temp": 4000},
        }

        result = lambda_handler({}, _make_context("turn_on"))

        assert result["status"] == "success"
        assert result["is_on"] is True
        mock_send.assert_called_once()
        mock_log.assert_called_once()

    @patch("smarthome.lambda_handler._log_state_change")
    @patch("smarthome.lambda_handler.send_command")
    def test_turn_off(self, mock_send, mock_log):
        mock_send.return_value = {
            "success": True,
            "message": "Command 'turn_off' sent",
            "state": {"is_on": False, "brightness": 0, "color_temp": 0},
        }

        result = lambda_handler({}, _make_context("turn_off"))

        assert result["status"] == "success"
        assert result["is_on"] is False

    @patch("smarthome.lambda_handler._log_state_change")
    @patch("smarthome.lambda_handler.send_command")
    def test_set_brightness(self, mock_send, mock_log):
        mock_send.return_value = {
            "success": True,
            "message": "Command 'set_brightness' sent",
            "state": {"is_on": True, "brightness": 50, "color_temp": 4000},
        }

        result = lambda_handler({"brightness": 50}, _make_context("set_brightness"))

        assert result["status"] == "success"
        assert result["brightness"] == 50

        # Verify brightness was passed in parameters
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["parameters"] == {"brightness": 50}

    @patch("smarthome.lambda_handler._log_state_change")
    @patch("smarthome.lambda_handler.send_command")
    def test_command_failure(self, mock_send, mock_log):
        mock_send.return_value = {
            "success": False,
            "message": "Bridge unreachable",
            "state": {},
        }

        result = lambda_handler({}, _make_context("turn_on"))

        assert result["status"] == "error"
        assert "Bridge unreachable" in result["message"]


class TestLambdaHandlerStatus:
    @patch("smarthome.lambda_handler.get_device_state")
    def test_get_status(self, mock_get_state):
        mock_get_state.return_value = {
            "is_on": True,
            "brightness": 80,
            "color_temp": 4000,
            "bridge_connected": True,
        }

        result = lambda_handler({}, _make_context("get_status"))

        assert result["status"] == "success"
        assert result["is_on"] is True
        assert result["brightness"] == 80
        assert result["bridge_connected"] is True

    @patch("smarthome.lambda_handler.get_device_state")
    def test_get_status_failure(self, mock_get_state):
        mock_get_state.return_value = None

        result = lambda_handler({}, _make_context("get_status"))

        assert result["status"] == "error"


class TestLambdaHandlerUnknownTool:
    def test_unknown_tool(self):
        result = lambda_handler({}, _make_context("unknown_action"))

        assert result["status"] == "error"
        assert "Unknown tool" in result["message"]
