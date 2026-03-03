"""Tests for MockTapoBulb device."""

import pytest

from smarthome.devices import MockTapoBulb


@pytest.mark.asyncio
async def test_default_state(mock_bulb):
    result = await mock_bulb.execute("get_status", {})
    status = result["state"]
    assert status["is_on"] is False
    assert status["brightness"] == 100
    assert status["color_temp"] == 2700


@pytest.mark.asyncio
async def test_turn_on(mock_bulb):
    result = await mock_bulb.execute("turn_on", {})
    assert result["success"] is True
    assert result["state"]["is_on"] is True


@pytest.mark.asyncio
async def test_turn_off(mock_bulb):
    await mock_bulb.execute("turn_on", {})
    result = await mock_bulb.execute("turn_off", {})
    assert result["success"] is True
    assert result["state"]["is_on"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("level", [0, 50, 100])
async def test_set_brightness_valid(mock_bulb, level):
    result = await mock_bulb.execute("set_brightness", {"brightness": level})
    assert result["success"] is True
    assert result["state"]["brightness"] == level


@pytest.mark.asyncio
@pytest.mark.parametrize("level", [-1, 101])
async def test_set_brightness_invalid(mock_bulb, level):
    result = await mock_bulb.execute("set_brightness", {"brightness": level})
    assert result["success"] is False
    assert "message" in result


@pytest.mark.asyncio
async def test_set_color_temp_valid(mock_bulb):
    result = await mock_bulb.execute("set_color_temp", {"color_temp": 4000})
    assert result["success"] is True
    assert result["state"]["color_temp"] == 4000


@pytest.mark.asyncio
async def test_set_color_temp_invalid(mock_bulb):
    result = await mock_bulb.execute("set_color_temp", {"color_temp": 2000})
    assert result["success"] is False
    assert "message" in result


@pytest.mark.asyncio
async def test_state_persistence(tmp_state_file):
    bulb1 = MockTapoBulb(state_file=tmp_state_file)
    await bulb1.execute("turn_on", {})
    await bulb1.execute("set_brightness", {"brightness": 42})

    bulb2 = MockTapoBulb(state_file=tmp_state_file)
    result = await bulb2.execute("get_status", {})
    assert result["state"]["is_on"] is True
    assert result["state"]["brightness"] == 42
