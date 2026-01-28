"""Shared fixtures for smart home tests."""

import pytest

from smarthome.devices import MockTapoBulb


@pytest.fixture
def tmp_state_file(tmp_path):
    """Provide a temporary state file path that doesn't touch ~/.smarthome/."""
    return tmp_path / "tapo_bulb_state.json"


@pytest.fixture
def mock_bulb(tmp_state_file):
    """Return a MockTapoBulb backed by a temporary state file."""
    return MockTapoBulb(state_file=tmp_state_file)
