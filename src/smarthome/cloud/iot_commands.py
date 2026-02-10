"""Generic IoT Core command client for sending actions to devices via MQTT.

This module is used by the Lambda handler to communicate with the local bridge.
It publishes MQTT commands and reads back state from the Device Shadow.

Not a "device" — this is a stateless command router that works for any device
managed by the bridge's DeviceRegistry.
"""

import json
import logging
import time
import uuid

logger = logging.getLogger(__name__)


def send_command(
    device_id: str,
    action: str,
    parameters: dict,
    thing_name: str,
    iot_client,
    command_wait: float = 2.0,
) -> dict:
    """Publish MQTT command and read back state from shadow.

    1. Publishes to smarthome/{device_id}/commands/{action}
    2. Waits command_wait seconds for bridge to process
    3. Reads device shadow for updated state
    4. Returns {success, message, state}

    Args:
        device_id: Target device identifier (e.g. 'tapo-bulb-default')
        action: Command action (e.g. 'turn_on', 'set_brightness')
        parameters: Action parameters dict
        thing_name: IoT Thing name for shadow lookup
        iot_client: boto3 iot-data client
        command_wait: Seconds to wait for bridge to process command

    Returns:
        dict with success, message, and state keys
    """
    request_id = str(uuid.uuid4())
    topic = f"smarthome/{device_id}/commands/{action}"
    payload = json.dumps({
        "request_id": request_id,
        "timestamp": time.time(),
        "parameters": parameters,
    })

    logger.info("Publishing command: topic=%s, request_id=%s", topic, request_id)

    try:
        iot_client.publish(
            topic=topic,
            qos=1,
            payload=payload.encode("utf-8"),
        )
    except Exception as e:
        logger.error("Failed to publish command: %s", e)
        return {"success": False, "message": f"Failed to publish command: {e}", "state": {}}

    # Wait for bridge to process the command and update shadow
    time.sleep(command_wait)

    # Read back the updated state from shadow
    state = get_device_state(device_id, thing_name, iot_client)
    if state is None:
        return {
            "success": False,
            "message": "Command sent but failed to read back state",
            "state": {},
        }

    return {
        "success": True,
        "message": f"Command '{action}' sent to device '{device_id}'",
        "state": state,
    }


def get_device_state(device_id: str, thing_name: str, iot_client) -> dict | None:
    """Read device state from IoT Device Shadow.

    Args:
        device_id: Device identifier to extract state for
        thing_name: IoT Thing name (bridge thing)
        iot_client: boto3 iot-data client

    Returns:
        Device state dict (is_on, brightness, color_temp, etc.) or None on failure
    """
    try:
        response = iot_client.get_thing_shadow(thingName=thing_name)
        shadow_payload = json.loads(response["payload"].read())

        reported = shadow_payload.get("state", {}).get("reported", {})
        devices = reported.get("devices", {})
        device_state = devices.get(device_id)

        if device_state is None:
            logger.warning("Device '%s' not found in shadow", device_id)
            return None

        return {
            "is_on": device_state.get("is_on", False),
            "brightness": device_state.get("brightness", 0),
            "color_temp": device_state.get("color_temp", 0),
            "bridge_connected": reported.get("bridge_connected", False),
        }

    except Exception as e:
        logger.error("Failed to read shadow: %s", e)
        return None
