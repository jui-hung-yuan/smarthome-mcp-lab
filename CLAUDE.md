# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart Home MCP Server for controlling TAPO L530E smart light bulbs through two MCP paths:

- **Local MCP (Claude Desktop)**: FastMCP server runs as a subprocess, controlling the bulb directly over the local network
- **Remote MCP (Claude Web App)**: AgentCore Gateway with Cognito OAuth → Lambda → IoT Core → local bridge → real bulb

Uses the `tapo` Python library for real device control, with automatic fallback to a mock implementation when credentials are unavailable.

## Commands

```bash
# Install dependencies
uv add <package-name>

# Run MCP server (for Claude Desktop integration)
uv run fastmcp run src/smarthome/mcp_servers/light_server.py

# Run in dev mode (interactive testing UI)
uv run fastmcp dev src/smarthome/mcp_servers/light_server.py

# Run IoT Bridge (connects local bulb to AWS IoT Core)
uv run python scripts/run_bridge.py          # real bulb
uv run python scripts/run_bridge.py --mock   # mock bulb

# Provision IoT Bridge Thing and certificates (run once)
uv run python scripts/create_bridge_thing.py

# Run tests
uv run pytest tests/ -v

# Build Lambda package for AgentCore Gateway
uv run python scripts/package_lambda.py

# Provision cloud resources (run in order)
uv run python scripts/create_cognito.py
uv run python scripts/create_lambda.py
uv run python scripts/create_agentcore_gateway.py

# Test gateway connectivity
uv run python scripts/test_gateway.py
```

## Architecture

- **devices/**: Device implementations with common `BaseDevice` interface
  - `base.py`: Abstract base class defining `execute()`, `apply_desired_state()`, `get_shadow_state()`
  - `tapo_bulb.py`: `TapoBulb` (real hardware) and `MockTapoBulb` (testing) implementations
- **mcp_servers/**: FastMCP server definitions that expose tools to Claude Desktop
- **logging/**: State logging (`DynamoStateLogger`) that writes device events to DynamoDB
- **bridge/**: AWS IoT Core integration for remote control via MQTT
  - `device_registry.py`: Manages multiple devices by ID
  - `iot_bridge.py`: Device-agnostic MQTT bridge using `DeviceRegistry`
- **cloud/**: Cloud-side modules for AWS Lambda integration
  - `iot_commands.py`: Generic IoT Core command client (publish MQTT + read shadow)

The `TapoBulb` class persists state to `~/.smarthome/tapo_bulb_state.json`. The MCP server (`light_server.py`) creates a global bulb instance and exposes `turn_on`, `turn_off`, and `get_status` as MCP tools via the `@app.tool()` decorator.

### IoT Bridge

The IoT Bridge (`src/smarthome/bridge/`) enables remote control via AWS IoT Core:

```
Claude (anywhere) → IoT Core MQTT → Local Bridge → Device Registry → Devices
```

The bridge is **device-agnostic**: any device implementing `BaseDevice` can be registered. Commands are routed by `device_id` extracted from the MQTT topic.

**Key components:**
- **config.py**: Loads IoT endpoint and certificate paths from `~/.smarthome/iot/config.json`
- **device_registry.py**: Manages multiple devices by ID for multi-device support
- **shadow_manager.py**: Handles Device Shadow sync (reported/desired state)
- **iot_bridge.py**: MQTT connection, command routing to registered devices, auto-reconnect

**Shadow structure** (multi-device):
```json
{
  "state": {
    "reported": {
      "bridge_connected": true,
      "devices": {
        "tapo-bulb-default": { "is_on": true, "brightness": 80, "color_temp": 2700 }
      }
    }
  }
}
```

See `docs/iot-bridge.md` for full setup instructions.

### AgentCore Gateway (Cloud Path)

The AgentCore Gateway exposes tools as a remote MCP server for Claude web app:

```
Claude Web App → AgentCore Gateway (OAuth/Cognito) → Lambda → IoT Core → Local Bridge → Real Bulb
```

**Key components:**
- **cloud/iot_commands.py**: Stateless functions that publish MQTT commands and read Device Shadow via boto3 `iot-data`
- **lambda_handler.py**: Lambda entry point that maps AgentCore tool invocations to IoT commands
- **scripts/create_cognito.py**: Provisions Cognito User Pool, resource server, two app clients (M2M + Claude web authorization_code), and a Cognito user
- **scripts/create_lambda.py**: Provisions IAM role + Lambda function
- **scripts/create_agentcore_gateway.py**: Provisions gateway with CUSTOM_JWT auth and Lambda target with inline tool schemas
- **scripts/test_gateway.py**: End-to-end connectivity test (OAuth token → MCP initialize → list tools → invoke tool)

**Config files** (in `~/.smarthome/`):
- `cognito_config.json`: M2M client ID/secret, Claude web client ID/secret, discovery URL, token endpoint
- `gateway_config.json`: Gateway ID, URL, ARN

The Lambda handler also accepts `tool_name` in the event body as a fallback for AWS Console testing.

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

### IoT Bridge Setup

To enable remote control via AWS IoT Core:

1. Provision IoT Bridge Thing: `uv run python scripts/create_bridge_thing.py`
2. Start the bridge: `uv run python scripts/run_bridge.py`

The bridge Thing (`smarthome-bridge-{id}`) can manage multiple devices. Its policy allows subscribing to `smarthome/*/commands/*` for any device.

Certificates are stored in `~/.smarthome/iot/`. See `docs/iot-bridge.md` for details.

## Key Patterns

- Tools are defined using FastMCP's `@app.tool()` decorator and return string messages
- Device state is persisted to JSON files in `~/.smarthome/`
- Devices are initialized as module-level globals in server files
- State logging is fire-and-forget: `DynamoStateLogger` catches all exceptions and disables itself after the first failure to avoid repeated retries

## Future Work

### Additional Device Types

The `BaseDevice` pattern makes it easy to add new device types:

1. Create a new device class inheriting from `BaseDevice`
2. Implement `execute()`, `apply_desired_state()`, `get_shadow_state()`
3. Register it in the bridge's `DeviceRegistry`

Example device types to add:
- Smart plugs (on/off only, no brightness)
- Thermostats (temperature, mode)
- Sensors (read-only state)

### Device Discovery

Currently devices are manually registered in `run_bridge.py`. Future enhancement:
- Auto-discover Tapo devices on local network
- Register discovered devices automatically
- Persist device registry to config file