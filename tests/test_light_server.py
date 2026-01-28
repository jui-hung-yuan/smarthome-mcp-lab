"""Tests for the MCP light server tools."""

import pytest
from unittest.mock import patch

from smarthome.devices import MockTapoBulb
from smarthome.mcp_servers import light_server

# The @app.tool() decorator wraps functions into FunctionTool objects.
# Access the underlying async functions via the .fn attribute.
_turn_on = light_server.turn_on.fn
_turn_off = light_server.turn_off.fn
_get_status = light_server.get_status.fn
_set_brightness = light_server.set_brightness.fn


@pytest.fixture(autouse=True)
def _inject_bulb(mock_bulb):
    """Inject the mock bulb into the server module and reset after each test."""
    light_server.bulb = mock_bulb
    yield
    light_server.bulb = None


@pytest.mark.asyncio
async def test_turn_on_formats_response():
    result = await _turn_on()
    assert "✓" in result
    assert "ON" in result


@pytest.mark.asyncio
async def test_turn_off_formats_response():
    result = await _turn_off()
    assert "✓" in result
    assert "OFF" in result


@pytest.mark.asyncio
async def test_get_status_formats_response():
    result = await _get_status()
    assert "Bulb is" in result
    assert "Mode: mock" in result
    assert "Brightness:" in result
    assert "Color Temperature:" in result


@pytest.mark.asyncio
async def test_set_brightness_formats_response():
    result = await _set_brightness(50)
    assert "✓" in result
    assert "50" in result


@pytest.mark.asyncio
async def test_set_brightness_error_formats_response():
    result = await _set_brightness(999)
    assert "✗" in result


@pytest.mark.asyncio
async def test_get_bulb_falls_back_to_mock():
    light_server.bulb = None
    with patch("smarthome.mcp_servers.light_server.dotenv_values", return_value={}):
        b = await light_server.get_bulb()
    assert isinstance(b, MockTapoBulb)
