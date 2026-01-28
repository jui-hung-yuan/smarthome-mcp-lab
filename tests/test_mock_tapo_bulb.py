"""Tests for MockTapoBulb device."""

import pytest

from smarthome.devices import MockTapoBulb


@pytest.mark.asyncio
async def test_default_state(mock_bulb):
    status = await mock_bulb.get_status()
    assert status["is_on"] is False
    assert status["brightness"] == 100
    assert status["color_temp"] == 2700


@pytest.mark.asyncio
async def test_turn_on(mock_bulb):
    result = await mock_bulb.turn_on()
    assert result["success"] is True
    assert result["state"]["is_on"] is True


@pytest.mark.asyncio
async def test_turn_off(mock_bulb):
    await mock_bulb.turn_on()
    result = await mock_bulb.turn_off()
    assert result["success"] is True
    assert result["state"]["is_on"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("level", [0, 50, 100])
async def test_set_brightness_valid(mock_bulb, level):
    result = await mock_bulb.set_brightness(level)
    assert result["success"] is True
    assert result["state"]["brightness"] == level


@pytest.mark.asyncio
@pytest.mark.parametrize("level", [-1, 101])
async def test_set_brightness_invalid(mock_bulb, level):
    result = await mock_bulb.set_brightness(level)
    assert result["success"] is False
    assert "message" in result


@pytest.mark.asyncio
async def test_state_persistence(tmp_state_file):
    bulb1 = MockTapoBulb(state_file=tmp_state_file)
    await bulb1.turn_on()
    await bulb1.set_brightness(42)

    bulb2 = MockTapoBulb(state_file=tmp_state_file)
    status = await bulb2.get_status()
    assert status["is_on"] is True
    assert status["brightness"] == 42
