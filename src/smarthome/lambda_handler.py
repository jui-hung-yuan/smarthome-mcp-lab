"""Lambda entry point for Bedrock AgentCore Gateway.

Receives tool invocations from AgentCore Gateway and routes them to IoT Core
commands that the local bridge executes against real devices.

Environment variables:
    IOT_THING_NAME: Bridge thing name (default: smarthome-bridge-home)
    DEVICE_ID: Target device ID (default: tapo-bulb-default)
    COMMAND_WAIT_SECONDS: Seconds to wait after publishing command (default: 2.0)
    AWS_DEFAULT_REGION: AWS region (default: eu-central-1)
"""

import json
import logging
import os

import boto3

from smarthome.cloud.iot_commands import send_command, get_device_state
from smarthome.logging.dynamo_logger import DynamoStateLogger

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Module-level clients (reused across warm Lambda invocations)
IOT_THING_NAME = os.environ.get("IOT_THING_NAME", "smarthome-bridge-home")
DEVICE_ID = os.environ.get("DEVICE_ID", "tapo-bulb-default")
COMMAND_WAIT = float(os.environ.get("COMMAND_WAIT_SECONDS", "2.0"))

iot_client = boto3.client("iot-data")
state_logger = DynamoStateLogger()  # Uses Lambda execution role (no profile_name)

# Tools that send commands to the bridge via MQTT
COMMAND_TOOLS = {"turn_on", "turn_off", "set_brightness"}
# Tools that only read state from the shadow
READ_TOOLS = {"get_status"}


def _extract_tool_name(context) -> str:
    """Extract tool name from AgentCore Gateway Lambda context.

    AgentCore passes the tool name as:
        context.client_context.custom['bedrockAgentCoreToolName']

    The value is prefixed with the target name and three underscores:
        'smarthome-light___turn_on' -> 'turn_on'
    """
    try:
        custom = context.client_context.custom
        raw_name = custom["bedrockAgentCoreToolName"]
    except (AttributeError, KeyError, TypeError):
        return ""

    # Strip "{target_name}___" prefix
    if "___" in raw_name:
        return raw_name.split("___", 1)[1]
    return raw_name


def lambda_handler(event, context):
    """Main Lambda handler for AgentCore Gateway tool invocations.

    Args:
        event: Tool input parameters (e.g. {"level": 80} for set_brightness)
        context: Lambda context with client_context.custom['bedrockAgentCoreToolName']

    Returns:
        JSON-serializable dict with tool result
    """
    tool_name = _extract_tool_name(context) or event.get("tool_name", "")
    logger.info("Tool invocation: %s, event: %s", tool_name, json.dumps(event))

    if tool_name in COMMAND_TOOLS:
        parameters = {}
        if tool_name == "set_brightness":
            parameters["level"] = event.get("level", 100)

        result = send_command(
            device_id=DEVICE_ID,
            action=tool_name,
            parameters=parameters,
            thing_name=IOT_THING_NAME,
            iot_client=iot_client,
            command_wait=COMMAND_WAIT,
        )

        # Fire-and-forget DynamoDB logging
        _log_state_change(tool_name, result)

        return _format_command_result(tool_name, result)

    elif tool_name in READ_TOOLS:
        state = get_device_state(
            device_id=DEVICE_ID,
            thing_name=IOT_THING_NAME,
            iot_client=iot_client,
        )

        if state is None:
            return {"status": "error", "message": "Unable to read device state"}

        return _format_status(state)

    else:
        logger.warning("Unknown tool: %s", tool_name)
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}


def _format_command_result(action: str, result: dict) -> dict:
    """Format command result for AgentCore Gateway response."""
    if result["success"]:
        state = result["state"]
        return {
            "status": "success",
            "message": result["message"],
            "is_on": state.get("is_on", False),
            "brightness": state.get("brightness", 0),
            "color_temp": state.get("color_temp", 0),
        }
    return {"status": "error", "message": result["message"]}


def _format_status(state: dict) -> dict:
    """Format device status for AgentCore Gateway response."""
    return {
        "status": "success",
        "is_on": state.get("is_on", False),
        "brightness": state.get("brightness", 0),
        "color_temp": state.get("color_temp", 0),
        "bridge_connected": state.get("bridge_connected", False),
    }


def _log_state_change(action: str, result: dict) -> None:
    """Fire-and-forget logging to DynamoDB (sync wrapper)."""
    import asyncio

    try:
        asyncio.get_event_loop().run_until_complete(
            state_logger.log_state_change(DEVICE_ID, action, result)
        )
    except Exception as e:
        logger.warning("State logging failed: %s", e)
