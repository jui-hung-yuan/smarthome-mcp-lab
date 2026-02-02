"""Tests for DynamoStateLogger using moto for in-memory DynamoDB."""

import boto3
import pytest
from moto import mock_aws
from boto3.dynamodb.conditions import Key

from smarthome.logging import DynamoStateLogger

TABLE_NAME = "smarthome-state-log"
REGION = "eu-central-1"
DEVICE_ID = "tapo-bulb-test"


def _create_table(dynamodb):
    """Create the DynamoDB table used by the logger."""
    dynamodb.create_table(
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


def _make_result(success=True, is_on=True, brightness=80, color_temp=4000):
    """Build a result dict matching the device operation format."""
    return {
        "success": success,
        "state": {
            "is_on": is_on,
            "brightness": brightness,
            "color_temp": color_temp,
        },
    }


@pytest.fixture
def aws_env(monkeypatch):
    """Set env vars so the logger finds the right table and region."""
    monkeypatch.setenv("DYNAMODB_TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture
def dynamodb_table(aws_env):
    """Provide a moto-backed DynamoDB table and a patched logger."""
    with mock_aws():
        session = boto3.Session(region_name=REGION)
        dynamodb = session.resource("dynamodb")
        _create_table(dynamodb)
        table = dynamodb.Table(TABLE_NAME)

        logger = DynamoStateLogger()
        # Inject the moto-backed table directly so the logger doesn't
        # try to create its own boto3 session with profile_name="self".
        logger._table = table

        yield logger, table


@pytest.mark.asyncio
async def test_log_state_change_writes_item(dynamodb_table):
    logger, table = dynamodb_table

    await logger.log_state_change(DEVICE_ID, "turn_on", _make_result())

    resp = table.query(KeyConditionExpression=Key("device_id").eq(DEVICE_ID))
    assert resp["Count"] == 1


@pytest.mark.asyncio
async def test_log_state_change_contains_expected_fields(dynamodb_table):
    logger, table = dynamodb_table

    await logger.log_state_change(
        DEVICE_ID, "set_brightness", _make_result(brightness=50, color_temp=3500)
    )

    resp = table.query(KeyConditionExpression=Key("device_id").eq(DEVICE_ID))
    item = resp["Items"][0]

    assert item["device_id"] == DEVICE_ID
    assert item["action"] == "set_brightness"
    assert item["is_on"] is True
    assert item["brightness"] == 50
    assert item["color_temp"] == 3500
    assert item["success"] is True
    assert "timestamp" in item
    assert "ttl" in item


@pytest.mark.asyncio
async def test_log_multiple_events_queryable_by_time(dynamodb_table):
    logger, table = dynamodb_table

    await logger.log_state_change(DEVICE_ID, "turn_on", _make_result())
    await logger.log_state_change(DEVICE_ID, "set_brightness", _make_result(brightness=30))
    await logger.log_state_change(DEVICE_ID, "turn_off", _make_result(is_on=False))

    resp = table.query(
        KeyConditionExpression=(
            Key("device_id").eq(DEVICE_ID) & Key("timestamp").gte("2000-01-01")
        )
    )
    assert resp["Count"] == 3

    # Items should come back in ascending timestamp order
    actions = [item["action"] for item in resp["Items"]]
    assert actions == ["turn_on", "set_brightness", "turn_off"]


@pytest.mark.asyncio
async def test_graceful_degradation_no_credentials(monkeypatch):
    """When boto3 session creation fails, logger should disable itself, not raise."""
    from unittest.mock import patch

    logger = DynamoStateLogger()
    with patch("smarthome.logging.dynamo_logger.boto3.Session", side_effect=Exception("no credentials")):
        await logger.log_state_change(DEVICE_ID, "turn_on", _make_result())
    assert logger._disabled is True


@pytest.mark.asyncio
async def test_graceful_degradation_no_table(aws_env):
    """With moto active but no table created, logger should disable itself."""
    with mock_aws():
        session = boto3.Session(region_name=REGION)
        dynamodb = session.resource("dynamodb")
        # Table does NOT exist
        logger = DynamoStateLogger()
        logger._table = dynamodb.Table("nonexistent-table")

        await logger.log_state_change(DEVICE_ID, "turn_on", _make_result())
        assert logger._disabled is True


@pytest.mark.asyncio
async def test_disabled_flag_prevents_retries(dynamodb_table):
    logger, table = dynamodb_table

    logger._disabled = True
    await logger.log_state_change(DEVICE_ID, "turn_on", _make_result())

    resp = table.query(KeyConditionExpression=Key("device_id").eq(DEVICE_ID))
    assert resp["Count"] == 0
