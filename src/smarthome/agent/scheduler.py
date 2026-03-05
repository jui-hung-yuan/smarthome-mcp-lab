"""HeartbeatScheduler: periodic task runner for scheduled automations."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .skill_loader import SkillLoader

logger = logging.getLogger(__name__)

_DEFAULT_SCHEDULE = """\
# Schedule

```json
[
  {"name": "dim-7pm",  "hour": 19, "minute": 0, "skill": "light-control", "action": "set_brightness", "params": {"brightness": 50}},
  {"name": "dim-9pm",  "hour": 21, "minute": 0, "skill": "light-control", "action": "set_brightness", "params": {"brightness": 25}},
  {"name": "dim-11pm", "hour": 23, "minute": 0, "skill": "light-control", "action": "set_brightness", "params": {"brightness": 5}}
]
```
"""


@dataclass
class ScheduledTask:
    name: str
    hour: int
    minute: int
    skill: str
    action: str
    params: dict


class HeartbeatScheduler:
    def __init__(
        self,
        skills: SkillLoader,
        schedule_path: Path,
        interval_seconds: int = 1800,
    ) -> None:
        self._skills = skills
        self._schedule_path = schedule_path
        self._interval_seconds = interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None
        # mtime cache to avoid re-parsing unchanged file
        self._cached_mtime: float | None = None
        self._cached_tasks: list[ScheduledTask] = []

    async def run(self) -> None:
        self._running = True
        last_tick = datetime.now()
        logger.info("Heartbeat: started (interval=%ds)", self._interval_seconds)
        while self._running:
            logger.debug("Heartbeat: next tick in %ds", self._interval_seconds)
            try:
                await asyncio.sleep(self._interval_seconds)
            except asyncio.CancelledError:
                break
            now = datetime.now()
            await self._check_tasks(last_tick, now)
            last_tick = now
        logger.info("Heartbeat: stopped")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def peek_tasks(self) -> list[ScheduledTask]:
        """Return current task list (reads file if stale)."""
        return self._load_tasks()

    def _load_tasks(self) -> list[ScheduledTask]:
        """Read and parse SCHEDULE.md; mtime-cached."""
        if not self._schedule_path.exists():
            return []
        mtime = self._schedule_path.stat().st_mtime
        if mtime == self._cached_mtime:
            return self._cached_tasks

        text = self._schedule_path.read_text()
        match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        if not match:
            logger.warning("Heartbeat: no JSON block found in %s", self._schedule_path)
            self._cached_mtime = mtime
            self._cached_tasks = []
            return []

        try:
            raw = json.loads(match.group(1))
        except json.JSONDecodeError as e:
            logger.warning("Heartbeat: failed to parse SCHEDULE.md: %s", e)
            self._cached_mtime = mtime
            self._cached_tasks = []
            return []

        tasks = []
        for item in raw:
            try:
                tasks.append(ScheduledTask(
                    name=item["name"],
                    hour=int(item["hour"]),
                    minute=int(item["minute"]),
                    skill=item["skill"],
                    action=item["action"],
                    params=item.get("params", {}),
                ))
            except (KeyError, ValueError) as e:
                logger.warning("Heartbeat: skipping malformed task %r: %s", item, e)

        self._cached_mtime = mtime
        self._cached_tasks = tasks
        logger.debug("Heartbeat: loaded %d task(s) from %s", len(tasks), self._schedule_path)
        return tasks

    async def _check_tasks(self, since: datetime, now: datetime) -> None:
        for task in self._load_tasks():
            task_time = now.replace(
                hour=task.hour, minute=task.minute, second=0, microsecond=0
            )
            if since < task_time <= now:
                logger.info("Heartbeat: firing '%s'", task.name)
                await self._fire(task)

    async def _fire(self, task: ScheduledTask) -> None:
        try:
            result = await self._skills.execute(
                skill_name=task.skill,
                action=task.action,
                params=task.params,
            )
            logger.info("Heartbeat: '%s' result: %s", task.name, result)
        except Exception as e:
            logger.error("Heartbeat: '%s' failed: %s", task.name, e)
