# Smart Home MCP Lab

A personal learning exercise for exploring MCP (Model Context Protocol) and agent development. Uses smart home control (TAPO L530E light bulbs) as a hands-on example for building and testing MCP servers with Claude Desktop.

## Features

- **Turn lights on/off** via Claude Desktop
- **Get bulb status** (on/off, brightness, color temperature)
- **Persistent state** - bulb state survives server restarts
- **Real bulb control** - connect to a physical TAPO L530E via local network using the `tapo` library
- **Mock fallback** - automatically falls back to a mock implementation when credentials are missing or the bulb is unreachable

## Project Structure

```
smarthome/
├── src/
│   └── smarthome/
│       ├── devices/
│       │   └── tapo_bulb.py      # Real + mock TAPO bulb implementations
│       └── mcp_servers/
│           └── light_server.py    # FastMCP server
├── pyproject.toml
└── README.md
```

## Setup

### 1. Install Dependencies

```bash
uv add fastmcp pydantic tapo python-dotenv
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
4. **MCP Server**: FastMCP exposes three tools that Claude can use:
   - `turn_on()` - Turn the bulb on
   - `turn_off()` - Turn the bulb off
   - `get_status()` - Get current bulb state (includes mode: real/mock)
5. **Claude Desktop**: Connects to the MCP server and calls tools based on your requests

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

## Next Steps

- [ ] Add brightness control
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
```

## License

MIT License