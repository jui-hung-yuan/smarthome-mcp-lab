# Smart Home MCP Lab

A personal learning exercise for exploring MCP (Model Context Protocol) and agent development. Uses smart home control (TAPO L530E light bulbs) as a hands-on example for building and testing MCP servers with Claude Desktop.

## Features

- **Turn lights on/off** via Claude Desktop
- **Get bulb status** (on/off, brightness, color temperature)
- **Persistent state** - bulb state survives server restarts
- **Real bulb control** - connect to a physical TAPO L530E via local network using the `tapo` library
- **Mock fallback** - automatically falls back to a mock implementation when credentials are missing or the bulb is unreachable
- **DynamoDB state logging** - every state change on a real bulb is logged to DynamoDB for historical analysis (fire-and-forget, never breaks MCP tools)
- **AWS IoT Core integration** - remote control via MQTT with Device Shadow for state sync

## Project Structure

```
smarthome/
├── src/
│   └── smarthome/
│       ├── devices/
│       │   └── tapo_bulb.py       # Real + mock TAPO bulb implementations
│       ├── logging/
│       │   └── dynamo_logger.py   # DynamoDB state change logger
│       ├── bridge/
│       │   ├── config.py          # IoT config loader
│       │   ├── shadow_manager.py  # Device Shadow operations
│       │   └── iot_bridge.py      # AWS IoT Core MQTT bridge
│       └── mcp_servers/
│           └── light_server.py    # FastMCP server
├── scripts/
│   ├── create_dynamodb_table.py   # One-time DynamoDB table setup
│   ├── create_iot_thing.py        # IoT Thing provisioning
│   └── run_bridge.py              # IoT Bridge entry point
├── docs/
│   └── iot-bridge.md              # IoT Bridge documentation
├── tests/
│   ├── mocks/                     # Test mocks
│   ├── test_iot_bridge.py         # IoT Bridge tests
│   ├── test_shadow_manager.py     # Shadow manager tests
│   └── ...                        # Other tests
├── pyproject.toml
└── README.md
```

## Setup

### 1. Install Dependencies

```bash
uv add fastmcp pydantic tapo python-dotenv boto3
```

### 2. Configure Claude Desktop

Edit your Claude Desktop config file at:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

Add this configuration:

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

**Important**: Replace `/path/to/your/smarthome` with the absolute path to your project directory.

### 3. Restart Claude Desktop

Quit and restart Claude Desktop completely for the config changes to take effect.

## Usage

Once configured, you can control your light through Claude Desktop with natural language:

- "Turn on my light"
- "Turn off the bulb"
- "What's the status of my light?"
- "Is my light on?"

## How It Works

1. **Real Bulb (`TapoBulb`)**: Connects to a physical TAPO L530E over the local network using the `tapo` library. State is read directly from the device via its HTTP API on each request — no local state file is needed.
2. **Mock Bulb (`MockTapoBulb`)**: Simulates a TAPO bulb for development and testing. State is persisted to `~/.smarthome/tapo_bulb_state.json` so it survives server restarts.
3. **Automatic Fallback**: On first tool call, the server tries to connect to a real bulb using credentials from `~/.smarthome/.env`. If the file is missing, incomplete, or the connection fails, it falls back to the mock. The `get_status` tool reports which mode is active.
4. **MCP Server**: FastMCP exposes tools that Claude can use:
   - `turn_on()` - Turn the bulb on
   - `turn_off()` - Turn the bulb off
   - `set_brightness(level)` - Set brightness (0-100)
   - `get_status()` - Get current bulb state (includes mode: real/mock)
5. **DynamoDB Logging**: When using a real bulb, every `turn_on`, `turn_off`, and `set_brightness` call logs the resulting state to a DynamoDB table. Logging is fire-and-forget — if DynamoDB is unreachable the logger disables itself and tools continue working normally. Mock bulb operations are not logged.
6. **Claude Desktop**: Connects to the MCP server and calls tools based on your requests

## Testing

### Without Claude Desktop

You can test the MCP server directly:

```bash
uv run fastmcp dev src/smarthome/mcp_servers/light_server.py
```

This opens an interactive testing interface where you can call tools and inspect responses.

### Check Bulb Connectivity

If the server falls back to mock mode unexpectedly, use these commands to diagnose network issues:

```bash
# Check if the bulb is reachable on the local network
ping 192.168.178.196

# Verify the route to the bulb's IP goes through the correct network interface
route get 192.168.178.196

# Scan the local subnet to discover connected devices (requires nmap)
nmap -sn 192.168.178.0/24
```

Replace the IP address with your bulb's actual IP. The `tapo` library communicates with the bulb directly over the local network (HTTP on port 80), so the bulb and your machine must be on the same network segment.

### 4. Set Up DynamoDB State Logging (Optional)

State logging requires AWS credentials via the `self` profile in `~/.aws/credentials` and a DynamoDB table.

**Create the table:**

```bash
uv run python scripts/create_dynamodb_table.py
```

This creates a `smarthome-state-log` table with PAY_PER_REQUEST billing and a 30-day TTL.

**Environment variables (all optional):**

| Variable | Default | Description |
|----------|---------|-------------|
| `DYNAMODB_TABLE_NAME` | `smarthome-state-log` | DynamoDB table name |
| `AWS_DEFAULT_REGION` | `eu-central-1` | AWS region |

AWS credentials are read from the `self` profile in `~/.aws/credentials` (not from `~/.smarthome/.env`).

If DynamoDB is not configured, the logger silently disables itself on first failure — no impact on MCP tools.

### 5. Set Up IoT Bridge for Remote Control (Optional)

The IoT Bridge enables remote control via AWS IoT Core MQTT.

**Provision IoT resources:**

```bash
uv run python scripts/create_iot_thing.py
```

This creates an IoT Thing, certificates, and policy in AWS.

**Start the bridge:**

```bash
# With real bulb
uv run python scripts/run_bridge.py

# With mock bulb (for testing)
uv run python scripts/run_bridge.py --mock
```

**Test via AWS CLI:**

```bash
aws iot-data publish \
  --topic "smarthome/tapo-bulb-default/commands/turn_on" \
  --payload '{"request_id":"test-1","parameters":{}}' \
  --cli-binary-format raw-in-base64-out
```

See `docs/iot-bridge.md` for full documentation.

## Next Steps

- [ ] Add color temperature control
- [ ] Add RGB color control
- [ ] Add multiple bulb support
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

# Run server
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
| `boto3` | AWS SDK for DynamoDB state logging |
| `awsiotsdk` | AWS IoT Core MQTT client |
| `moto` (dev) | In-memory AWS mock for testing |

## License

MIT License