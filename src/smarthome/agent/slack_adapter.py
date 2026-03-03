"""Slack channel adapter for the SmartHome agent.

One SlackSession per (channel_id, thread_ts) key — isolated history,
shared system_prompt, shared AgentLoop / MemoryManager / SkillLoader.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from .loop import AgentLoop

logger = logging.getLogger(__name__)


@dataclass
class SlackAdapterConfig:
    bot_token: str
    app_token: str
    signing_secret: str
    allowed_users: list[str] | None = None
    session_ttl_minutes: int = 30


@dataclass
class SlackSession:
    system_prompt: str
    history: list[dict[str, Any]] = field(default_factory=list)
    last_active: float = field(default_factory=time.monotonic)


class SlackAdapter:
    def __init__(self, loop: AgentLoop, config: SlackAdapterConfig) -> None:
        self._loop = loop
        self._config = config
        self._sessions: dict[str, SlackSession] = {}
        self._sessions_lock = asyncio.Lock()

        self._app = AsyncApp(
            token=config.bot_token,
            signing_secret=config.signing_secret,
        )
        # In channels/groups: only respond when @mentioned.
        # In DMs (channel_type "im"): respond to every message (no @mention needed).
        self._app.event("app_mention")(self._on_message)
        self._app.event("message")(self._on_dm)

    async def start(self) -> None:
        """Start Socket Mode handler and idle cleanup task."""
        asyncio.create_task(self._evict_idle_sessions())
        handler = AsyncSocketModeHandler(self._app, self._config.app_token)
        await handler.start_async()

    async def _on_dm(self, event: dict[str, Any], say: Any) -> None:
        """Handle message events — only act in direct messages (channel_type=im)."""
        if event.get("channel_type") != "im":
            return
        await self._on_message(event, say)

    async def _on_message(self, event: dict[str, Any], say: Any) -> None:
        # Skip bot messages and edits/deletions
        if event.get("bot_id") or event.get("subtype"):
            return

        user = event.get("user", "")
        if self._config.allowed_users and user not in self._config.allowed_users:
            logger.debug("Ignoring message from unlisted user %s", user)
            return

        text: str = event.get("text", "").strip()
        if not text:
            return

        channel: str = event.get("channel", "")
        thread_ts: str = event.get("thread_ts") or event["ts"]
        session_key = f"{channel}:{thread_ts}"

        session = await self._get_session(session_key)
        session.last_active = time.monotonic()

        try:
            response = await self._loop.turn(session.system_prompt, session.history, text)
        except Exception as e:
            logger.exception("AgentLoop.turn() failed: %s", e)
            response = "Sorry, something went wrong. Please try again."

        await say(text=response, thread_ts=thread_ts)

    async def _get_session(self, key: str) -> SlackSession:
        async with self._sessions_lock:
            if key not in self._sessions:
                system_prompt = await self._loop.build_system_prompt()
                self._sessions[key] = SlackSession(system_prompt=system_prompt)
                logger.debug("Created new session: %s", key)
            return self._sessions[key]

    async def _evict_idle_sessions(self) -> None:
        ttl_seconds = self._config.session_ttl_minutes * 60
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            async with self._sessions_lock:
                stale = [k for k, s in self._sessions.items() if now - s.last_active > ttl_seconds]
            for key in stale:
                async with self._sessions_lock:
                    session = self._sessions.pop(key, None)
                if session and session.history:
                    logger.debug("Evicting idle session %s, flushing memory", key)
                    try:
                        await self._loop.flush_memory(session.system_prompt, session.history)
                    except Exception as e:
                        logger.warning("Memory flush failed for session %s: %s", key, e)
