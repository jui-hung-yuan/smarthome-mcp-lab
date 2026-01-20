# Smart Home MCP Lab

A personal learning exercise for exploring MCP (Model Context Protocol) and agent development. Uses smart home control (TAPO L530E light bulbs) as a hands-on example for building and testing MCP servers with Claude Desktop.

## Features

- **Turn lights on/off** via Claude Desktop
- **Get bulb status** (on/off, brightness, color temperature)
- **Persistent state** - bulb state survives server restarts
- **Mock implementation** - test without physical hardware

## Project Structure

```
smarthome/
├── src/
│   └── smarthome/
│       ├── devices/
│       │   └── tapo_bulb.py      # Mock TAPO bulb implementation
│       └── mcp_servers/
│           └── light_server.py    # FastMCP server
├── pyproject.toml
└── README.md
```

## Setup

### 1. Install Dependencies

```bash
uv add fastmcp pydantic
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

1. **Mock Bulb**: The `TapoBulb` class simulates a real TAPO L530E bulb
2. **State Persistence**: Bulb state is saved to `~/.smarthome/tapo_bulb_state.json`
3. **MCP Server**: FastMCP exposes three tools that Claude can use:
   - `turn_on()` - Turn the bulb on
   - `turn_off()` - Turn the bulb off
   - `get_status()` - Get current bulb state
4. **Claude Desktop**: Connects to the MCP server and calls tools based on your requests

## Testing Without Claude Desktop

You can test the MCP server directly:

```bash
uv run fastmcp dev src/smarthome/mcp_servers/light_server.py
```

This opens an interactive testing interface.

## Next Steps

- [ ] Add brightness control
- [ ] Add color temperature control
- [ ] Add RGB color control
- [ ] Replace mock bulb with real `python-kasa` library
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