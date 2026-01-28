"""Tests for TapoBulb (real device wrapper) with mocked tapo library."""

import pytest
from unittest.mock import AsyncMock, MagicMock

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
    return TapoBulb(mock_device)


@pytest.mark.asyncio
async def test_turn_on_delegates(tapo_bulb, mock_device):
    result = await tapo_bulb.turn_on()
    mock_device.on.assert_awaited_once()
    mock_device.get_device_info.assert_awaited()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_turn_off_delegates(tapo_bulb, mock_device):
    result = await tapo_bulb.turn_off()
    mock_device.off.assert_awaited_once()
    mock_device.get_device_info.assert_awaited()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_get_status_parses_device_info(tapo_bulb):
    status = await tapo_bulb.get_status()
    assert status["is_on"] is True
    assert status["brightness"] == 75
    assert status["color_temp"] == 4000
    assert "last_updated" in status


@pytest.mark.asyncio
async def test_set_brightness_valid(tapo_bulb, mock_device):
    result = await tapo_bulb.set_brightness(50)
    mock_device.set_brightness.assert_awaited_once_with(50)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_set_brightness_invalid(tapo_bulb, mock_device):
    result = await tapo_bulb.set_brightness(150)
    assert result["success"] is False
    mock_device.set_brightness.assert_not_awaited()
