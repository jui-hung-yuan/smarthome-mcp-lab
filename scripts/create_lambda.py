"""Provision Lambda function for AgentCore Gateway handler.

Creates:
1. IAM Role with permissions for IoT Publish, GetThingShadow, DynamoDB PutItem, CloudWatch Logs
2. Lambda function (smarthome-gateway-handler) from dist/smarthome-lambda.zip

Prerequisites:
    uv run python scripts/package_lambda.py   (builds the zip)

Usage:
    uv run python scripts/create_lambda.py
"""

import json
import os
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-central-1")
FUNCTION_NAME = "smarthome-gateway-handler"
ROLE_NAME = "smarthome-gateway-lambda-role"
IOT_THING_NAME = os.environ.get("IOT_THING_NAME", "smarthome-bridge-home")
DEVICE_ID = os.environ.get("DEVICE_ID", "tapo-bulb-default")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ZIP_PATH = PROJECT_ROOT / "dist" / "smarthome-lambda.zip"

ASSUME_ROLE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}


def get_session():
    """Create boto3 session using the 'self' AWS profile."""
    return boto3.Session(profile_name="self", region_name=REGION)


def get_account_id(session) -> str:
    """Get the AWS account ID."""
    sts = session.client("sts")
    return sts.get_caller_identity()["Account"]


def create_iam_role(session, account_id: str) -> str:
    """Create IAM role for Lambda with required permissions.

    Returns:
        Role ARN
    """
    iam = session.client("iam")

    # Create role
    try:
        response = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(ASSUME_ROLE_POLICY),
            Description="Lambda execution role for SmartHome AgentCore Gateway handler",
        )
        role_arn = response["Role"]["Arn"]
        print(f"Created IAM role: {ROLE_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            response = iam.get_role(RoleName=ROLE_NAME)
            role_arn = response["Role"]["Arn"]
            print(f"IAM role '{ROLE_NAME}' already exists: {role_arn}")
        else:
            raise

    # Attach basic Lambda execution policy (CloudWatch Logs)
    iam.attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )

    # Create and attach inline policy for IoT + DynamoDB
    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "iot:Publish",
                "Resource": f"arn:aws:iot:{REGION}:{account_id}:topic/smarthome/*/commands/*",
            },
            {
                "Effect": "Allow",
                "Action": "iot:GetThingShadow",
                "Resource": f"arn:aws:iot:{REGION}:{account_id}:thing/{IOT_THING_NAME}",
            },
            {
                "Effect": "Allow",
                "Action": "dynamodb:PutItem",
                "Resource": f"arn:aws:dynamodb:{REGION}:{account_id}:table/smarthome-state-log",
            },
        ],
    }

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="smarthome-gateway-permissions",
        PolicyDocument=json.dumps(inline_policy),
    )
    print("Attached inline policy: smarthome-gateway-permissions")

    return role_arn


def create_lambda_function(session, role_arn: str) -> str:
    """Create or update Lambda function.

    Returns:
        Function ARN
    """
    if not ZIP_PATH.exists():
        raise FileNotFoundError(
            f"Lambda package not found at {ZIP_PATH}. "
            f"Run 'uv run python scripts/package_lambda.py' first."
        )

    lambda_client = session.client("lambda")
    zip_bytes = ZIP_PATH.read_bytes()

    environment = {
        "Variables": {
            "IOT_THING_NAME": IOT_THING_NAME,
            "DEVICE_ID": DEVICE_ID,
            "COMMAND_WAIT_SECONDS": "2.0",
        }
    }

    try:
        response = lambda_client.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="smarthome.lambda_handler.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Description="SmartHome AgentCore Gateway handler - routes tools to IoT Core",
            Timeout=30,
            MemorySize=256,
            Environment=environment,
            Architectures=["arm64"],
        )
        function_arn = response["FunctionArn"]
        print(f"Created Lambda function: {FUNCTION_NAME}")

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            # Function exists, update code first
            print(f"Function '{FUNCTION_NAME}' already exists, updating...")
            lambda_client.update_function_code(
                FunctionName=FUNCTION_NAME,
                ZipFile=zip_bytes,
            )
            # Wait for code update to complete before updating config
            print("Waiting for code update to complete...")
            waiter = lambda_client.get_waiter("function_updated_v2")
            waiter.wait(FunctionName=FUNCTION_NAME)
            lambda_client.update_function_configuration(
                FunctionName=FUNCTION_NAME,
                Role=role_arn,
                Handler="smarthome.lambda_handler.lambda_handler",
                Timeout=30,
                MemorySize=256,
                Environment=environment,
            )
            response = lambda_client.get_function(FunctionName=FUNCTION_NAME)
            function_arn = response["Configuration"]["FunctionArn"]
            print(f"Updated Lambda function: {FUNCTION_NAME}")
        else:
            raise

    return function_arn


def main():
    print(f"Provisioning Lambda for AgentCore Gateway (region: {REGION})")
    print(f"Lambda package: {ZIP_PATH}")
    print()

    session = get_session()
    account_id = get_account_id(session)
    print(f"Account: {account_id}")
    print()

    # 1. Create IAM role
    role_arn = create_iam_role(session, account_id)

    # Wait for role propagation
    print("Waiting for IAM role propagation (10s)...")
    time.sleep(10)

    # 2. Create Lambda function
    function_arn = create_lambda_function(session, role_arn)

    print()
    print("=" * 60)
    print("Lambda provisioned successfully!")
    print()
    print(f"Function: {FUNCTION_NAME}")
    print(f"ARN:      {function_arn}")
    print(f"Runtime:  python3.12 (arm64)")
    print(f"IoT Thing: {IOT_THING_NAME}")
    print(f"Device:   {DEVICE_ID}")
    print()
    print("Next step:")
    print("  uv run python scripts/create_agentcore_gateway.py")
    print("=" * 60)


if __name__ == "__main__":
    main()