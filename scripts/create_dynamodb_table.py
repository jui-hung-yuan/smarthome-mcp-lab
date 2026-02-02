"""Create the DynamoDB table for smart home state logging.

Run once to set up the table:
    uv run python scripts/create_dynamodb_table.py
"""

import os

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "smarthome-state-log")
REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-central-1")


def create_table() -> None:
    session = boto3.Session(profile_name="self", region_name=REGION)
    client = session.client("dynamodb")

    try:
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "device_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "device_id", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"Table '{TABLE_NAME}' created successfully. Waiting for it to become active...")

        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=TABLE_NAME)

        client.update_time_to_live(
            TableName=TABLE_NAME,
            TimeToLiveSpecification={
                "Enabled": True,
                "AttributeName": "ttl",
            },
        )
        print(f"TTL enabled on 'ttl' attribute.")
        print(f"Table '{TABLE_NAME}' is ready.")

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"Table '{TABLE_NAME}' already exists.")
        else:
            raise


if __name__ == "__main__":
    create_table()
