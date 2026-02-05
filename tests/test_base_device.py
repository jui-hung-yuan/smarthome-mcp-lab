"""Tests for BaseDevice interface compliance."""

import pytest
from smarthome.devices.base import BaseDevice
from smarthome.devices.tapo_bulb import MockTapoBulb


@pytest.fixture
def mock_bulb(tmp_path):
    """Create a mock bulb for testing."""
    state_file = tmp_path / "bulb_state.json"
    return MockTapoBulb(state_file)


class TestBaseDeviceInterface:
    """Tests that MockTapoBulb properly implements BaseDevice."""

    def test_is_base_device(self, mock_bulb):
        """Test that MockTapoBulb is a BaseDevice instance."""
        assert isinstance(mock_bulb, BaseDevice)

    def test_device_type(self, mock_bulb):
        """Test device_type property returns correct type."""
        assert mock_bulb.device_type == "bulb"

    def test_supported_actions(self, mock_bulb):
        """Test supported_actions property returns correct actions."""
        actions = mock_bulb.supported_actions
        assert "turn_on" in actions
        assert "turn_off" in actions
        assert "set_brightness" in actions
        assert "get_status" in actions


class TestExecuteMethod:
    """Tests for the execute() method."""

    @pytest.mark.asyncio
    async def test_execute_turn_on(self, mock_bulb):
        """Test execute turn_on action."""
        result = await mock_bulb.execute("turn_on", {})

        assert result["success"] is True
        assert "turned on" in result["message"].lower()
        assert result["state"]["is_on"] is True

    @pytest.mark.asyncio
    async def test_execute_turn_off(self, mock_bulb):
        """Test execute turn_off action."""
        await mock_bulb.turn_on()

        result = await mock_bulb.execute("turn_off", {})

        assert result["success"] is True
        assert "turned off" in result["message"].lower()
        assert result["state"]["is_on"] is False

    @pytest.mark.asyncio
    async def test_execute_set_brightness(self, mock_bulb):
        """Test execute set_brightness action."""
        result = await mock_bulb.execute("set_brightness", {"brightness": 75})

        assert result["success"] is True
        assert result["state"]["brightness"] == 75

    @pytest.mark.asyncio
    async def test_execute_set_brightness_missing_param(self, mock_bulb):
        """Test execute set_brightness with missing parameter."""
        result = await mock_bulb.execute("set_brightness", {})

        assert result["success"] is False
        assert "required" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_get_status(self, mock_bulb):
        """Test execute get_status action."""
        result = await mock_bulb.execute("get_status", {})

        assert result["success"] is True
        assert "state" in result
        assert "is_on" in result["state"]
        assert "brightness" in result["state"]

    @pytest.mark.asyncio
    async def test_execute_unknown_action(self, mock_bulb):
        """Test execute with unknown action returns error."""
        result = await mock_bulb.execute("unknown_action", {})

        assert result["success"] is False
        assert "unknown" in result["message"].lower()
        assert "state" in result


class TestApplyDesiredState:
    """Tests for the apply_desired_state() method."""

    @pytest.mark.asyncio
    async def test_apply_desired_state_turn_on(self, mock_bulb):
        """Test applying desired state to turn on."""
        await mock_bulb.apply_desired_state({"is_on": True})

        status = await mock_bulb.get_status()
        assert status["is_on"] is True

    @pytest.mark.asyncio
    async def test_apply_desired_state_turn_off(self, mock_bulb):
        """Test applying desired state to turn off."""
        await mock_bulb.turn_on()

        await mock_bulb.apply_desired_state({"is_on": False})

        status = await mock_bulb.get_status()
        assert status["is_on"] is False

    @pytest.mark.asyncio
    async def test_apply_desired_state_brightness(self, mock_bulb):
        """Test applying desired brightness."""
        await mock_bulb.apply_desired_state({"brightness": 50})

        status = await mock_bulb.get_status()
        assert status["brightness"] == 50

    @pytest.mark.asyncio
    async def test_apply_desired_state_multiple_fields(self, mock_bulb):
        """Test applying multiple desired state fields."""
        await mock_bulb.apply_desired_state({"is_on": True, "brightness": 75})

        status = await mock_bulb.get_status()
        assert status["is_on"] is True
        assert status["brightness"] == 75

    @pytest.mark.asyncio
    async def test_apply_desired_state_ignores_unknown_fields(self, mock_bulb):
        """Test that unknown fields are ignored without error."""
        initial_status = await mock_bulb.get_status()

        await mock_bulb.apply_desired_state({"unknown_field": "value"})

        status = await mock_bulb.get_status()
        assert status["is_on"] == initial_status["is_on"]
        assert status["brightness"] == initial_status["brightness"]


class TestGetShadowState:
    """Tests for the get_shadow_state() method."""

    @pytest.mark.asyncio
    async def test_get_shadow_state_returns_required_fields(self, mock_bulb):
        """Test that get_shadow_state returns required fields."""
        state = await mock_bulb.get_shadow_state()

        assert "is_on" in state
        assert "brightness" in state
        assert "color_temp" in state

    @pytest.mark.asyncio
    async def test_get_shadow_state_reflects_current_state(self, mock_bulb):
        """Test that get_shadow_state reflects the current device state."""
        await mock_bulb.turn_on()
        await mock_bulb.set_brightness(42)

        state = await mock_bulb.get_shadow_state()

        assert state["is_on"] is True
        assert state["brightness"] == 42

    @pytest.mark.asyncio
    async def test_get_shadow_state_excludes_last_updated(self, mock_bulb):
        """Test that get_shadow_state doesn't include transient fields like last_updated."""
        state = await mock_bulb.get_shadow_state()

        # Shadow state should be minimal, not include last_updated
        assert "last_updated" not in state
