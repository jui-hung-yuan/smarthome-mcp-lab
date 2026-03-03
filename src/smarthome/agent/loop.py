"""AgentLoop: tool-use agent loop with memory and skill dispatch."""

import json
import logging
from pathlib import Path
from typing import Any

import anthropic

from .config import AgentConfig
from .memory.manager import MemoryManager
from .skill_loader import SkillLoader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions sent to Claude API
# ---------------------------------------------------------------------------

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "execute_skill",
        "description": (
            "Execute a device-control skill. Use this to control smart home devices. "
            "Check the Available Skills section of the system prompt for valid skill names, "
            "actions, and parameter schemas."
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
                    "description": "Relative path within .agent_memory/ (e.g. 'USER.md')",
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
    ):
        self._config = config
        self._memory = memory
        self._skills = skills
        self._client = anthropic.Anthropic(max_retries=5)

    async def run_session(self) -> None:
        """Interactive CLI session."""
        print("\nSmart Home Agent ready. Type 'exit' or 'quit' to end the session.\n")

        # Pre-load session context for system prompt
        session_context = await self._memory.load_session_context()
        system_prompt = self._build_system_prompt(session_context)

        conversation: list[dict[str, Any]] = []
        session_turns: list[str] = []

        while True:
            try:
                user_input = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if user_input.lower() in ("exit", "quit", ""):
                if user_input.lower() in ("exit", "quit"):
                    break
                continue

            conversation.append({"role": "user", "content": user_input})
            session_turns.append(f"User: {user_input}")

            response_text = await self._agent_turn(system_prompt, conversation)

            print(f"\n{response_text}\n")
            conversation.append({"role": "assistant", "content": response_text})
            session_turns.append(f"Assistant: {response_text[:200]}{'...' if len(response_text) > 200 else ''}")

        # Append session summary
        if session_turns:
            summary = self._summarize_turns(session_turns)
            await self._memory.append_session_summary(summary)

    async def _agent_turn(
        self,
        system_prompt: str,
        conversation: list[dict[str, Any]],
    ) -> str:
        """Run the agentic tool-use loop for one user turn, return final text."""
        messages = list(conversation)

        while True:
            response = self._client.messages.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                system=system_prompt,
                tools=_TOOLS,
                messages=messages,
            )

            if response.stop_reason == "end_turn":
                return self._extract_text(response)

            if response.stop_reason == "tool_use":
                # Add assistant message with tool calls
                messages.append({"role": "assistant", "content": response.content})

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

                messages.append({"role": "user", "content": tool_results})
            else:
                # Unexpected stop reason; return whatever text we have
                return self._extract_text(response)

    async def _dispatch_tool(self, name: str, inputs: dict) -> Any:
        """Dispatch a tool call and return the result dict."""
        logger.debug("Tool call: %s(%s)", name, inputs)

        if name == "execute_skill":
            result = await self._skills.execute(
                skill_name=inputs.get("skill_name", ""),
                action=inputs.get("action", ""),
                params=inputs.get("params") or {},
            )
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

        else:
            return {"success": False, "message": f"Unknown tool: {name}"}

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
- `memory/YYYY-MM-DD.md` — daily logs (written automatically at session end, do not write here directly)

Always append (`mode: append`) unless correcting a specific entry.""",
        ]

        skills_section = self._skills.build_system_prompt_section()
        if skills_section:
            parts.append(skills_section)

        if session_context:
            parts.append(f"## Loaded Memory\n\n{session_context}")

        return "\n\n".join(parts)

    @staticmethod
    def _extract_text(response: anthropic.types.Message) -> str:
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return "(no response)"

    @staticmethod
    def _summarize_turns(turns: list[str]) -> str:
        """Produce a brief bulleted summary from conversation turns."""
        lines = ["### Summary"]
        for turn in turns[:20]:  # cap to avoid huge entries
            lines.append(f"- {turn[:120]}")
        return "\n".join(lines)
