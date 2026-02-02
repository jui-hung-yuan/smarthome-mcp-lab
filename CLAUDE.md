# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart Home MCP Server for controlling TAPO L530E smart light bulbs through Claude Desktop. Uses the `tapo` Python library for real device control, with automatic fallback to a mock implementation when credentials are unavailable.

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
- **logging/**: State logging (`DynamoStateLogger`) that writes device events to DynamoDB

The `TapoBulb` class persists state to `~/.smarthome/tapo_bulb_state.json`. The MCP server (`light_server.py`) creates a global bulb instance and exposes `turn_on`, `turn_off`, and `get_status` as MCP tools via the `@app.tool()` decorator.

## Setup

To control a real Tapo bulb, create `~/.smarthome/.env` with your credentials:

```
TAPO_USERNAME=your_tapo_email
TAPO_PASSWORD=your_tapo_password
TAPO_IP_ADDRESS=192.168.x.x
```

If this file is missing or the bulb is unreachable, the server automatically falls back to mock mode.

### DynamoDB State Logging

State changes are logged to DynamoDB (table: `smarthome-state-log`). AWS credentials come from the `self` profile in `~/.aws/credentials` (set `AWS_PROFILE=self`).

Environment variables:
- `DYNAMODB_TABLE_NAME` (default: `smarthome-state-log`)
- `AWS_DEFAULT_REGION` (default: `eu-central-1`)

Create the table once:
```bash
uv run python scripts/create_dynamodb_table.py
```

Logging is fire-and-forget: if DynamoDB is unreachable, the logger disables itself and MCP tools continue working normally.

## Key Patterns

- Tools are defined using FastMCP's `@app.tool()` decorator and return string messages
- Device state is persisted to JSON files in `~/.smarthome/`
- Devices are initialized as module-level globals in server files
- State logging is fire-and-forget: `DynamoStateLogger` catches all exceptions and disables itself after the first failure to avoid repeated retries