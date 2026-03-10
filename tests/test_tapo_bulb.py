"""Tests for TapoBulb (real device wrapper) with mocked tapo library."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from smarthome.devices import TapoBulb


@pytest.fixture
def mock_device():
    """Create a mock tapo device with standard responses."""
    device = AsyncMock()
    info = MagicMock()
    info.device_on = True
    info.brightness = 75
    info.color_temp = 4000
    device.get_device_info.return_value = info
    return device


@pytest.fixture
def tapo_bulb(mock_device):
    return TapoBulb(mock_device, "user@example.com", "password", "192.168.1.100")


@pytest.mark.asyncio
async def test_turn_on_delegates(tapo_bulb, mock_device):
    result = await tapo_bulb.execute("turn_on", {})
    mock_device.on.assert_awaited_once()
    mock_device.get_device_info.assert_awaited()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_turn_off_delegates(tapo_bulb, mock_device):
    result = await tapo_bulb.execute("turn_off", {})
    mock_device.off.assert_awaited_once()
    mock_device.get_device_info.assert_awaited()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_get_status_parses_device_info(tapo_bulb):
    result = await tapo_bulb.execute("get_status", {})
    status = result["state"]
    assert status["is_on"] is True
    assert status["brightness"] == 75
    assert status["color_temp"] == 4000
    assert "last_updated" in status


@pytest.mark.asyncio
async def test_set_brightness_valid(tapo_bulb, mock_device):
    result = await tapo_bulb.execute("set_brightness", {"brightness": 50})
    mock_device.set_brightness.assert_awaited_once_with(50)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_set_brightness_invalid(tapo_bulb, mock_device):
    result = await tapo_bulb.execute("set_brightness", {"brightness": 150})
    assert result["success"] is False
    mock_device.set_brightness.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_color_temp_valid(tapo_bulb, mock_device):
    result = await tapo_bulb.execute("set_color_temp", {"color_temp": 4000})
    mock_device.set_color_temperature.assert_awaited_once_with(4000)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_set_color_temp_invalid(tapo_bulb, mock_device):
    result = await tapo_bulb.execute("set_color_temp", {"color_temp": 2000})
    assert result["success"] is False
    mock_device.set_color_temperature.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconnects_on_session_timeout(tapo_bulb, mock_device):
    """On SessionTimeout, execute() reconnects and retries the command."""
    mock_new_device = AsyncMock()
    info = MagicMock()
    info.device_on = True
    info.brightness = 75
    info.color_temp = 4000
    mock_new_device.get_device_info.return_value = info

    mock_device.on.side_effect = Exception("Tapo(SessionTimeout)")

    mock_client = AsyncMock()
    mock_client.l530.return_value = mock_new_device

    with patch("smarthome.devices.tapo_bulb.ApiClient", return_value=mock_client):
        result = await tapo_bulb.execute("turn_on", {})

    assert result["success"] is True
    mock_client.l530.assert_awaited_once_with("192.168.1.100")
    mock_new_device.on.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_session_timeout_error_is_reraised(tapo_bulb, mock_device):
    """Non-SessionTimeout exceptions are not swallowed."""
    mock_device.on.side_effect = Exception("Connection refused")

    with pytest.raises(Exception, match="Connection refused"):
        await tapo_bulb.execute("turn_on", {})
