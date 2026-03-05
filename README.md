# Smart Home MCP Lab

A personal learning exercise for exploring MCP (Model Context Protocol) and agent development. Uses smart home control (TAPO L530E light bulbs) as a hands-on example for building and testing MCP servers and local agents.

## Control Paths

| Path | Status | Description |
|------|--------|-------------|
| **Local MCP** | ✅ Done | FastMCP server as Claude Desktop subprocess, LAN control |
| **Remote MCP** | ✅ Done | AgentCore Gateway + Cognito + Lambda + IoT Core |
| **Local Agent** | ✅ Done | OpenClaw-inspired agent loop with Markdown memory, hybrid search, and device skills |

## Features

### MCP Paths
- **Turn lights on/off**, **set brightness**, **get bulb status** (on/off, brightness, color temp)
- **Real bulb control** via `tapo` library over local network
- **Mock fallback** — automatically uses a mock when credentials are missing or the bulb is unreachable
- **Persistent state** — bulb state survives server restarts
- **DynamoDB state logging** — fire-and-forget, never blocks MCP tools
- **AWS IoT Core integration** — MQTT bridge with Device Shadow for state sync
- **AgentCore Gateway** — remote MCP server with Cognito OAuth for Claude web app
- **Multi-device support** — single bridge manages multiple devices via `DeviceRegistry`
- **Device-agnostic architecture** — `BaseDevice` interface makes adding new device types straightforward

### Local Agent
- **Interactive CLI and Slack bot** — two front-ends sharing the same agent loop, memory, and skills
- **Slack Socket Mode** — per-thread sessions, `@mention` in channels, direct messages; idle sessions auto-evict after 30 min with memory flush
- **Persistent memory, no cloud dependency** — Markdown files + SQLite index, runs entirely on-device
- **Hybrid memory search** — BM25 (FTS5) + vector embeddings (ollama) merged via Reciprocal Rank Fusion
- **Pluggable skills** — drop a folder into `skills/`, write `SKILL.md` — zero changes to the loop
- **Progressive skill disclosure** — only a skill index (name + description) is in the system prompt at startup; full docs load on first use via `describe_skill`, then stay injected for the session
- **Color temperature control** — `set_color_temp` (2500–6500 K) via the agent skill
- **Heartbeat scheduler** — `HeartbeatScheduler` fires time-based automations from `SCHEDULE.md`; Claude manages tasks via the `schedule_task` tool (add/remove/list), changes persist across restarts

## Project Structure

```
src/smarthome/
├── devices/              # Shared device layer (all paths use this)
│   ├── base.py           # BaseDevice ABC: execute(), apply_desired_state(), get_shadow_state()
│   ├── device_registry.py # Manages multiple devices by ID
│   └── tapo_bulb.py      # TapoBulb (real hardware) + MockTapoBulb (testing/fallback)
├── aws_mcp/              # AWS path: Local MCP server + Lambda + IoT bridge
│   ├── bridge/           # IoT Core MQTT bridge (config, iot_bridge, shadow_manager)
│   ├── cloud/            # Lambda-side IoT helpers (iot_commands)
│   ├── logging/          # DynamoDB state logger
│   ├── mcp_servers/      # FastMCP server (light_server.py)
│   └── lambda_handler.py # AgentCore Gateway Lambda entry point
└── agent/                # Local-first agent loop (CLI + Slack)
    ├── __main__.py       # Entry: `python -m smarthome.agent [--mock|--slack]`
    ├── config.py         # AgentConfig: paths, model, mock flag
    ├── loop.py           # AgentLoop: Claude tool-use loop + 5 built-in tools
    ├── scheduler.py      # HeartbeatScheduler: fires SCHEDULE.md tasks on a periodic tick
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

scripts/aws/              # AWS provisioning and operation scripts
docs/                     # Setup guides and architecture notes
tests/                    # Unit tests (188 tests, all passing)
```

## How It Works

### Local MCP (Claude Desktop)

Claude Desktop runs the FastMCP server as a local subprocess:

```
Claude Desktop → FastMCP server (subprocess) → TapoBulb / MockTapoBulb
```

Tools exposed: `turn_on`, `turn_off`, `set_brightness(level)`, `get_status`

On first tool call the server tries to connect to a real bulb using credentials from `~/.smarthome/.env`. Falls back to mock automatically if credentials are missing or the bulb is unreachable.

### Remote MCP (Claude Web App)

```
Claude Web App
  → AgentCore Gateway (Cognito JWT auth)
  → Lambda (smarthome-gateway-handler)
  → IoT Core MQTT
  → IoT Bridge (local network)
  → TapoBulb
```

See [docs/claude-web-oauth.md](docs/claude-web-oauth.md) for the OAuth flow details and [docs/mcp-setup.md](docs/mcp-setup.md) for full provisioning steps.

### Local Agent

An OpenClaw-inspired agent loop that runs entirely locally — no cloud dependency. Two front-ends share the same `AgentLoop`, memory, and skills:

```
CLI input   →  AgentLoop
Slack input ↗     ├── memory/  ~/.smarthome/memory/ — MEMORY.md, USER.md, SOUL.md, daily logs
                  └── skills/  light-control — wraps TapoBulb / MockTapoBulb
```

**Front-ends:**
- **CLI** — interactive REPL, one session per process
- **Slack** (`--slack`) — Socket Mode bot; one session per `(channel, thread)`, responds to `@mention` in channels and all messages in DMs; idle sessions auto-evict after 30 min with memory flush

**5 built-in tools** Claude can call:
1. `execute_skill(skill_name, action, params)` — dispatches to any loaded skill
2. `describe_skill(skill_name)` — loads full skill docs once; injected into system prompt for the session
3. `memory_search(query)` — hybrid BM25 + vector search (Reciprocal Rank Fusion)
4. `memory_write(path, content, mode)` — persists to Markdown files
5. `schedule_task(action, ...)` — add/remove/list scheduled automations in `SCHEDULE.md`

Memory is stored in `~/.smarthome/memory/` as Markdown files (`MEMORY.md`, `USER.md`, `SOUL.md`, daily logs), indexed in SQLite with FTS5 and optional sqlite-vec embeddings. Embeddings use `ollama`; BM25-only fallback if unavailable.

**Adding a skill**: drop a folder under `skills/`, write `SKILL.md` + `scripts/*.py` with `execute(action, params) → dict`. Zero changes to `loop.py`.

### Device Layer

All devices implement `BaseDevice`:
- `execute(action, parameters)` — dispatch any action (turn_on, set_brightness, …)
- `apply_desired_state(desired)` — apply state from IoT Shadow delta
- `get_shadow_state()` — report current state to shadow

`TapoBulb` connects to real hardware. `MockTapoBulb` simulates a bulb in memory, optionally persisting state to `~/.smarthome/tapo_bulb_state.json`.

## Setup

See **[docs/mcp-setup.md](docs/mcp-setup.md)** for full step-by-step instructions covering both paths.

### Quick start — Local MCP

1. Create `~/.smarthome/.env` with bulb credentials (or skip — mock mode works without it):
   ```
   TAPO_USERNAME=your_tapo_email
   TAPO_PASSWORD=your_tapo_password
   TAPO_IP_ADDRESS=192.168.x.x
   ```

2. Add to Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):
   ```json
   {
     "mcpServers": {
       "smarthome": {
         "command": "uv",
         "args": ["run", "--directory", "/path/to/smarthome",
                  "fastmcp", "run",
                  "src/smarthome/aws_mcp/mcp_servers/light_server.py"]
       }
     }
   }
   ```

3. Restart Claude Desktop.

### Quick start — Local Agent

1. Add your Anthropic API key:
   ```bash
   mkdir -p ~/.smarthome
   echo 'ANTHROPIC_API_KEY=sk-...' >> ~/.smarthome/.env
   ```

2. Seed memory files (optional but recommended):
   ```bash
   mkdir -p ~/.smarthome/memory
   echo "# Memory" > ~/.smarthome/memory/MEMORY.md
   echo "# User Preferences" > ~/.smarthome/memory/USER.md
   ```

3. Run with mock bulb (no hardware needed):
   ```bash
   uv run python -m smarthome.agent --mock
   ```

4. Run with real bulb — add `TAPO_USERNAME`, `TAPO_PASSWORD`, `TAPO_IP_ADDRESS` to `~/.smarthome/.env`, then:
   ```bash
   uv run python -m smarthome.agent
   ```

5. Run as a Slack bot — add `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_SIGNING_SECRET` to `~/.smarthome/.env`, then:
   ```bash
   uv run python -m smarthome.agent --slack --mock   # mock bulb
   uv run python -m smarthome.agent --slack          # real bulb
   ```

### Quick start — Remote MCP (AWS)

Run provisioning scripts in order (requires AWS profile `self`):

```bash
AWS_PROFILE=self uv run python scripts/aws/create_bridge_thing.py
AWS_PROFILE=self uv run python scripts/aws/create_cognito.py
uv run python scripts/aws/package_lambda.py
AWS_PROFILE=self uv run python scripts/aws/create_lambda.py
AWS_PROFILE=self uv run python scripts/aws/create_agentcore_gateway.py

# Start the local bridge (keep running on-premises)
uv run python scripts/aws/run_bridge.py

# Test end-to-end
AWS_PROFILE=self uv run python scripts/aws/test_gateway.py
```

## Testing

```bash
# Unit tests
uv run pytest tests/ -v

# Interactive MCP dev UI (localhost:6274)
uv run fastmcp dev src/smarthome/aws_mcp/mcp_servers/light_server.py
```

## Key Dependencies

Dependencies are split so the local agent can be installed without the AWS/MCP stack.

**Core (local agent):**

| Package | Purpose |
|---------|---------|
| `anthropic` | Claude API SDK (agent loop) |
| `tapo` | TAPO device control over local network |
| `slack-bolt` | Slack Socket Mode bot |
| `sqlite-vec` | Vector search extension for SQLite |
| `httpx` | Async HTTP client (ollama embeddings) |
| `aiohttp`, `pydantic`, `python-dotenv` | HTTP, validation, env config |

**`aws-mcp` extra (MCP paths only):**

| Package | Purpose |
|---------|---------|
| `fastmcp` | MCP server framework |
| `boto3` | AWS SDK (DynamoDB, IoT Core, Lambda, Cognito) |
| `awsiotsdk` | AWS IoT Core MQTT client |

**Dev:**

| Package | Purpose |
|---------|---------|
| `moto[dynamodb]` | In-memory AWS mock for tests |
| `pytest`, `pytest-asyncio` | Test runner |

Install for each environment:
```bash
uv sync --no-dev             # Raspberry Pi — local agent only
uv sync --extra aws-mcp      # Dev machine — everything
```

## What's Next

- [x] Local MCP via Claude Desktop
- [x] Remote MCP via AgentCore Gateway + Cognito OAuth
- [x] Multi-device support via `DeviceRegistry`
- [x] Local agent loop with Markdown memory
- [x] Bulb control as an agent skill
- [x] Color temperature control
- [x] Heartbeat scheduler with `SCHEDULE.md` and `schedule_task` tool
- [ ] Additional device types (smart plugs, sensors)
- [ ] Device auto-discovery on local network

## License

MIT
