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

# Run IoT Bridge (connects local bulb to AWS IoT Core)
uv run python scripts/run_bridge.py          # real bulb
uv run python scripts/run_bridge.py --mock   # mock bulb

# Provision IoT Thing and certificates (run once)
uv run python scripts/create_iot_thing.py

# Run tests
uv run pytest tests/ -v
```

## Architecture

- **devices/**: Device implementations (`TapoBulb` for real hardware, `MockTapoBulb` for testing)
- **mcp_servers/**: FastMCP server definitions that expose tools to Claude Desktop
- **logging/**: State logging (`DynamoStateLogger`) that writes device events to DynamoDB
- **bridge/**: AWS IoT Core integration for remote control via MQTT

The `TapoBulb` class persists state to `~/.smarthome/tapo_bulb_state.json`. The MCP server (`light_server.py`) creates a global bulb instance and exposes `turn_on`, `turn_off`, and `get_status` as MCP tools via the `@app.tool()` decorator.

### IoT Bridge

The IoT Bridge (`src/smarthome/bridge/`) enables remote control via AWS IoT Core:

```
Claude (anywhere) → IoT Core MQTT → Local Bridge → TAPO Bulb
```

- **config.py**: Loads IoT endpoint and certificate paths from `~/.smarthome/iot/config.json`
- **shadow_manager.py**: Handles Device Shadow sync (reported/desired state)
- **iot_bridge.py**: MQTT connection, command routing, auto-reconnect

See `docs/iot-bridge.md` for full setup instructions.

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

1. Provision IoT Thing: `uv run python scripts/create_iot_thing.py`
2. Start the bridge: `uv run python scripts/run_bridge.py`

Certificates are stored in `~/.smarthome/iot/`. See `docs/iot-bridge.md` for details.

## Key Patterns

- Tools are defined using FastMCP's `@app.tool()` decorator and return string messages
- Device state is persisted to JSON files in `~/.smarthome/`
- Devices are initialized as module-level globals in server files
- State logging is fire-and-forget: `DynamoStateLogger` catches all exceptions and disables itself after the first failure to avoid repeated retries

## Future Work

### Multi-Device Support (Single Bridge + Registry)

Currently one bridge manages one device. To support multiple devices efficiently:

1. Create `DeviceRegistry` class to manage multiple devices by ID
2. Modify `IoTBridge` to accept a registry instead of a single bulb
3. Use wildcard topic subscription: `smarthome/+/commands/+`
4. Extract `device_id` from topic to route commands to correct device

**Target structure:**
```
src/smarthome/
├── devices/
│   ├── base.py           # Abstract base class for all devices
│   └── ...
├── bridge/
│   ├── device_registry.py # NEW: Manages multiple devices
│   └── iot_bridge.py      # Modified to use registry
```

**Benefits:** Single MQTT connection, single certificate, easier management for 5-10+ devices.

### BaseDevice Pattern (Common Interface)

Currently the bridge has bulb-specific code:
- `_action_handlers` dict and wrapper methods like `_handle_turn_on()`
- `_apply_desired_state()` checks for `is_on`, `brightness` fields
- `_report_current_state()` assumes bulb state structure

Instead, devices should own their actions and state via a common interface:

```python
# devices/base.py
class BaseDevice(ABC):
    @abstractmethod
    async def execute(self, action: str, parameters: dict) -> dict[str, Any]:
        """Execute action, return {"success": bool, "message": str, "state": dict}"""
        pass

    @abstractmethod
    async def apply_desired_state(self, desired: dict[str, Any]) -> None:
        """Apply shadow desired state. Device knows its own state fields."""
        pass

    @abstractmethod
    async def get_shadow_state(self) -> dict[str, Any]:
        """Get current state for shadow reporting."""
        pass

    @property
    @abstractmethod
    def supported_actions(self) -> list[str]:
        """List of actions this device supports."""
        pass
```

Each device implements these methods with its own logic. Bridge becomes a generic router:

```python
# iot_bridge.py (simplified)
async def _handle_command(self, topic, payload):
    device = self._registry.get(device_id)
    result = await device.execute(action, parameters)

async def _apply_desired_state(self, desired):
    device = self._registry.get(device_id)
    await device.apply_desired_state(desired)

async def _report_current_state(self):
    device = self._registry.get(device_id)
    state = await device.get_shadow_state()
    await self._shadow_manager.update_reported(state)
```

**Benefits:**
- Adding new action = edit device only (not bridge)
- Different device types can have different state fields (bulb has brightness, plug doesn't)
- Bridge stays simple and generic