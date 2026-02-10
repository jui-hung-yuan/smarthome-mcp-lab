"""Provision Bedrock AgentCore Gateway for remote MCP access.

Creates:
1. IAM Role for gateway to invoke Lambda
2. AgentCore Gateway with CUSTOM_JWT authorizer (Cognito)
3. Gateway Target (smarthome-light) with inline tool schemas pointing to Lambda

Prerequisites:
    uv run python scripts/create_cognito.py   (creates Cognito config)
    uv run python scripts/create_lambda.py     (creates Lambda function)

Usage:
    uv run python scripts/create_agentcore_gateway.py
"""

import json
import os
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-central-1")
GATEWAY_NAME = "smarthome-gateway"
TARGET_NAME = "smarthome-light"
GATEWAY_ROLE_NAME = "smarthome-agentcore-gateway-role"
LAMBDA_FUNCTION_NAME = "smarthome-gateway-handler"

CONFIG_DIR = Path("~/.smarthome").expanduser()
COGNITO_CONFIG_FILE = CONFIG_DIR / "cognito_config.json"
GATEWAY_CONFIG_FILE = CONFIG_DIR / "gateway_config.json"

ASSUME_ROLE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}

# Tool schemas for the light server
TOOL_SCHEMAS = [
    {
        "name": "turn_on",
        "description": "Turn on the TAPO smart light bulb.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "outputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "success or error"},
                "message": {"type": "string", "description": "Result message"},
                "is_on": {"type": "boolean", "description": "Whether the bulb is on"},
                "brightness": {"type": "integer", "description": "Brightness level 0-100"},
                "color_temp": {"type": "integer", "description": "Color temperature in Kelvin"},
            },
        },
    },
    {
        "name": "turn_off",
        "description": "Turn off the TAPO smart light bulb.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "outputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "success or error"},
                "message": {"type": "string", "description": "Result message"},
                "is_on": {"type": "boolean", "description": "Whether the bulb is on"},
                "brightness": {"type": "integer", "description": "Brightness level 0-100"},
                "color_temp": {"type": "integer", "description": "Color temperature in Kelvin"},
            },
        },
    },
    {
        "name": "get_status",
        "description": "Get the current status of the TAPO smart light bulb including on/off state, brightness, and color temperature.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "outputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "success or error"},
                "is_on": {"type": "boolean", "description": "Whether the bulb is on"},
                "brightness": {"type": "integer", "description": "Brightness level 0-100"},
                "color_temp": {"type": "integer", "description": "Color temperature in Kelvin"},
                "bridge_connected": {"type": "boolean", "description": "Whether the local bridge is connected"},
            },
        },
    },
    {
        "name": "set_brightness",
        "description": "Set the brightness level of the TAPO smart light bulb.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "integer",
                    "description": "Brightness level from 0 to 100",
                },
            },
            "required": ["level"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "success or error"},
                "message": {"type": "string", "description": "Result message"},
                "is_on": {"type": "boolean", "description": "Whether the bulb is on"},
                "brightness": {"type": "integer", "description": "Brightness level 0-100"},
                "color_temp": {"type": "integer", "description": "Color temperature in Kelvin"},
            },
        },
    },
]


def get_session():
    """Create boto3 session using the 'self' AWS profile."""
    return boto3.Session(profile_name="self", region_name=REGION)


def load_cognito_config() -> dict:
    """Load Cognito config from ~/.smarthome/cognito_config.json."""
    if not COGNITO_CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Cognito config not found at {COGNITO_CONFIG_FILE}. "
            f"Run 'uv run python scripts/create_cognito.py' first."
        )
    return json.loads(COGNITO_CONFIG_FILE.read_text())


def get_account_id(session) -> str:
    """Get the AWS account ID."""
    sts = session.client("sts")
    return sts.get_caller_identity()["Account"]


def get_lambda_arn(session, account_id: str) -> str:
    """Get the Lambda function ARN."""
    return f"arn:aws:lambda:{REGION}:{account_id}:function:{LAMBDA_FUNCTION_NAME}"


def create_gateway_role(session, account_id: str) -> str:
    """Create IAM role for AgentCore Gateway to invoke Lambda.

    Returns:
        Role ARN
    """
    iam = session.client("iam")

    # Create role
    try:
        response = iam.create_role(
            RoleName=GATEWAY_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(ASSUME_ROLE_POLICY),
            Description="IAM role for AgentCore Gateway to invoke SmartHome Lambda",
        )
        role_arn = response["Role"]["Arn"]
        print(f"Created IAM role: {GATEWAY_ROLE_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            response = iam.get_role(RoleName=GATEWAY_ROLE_NAME)
            role_arn = response["Role"]["Arn"]
            print(f"IAM role '{GATEWAY_ROLE_NAME}' already exists: {role_arn}")
        else:
            raise

    # Inline policy: invoke the Lambda function
    lambda_arn = get_lambda_arn(session, account_id)
    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "lambda:InvokeFunction",
                "Resource": lambda_arn,
            }
        ],
    }

    iam.put_role_policy(
        RoleName=GATEWAY_ROLE_NAME,
        PolicyName="smarthome-gateway-invoke-lambda",
        PolicyDocument=json.dumps(inline_policy),
    )
    print(f"Attached Lambda invoke policy for: {lambda_arn}")

    return role_arn


def find_existing_gateway(client, name: str) -> dict | None:
    """Find an existing gateway by name. Returns gateway dict or None."""
    try:
        paginator = client.get_paginator("list_gateways")
        for page in paginator.paginate():
            for gw in page.get("items", []):
                if gw.get("name") == name:
                    return gw
    except Exception:
        pass
    return None


def build_allowed_clients(cognito_config: dict) -> list[str]:
    """Build list of allowed client IDs from Cognito config.

    Includes both the M2M client and the Claude web client (if present).
    """
    clients = [cognito_config["client_id"]]
    claude_web_id = cognito_config.get("claude_web_client_id")
    if claude_web_id:
        clients.append(claude_web_id)
    return clients


def create_gateway(session, role_arn: str, cognito_config: dict) -> dict:
    """Create AgentCore Gateway with CUSTOM_JWT authorizer.

    Returns:
        Gateway response dict with gatewayId, gatewayUrl, etc.
    """
    client = session.client("bedrock-agentcore-control")
    allowed_clients = build_allowed_clients(cognito_config)

    # Check for existing gateway
    existing = find_existing_gateway(client, GATEWAY_NAME)
    if existing:
        gateway_id = existing["gatewayId"]
        print(f"Gateway '{GATEWAY_NAME}' already exists: {gateway_id}")

        # Update authorizer to ensure allowedClients is current
        # update_gateway requires all mandatory fields (full replacement)
        gw_details = client.get_gateway(gatewayIdentifier=gateway_id)
        print(f"Updating allowedClients: {allowed_clients}")
        client.update_gateway(
            gatewayIdentifier=gateway_id,
            name=gw_details["name"],
            roleArn=gw_details["roleArn"],
            protocolType=gw_details["protocolType"],
            authorizerType=gw_details["authorizerType"],
            authorizerConfiguration={
                "customJWTAuthorizer": {
                    "discoveryUrl": cognito_config["discovery_url"],
                    "allowedClients": allowed_clients,
                }
            },
        )

        # Wait for update to complete
        print("Waiting for gateway update to complete...")
        while True:
            gw = client.get_gateway(gatewayIdentifier=gateway_id)
            status = gw["status"]
            if status == "READY":
                print("Gateway is READY.")
                return gw
            elif status in ("FAILED", "UPDATE_UNSUCCESSFUL"):
                reasons = gw.get("statusReasons", [])
                raise RuntimeError(f"Gateway update failed: {status} — {reasons}")
            print(f"  Status: {status}, waiting...")
            time.sleep(5)

    response = client.create_gateway(
        name=GATEWAY_NAME,
        description="SmartHome MCP Gateway for remote light control via Claude web app",
        roleArn=role_arn,
        protocolType="MCP",
        authorizerType="CUSTOM_JWT",
        authorizerConfiguration={
            "customJWTAuthorizer": {
                "discoveryUrl": cognito_config["discovery_url"],
                "allowedClients": allowed_clients,
            }
        },
    )

    print(f"Created Gateway: {response['gatewayId']}")
    print(f"Status: {response['status']}")

    # Wait for gateway to be ready
    gateway_id = response["gatewayId"]
    print("Waiting for gateway to become READY...")
    while True:
        gw = client.get_gateway(gatewayIdentifier=gateway_id)
        status = gw["status"]
        if status == "READY":
            print("Gateway is READY.")
            return gw
        elif status in ("FAILED", "UPDATE_UNSUCCESSFUL"):
            reasons = gw.get("statusReasons", [])
            raise RuntimeError(f"Gateway creation failed: {status} — {reasons}")
        print(f"  Status: {status}, waiting...")
        time.sleep(5)


def find_existing_target(client, gateway_id: str, name: str) -> dict | None:
    """Find an existing target by name. Returns target dict or None."""
    try:
        paginator = client.get_paginator("list_gateway_targets")
        for page in paginator.paginate(gatewayIdentifier=gateway_id):
            for tgt in page.get("items", []):
                if tgt.get("name") == name:
                    return tgt
    except Exception:
        pass
    return None


def create_gateway_target(session, gateway_id: str, lambda_arn: str) -> dict:
    """Create gateway target with inline tool schemas pointing to Lambda.

    Returns:
        Target response dict
    """
    client = session.client("bedrock-agentcore-control")

    # Check for existing target
    existing = find_existing_target(client, gateway_id, TARGET_NAME)
    if existing:
        target_id = existing["targetId"]
        print(f"Target '{TARGET_NAME}' already exists: {target_id}")
        return existing

    response = client.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name=TARGET_NAME,
        description="Smart light bulb control via IoT Core bridge",
        targetConfiguration={
            "mcp": {
                "lambda": {
                    "lambdaArn": lambda_arn,
                    "toolSchema": {
                        "inlinePayload": TOOL_SCHEMAS,
                    },
                }
            }
        },
        credentialProviderConfigurations=[
            {"credentialProviderType": "GATEWAY_IAM_ROLE"}
        ],
    )

    print(f"Created Target: {response['targetId']}")
    print(f"Status: {response['status']}")

    return response


def save_config(gateway: dict, cognito_config: dict) -> Path:
    """Save gateway configuration to JSON file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    config = {
        "gateway_id": gateway["gatewayId"],
        "gateway_url": gateway["gatewayUrl"],
        "gateway_arn": gateway["gatewayArn"],
        "region": REGION,
        "cognito_client_id": cognito_config["client_id"],
        "cognito_token_endpoint": cognito_config["token_endpoint"],
        "cognito_scopes": cognito_config["scopes"],
    }

    GATEWAY_CONFIG_FILE.write_text(json.dumps(config, indent=2))
    print(f"\nConfiguration saved to {GATEWAY_CONFIG_FILE}")
    return GATEWAY_CONFIG_FILE


def main():
    print(f"Provisioning AgentCore Gateway (region: {REGION})")
    print()

    # Load Cognito config
    cognito_config = load_cognito_config()
    print(f"M2M Client ID:        {cognito_config['client_id']}")
    if cognito_config.get("claude_web_client_id"):
        print(f"Claude Web Client ID: {cognito_config['claude_web_client_id']}")
    print()

    session = get_session()
    account_id = get_account_id(session)
    print(f"Account: {account_id}")
    print()

    # 1. Create IAM role for gateway
    role_arn = create_gateway_role(session, account_id)

    # Wait for role propagation
    print("Waiting for IAM role propagation (10s)...")
    time.sleep(10)

    # 2. Create gateway
    gateway = create_gateway(session, role_arn, cognito_config)
    gateway_id = gateway["gatewayId"]
    gateway_url = gateway["gatewayUrl"]

    # 3. Create target
    lambda_arn = get_lambda_arn(session, account_id)
    create_gateway_target(session, gateway_id, lambda_arn)

    # 4. Save configuration
    save_config(gateway, cognito_config)

    print()
    print("=" * 60)
    print("AgentCore Gateway provisioned successfully!")
    print()
    print(f"Gateway URL: {gateway_url}")
    print(f"Gateway ID:  {gateway_id}")
    print()
    print("To connect from Claude web app, add an MCP connector with:")
    print(f"  Gateway URL:    {gateway_url}")
    if cognito_config.get("claude_web_client_id"):
        print(f"  Client ID:      {cognito_config['claude_web_client_id']}")
        print(f"  Client Secret:  (see ~/.smarthome/cognito_config.json)")
    else:
        print(f"  Client ID:      {cognito_config['client_id']}")
    print()
    print("Make sure the local bridge is running:")
    print("  uv run python scripts/run_bridge.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
