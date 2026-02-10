"""Provision Cognito resources for AgentCore Gateway OAuth authentication.

Creates:
1. Cognito User Pool (smarthome-gateway-pool)
2. Resource Server with gateway:read and gateway:write scopes
3. M2M App Client with client_credentials grant (for test_gateway.py)
4. Claude Web App Client with authorization_code grant + PKCE (for Claude MCP connector)
5. Cognito user for hosted UI login

Saves client_id, client_secret, and discovery_url to ~/.smarthome/cognito_config.json.

Usage:
    uv run python scripts/create_cognito.py
"""

import json
import os
import secrets
import string
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-central-1")
POOL_NAME = "smarthome-gateway-pool"
RESOURCE_SERVER_ID = "smarthome-gateway"
CLIENT_NAME = "smarthome-gateway-client"
CLAUDE_WEB_CLIENT_NAME = "smarthome-claude-web-client"
CLAUDE_USER_USERNAME = "claude-user"
CLAUDE_WEB_CALLBACK_URLS = [
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
]
CONFIG_DIR = Path("~/.smarthome").expanduser()
CONFIG_FILE = CONFIG_DIR / "cognito_config.json"


def get_cognito_client():
    """Create Cognito IDP client using the 'self' AWS profile."""
    session = boto3.Session(profile_name="self", region_name=REGION)
    return session.client("cognito-idp")


def find_existing_pool(client, pool_name: str) -> str | None:
    """Find an existing User Pool by name. Returns pool ID or None."""
    paginator = client.get_paginator("list_user_pools")
    for page in paginator.paginate(MaxResults=60):
        for pool in page["UserPools"]:
            if pool["Name"] == pool_name:
                return pool["Id"]
    return None


def create_user_pool(client) -> str:
    """Create Cognito User Pool or return existing one."""
    existing_id = find_existing_pool(client, POOL_NAME)
    if existing_id:
        print(f"User Pool '{POOL_NAME}' already exists: {existing_id}")
        return existing_id

    response = client.create_user_pool(
        PoolName=POOL_NAME,
        AdminCreateUserConfig={"AllowAdminCreateUserOnly": True},
    )
    pool_id = response["UserPool"]["Id"]
    print(f"Created User Pool: {pool_id}")
    return pool_id


def create_resource_server(client, pool_id: str) -> None:
    """Create Resource Server with gateway scopes."""
    try:
        client.create_resource_server(
            UserPoolId=pool_id,
            Identifier=RESOURCE_SERVER_ID,
            Name="SmartHome Gateway",
            Scopes=[
                {"ScopeName": "read", "ScopeDescription": "Read device state"},
                {"ScopeName": "write", "ScopeDescription": "Control devices"},
            ],
        )
        print(f"Created Resource Server: {RESOURCE_SERVER_ID}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidParameterException" and "already exists" in str(e):
            print(f"Resource Server '{RESOURCE_SERVER_ID}' already exists.")
        else:
            raise


def create_app_client(client, pool_id: str) -> dict:
    """Create M2M App Client with client_credentials grant.

    Returns:
        dict with ClientId and ClientSecret
    """
    # Check for existing client
    paginator = client.get_paginator("list_user_pool_clients")
    for page in paginator.paginate(UserPoolId=pool_id, MaxResults=60):
        for app in page["UserPoolClients"]:
            if app["ClientName"] == CLIENT_NAME:
                print(f"App Client '{CLIENT_NAME}' already exists: {app['ClientId']}")
                print("NOTE: Cannot retrieve existing client secret. Delete and recreate if needed.")
                return {"ClientId": app["ClientId"], "ClientSecret": None}

    response = client.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName=CLIENT_NAME,
        GenerateSecret=True,
        AllowedOAuthFlows=["client_credentials"],
        AllowedOAuthScopes=[
            f"{RESOURCE_SERVER_ID}/read",
            f"{RESOURCE_SERVER_ID}/write",
        ],
        AllowedOAuthFlowsUserPoolClient=True,
    )

    app_client = response["UserPoolClient"]
    print(f"Created App Client: {app_client['ClientId']}")
    return {
        "ClientId": app_client["ClientId"],
        "ClientSecret": app_client["ClientSecret"],
    }


def create_claude_web_client(client, pool_id: str) -> dict:
    """Create Claude Web App Client with authorization_code grant + PKCE.

    This client is used by Claude web app's MCP connector, which follows
    the authorization_code OAuth flow (browser redirect → login → callback).

    Returns:
        dict with ClientId and ClientSecret
    """
    # Check for existing client
    paginator = client.get_paginator("list_user_pool_clients")
    for page in paginator.paginate(UserPoolId=pool_id, MaxResults=60):
        for app in page["UserPoolClients"]:
            if app["ClientName"] == CLAUDE_WEB_CLIENT_NAME:
                print(f"App Client '{CLAUDE_WEB_CLIENT_NAME}' already exists: {app['ClientId']}")
                print("NOTE: Cannot retrieve existing client secret. Delete and recreate if needed.")
                return {"ClientId": app["ClientId"], "ClientSecret": None}

    response = client.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName=CLAUDE_WEB_CLIENT_NAME,
        GenerateSecret=True,
        AllowedOAuthFlows=["code"],
        AllowedOAuthScopes=[
            "openid",
            "email",
            "phone",
            "profile",
            f"{RESOURCE_SERVER_ID}/read",
            f"{RESOURCE_SERVER_ID}/write",
        ],
        AllowedOAuthFlowsUserPoolClient=True,
        CallbackURLs=CLAUDE_WEB_CALLBACK_URLS,
        SupportedIdentityProviders=["COGNITO"],
    )

    app_client = response["UserPoolClient"]
    print(f"Created Claude Web App Client: {app_client['ClientId']}")
    return {
        "ClientId": app_client["ClientId"],
        "ClientSecret": app_client["ClientSecret"],
    }


def create_cognito_user(client, pool_id: str) -> None:
    """Create a Cognito user for hosted UI login.

    Sets a permanent password to skip the temporary password flow.
    """
    try:
        client.admin_get_user(
            UserPoolId=pool_id,
            Username=CLAUDE_USER_USERNAME,
        )
        print(f"User '{CLAUDE_USER_USERNAME}' already exists.")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "UserNotFoundException":
            raise

    # Create user with a permanent password that satisfies Cognito policy
    # (must contain uppercase, lowercase, digits, and special characters)
    password = (
        secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.ascii_lowercase)
        + secrets.choice(string.digits)
        + secrets.choice("!@#$%^&*")
        + "".join(secrets.choice(string.ascii_letters + string.digits + "!@#$%^&*") for _ in range(20))
    )
    # Shuffle so the guaranteed characters aren't always at the start
    password = "".join(secrets.SystemRandom().sample(password, len(password)))

    client.admin_create_user(
        UserPoolId=pool_id,
        Username=CLAUDE_USER_USERNAME,
        TemporaryPassword=password,
        MessageAction="SUPPRESS",  # Don't send welcome email
    )

    # Set permanent password (skips FORCE_CHANGE_PASSWORD state)
    client.admin_set_user_password(
        UserPoolId=pool_id,
        Username=CLAUDE_USER_USERNAME,
        Password=password,
        Permanent=True,
    )

    print(f"Created user '{CLAUDE_USER_USERNAME}' with permanent password.")
    print(f"  Password: {password}")
    print("  Save this password — it cannot be retrieved later.")


def create_domain(client, pool_id: str) -> str:
    """Create Cognito domain for OAuth token endpoint."""
    # Use pool_id suffix to create a unique domain
    domain_prefix = f"smarthome-gw-{pool_id.split('_')[1][:8].lower()}"

    try:
        client.create_user_pool_domain(
            Domain=domain_prefix,
            UserPoolId=pool_id,
        )
        print(f"Created domain: {domain_prefix}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidParameterException" and "already exists" in str(e):
            print(f"Domain already exists for this pool.")
        else:
            raise

    return domain_prefix


def save_config(
    pool_id: str, domain_prefix: str, app_client: dict, claude_web_client: dict
) -> Path:
    """Save Cognito configuration to JSON file.

    Preserves existing values for client_secret and claude_web_client_secret
    when the new value is None (i.e., client already existed and secret
    couldn't be retrieved).
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    discovery_url = (
        f"https://cognito-idp.{REGION}.amazonaws.com/{pool_id}/.well-known/openid-configuration"
    )

    # Load existing config to preserve secrets we can't re-read
    existing_config = {}
    if CONFIG_FILE.exists():
        existing_config = json.loads(CONFIG_FILE.read_text())

    config = {
        "user_pool_id": pool_id,
        "region": REGION,
        "client_id": app_client["ClientId"],
        "client_secret": app_client["ClientSecret"] or existing_config.get("client_secret"),
        "claude_web_client_id": claude_web_client["ClientId"],
        "claude_web_client_secret": claude_web_client["ClientSecret"]
        or existing_config.get("claude_web_client_secret"),
        "discovery_url": discovery_url,
        "token_endpoint": f"https://{domain_prefix}.auth.{REGION}.amazoncognito.com/oauth2/token",
        "scopes": [
            f"{RESOURCE_SERVER_ID}/read",
            f"{RESOURCE_SERVER_ID}/write",
        ],
    }

    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    print(f"\nConfiguration saved to {CONFIG_FILE}")
    return CONFIG_FILE


def main():
    print(f"Provisioning Cognito for AgentCore Gateway (region: {REGION})")
    print()

    client = get_cognito_client()

    # 1. Create User Pool
    pool_id = create_user_pool(client)

    # 2. Create Resource Server
    create_resource_server(client, pool_id)

    # 3. Create domain (needed for OAuth token endpoint)
    domain_prefix = create_domain(client, pool_id)

    # 4. Create M2M App Client (for test_gateway.py)
    app_client = create_app_client(client, pool_id)

    # 5. Create Claude Web App Client (for Claude MCP connector)
    claude_web_client = create_claude_web_client(client, pool_id)

    # 6. Create Cognito user (for hosted UI login)
    create_cognito_user(client, pool_id)

    # 7. Save configuration
    save_config(pool_id, domain_prefix, app_client, claude_web_client)

    print()
    print("=" * 60)
    print("Cognito provisioned successfully!")
    print()
    print(f"M2M Client ID:        {app_client['ClientId']}")
    if app_client["ClientSecret"]:
        print(f"M2M Client Secret:    {app_client['ClientSecret'][:8]}...")
    print()
    print(f"Claude Web Client ID:     {claude_web_client['ClientId']}")
    if claude_web_client["ClientSecret"]:
        print(f"Claude Web Client Secret: {claude_web_client['ClientSecret'][:8]}...")
    print()
    print("Next steps:")
    print("  1. Build Lambda package: uv run python scripts/package_lambda.py")
    print("  2. Create Lambda:        uv run python scripts/create_lambda.py")
    print("  3. Create Gateway:       uv run python scripts/create_agentcore_gateway.py")
    print()
    print("To connect from Claude web app, use:")
    print(f"  Client ID:     {claude_web_client['ClientId']}")
    print(f"  Client Secret: (see ~/.smarthome/cognito_config.json)")
    print("=" * 60)


if __name__ == "__main__":
    main()
