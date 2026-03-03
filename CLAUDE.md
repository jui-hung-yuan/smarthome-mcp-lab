# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart home controller for a TAPO L530E bulb. Three control paths are implemented or planned:

| Path | Status | Entry point |
|------|--------|-------------|
| **Local MCP** — FastMCP server, Claude Desktop subprocess | ✅ Done | `src/smarthome/aws_mcp/mcp_servers/light_server.py` |
| **Remote MCP** — AgentCore Gateway + Cognito + Lambda + IoT Core | ✅ Done | `src/smarthome/aws_mcp/lambda_handler.py` |
| **Local Agent** — OpenClaw-inspired, Markdown memory, skills | ✅ Done | `src/smarthome/agent/__main__.py` |

## Repository Structure

```
src/smarthome/
├── devices/              # Shared device layer (used by all paths)
│   ├── base.py           # BaseDevice: execute(), apply_desired_state(), get_shadow_state()
│   ├── device_registry.py # Manages multiple devices by ID
│   └── tapo_bulb.py      # TapoBulb (real hardware) + MockTapoBulb (testing)
├── aws_mcp/              # AWS path: MCP server + Lambda + IoT bridge
│   ├── bridge/           # IoT Core MQTT bridge (config, iot_bridge, shadow_manager)
│   ├── cloud/            # Lambda-side IoT helpers (iot_commands)
│   ├── logging/          # Fire-and-forget DynamoDB state logger
│   ├── mcp_servers/      # FastMCP server (light_server.py)
│   └── lambda_handler.py # AgentCore Gateway Lambda entry point
└── agent/                # Local-first agent loop (CLI)
    ├── __main__.py       # Entry: `python -m smarthome.agent [--mock|--slack]`
    ├── config.py         # AgentConfig: paths, model, mock flag
    ├── loop.py           # AgentLoop: Claude tool-use loop + 3 built-in tools
    ├── skill_loader.py   # Discovers skills/*/SKILL.md, dynamic dispatch
    ├── slack_adapter.py  # Slack channel adapter (Socket Mode, per-thread sessions)
    ├── memory/
    │   ├── manager.py    # MemoryManager: search, write, sync, session context
    │   ├── schema.py     # SQLite schema: files, chunks, FTS5, vec, device_events
    │   ├── chunker.py    # Markdown → overlapping chunks (~400 tokens)
    │   └── embedder.py   # OllamaEmbedder: async HTTP → ollama /api/embed
    └── skills/
        └── light-control/
            ├── SKILL.md  # Skill docs + frontmatter (name, description)
            └── scripts/
                └── bulb.py  # execute(action, params) wraps TapoBulb/MockTapoBulb
```

## Commands

```bash
# Run tests
uv run pytest tests/ -v

# Local MCP dev mode (FastMCP test UI at localhost:6274)
uv run fastmcp dev src/smarthome/aws_mcp/mcp_servers/light_server.py

# IoT Bridge (remote path, requires AWS setup)
uv run python scripts/aws/run_bridge.py --mock   # mock bulb, no hardware needed
uv run python scripts/aws/run_bridge.py          # real bulb

# Build and deploy Lambda
uv run python scripts/aws/package_lambda.py
AWS_PROFILE=self uv run python scripts/aws/create_lambda.py

# Test remote path end-to-end
AWS_PROFILE=self uv run python scripts/aws/test_gateway.py

# Local Agent — CLI
uv run python -m smarthome.agent --mock    # mock bulb, no hardware needed
uv run python -m smarthome.agent           # real bulb (requires TAPO_* in ~/.smarthome/.env)
uv run python -m smarthome.agent --debug   # verbose logging

# Local Agent — Slack (requires SLACK_* in ~/.smarthome/.env)
uv run python -m smarthome.agent --slack --mock
uv run python -m smarthome.agent --slack
```

Full setup instructions for both paths: **[docs/mcp-setup.md](docs/mcp-setup.md)**

## AWS-MCP Path (implemented)

```
Claude Desktop  →  FastMCP subprocess  →  TapoBulb / MockTapoBulb
Claude Web App  →  AgentCore Gateway (Cognito JWT)
                →  Lambda (smarthome-gateway-handler)
                →  IoT Core MQTT
                →  IoT Bridge (local network)
                →  TapoBulb
```

Provisioning scripts in `scripts/aws/` (run in order for first-time setup):
1. `create_bridge_thing.py` — IoT Thing + certificates
2. `create_cognito.py` — User Pool + two OAuth clients
3. `package_lambda.py` + `create_lambda.py` — build zip, deploy Lambda
4. `create_agentcore_gateway.py` — Gateway with Cognito JWT auth

## Local Agent Path (implemented)

A local agent loop with Markdown-based persistent memory and pluggable skills. No cloud dependency — runs entirely on the local machine. Supports two front-ends that share the same `AgentLoop`, memory, and skills:

```
CLI input   →  AgentLoop (loop.py)
Slack input ↗     ├── memory/   ~/.smarthome/memory/
                  └── skills/   light-control → TapoBulb / MockTapoBulb
```

**Front-ends:**
- **CLI** (`--` no flag): interactive REPL, one session per process
- **Slack** (`--slack`): Socket Mode bot; one session per `(channel, thread)`, idle sessions auto-evicted after 30 min with memory flush. In channels, responds only to `@mention`; in DMs, responds to all messages.

**3 built-in tools** Claude can call:
1. `execute_skill(skill_name, action, params)` — dispatches to any loaded skill
2. `memory_search(query)` — hybrid BM25 + vector search (Reciprocal Rank Fusion)
3. `memory_write(path, content, mode)` — persists to Markdown files

**Configuration** (`~/.smarthome/.env`):
- `ANTHROPIC_API_KEY` — required
- `TAPO_USERNAME`, `TAPO_PASSWORD`, `TAPO_IP_ADDRESS` — required for real bulb; omit for `--mock`
- `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_SIGNING_SECRET` — required for `--slack`
- `SLACK_ALLOWED_USERS` — optional comma-separated Slack user IDs allowlist

**Memory storage** (`~/.smarthome/memory/`):
- Markdown files: `MEMORY.md` (facts/routines), `USER.md` (preferences), `SOUL.md` (tone), `YYYY-MM-DD.md` (daily logs)
- SQLite index at `.index/memory.db`: FTS5 (BM25) + optional sqlite-vec (384-dim vectors)
- Embeddings via `ollama pull embeddinggemma` (~622 MB); graceful BM25-only fallback if ollama unavailable

**Mock state** shared across all paths: `~/.smarthome/tapo_bulb_state.json`

**Adding a skill**: drop a folder into `skills/`, write `SKILL.md` + `scripts/*.py` exposing `execute(action, params) → dict`. Zero changes to `loop.py`.

## Key Patterns

- **BaseDevice** (`smarthome.devices.base`): all device implementations expose `execute(action, params)`, `apply_desired_state(state)`, `get_shadow_state()`. The bridge, agent skills, and tests all use this interface.
- **MockTapoBulb**: in-memory implementation with optional JSON state persistence — use in all tests and `--mock` runs.
- **Fire-and-forget logging**: `DynamoStateLogger` catches all exceptions and self-disables after first failure; MCP tools are never blocked by logging.
- **FastMCP tools**: defined with `@app.tool()` decorator, return plain strings.
- **SkillLoader** (`skill_loader.py`): scans `skills/*/SKILL.md` at startup, dynamically imports scripts, builds system prompt section, exposes single `execute_skill` tool to Claude.
- **MemoryManager** (`memory/manager.py`): incremental file sync (hash+mtime), hybrid BM25+vector search with RRF merge, session context loader.
- **OllamaEmbedder** (`memory/embedder.py`): availability checked once on first call; if ollama unreachable, vector search disabled silently, BM25 still works.
- **SlackAdapter** (`slack_adapter.py`): thin transport layer over `AgentLoop`; `AgentLoop.turn()` is the shared entry point for both CLI and Slack. Sessions keyed by `channel:thread_ts`.
