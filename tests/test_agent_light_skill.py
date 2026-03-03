"""Tests for the light-control skill (bulb.py) using MockTapoBulb.

The skill lives in skills/light-control/scripts/bulb.py — the dash in the
directory name means it can't be imported via normal Python import; we load
it with importlib the same way SkillLoader does at runtime.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_bulb_module() -> ModuleType:
    """Load skills/light-control/scripts/bulb.py via importlib."""
    bulb_path = (
        Path(__file__).parent.parent
        / "src" / "smarthome" / "agent" / "skills" / "light-control" / "scripts" / "bulb.py"
    )
    module_name = "smarthome.agent.skills.light_control.scripts.bulb"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, bulb_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def reset_skill_module():
    """Reset module-level state between tests."""
    mod = _load_bulb_module()
    mod._device = None
    mod._mock = False
    yield
    mod._device = None
    mod._mock = False


@pytest.fixture
def bulb(tmp_path):
    """Configure the skill to use MockTapoBulb with a temp state file."""
    mod = _load_bulb_module()
    mod.configure(mock=True)
    mod._mock_state_file = tmp_path / "bulb_state.json"
    return mod


# ---------------------------------------------------------------------------
# turn_on / turn_off
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_turn_on(bulb):
    result = await bulb.execute("turn_on", {})
    assert result["success"] is True
    assert result["state"]["is_on"] is True


@pytest.mark.asyncio
async def test_turn_off(bulb):
    await bulb.execute("turn_on", {})
    result = await bulb.execute("turn_off", {})
    assert result["success"] is True
    assert result["state"]["is_on"] is False


# ---------------------------------------------------------------------------
# set_brightness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_brightness_valid(bulb):
    result = await bulb.execute("set_brightness", {"brightness": 40})
    assert result["success"] is True
    assert result["state"]["brightness"] == 40


@pytest.mark.asyncio
async def test_set_brightness_invalid_range(bulb):
    result = await bulb.execute("set_brightness", {"brightness": 150})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_set_brightness_missing_param(bulb):
    result = await bulb.execute("set_brightness", {})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# set_color_temp
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_color_temp_valid(bulb):
    result = await bulb.execute("set_color_temp", {"color_temp": 3000})
    assert result["success"] is True
    assert result["state"]["color_temp"] == 3000


@pytest.mark.asyncio
async def test_set_color_temp_invalid_range(bulb):
    result = await bulb.execute("set_color_temp", {"color_temp": 1000})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_set_color_temp_missing_param(bulb):
    result = await bulb.execute("set_color_temp", {})
    assert result["success"] is False
    assert "color_temp" in result["message"]


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status_returns_state(bulb):
    result = await bulb.execute("get_status", {})
    assert result["success"] is True
    state = result["state"]
    assert "is_on" in state
    assert "brightness" in state
    assert "color_temp" in state


# ---------------------------------------------------------------------------
# unknown action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_action_returns_failure(bulb):
    result = await bulb.execute("fly_to_moon", {})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# real bulb: missing env vars
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_real_bulb_missing_env_vars_returns_error(monkeypatch):
    mod = _load_bulb_module()
    mod._device = None
    mod._mock = False
    monkeypatch.delenv("TAPO_USERNAME", raising=False)
    monkeypatch.delenv("TAPO_PASSWORD", raising=False)
    monkeypatch.delenv("TAPO_IP", raising=False)
    result = await mod.execute("turn_on", {})
    assert result["success"] is False
    assert "TAPO_USERNAME" in result["message"] or "env" in result["message"].lower()