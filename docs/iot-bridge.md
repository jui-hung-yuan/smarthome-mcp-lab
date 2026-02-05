# IoT Bridge - AWS IoT Core Integration

The IoT Bridge connects your local smart home devices to AWS IoT Core, enabling remote control from anywhere via MQTT.

## Architecture

```
Future Flow:
Claude (anywhere) → Lambda MCP Server → IoT Core → Local Bridge → TAPO Bulb
                                              ↓
                                      Device Shadow (state sync)
```

The Local Bridge runs on your home network and:
1. Connects to AWS IoT Core via MQTT (TLS on port 8883)
2. Subscribes to command topics
3. Executes commands on the local TAPO bulb
4. Publishes responses and updates Device Shadow

## Topic Design

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `smarthome/{device_id}/commands/{action}` | Cloud → Bridge | Command requests |
| `smarthome/{device_id}/responses/{request_id}` | Bridge → Cloud | Command responses |
| `$aws/things/{thing}/shadow/update` | Bridge → AWS | Report device state |
| `$aws/things/{thing}/shadow/update/delta` | AWS → Bridge | Desired state changes |

### Command Payload

```json
{
  "request_id": "uuid-v4",
  "timestamp": "ISO-8601",
  "parameters": { "brightness": 75 }
}
```

### Response Payload

```json
{
  "request_id": "uuid-v4",
  "success": true,
  "message": "Bulb turned on",
  "state": { "is_on": true, "brightness": 100, "color_temp": 2700 }
}
```

## Setup

### 1. Provision IoT Resources

Run the provisioning script to create the IoT Thing, certificates, and policy:

```bash
uv run python scripts/create_iot_thing.py
```

This creates:
- IoT Thing: `tapo-bulb-default`
- X.509 certificates in `~/.smarthome/iot/tapo-bulb-default/`
- IoT Policy with minimal permissions
- Config file: `~/.smarthome/iot/config.json`

### 2. Start the Bridge

```bash
# With real bulb (uses credentials from ~/.smarthome/.env)
uv run python scripts/run_bridge.py

# With mock bulb (for testing without hardware)
uv run python scripts/run_bridge.py --mock

# With debug logging
uv run python scripts/run_bridge.py --debug
```

### 3. Test via AWS CLI

```bash
# Send a turn_on command
aws iot-data publish \
  --topic "smarthome/tapo-bulb-default/commands/turn_on" \
  --payload '{"request_id":"test-1","parameters":{}}' \
  --cli-binary-format raw-in-base64-out

# Send a set_brightness command
aws iot-data publish \
  --topic "smarthome/tapo-bulb-default/commands/set_brightness" \
  --payload '{"request_id":"test-2","parameters":{"brightness":50}}' \
  --cli-binary-format raw-in-base64-out
```

### 4. Check Device Shadow

View the Device Shadow in AWS Console:
- IoT Core → Things → tapo-bulb-default → Device Shadows → Classic Shadow

Or via CLI:
```bash
aws iot-data get-thing-shadow \
  --thing-name tapo-bulb-default \
  /dev/stdout | jq
```

## Device Shadow Schema

```json
{
  "state": {
    "desired": { "is_on": true, "brightness": 75 },
    "reported": {
      "is_on": true,
      "brightness": 75,
      "color_temp": 2700,
      "bridge_connected": true,
      "device_reachable": true
    }
  }
}
```

## Configuration

### Config File

Located at `~/.smarthome/iot/config.json`:

```json
{
  "endpoint": "xxxxx.iot.region.amazonaws.com",
  "thing_name": "tapo-bulb-default",
  "device_id": "tapo-bulb-default",
  "cert_path": "/Users/you/.smarthome/iot/tapo-bulb-default/certificate.pem",
  "key_path": "/Users/you/.smarthome/iot/tapo-bulb-default/private.key",
  "root_ca_path": "/Users/you/.smarthome/iot/tapo-bulb-default/AmazonRootCA1.pem"
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `IOT_ENDPOINT` | from config.json | AWS IoT Core endpoint |
| `IOT_THING_NAME` | `tapo-bulb-default` | IoT Thing name |
| `IOT_CONFIG_PATH` | `~/.smarthome/iot/config.json` | Config file location |

## Certificate Storage

```
~/.smarthome/iot/
├── config.json              # Endpoint, thing name, cert paths
└── tapo-bulb-default/
    ├── certificate.pem      # Device certificate
    ├── private.key          # Private key (chmod 600)
    └── AmazonRootCA1.pem    # Amazon Root CA
```

## Supported Commands

| Action | Parameters | Description |
|--------|------------|-------------|
| `turn_on` | none | Turn the bulb on |
| `turn_off` | none | Turn the bulb off |
| `get_status` | none | Get current state |
| `set_brightness` | `brightness: 0-100` | Set brightness level |

## Security

- Private keys stored with `600` permissions (owner read/write only)
- `~/.smarthome/iot/` directory should not be committed to git
- IoT policy uses least privilege (specific topic prefixes only)
- All MQTT traffic encrypted via TLS (port 8883)

## Troubleshooting

### Bridge won't connect

1. Check certificates exist: `ls -la ~/.smarthome/iot/tapo-bulb-default/`
2. Verify endpoint: `aws iot describe-endpoint --endpoint-type iot:Data-ATS`
3. Check policy is attached: `aws iot list-attached-policies --target <cert-arn>`

### Commands not reaching bridge

1. Check bridge is running and subscribed (look for "Subscribed to command topic" in logs)
2. Verify topic name matches: `smarthome/{device_id}/commands/{action}`
3. Test with AWS IoT Console MQTT test client

### Shadow not updating

1. Check bridge logs for shadow update errors
2. Verify shadow policy permissions include `$aws/things/{thing}/shadow/*`

## Module Structure

```
src/smarthome/bridge/
├── __init__.py           # Exports IoTBridge, ShadowManager, IoTConfig
├── config.py             # Configuration loader
├── shadow_manager.py     # Device Shadow operations
└── iot_bridge.py         # Main bridge implementation

scripts/
├── create_iot_thing.py   # IoT provisioning script
└── run_bridge.py         # Bridge entry point
```
