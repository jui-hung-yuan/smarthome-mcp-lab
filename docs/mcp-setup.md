# MCP Server Setup

Two MCP integration paths are implemented. Both ultimately control the same TAPO L530E bulb.

---

## Path 1: Local MCP (Claude Desktop)

FastMCP server runs as a subprocess on your machine and talks to the bulb directly over the local network.

```
Claude Desktop → subprocess → FastMCP server → TAPO bulb (LAN)
```

### Prerequisites

- Python 3.10+ with `uv`
- TAPO L530E bulb on the same network (or skip for mock mode)

### Setup

**1. Create bulb credentials** (skip for mock mode):

```
~/.smarthome/.env
```
```
TAPO_USERNAME=your_tapo_email
TAPO_PASSWORD=your_tapo_password
TAPO_IP_ADDRESS=192.168.x.x
```

If this file is missing or the bulb is unreachable, the server falls back to a mock automatically.

**2. Register with Claude Desktop** — add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "smarthome": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/smarthome",
        "fastmcp",
        "run",
        "src/smarthome/aws_mcp/mcp_servers/light_server.py"
      ]
    }
  }
}
```

**3. (Optional) Interactive dev mode** — launches FastMCP's test UI at `http://localhost:6274`:

```bash
uv run fastmcp dev src/smarthome/aws_mcp/mcp_servers/light_server.py
```

### DynamoDB State Logging (optional)

State changes are optionally logged to DynamoDB (`smarthome-state-log` table).

```bash
# Create the table once
AWS_PROFILE=self uv run python scripts/aws/create_dynamodb_table.py
```

Environment variables:
| Variable | Default |
|----------|---------|
| `DYNAMODB_TABLE_NAME` | `smarthome-state-log` |
| `AWS_DEFAULT_REGION` | `eu-central-1` |

Logging is fire-and-forget — if DynamoDB is unreachable, the logger disables itself silently.

---

## Path 2: Remote MCP (Claude Web App via AgentCore Gateway)

AgentCore Gateway exposes the same tools as a remote MCP server with Cognito OAuth authentication.

```
Claude Web App
  → AgentCore Gateway (Cognito JWT auth)
  → Lambda (smarthome-gateway-handler)
  → IoT Core MQTT
  → IoT Bridge (runs on your home network)
  → TAPO bulb
```

### Prerequisites

- AWS account with appropriate permissions (IAM, IoT, Lambda, Cognito, Bedrock AgentCore)
- AWS profile `self` configured in `~/.aws/credentials`
- IoT Bridge running on your local network (see step 4)

### Step 1: Provision IoT Bridge Thing

Creates the IoT Thing, X.509 certificates, and MQTT policy:

```bash
AWS_PROFILE=self uv run python scripts/aws/create_bridge_thing.py
```

Writes to `~/.smarthome/iot/config.json` and `~/.smarthome/iot/` certificates.

### Step 2: Provision Cognito

Creates User Pool, resource server (`smarthome-gateway`), two app clients, and a Cognito user:

```bash
AWS_PROFILE=self uv run python scripts/aws/create_cognito.py
```

Writes to `~/.smarthome/cognito_config.json`:
- `smarthome-gateway-client` — M2M (`client_credentials`), used by `test_gateway.py`
- `smarthome-claude-web-client` — browser (`authorization_code`), used by Claude web app

> See `docs/claude-web-oauth.md` for why two clients are needed and how Claude's OAuth discovery works.

### Step 3: Build and deploy Lambda

```bash
# Build the deployment zip (dist/smarthome-lambda.zip)
uv run python scripts/aws/package_lambda.py

# Provision IAM role + Lambda function
AWS_PROFILE=self uv run python scripts/aws/create_lambda.py
```

Lambda handler: `smarthome.aws_mcp.lambda_handler.lambda_handler`
Runtime: Python 3.12 (arm64)

### Step 4: Provision AgentCore Gateway

```bash
AWS_PROFILE=self uv run python scripts/aws/create_agentcore_gateway.py
```

Writes to `~/.smarthome/gateway_config.json` (gateway ID, URL, ARN).

### Step 5: Start the IoT Bridge

Run this on the machine that has local network access to the bulb:

```bash
# Real bulb
uv run python scripts/aws/run_bridge.py

# Mock bulb (for testing without hardware)
uv run python scripts/aws/run_bridge.py --mock
```

The bridge connects to IoT Core via MQTT (TLS port 8883) and subscribes to:
`smarthome/{device_id}/commands/+`

### Step 6: Connect Claude Web App

In Claude web app → Settings → MCP → Add server, enter the gateway URL from `~/.smarthome/gateway_config.json`.

Claude will redirect you to Cognito's hosted UI to log in. Use the Cognito user created in Step 2.

### Test end-to-end connectivity

```bash
AWS_PROFILE=self uv run python scripts/aws/test_gateway.py
```

This runs the full flow: M2M OAuth token → MCP initialize → list tools → invoke `get_status`.

### Config files written by provisioning scripts

| File | Contents |
|------|----------|
| `~/.smarthome/.env` | Bulb credentials (manual) |
| `~/.smarthome/iot/config.json` | IoT endpoint, thing name, cert paths |
| `~/.smarthome/iot/` | X.509 certificates (600 permissions) |
| `~/.smarthome/cognito_config.json` | Client IDs/secrets, token endpoint |
| `~/.smarthome/gateway_config.json` | Gateway ID, URL, ARN |

### Troubleshooting

**Bridge won't connect to IoT Core**
- Check certs exist: `ls -la ~/.smarthome/iot/`
- Verify endpoint: `aws iot describe-endpoint --endpoint-type iot:Data-ATS`
- Check policy is attached: `aws iot list-attached-policies --target <cert-arn>`

**Lambda returns error**
- Check CloudWatch logs: `aws logs tail /aws/lambda/smarthome-gateway-handler --follow`
- Verify bridge is running (Lambda reads state from Device Shadow)

**Claude web app OAuth fails**
- The Claude web app client must allow all standard OIDC scopes (`openid`, `email`, `phone`, `profile`) in addition to custom resource server scopes — see `docs/claude-web-oauth.md` for the full explanation.
