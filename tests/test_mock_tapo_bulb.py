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


@pytest.mark.asyncio
async def test_default_state_includes_color_fields(mock_bulb):
    result = await mock_bulb.execute("get_status", {})
    status = result["state"]
    assert status["hue"] == 0
    assert status["saturation"] == 0
    assert status["color_mode"] == "color_temp"


@pytest.mark.asyncio
@pytest.mark.parametrize("color_name,expected_hue,expected_sat", [
    ("Lime", 75, 100),
    ("BlueViolet", 271, 80),
])
async def test_set_color_valid(mock_bulb, color_name, expected_hue, expected_sat):
    result = await mock_bulb.execute("set_color", {"color_name": color_name})
    assert result["success"] is True
    state = result["state"]
    assert state["hue"] == expected_hue
    assert state["saturation"] == expected_sat
    assert state["color_mode"] == "color"
    assert state["color_temp"] == 0


@pytest.mark.asyncio
async def test_set_color_invalid(mock_bulb):
    result = await mock_bulb.execute("set_color", {"color_name": "NotAColor"})
    assert result["success"] is False
    assert "Unknown color" in result["message"]


@pytest.mark.asyncio
async def test_set_color_then_color_temp_resets_mode(mock_bulb):
    await mock_bulb.execute("set_color", {"color_name": "Lime"})
    result = await mock_bulb.execute("set_color_temp", {"color_temp": 3000})
    state = result["state"]
    assert state["color_mode"] == "color_temp"
    assert state["hue"] == 0
    assert state["saturation"] == 0
    assert state["color_temp"] == 3000
