"""Tests for HeartbeatScheduler: _load_tasks, _check_tasks, _fire."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smarthome.agent.scheduler import HeartbeatScheduler, ScheduledTask

# ---------------------------------------------------------------------------
# Sample schedule content
# ---------------------------------------------------------------------------

_SCHEDULE_CONTENT = """\
# Schedule

```json
[
  {"name": "dim-7pm",  "hour": 19, "minute": 0,  "skill": "light-control", "action": "set_brightness", "params": {"brightness": 50}},
  {"name": "dim-9pm",  "hour": 21, "minute": 0,  "skill": "light-control", "action": "set_brightness", "params": {"brightness": 25}},
  {"name": "dim-11pm", "hour": 23, "minute": 0,  "skill": "light-control", "action": "set_brightness", "params": {"brightness": 5}}
]
```
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def schedule_file(tmp_path):
    """Write a valid SCHEDULE.md and return the path."""
    p = tmp_path / "SCHEDULE.md"
    p.write_text(_SCHEDULE_CONTENT)
    return p


@pytest.fixture
def mock_skills():
    """AsyncMock SkillLoader.execute returning {"success": True}."""
    skills = MagicMock()
    skills.execute = AsyncMock(return_value={"success": True})
    return skills


@pytest.fixture
def scheduler(mock_skills, schedule_file):
    return HeartbeatScheduler(skills=mock_skills, schedule_path=schedule_file, interval_seconds=1800)


# ---------------------------------------------------------------------------
# TestLoadTasks
# ---------------------------------------------------------------------------

class TestLoadTasks:
    def test_parses_valid_schedule(self, scheduler):
        tasks = scheduler._load_tasks()
        assert len(tasks) == 3
        t = tasks[0]
        assert isinstance(t, ScheduledTask)
        assert t.name == "dim-7pm"
        assert t.hour == 19
        assert t.minute == 0
        assert t.skill == "light-control"
        assert t.action == "set_brightness"
        assert t.params == {"brightness": 50}

    def test_missing_file_returns_empty(self, mock_skills, tmp_path):
        s = HeartbeatScheduler(
            skills=mock_skills,
            schedule_path=tmp_path / "nonexistent.md",
        )
        assert s._load_tasks() == []

    def test_no_json_block_returns_empty(self, mock_skills, tmp_path):
        p = tmp_path / "SCHEDULE.md"
        p.write_text("# Schedule\n\nNo JSON here.\n")
        s = HeartbeatScheduler(skills=mock_skills, schedule_path=p)
        assert s._load_tasks() == []

    def test_invalid_json_returns_empty(self, mock_skills, tmp_path):
        p = tmp_path / "SCHEDULE.md"
        p.write_text("# Schedule\n\n```json\n{not valid json\n```\n")
        s = HeartbeatScheduler(skills=mock_skills, schedule_path=p)
        assert s._load_tasks() == []

    def test_malformed_task_skipped(self, mock_skills, tmp_path):
        """One task missing 'name' key → 2 tasks returned."""
        p = tmp_path / "SCHEDULE.md"
        p.write_text(
            "# Schedule\n\n```json\n"
            + json.dumps([
                {"name": "ok-1", "hour": 10, "minute": 0, "skill": "s", "action": "a"},
                {"hour": 11, "minute": 0, "skill": "s", "action": "a"},  # missing name
                {"name": "ok-2", "hour": 12, "minute": 0, "skill": "s", "action": "a"},
            ])
            + "\n```\n"
        )
        s = HeartbeatScheduler(skills=mock_skills, schedule_path=p)
        tasks = s._load_tasks()
        assert len(tasks) == 2
        assert tasks[0].name == "ok-1"
        assert tasks[1].name == "ok-2"

    def test_mtime_cache_avoids_reparse(self, scheduler, schedule_file):
        """Call _load_tasks twice with same mtime → json.loads called only once."""
        with patch("smarthome.agent.scheduler.json.loads", wraps=json.loads) as mock_loads:
            scheduler._load_tasks()
            scheduler._load_tasks()
        assert mock_loads.call_count == 1


# ---------------------------------------------------------------------------
# TestCheckTasks
# ---------------------------------------------------------------------------

class TestCheckTasks:
    def _make_dt(self, hour, minute):
        return datetime(2026, 3, 5, hour, minute, 0)

    def _task_at(self, hour, minute):
        return ScheduledTask(
            name="test-task",
            hour=hour,
            minute=minute,
            skill="light-control",
            action="set_brightness",
            params={"brightness": 50},
        )

    @pytest.mark.asyncio
    async def test_fires_task_in_window(self, scheduler):
        """since=18:59, now=19:01, task at 19:00 → fired."""
        since = self._make_dt(18, 59)
        now = self._make_dt(19, 1)
        task = self._task_at(19, 0)

        with patch.object(scheduler, "_load_tasks", return_value=[task]):
            with patch.object(scheduler, "_fire", new_callable=AsyncMock) as mock_fire:
                await scheduler._check_tasks(since, now)
        mock_fire.assert_awaited_once_with(task)

    @pytest.mark.asyncio
    async def test_skips_task_before_window(self, scheduler):
        """since=19:01, now=19:30, task at 19:00 → not fired."""
        since = self._make_dt(19, 1)
        now = self._make_dt(19, 30)
        task = self._task_at(19, 0)

        with patch.object(scheduler, "_load_tasks", return_value=[task]):
            with patch.object(scheduler, "_fire", new_callable=AsyncMock) as mock_fire:
                await scheduler._check_tasks(since, now)
        mock_fire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_task_after_window(self, scheduler):
        """since=18:00, now=18:30, task at 19:00 → not fired."""
        since = self._make_dt(18, 0)
        now = self._make_dt(18, 30)
        task = self._task_at(19, 0)

        with patch.object(scheduler, "_load_tasks", return_value=[task]):
            with patch.object(scheduler, "_fire", new_callable=AsyncMock) as mock_fire:
                await scheduler._check_tasks(since, now)
        mock_fire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_boundary_exactly_since(self, scheduler):
        """task_time == since → not fired (exclusive lower bound)."""
        since = self._make_dt(19, 0)
        now = self._make_dt(19, 30)
        task = self._task_at(19, 0)

        with patch.object(scheduler, "_load_tasks", return_value=[task]):
            with patch.object(scheduler, "_fire", new_callable=AsyncMock) as mock_fire:
                await scheduler._check_tasks(since, now)
        mock_fire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_boundary_exactly_now(self, scheduler):
        """task_time == now → fired (inclusive upper bound)."""
        since = self._make_dt(18, 59)
        now = self._make_dt(19, 0)
        task = self._task_at(19, 0)

        with patch.object(scheduler, "_load_tasks", return_value=[task]):
            with patch.object(scheduler, "_fire", new_callable=AsyncMock) as mock_fire:
                await scheduler._check_tasks(since, now)
        mock_fire.assert_awaited_once_with(task)

    @pytest.mark.asyncio
    async def test_multiple_tasks_all_fire(self, scheduler):
        """Two tasks in window → both fired."""
        since = self._make_dt(18, 59)
        now = self._make_dt(21, 1)
        task1 = self._task_at(19, 0)
        task1 = ScheduledTask("t1", 19, 0, "s", "a", {})
        task2 = ScheduledTask("t2", 21, 0, "s", "a", {})

        with patch.object(scheduler, "_load_tasks", return_value=[task1, task2]):
            with patch.object(scheduler, "_fire", new_callable=AsyncMock) as mock_fire:
                await scheduler._check_tasks(since, now)
        assert mock_fire.await_count == 2


# ---------------------------------------------------------------------------
# TestFire
# ---------------------------------------------------------------------------

class TestFire:
    @pytest.mark.asyncio
    async def test_calls_skill_execute(self, scheduler, mock_skills):
        task = ScheduledTask(
            name="dim-7pm",
            hour=19,
            minute=0,
            skill="light-control",
            action="set_brightness",
            params={"brightness": 50},
        )
        await scheduler._fire(task)
        mock_skills.execute.assert_awaited_once_with(
            skill_name="light-control",
            action="set_brightness",
            params={"brightness": 50},
        )

    @pytest.mark.asyncio
    async def test_skill_error_is_isolated(self, scheduler, mock_skills):
        """If skills.execute raises, _fire must not propagate the exception."""
        mock_skills.execute.side_effect = RuntimeError("bulb offline")
        task = ScheduledTask("err-task", 19, 0, "light-control", "turn_on", {})
        # Should not raise
        await scheduler._fire(task)
