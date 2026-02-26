# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart home controller for a TAPO L530E bulb. Three control paths are implemented or planned:

| Path | Status | Entry point |
|------|--------|-------------|
| **Local MCP** — FastMCP server, Claude Desktop subprocess | ✅ Done | `src/smarthome/aws_mcp/mcp_servers/light_server.py` |
| **Remote MCP** — AgentCore Gateway + Cognito + Lambda + IoT Core | ✅ Done | `src/smarthome/aws_mcp/lambda_handler.py` |
| **Local Agent** — OpenClaw-inspired, Markdown memory, skills | 🚧 Next | `src/smarthome/agent/` (planned) |

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
└── agent/                # (planned) Local-first agent
    ├── memory/           # Markdown-based conversation memory
    └── skills/           # Pluggable device control skills
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

## Local Agent Path (planned)

Inspired by OpenClaw's architecture: a local agent loop with Markdown-based persistent memory and pluggable skills. No cloud dependency — runs entirely on the local machine.

```
User  →  Agent loop (src/smarthome/agent/)
          ├── memory/     Markdown files, one per topic/session
          │               loaded as context at conversation start
          └── skills/     Pluggable async callables
                          └── bulb_skill.py  ←  wraps smarthome.devices
```

**Bulb control as a skill**: the `TapoBulb` / `MockTapoBulb` implementations in `smarthome.devices` are wrapped as a skill that the agent can call. The skill interface mirrors the existing `execute()` method on `BaseDevice`.

Planned module layout:
```
src/smarthome/agent/
├── __init__.py
├── loop.py          # Main agent loop (read memory → call LLM → run skill → update memory)
├── memory/
│   ├── manager.py   # Load/save/search Markdown memory files
│   └── *.md         # Persisted memory (gitignored)
└── skills/
    ├── base.py      # Skill protocol / abstract interface
    └── bulb_skill.py # Wraps smarthome.devices.TapoBulb
```

## Key Patterns

- **BaseDevice** (`smarthome.devices.base`): all device implementations expose `execute(action, params)`, `apply_desired_state(state)`, `get_shadow_state()`. The bridge, agent skills, and tests all use this interface.
- **MockTapoBulb**: in-memory implementation with optional JSON state persistence — use in all tests and `--mock` runs.
- **Fire-and-forget logging**: `DynamoStateLogger` catches all exceptions and self-disables after first failure; MCP tools are never blocked by logging.
- **FastMCP tools**: defined with `@app.tool()` decorator, return plain strings.
