# Smart Home MCP Lab

A personal learning exercise for exploring MCP (Model Context Protocol) and agent development. Uses smart home control (TAPO L530E light bulbs) as a hands-on example for building and testing MCP servers and local agents.

## Control Paths

| Path | Status | Description |
|------|--------|-------------|
| **Local MCP** | ✅ Done | FastMCP server as Claude Desktop subprocess, LAN control |
| **Remote MCP** | ✅ Done | AgentCore Gateway + Cognito + Lambda + IoT Core |
| **Local Agent** | 🚧 Next | OpenClaw-inspired agent loop with Markdown memory and device skills |

## Features

- **Turn lights on/off**, **set brightness**, **get bulb status** (on/off, brightness, color temp)
- **Real bulb control** via `tapo` library over local network
- **Mock fallback** — automatically uses a mock when credentials are missing or the bulb is unreachable
- **Persistent state** — bulb state survives server restarts
- **DynamoDB state logging** — fire-and-forget, never blocks MCP tools
- **AWS IoT Core integration** — MQTT bridge with Device Shadow for state sync
- **AgentCore Gateway** — remote MCP server with Cognito OAuth for Claude web app
- **Multi-device support** — single bridge manages multiple devices via `DeviceRegistry`
- **Device-agnostic architecture** — `BaseDevice` interface makes adding new device types straightforward

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
└── agent/                # (planned) Local-first agent loop
    ├── memory/           # Markdown-based conversation memory
    └── skills/           # Pluggable device control skills

scripts/aws/              # AWS provisioning and operation scripts
docs/                     # Setup guides and architecture notes
tests/                    # Unit tests (104 tests, all passing)
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

### Local Agent (planned)

An OpenClaw-inspired agent loop that runs entirely locally — no cloud dependency:

```
User → Agent loop
         ├── memory/   Markdown files loaded as context each turn
         └── skills/   Async callables wrapping smarthome.devices
                       └── bulb_skill  ←  TapoBulb / MockTapoBulb
```

The bulb becomes a **skill** the agent can invoke. Memory is persisted as plain Markdown files, one per topic, loaded at conversation start.

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

| Package | Purpose |
|---------|---------|
| `fastmcp` | MCP server framework |
| `tapo` | TAPO device control over local network |
| `boto3` | AWS SDK (DynamoDB, IoT Core, Lambda, Cognito) |
| `awsiotsdk` | AWS IoT Core MQTT client |
| `moto` (dev) | In-memory AWS mock for tests |

## What's Next

- [x] Local MCP via Claude Desktop
- [x] Remote MCP via AgentCore Gateway + Cognito OAuth
- [x] Multi-device support via `DeviceRegistry`
- [ ] Local agent loop with Markdown memory (`src/smarthome/agent/`)
- [ ] Bulb control as an agent skill
- [ ] Color temperature and RGB control
- [ ] Additional device types (smart plugs, sensors)
- [ ] Device auto-discovery on local network

## License

MIT
