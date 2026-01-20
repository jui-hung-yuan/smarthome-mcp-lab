# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart Home MCP Server for controlling TAPO L530E smart light bulbs through Claude Desktop. Currently uses a mock implementation for development/testing.

## Commands

```bash
# Install dependencies
uv add <package-name>

# Run MCP server (for Claude Desktop integration)
uv run fastmcp run src/smarthome/mcp_servers/light_server.py

# Run in dev mode (interactive testing UI)
uv run fastmcp dev src/smarthome/mcp_servers/light_server.py
```

## Architecture

- **devices/**: Device implementations (currently mock `TapoBulb` class)
- **mcp_servers/**: FastMCP server definitions that expose tools to Claude Desktop

The `TapoBulb` class persists state to `~/.smarthome/tapo_bulb_state.json`. The MCP server (`light_server.py`) creates a global bulb instance and exposes `turn_on`, `turn_off`, and `get_status` as MCP tools via the `@app.tool()` decorator.

## Key Patterns

- Tools are defined using FastMCP's `@app.tool()` decorator and return string messages
- Device state is persisted to JSON files in `~/.smarthome/`
- Devices are initialized as module-level globals in server files