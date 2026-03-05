"""Tests for schedule_task tool: _handle_schedule_task, _read_schedule_raw, _write_schedule_raw."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smarthome.agent.loop import AgentLoop, _read_schedule_raw, _write_schedule_raw
from smarthome.agent.config import AgentConfig


# ---------------------------------------------------------------------------
# Helpers: _read_schedule_raw / _write_schedule_raw
# ---------------------------------------------------------------------------

def test_round_trip(tmp_path):
    tasks = [
        {"name": "dim-7pm", "hour": 19, "minute": 0, "skill": "s", "action": "a", "params": {}},
        {"name": "dim-9pm", "hour": 21, "minute": 0, "skill": "s", "action": "a", "params": {}},
    ]
    p = tmp_path / "SCHEDULE.md"
    _write_schedule_raw(p, tasks)
    result = _read_schedule_raw(p)
    assert result == tasks


def test_read_missing_file(tmp_path):
    assert _read_schedule_raw(tmp_path / "nonexistent.md") == []


def test_read_invalid_json(tmp_path):
    p = tmp_path / "SCHEDULE.md"
    p.write_text("# Schedule\n\n```json\n{bad json\n```\n")
    assert _read_schedule_raw(p) == []


def test_write_creates_markdown_format(tmp_path):
    p = tmp_path / "SCHEDULE.md"
    _write_schedule_raw(p, [{"name": "t", "hour": 9, "minute": 0}])
    text = p.read_text()
    assert text.startswith("# Schedule")
    assert "```json" in text


# ---------------------------------------------------------------------------
# Fixture: minimal AgentLoop with mocked dependencies
# ---------------------------------------------------------------------------

@pytest.fixture
def loop_factory(tmp_path):
    """Return a factory that builds an AgentLoop with mocked internals.

    Usage: loop_factory() → AgentLoop (scheduler enabled by default)
           loop_factory(scheduler=None) → scheduler disabled
    """
    def _make(scheduler=MagicMock(), tasks=None):
        config = AgentConfig(memory_dir=tmp_path / "memory")
        config.memory_dir.mkdir(parents=True, exist_ok=True)

        # Pre-populate SCHEDULE.md if tasks given
        if tasks is not None:
            _write_schedule_raw(config.memory_dir / "SCHEDULE.md", tasks)

        memory = MagicMock()
        skills = MagicMock()

        with patch("smarthome.agent.loop.anthropic.Anthropic"):
            loop = AgentLoop(config=config, memory=memory, skills=skills, scheduler=scheduler)
        return loop

    return _make


# ---------------------------------------------------------------------------
# TestHandleScheduleTask
# ---------------------------------------------------------------------------

class TestHandleScheduleTask:

    @pytest.mark.asyncio
    async def test_list_empty(self, loop_factory):
        loop = loop_factory(tasks=[])
        result = await loop._handle_schedule_task({"action": "list"})
        assert result["success"] is True
        assert result["tasks"] == []

    @pytest.mark.asyncio
    async def test_list_returns_tasks(self, loop_factory):
        tasks = [
            {"name": "dim-7pm", "hour": 19, "minute": 0, "skill": "s", "action": "a", "params": {}},
            {"name": "dim-9pm", "hour": 21, "minute": 0, "skill": "s", "action": "a", "params": {}},
        ]
        loop = loop_factory(tasks=tasks)
        result = await loop._handle_schedule_task({"action": "list"})
        assert result["success"] is True
        assert "dim-7pm" in result["message"]
        assert "dim-9pm" in result["message"]

    @pytest.mark.asyncio
    async def test_add_creates_task(self, loop_factory):
        loop = loop_factory(tasks=[])
        result = await loop._handle_schedule_task({
            "action": "add",
            "name": "evening-dim",
            "hour": 20,
            "minute": 30,
            "skill": "light-control",
            "skill_action": "set_brightness",
            "params": {"brightness": 40},
        })
        assert result["success"] is True
        schedule_path = loop._config.memory_dir / "SCHEDULE.md"
        persisted = _read_schedule_raw(schedule_path)
        assert any(t["name"] == "evening-dim" for t in persisted)

    @pytest.mark.asyncio
    async def test_add_replaces_same_name(self, loop_factory):
        existing = [{"name": "dup", "hour": 10, "minute": 0, "skill": "s", "action": "a", "params": {}}]
        loop = loop_factory(tasks=existing)
        await loop._handle_schedule_task({
            "action": "add",
            "name": "dup",
            "hour": 11,
            "minute": 0,
            "skill": "light-control",
            "skill_action": "turn_on",
        })
        persisted = _read_schedule_raw(loop._config.memory_dir / "SCHEDULE.md")
        dup_tasks = [t for t in persisted if t["name"] == "dup"]
        assert len(dup_tasks) == 1
        assert dup_tasks[0]["hour"] == 11

    @pytest.mark.asyncio
    async def test_add_missing_required_fields(self, loop_factory):
        loop = loop_factory(tasks=[])
        result = await loop._handle_schedule_task({
            "action": "add",
            "name": "incomplete",
            # missing hour, minute, skill, skill_action
        })
        assert result["success"] is False
        assert "hour" in result["message"] or "Missing" in result["message"]

    @pytest.mark.asyncio
    async def test_remove_existing(self, loop_factory):
        tasks = [{"name": "to-remove", "hour": 9, "minute": 0, "skill": "s", "action": "a", "params": {}}]
        loop = loop_factory(tasks=tasks)
        result = await loop._handle_schedule_task({"action": "remove", "name": "to-remove"})
        assert result["success"] is True
        persisted = _read_schedule_raw(loop._config.memory_dir / "SCHEDULE.md")
        assert not any(t["name"] == "to-remove" for t in persisted)

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, loop_factory):
        loop = loop_factory(tasks=[])
        result = await loop._handle_schedule_task({"action": "remove", "name": "ghost"})
        assert result["success"] is False
        assert "ghost" in result["message"]

    @pytest.mark.asyncio
    async def test_scheduler_disabled(self, loop_factory):
        loop = loop_factory(scheduler=None)
        result = await loop._handle_schedule_task({"action": "list"})
        assert result["success"] is False
        assert "disabled" in result["message"].lower() or "scheduler" in result["message"].lower()
