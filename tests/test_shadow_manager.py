"""Tests for the ShadowManager class."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from smarthome.bridge.shadow_manager import ShadowManager

# Import mocks directly to avoid module path issues
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mocks.mock_iot_client import MockMqttConnection, MockShadowClient


@pytest.fixture
def mock_connection():
    """Create a mock MQTT connection."""
    return MockMqttConnection()


@pytest.fixture
def mock_shadow_client():
    """Create a mock shadow client."""
    return MockShadowClient()


@pytest.fixture
def shadow_manager(mock_connection):
    """Create a ShadowManager with mock connection."""
    return ShadowManager(mock_connection, "test-thing")


class TestShadowManagerUpdateReported:
    """Tests for update_reported method."""

    @pytest.mark.asyncio
    async def test_update_reported_success(self, shadow_manager, mock_shadow_client):
        """Test successful shadow update."""
        with patch.object(
            shadow_manager, "_get_client", return_value=mock_shadow_client
        ):
            result = await shadow_manager.update_reported(
                {"is_on": True, "brightness": 75}
            )

            assert result is True
            assert len(mock_shadow_client.reported_states) == 1
            assert mock_shadow_client.reported_states[0] == {
                "is_on": True,
                "brightness": 75,
            }

    @pytest.mark.asyncio
    async def test_update_reported_includes_all_fields(
        self, shadow_manager, mock_shadow_client
    ):
        """Test that all state fields are included in update."""
        with patch.object(
            shadow_manager, "_get_client", return_value=mock_shadow_client
        ):
            state = {
                "is_on": True,
                "brightness": 100,
                "color_temp": 2700,
                "bridge_connected": True,
                "device_reachable": True,
            }

            await shadow_manager.update_reported(state)

            reported = mock_shadow_client.get_last_reported()
            assert reported == state

    @pytest.mark.asyncio
    async def test_update_reported_failure(self, shadow_manager):
        """Test handling of shadow update failure."""
        mock_client = MagicMock()
        mock_client.publish_update_shadow.side_effect = Exception("Network error")

        with patch.object(shadow_manager, "_get_client", return_value=mock_client):
            result = await shadow_manager.update_reported({"is_on": True})

            assert result is False


class TestShadowManagerSubscribeToDelta:
    """Tests for subscribe_to_delta method."""

    @pytest.mark.asyncio
    async def test_subscribe_to_delta_success(
        self, shadow_manager, mock_shadow_client
    ):
        """Test successful subscription to delta updates."""
        callback_called = []

        def callback(delta):
            callback_called.append(delta)

        with patch.object(
            shadow_manager, "_get_client", return_value=mock_shadow_client
        ):
            result = await shadow_manager.subscribe_to_delta(callback)

            assert result is True

            # Simulate a delta update
            mock_shadow_client.simulate_delta({"is_on": True})

            assert len(callback_called) == 1
            assert callback_called[0] == {"is_on": True}

    @pytest.mark.asyncio
    async def test_subscribe_to_delta_multiple_updates(
        self, shadow_manager, mock_shadow_client
    ):
        """Test receiving multiple delta updates."""
        received_deltas = []

        def callback(delta):
            received_deltas.append(delta)

        with patch.object(
            shadow_manager, "_get_client", return_value=mock_shadow_client
        ):
            await shadow_manager.subscribe_to_delta(callback)

            mock_shadow_client.simulate_delta({"is_on": True})
            mock_shadow_client.simulate_delta({"brightness": 50})
            mock_shadow_client.simulate_delta({"is_on": False, "brightness": 100})

            assert len(received_deltas) == 3
            assert received_deltas[0] == {"is_on": True}
            assert received_deltas[1] == {"brightness": 50}
            assert received_deltas[2] == {"is_on": False, "brightness": 100}


class TestShadowManagerGetShadow:
    """Tests for get_shadow method."""

    @pytest.mark.asyncio
    async def test_get_shadow_success(self, shadow_manager, mock_shadow_client):
        """Test successful shadow retrieval."""
        mock_shadow_client.desired_state = {"is_on": True}
        mock_shadow_client.reported_states = [{"is_on": False, "brightness": 100}]

        with patch.object(
            shadow_manager, "_get_client", return_value=mock_shadow_client
        ):
            result = await shadow_manager.get_shadow()

            assert result is not None
            assert result["desired"] == {"is_on": True}
            assert result["reported"] == {"is_on": False, "brightness": 100}

    @pytest.mark.asyncio
    async def test_get_shadow_empty(self, shadow_manager, mock_shadow_client):
        """Test getting shadow when no state exists."""
        with patch.object(
            shadow_manager, "_get_client", return_value=mock_shadow_client
        ):
            result = await shadow_manager.get_shadow()

            assert result is not None
            assert result["desired"] == {}
            assert result["reported"] == {}


class TestShadowManagerVersion:
    """Tests for shadow versioning."""

    def test_initial_version_is_none(self, shadow_manager):
        """Test that version is None before any operations."""
        assert shadow_manager.version is None
