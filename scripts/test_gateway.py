"""Test AgentCore Gateway connectivity and MCP tool invocation.

Tests step by step:
1. Load config files
2. Get OAuth token from Cognito (client_credentials grant)
3. Test gateway URL connectivity
4. Send MCP initialize request
5. List available tools
6. Invoke get_status tool
7. Invoke turn_on tool

Reports round-trip latency for each request and prints a summary at the end.

Usage:
    uv run python scripts/test_gateway.py
"""

import base64
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_DIR = Path("~/.smarthome").expanduser()
COGNITO_CONFIG_FILE = CONFIG_DIR / "cognito_config.json"
GATEWAY_CONFIG_FILE = CONFIG_DIR / "gateway_config.json"


def load_configs() -> tuple[dict, dict]:
    """Load Cognito and gateway config files."""
    cognito = json.loads(COGNITO_CONFIG_FILE.read_text())
    gateway = json.loads(GATEWAY_CONFIG_FILE.read_text())
    return cognito, gateway


def get_oauth_token(cognito_config: dict) -> str:
    """Get OAuth access token from Cognito using client_credentials grant."""
    token_url = cognito_config["token_endpoint"]
    client_id = cognito_config["client_id"]
    client_secret = cognito_config["client_secret"]
    scopes = " ".join(cognito_config["scopes"])

    # Basic auth header
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "scope": scopes,
    }).encode()

    req = urllib.request.Request(
        token_url,
        data=data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    response = urllib.request.urlopen(req)
    result = json.loads(response.read())
    return result["access_token"]


def test_url(url: str, token: str, payload: dict, description: str) -> tuple[dict | None, float]:
    """Send a POST request and return the response and latency in ms."""
    print(f"\n--- {description} ---")
    print(f"  URL: {url}")

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )

    try:
        t0 = time.monotonic()
        response = urllib.request.urlopen(req)
        body = response.read().decode()
        latency_ms = (time.monotonic() - t0) * 1000
        print(f"  Status: {response.status}")
        print(f"  Latency: {latency_ms:.0f} ms")
        print(f"  Headers: {dict(response.headers)}")
        print(f"  Body: {body[:500]}")
        try:
            return json.loads(body), latency_ms
        except json.JSONDecodeError:
            return {"raw": body}, latency_ms
    except urllib.error.HTTPError as e:
        latency_ms = (time.monotonic() - t0) * 1000
        body = e.read().decode() if e.readable() else ""
        print(f"  HTTP Error: {e.code} {e.reason}")
        print(f"  Latency: {latency_ms:.0f} ms")
        print(f"  Headers: {dict(e.headers)}")
        print(f"  Body: {body[:500]}")
        return None, latency_ms
    except Exception as e:
        print(f"  Error: {type(e).__name__}: {e}")
        return None, 0.0


def build_candidate_urls(gateway_config: dict) -> list[tuple[str, str]]:
    """Build candidate URLs to test."""
    gateway_url = gateway_config["gateway_url"]
    gateway_arn = gateway_config["gateway_arn"]
    region = gateway_config["region"]

    # URL-encode the ARN
    encoded_arn = gateway_arn.replace(":", "%3A").replace("/", "%2F")
    runtime_url = (
        f"https://bedrock-agentcore.{region}.amazonaws.com"
        f"/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"
    )

    return [
        (gateway_url, "Gateway URL (from create_gateway)"),
        (runtime_url, "Runtime invocation URL (from docs)"),
    ]


def main():
    print("=" * 60)
    print("AgentCore Gateway Connectivity Test")
    print("=" * 60)

    # Step 1: Load configs
    print("\n[1] Loading configs...")
    cognito, gateway = load_configs()
    print(f"  Gateway ID:  {gateway['gateway_id']}")
    print(f"  Gateway URL: {gateway['gateway_url']}")
    print(f"  Gateway ARN: {gateway['gateway_arn']}")
    print(f"  Client ID:   {cognito['client_id']}")

    # Step 2: Get OAuth token
    print("\n[2] Getting OAuth token from Cognito...")
    try:
        token = get_oauth_token(cognito)
        print(f"  Token: {token[:20]}...{token[-10:]}")
        print(f"  Token length: {len(token)}")
    except Exception as e:
        print(f"  FAILED: {e}")
        sys.exit(1)

    # Step 3: Test candidate URLs
    print("\n[3] Testing gateway URLs...")
    urls = build_candidate_urls(gateway)

    mcp_initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    }

    mcp_list_tools = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }

    working_url = None
    for url, label in urls:
        result, _ = test_url(url, token, mcp_initialize, f"MCP initialize → {label}")
        if result is not None:
            working_url = url
            print(f"\n  >>> '{label}' works!")
            break

    if working_url is None:
        print("\n[FAILED] No URL responded successfully.")
        print("\nDebug steps:")
        print("  1. Check gateway status: aws bedrock-agentcore-control get-gateway \\")
        print(f"       --gateway-identifier {gateway['gateway_id']} --region {gateway['region']}")
        print("  2. Check Lambda logs in CloudWatch")
        print("  3. Verify IAM role permissions")
        sys.exit(1)

    # Step 4: List tools
    print("\n[4] Listing MCP tools...")
    test_url(working_url, token, mcp_list_tools, "MCP tools/list")

    # Step 5: Invoke get_status
    print("\n[5] Invoking get_status tool...")
    mcp_get_status = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "smarthome-light___get_status",
            "arguments": {},
        },
    }
    _, get_status_latency = test_url(
        working_url, token, mcp_get_status, "MCP tools/call → get_status"
    )

    # Step 6: Invoke turn_on
    print("\n[6] Invoking turn_on tool...")
    mcp_turn_on = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "smarthome-light___turn_on",
            "arguments": {},
        },
    }
    _, turn_on_latency = test_url(
        working_url, token, mcp_turn_on, "MCP tools/call → turn_on"
    )

    # Latency summary
    print("\n" + "=" * 60)
    print("Latency Summary")
    print("-" * 40)
    print(f"  {'Tool':<20} {'Round-trip':>10}")
    print(f"  {'-'*20} {'-'*10}")
    for tool, ms in [("get_status", get_status_latency), ("turn_on", turn_on_latency)]:
        value = f"{ms:.0f} ms" if ms > 0 else "N/A"
        print(f"  {tool:<20} {value:>10}")
    print()

    print("=" * 60)
    print("Test complete.")
    if working_url:
        print(f"\nWorking URL for Claude web app connector:")
        print(f"  {working_url}")
    print("=" * 60)


if __name__ == "__main__":
    main()