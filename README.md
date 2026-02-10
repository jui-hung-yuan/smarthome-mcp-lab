# Smart Home MCP Lab

A personal learning exercise for exploring MCP (Model Context Protocol) and agent development. Uses smart home control (TAPO L530E light bulbs) as a hands-on example for building and testing MCP servers — both locally via Claude Desktop and remotely via Claude web app.

## Features

- **Two MCP paths** — control lights from Claude Desktop (local) or Claude web app (remote)
- **Turn lights on/off** and **get bulb status** (on/off, brightness, color temperature)
- **Real bulb control** — connect to a physical TAPO L530E via local network using the `tapo` library
- **Mock fallback** — automatically falls back to a mock implementation when credentials are missing or the bulb is unreachable
- **Persistent state** — bulb state survives server restarts
- **DynamoDB state logging** — every state change on a real bulb is logged to DynamoDB (fire-and-forget, never breaks MCP tools)
- **AWS IoT Core integration** — remote control via MQTT with Device Shadow for state sync
- **AgentCore Gateway** — remote MCP server with Cognito OAuth for Claude web app
- **Multi-device support** — single bridge manages multiple devices via `DeviceRegistry`
- **Device-agnostic architecture** — `BaseDevice` interface allows easy addition of new device types

## Project Structure

```
smarthome/
├── src/
│   └── smarthome/
│       ├── devices/
│       │   ├── base.py            # BaseDevice ABC (common interface)
│       │   └── tapo_bulb.py       # Real + mock TAPO bulb implementations
│       ├── logging/
│       │   └── dynamo_logger.py   # DynamoDB state change logger
│       ├── bridge/
│       │   ├── config.py          # IoT config loader
│       │   ├── device_registry.py # Multi-device registry
│       │   ├── shadow_manager.py  # Device Shadow operations
│       │   └── iot_bridge.py      # Device-agnostic MQTT bridge
│       ├── cloud/
│       │   └── iot_commands.py    # IoT Core command client (MQTT + shadow)
│       ├── mcp_servers/
│       │   └── light_server.py    # FastMCP server (local MCP)
│       └── lambda_handler.py      # Lambda entry point (remote MCP)
├── scripts/
│   ├── create_dynamodb_table.py       # One-time DynamoDB table setup
│   ├── create_bridge_thing.py         # IoT Bridge Thing provisioning
│   ├── run_bridge.py                  # IoT Bridge entry point
│   ├── create_cognito.py              # Cognito User Pool + OAuth clients
│   ├── create_lambda.py               # Lambda function provisioning
│   ├── create_agentcore_gateway.py    # AgentCore Gateway provisioning
│   ├── package_lambda.py              # Build Lambda deployment package
│   └── test_gateway.py                # End-to-end gateway connectivity test
├── docs/
│   ├── iot-bridge.md              # IoT Bridge documentation
│   └── claude-web-oauth.md        # Claude web app OAuth integration notes
├── tests/
│   ├── mocks/                     # Test mocks
│   ├── test_base_device.py        # BaseDevice interface tests
│   ├── test_device_registry.py    # DeviceRegistry tests
│   ├── test_iot_bridge.py         # IoT Bridge tests
│   ├── test_iot_commands.py       # IoT Core command client tests
│   ├── test_lambda_handler.py     # Lambda handler tests
│   ├── test_shadow_manager.py     # Shadow manager tests
│   └── ...                        # Other tests
├── pyproject.toml
└── README.md
```

## How It Works

### Local MCP (Claude Desktop)

Claude Desktop runs the FastMCP server as a local subprocess and calls tools directly:

```
Claude Desktop → FastMCP Server (subprocess) → TapoBulb → Real Bulb (local network)
                                              → MockTapoBulb (fallback)
```

The MCP server exposes these tools:
- `turn_on()` / `turn_off()` — control the bulb
- `set_brightness(level)` — set brightness (0-100)
- `get_status()` — get current bulb state (includes mode: real/mock)

On first tool call, the server tries to connect to a real bulb using credentials from `~/.smarthome/.env`. If the file is missing or the connection fails, it falls back to the mock.

### Remote MCP (Claude Web App)

Claude web app connects through the cloud path via AgentCore Gateway:

```
Claude Web App → Cognito (OAuth) → AgentCore Gateway → Lambda → IoT Core → Local Bridge → Real Bulb
```

Each component's role:
- **Cognito** — OAuth authentication (authorization_code flow for Claude web, client_credentials for testing)
- **AgentCore Gateway** — remote MCP server that validates JWT tokens and routes tool calls to Lambda
- **Lambda** — stateless handler that maps MCP tool invocations to IoT Core MQTT commands
- **IoT Core** — MQTT broker that routes commands to the local bridge
- **Local Bridge** — runs on-premises, receives MQTT commands and controls devices via `DeviceRegistry`

See `docs/claude-web-oauth.md` for OAuth integration details and `docs/iot-bridge.md` for bridge details.

### Device Layer

All devices implement a common `BaseDevice` abstract class with:
- `execute(action, parameters)` — execute any action (turn_on, set_brightness, etc.)
- `apply_desired_state(desired)` — apply state from IoT Shadow
- `get_shadow_state()` — get current state for shadow reporting

**TapoBulb** connects to a physical TAPO L530E over the local network. **MockTapoBulb** simulates a bulb for development, persisting state to `~/.smarthome/tapo_bulb_state.json`.

### DynamoDB Logging

When using a real bulb, every state change is logged to a DynamoDB table. Logging is fire-and-forget — if DynamoDB is unreachable the logger disables itself and tools continue working normally. Mock bulb operations are not logged.

## Setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/) for dependency management
- AWS credentials via the `self` profile in `~/.aws/credentials` (for DynamoDB, IoT Core, Lambda, Cognito, AgentCore)

### Device Setup

Create `~/.smarthome/.env` with your Tapo credentials:

```
TAPO_USERNAME=your_tapo_email
TAPO_PASSWORD=your_tapo_password
TAPO_IP_ADDRESS=192.168.x.x
```

If this file is missing or the bulb is unreachable, the server automatically falls back to mock mode.

### Local MCP Setup (Claude Desktop)

1. Install dependencies:

```bash
uv add fastmcp pydantic tapo python-dotenv boto3
```

2. Edit your Claude Desktop config file at:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "tapo-light": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/your/smarthome",
        "run",
        "fastmcp",
        "run",
        "src/smarthome/mcp_servers/light_server.py"
      ]
    }
  }
}
```

3. Restart Claude Desktop.

### Remote MCP Setup (Claude Web App)

Provision cloud resources in this order:

**1. DynamoDB table (optional — state logging):**

```bash
uv run python scripts/create_dynamodb_table.py
```

**2. IoT Bridge Thing + start bridge:**

```bash
uv run python scripts/create_bridge_thing.py
uv run python scripts/run_bridge.py          # real bulb
uv run python scripts/run_bridge.py --mock   # mock bulb (testing)
```

**3. Cognito (user pool, both OAuth clients, user):**

```bash
uv run python scripts/create_cognito.py
```

Creates an M2M client (for `test_gateway.py`) and a Claude web client (for Claude's MCP connector). Saves config to `~/.smarthome/cognito_config.json`.

**4. Lambda:**

```bash
uv run python scripts/package_lambda.py
uv run python scripts/create_lambda.py
```

**5. AgentCore Gateway:**

```bash
uv run python scripts/create_agentcore_gateway.py
```

**6. Connect from Claude web app:**

Add the gateway URL as an MCP connector in Claude web app settings. Use the Claude web client ID and secret from `~/.smarthome/cognito_config.json` for OAuth.

## Testing

### Local Testing

Test the MCP server interactively (no Claude Desktop needed):

```bash
uv run fastmcp dev src/smarthome/mcp_servers/light_server.py
```

### Remote Testing

End-to-end connectivity test (OAuth token → MCP initialize → list tools → invoke tool):

```bash
uv run python scripts/test_gateway.py
```

### Unit Tests

```bash
uv run pytest tests/ -v
```

### Check Bulb Connectivity

If the server falls back to mock mode unexpectedly:

```bash
# Check if the bulb is reachable on the local network
ping 192.168.178.196

# Verify the route to the bulb's IP
route get 192.168.178.196

# Scan the local subnet (requires nmap)
nmap -sn 192.168.178.0/24
```

Replace the IP address with your bulb's actual IP.

## Next Steps

- [x] ~~Add multiple bulb support~~ (Done: `DeviceRegistry` + device-agnostic bridge)
- [x] ~~IoT Bridge for remote control~~ (Done: MQTT bridge with Device Shadow)
- [x] ~~AgentCore Gateway + Claude web app~~ (Done: OAuth with Cognito, see `docs/claude-web-oauth.md`)
- [ ] Add color temperature control
- [ ] Add RGB color control
- [ ] Add additional device types (smart plugs, sensors)
- [ ] Add device auto-discovery on local network
- [ ] Add scenes/routines

## Troubleshooting

### Server not appearing in Claude Desktop

1. Check the config file path is correct
2. Ensure the `command` path points to your project
3. Check Claude Desktop logs (Help → View Logs)
4. Restart Claude Desktop

### State file location

The bulb state is saved to `~/.smarthome/tapo_bulb_state.json`. You can:
- View it to see current state
- Delete it to reset to defaults
- Edit it manually for testing

## Development

### Project uses UV for dependency management

```bash
# Add new dependency
uv add package-name

# Run local MCP server
uv run fastmcp run src/smarthome/mcp_servers/light_server.py

# Run with dev mode (interactive testing)
uv run fastmcp dev src/smarthome/mcp_servers/light_server.py

# Run tests
uv run pytest tests/ -v
```

### Key Dependencies

| Package | Purpose |
|---------|---------|
| `fastmcp` | MCP server framework |
| `tapo` | TAPO device control over local network |
| `boto3` | AWS SDK for DynamoDB, IoT Core, Lambda, Cognito |
| `awsiotsdk` | AWS IoT Core MQTT client |
| `moto` (dev) | In-memory AWS mock for testing |

## License

MIT License
