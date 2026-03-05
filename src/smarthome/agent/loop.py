"""AgentLoop: tool-use agent loop with memory and skill dispatch."""

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

import anthropic

from .config import AgentConfig
from .memory.manager import MemoryManager
from .skill_loader import SkillLoader

if TYPE_CHECKING:
    from .scheduler import HeartbeatScheduler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions sent to Claude API
# ---------------------------------------------------------------------------

_NO_REPLY = "NO_REPLY"

_MEMORY_FLUSH_PROMPT = f"""\
Session ended. Review the conversation and decide what's worth recording to the daily log.

Write to the daily log (use memory_write with path "memory/YYYY-MM-DD.md") ONLY if the session contained:
- A new user preference or habit (e.g. "I always want warm light for reading")
- Context that would help future sessions (e.g. schedules, routines, named scenes)
- Something the user explicitly asked to remember

Do NOT record:
- Routine device commands (turn on/off, status check, brightness adjustment)
- Simple one-off requests with no lasting relevance
- Anything already captured in MEMORY.md or USER.md

If nothing is worth recording, reply with exactly: {_NO_REPLY}"""

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "execute_skill",
        "description": (
            "Execute a device-control skill. Use this to control smart home devices. "
            "Always call describe_skill(skill_name) first to load actions and parameters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to invoke (e.g. 'light-control')",
                },
                "action": {
                    "type": "string",
                    "description": "Action to perform (e.g. 'turn_on', 'set_brightness')",
                },
                "params": {
                    "type": "object",
                    "description": "Action parameters (e.g. {\"brightness\": 50})",
                },
            },
            "required": ["skill_name", "action"],
        },
    },
    {
        "name": "memory_search",
        "description": (
            "Search persistent memory for relevant context. "
            "Use this when the user references past conversations, preferences, or prior device states."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 6)",
                    "default": 6,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "describe_skill",
        "description": (
            "Load full documentation for a skill before using it. "
            "Returns supported actions, parameter schemas, and usage examples. "
            "Call once per skill per session. Docs are injected into your active context "
            "automatically and persist — do NOT call again for the same skill."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to describe (e.g. 'light-control')",
                },
            },
            "required": ["skill_name"],
        },
    },
    {
        "name": "schedule_task",
        "description": (
            "Add, remove, or list scheduled automation tasks. "
            "Changes persist across restarts and take effect on the next heartbeat tick."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "remove", "list"],
                    "description": "Operation to perform",
                },
                "name": {
                    "type": "string",
                    "description": "Unique task name (required for add/remove)",
                },
                "hour": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 23,
                    "description": "Hour in 24-hour local time (required for add)",
                },
                "minute": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 59,
                    "description": "Minute (required for add)",
                },
                "skill": {
                    "type": "string",
                    "description": "Skill name to invoke (required for add)",
                },
                "skill_action": {
                    "type": "string",
                    "description": "Skill action to call (required for add)",
                },
                "params": {
                    "type": "object",
                    "description": "Parameters to pass to the skill action",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "memory_write",
        "description": (
            "Write or append to a persistent memory file. "
            "Use this to save user preferences, decisions, or summaries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within ~/.smarthome/memory/ (e.g. 'USER.md')",
                },
                "content": {
                    "type": "string",
                    "description": "Markdown content to write",
                },
                "mode": {
                    "type": "string",
                    "enum": ["append", "overwrite"],
                    "description": "Write mode: 'append' adds to end, 'overwrite' replaces file",
                    "default": "append",
                },
            },
            "required": ["path", "content"],
        },
    },
]


# ---------------------------------------------------------------------------
# SCHEDULE.md helpers
# ---------------------------------------------------------------------------

def _read_schedule_raw(schedule_path) -> list[dict]:
    """Parse the JSON block from SCHEDULE.md and return raw task dicts."""
    from pathlib import Path
    path = Path(schedule_path)
    if not path.exists():
        return []
    text = path.read_text()
    match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return []


def _write_schedule_raw(schedule_path, tasks: list[dict]) -> None:
    """Overwrite the JSON block in SCHEDULE.md with the given task list."""
    from pathlib import Path
    path = Path(schedule_path)
    blob = json.dumps(tasks, indent=2)
    path.write_text(f"# Schedule\n\n```json\n{blob}\n```\n")


# ---------------------------------------------------------------------------
# AgentLoop
# ---------------------------------------------------------------------------

class AgentLoop:
    """Single-session agent loop.

    1. Loads memory context into system prompt
    2. Runs agentic tool-use loop until a final text response
    3. Appends session summary to daily log
    """

    def __init__(
        self,
        config: AgentConfig,
        memory: MemoryManager,
        skills: SkillLoader,
        scheduler: "HeartbeatScheduler | None" = None,
    ):
        self._config = config
        self._memory = memory
        self._skills = skills
        self._scheduler = scheduler
        self._client = anthropic.Anthropic(max_retries=5)
        self._pending_blocks: list | None = None
        self._loaded_skill_docs: dict[str, str] = {}   # skill_name → full body, injected into system prompt

    async def run_session(self) -> None:
        """Interactive CLI session."""
        print("\nSmart Home Agent ready. Type 'exit' or 'quit' to end the session.\n")

        # Pre-load session context for system prompt
        session_context = await self._memory.load_session_context()
        system_prompt = self._build_system_prompt(session_context)

        conversation: list[dict[str, Any]] = []

        while True:
            try:
                user_input = await asyncio.to_thread(input, "> ")
                user_input = user_input.strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if user_input.lower() in ("exit", "quit", ""):
                if user_input.lower() in ("exit", "quit"):
                    break
                continue

            conversation.append({"role": "user", "content": user_input})

            response_text = await self._agent_turn(system_prompt, conversation)

            print(f"\n{response_text}\n")

        # Let Claude decide what (if anything) is worth writing to the daily log
        if conversation:
            await self._flush_memory(system_prompt, conversation)

    async def build_system_prompt(self) -> str:
        """Build the system prompt with current memory context. Call once per session."""
        session_context = await self._memory.load_session_context()
        return self._build_system_prompt(session_context)

    async def turn(
        self,
        system_prompt: str,
        conversation: list[dict],
        user_message: str,
    ) -> str:
        """Append user message, run agent turn, append response. Returns response text."""
        conversation.append({"role": "user", "content": user_message})
        response = await self._agent_turn(system_prompt, conversation)
        return response

    async def flush_memory(
        self,
        system_prompt: str,
        conversation: list[dict[str, Any]],
    ) -> None:
        """Flush session memory to daily log (called on session eviction)."""
        await self._flush_memory(system_prompt, conversation)

    async def _agent_turn(
        self,
        system_prompt: str,
        conversation: list[dict[str, Any]],
    ) -> str:
        """Run the agentic tool-use loop. Mutates conversation in-place (tool calls,
        tool results, final assistant text) so all history persists across turns."""
        self._pending_blocks = None

        while True:
            response = await asyncio.to_thread(
                self._client.messages.create,
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                system=self._effective_system_prompt(system_prompt),
                tools=_TOOLS,
                messages=conversation,
            )

            if response.stop_reason == "end_turn":
                text = self._extract_text(response)
                conversation.append({"role": "assistant", "content": text})
                return text

            if response.stop_reason == "tool_use":
                # Add assistant message with tool calls
                conversation.append({"role": "assistant", "content": response.content})

                # Process each tool call
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    result = await self._dispatch_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })

                conversation.append({"role": "user", "content": tool_results})
            else:
                # Unexpected stop reason; return whatever text we have
                text = self._extract_text(response)
                conversation.append({"role": "assistant", "content": text})
                return text

    async def _dispatch_tool(self, name: str, inputs: dict) -> Any:
        """Dispatch a tool call and return the result dict."""
        logger.debug("Tool call: %s(%s)", name, inputs)

        if name == "execute_skill":
            result = await self._skills.execute(
                skill_name=inputs.get("skill_name", ""),
                action=inputs.get("action", ""),
                params=inputs.get("params") or {},
            )
            if "_slack_blocks" in result:
                self._pending_blocks = result.pop("_slack_blocks")
            # Log device event
            await self._memory.log_device_event(
                device_id=inputs.get("skill_name", "unknown"),
                action=inputs.get("action", "unknown"),
                params=inputs.get("params") or {},
                result=result,
            )
            return result

        elif name == "memory_search":
            results = await self._memory.search(
                query=inputs.get("query", ""),
                max_results=inputs.get("max_results", 6),
            )
            if not results:
                return {"results": [], "message": "No matching memories found."}
            formatted = []
            for r in results:
                formatted.append({
                    "file": r.path,
                    "lines": f"{r.start_line}-{r.end_line}",
                    "snippet": r.text[:500],
                })
            return {"results": formatted}

        elif name == "memory_write":
            await self._memory.write(
                rel_path=inputs.get("path", "MEMORY.md"),
                content=inputs.get("content", ""),
                mode=inputs.get("mode", "append"),
            )
            return {"success": True, "message": f"Written to {inputs.get('path')}"}

        elif name == "describe_skill":
            skill_name = inputs.get("skill_name", "")
            if skill_name in self._loaded_skill_docs:
                return {
                    "success": True,
                    "skill_name": skill_name,
                    "docs": self._loaded_skill_docs[skill_name],
                    "cached": True,
                }
            result = self._skills.describe_skill(skill_name)
            if result.get("success"):
                self._loaded_skill_docs[skill_name] = result["docs"]
            return result

        elif name == "schedule_task":
            return await self._handle_schedule_task(inputs)

        else:
            return {"success": False, "message": f"Unknown tool: {name}"}

    async def _handle_schedule_task(self, inputs: dict) -> Any:
        """Add, remove, or list scheduled tasks in SCHEDULE.md."""
        if self._scheduler is None:
            return {"success": False, "message": "Scheduler is disabled (--no-scheduler)."}

        schedule_path = self._config.memory_dir / "SCHEDULE.md"
        action = inputs.get("action", "")

        # Read existing tasks as raw dicts
        tasks = _read_schedule_raw(schedule_path)

        if action == "list":
            if not tasks:
                return {"success": True, "tasks": [], "message": "No tasks scheduled."}
            rows = [
                f"{t['name']}: {t['hour']:02d}:{t['minute']:02d} → {t['skill']}.{t['action']}({t.get('params', {})})"
                for t in tasks
            ]
            return {"success": True, "tasks": tasks, "message": "\n".join(rows)}

        elif action == "add":
            required = ["name", "hour", "minute", "skill", "skill_action"]
            missing = [f for f in required if f not in inputs]
            if missing:
                return {"success": False, "message": f"Missing required fields: {missing}"}
            name = inputs["name"]
            # Remove existing task with same name if present
            tasks = [t for t in tasks if t.get("name") != name]
            tasks.append({
                "name": name,
                "hour": inputs["hour"],
                "minute": inputs["minute"],
                "skill": inputs["skill"],
                "action": inputs["skill_action"],
                "params": inputs.get("params") or {},
            })
            _write_schedule_raw(schedule_path, tasks)
            return {"success": True, "message": f"Task '{name}' added at {inputs['hour']:02d}:{inputs['minute']:02d}."}

        elif action == "remove":
            name = inputs.get("name", "")
            if not name:
                return {"success": False, "message": "Provide 'name' to remove."}
            before = len(tasks)
            tasks = [t for t in tasks if t.get("name") != name]
            if len(tasks) == before:
                return {"success": False, "message": f"No task named '{name}' found."}
            _write_schedule_raw(schedule_path, tasks)
            return {"success": True, "message": f"Task '{name}' removed."}

        else:
            return {"success": False, "message": f"Unknown schedule action: {action}"}

    def take_pending_blocks(self) -> list | None:
        """Return and clear pending Slack blocks from the last agent turn."""
        blocks = self._pending_blocks
        self._pending_blocks = None
        return blocks

    def _effective_system_prompt(self, base: str) -> str:
        """Return base system prompt extended with any loaded skill docs."""
        if not self._loaded_skill_docs:
            return base
        parts = [base]
        for name, docs in self._loaded_skill_docs.items():
            parts.append(f"## Active Skill Docs: {name}\n\n{docs}")
        return "\n\n".join(parts)

    def _build_system_prompt(self, session_context: str) -> str:
        parts = [
            "You are a smart home assistant. You help control smart home devices "
            "and remember user preferences. Be concise and direct.",
            """\
## Memory Instructions

You have persistent memory across sessions. Use it proactively:

**Write to memory when:**
- The user states a preference (e.g. "I like warm light for movies") → write to `USER.md`
- A fact or routine is worth remembering long-term → write to `MEMORY.md`
- The user asks you to remember something → write to `MEMORY.md` or `USER.md`

**Search memory when:**
- The user references past conversations or preferences (e.g. "like last time")
- You need context that isn't in the current session

**Memory files:**
- `USER.md` — user preferences and working style
- `MEMORY.md` — key facts, decisions, routines
- `memory/YYYY-MM-DD.md` — daily logs (notable events only, not routine commands)

Always append (`mode: append`) unless correcting a specific entry.""",
        ]

        skills_section = self._skills.build_system_prompt_section()
        if skills_section:
            parts.append(skills_section)

        if session_context:
            parts.append(f"## Loaded Memory\n\n{session_context}")

        return "\n\n".join(parts)

    async def _flush_memory(
        self,
        system_prompt: str,
        conversation: list[dict[str, Any]],
    ) -> None:
        """Ask Claude to decide what (if anything) is worth writing to the daily log."""
        from datetime import date
        messages = list(conversation)
        today = date.today().isoformat()
        flush_prompt = _MEMORY_FLUSH_PROMPT.replace("YYYY-MM-DD", today)
        messages.append({"role": "user", "content": flush_prompt})
        try:
            reply = await self._agent_turn(system_prompt, messages)
            if reply.strip().startswith(_NO_REPLY):
                logger.debug("Memory flush: nothing worth recording.")
        except Exception as e:
            logger.warning("Memory flush failed: %s", e)

    @staticmethod
    def _extract_text(response: anthropic.types.Message) -> str:
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return "(no response)"
