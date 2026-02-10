"""DynamoDB state logger for smart home device events."""

import logging
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "smarthome-state-log"
DEFAULT_REGION = "eu-central-1"
TTL_DAYS = 30


class DynamoStateLogger:
    """Fire-and-forget logger that writes device state changes to DynamoDB.

    Lazy-initializes the boto3 Table resource on first write.
    After any connection/table failure, sets ``_disabled`` to avoid retrying.
    """

    def __init__(self, profile_name: str | None = None) -> None:
        self._profile_name = profile_name
        self._table = None
        self._disabled = False

    def _get_table(self):
        """Lazily create and return the DynamoDB Table resource."""
        if self._table is not None:
            return self._table

        table_name = os.environ.get("DYNAMODB_TABLE_NAME", DEFAULT_TABLE_NAME)
        region = os.environ.get("AWS_DEFAULT_REGION", DEFAULT_REGION)

        session_kwargs = {"region_name": region}
        if self._profile_name:
            session_kwargs["profile_name"] = self._profile_name

        session = boto3.Session(**session_kwargs)
        dynamodb = session.resource("dynamodb")
        self._table = dynamodb.Table(table_name)
        return self._table

    async def log_state_change(
        self, device_id: str, action: str, result: dict[str, Any]
    ) -> None:
        """Log a device state change to DynamoDB.

        This is fire-and-forget: failures are logged as warnings and never
        propagate to the caller.

        Args:
            device_id: Identifier for the device (e.g. ``tapo-bulb-default``).
            action: The action performed (``turn_on``, ``turn_off``, ``set_brightness``).
            result: The result dict returned by the device operation, expected to
                contain ``success`` (bool) and ``state`` (dict with ``is_on``,
                ``brightness``, ``color_temp``).
        """
        if self._disabled:
            return

        try:
            table = self._get_table()

            now = datetime.now(timezone.utc)
            state = result.get("state", {})

            item = {
                "device_id": device_id,
                "timestamp": now.isoformat(timespec="microseconds"),
                "action": action,
                "is_on": result.get("success", False) and state.get("is_on", False),
                "brightness": Decimal(str(state.get("brightness", 0))),
                "color_temp": Decimal(str(state.get("color_temp", 0))),
                "success": result.get("success", False),
                "ttl": int((now + timedelta(days=TTL_DAYS)).timestamp()),
            }

            table.put_item(Item=item)
        except (BotoCoreError, ClientError, Exception) as exc:
            logger.warning("DynamoDB logging failed, disabling logger: %s", exc)
            self._disabled = True
