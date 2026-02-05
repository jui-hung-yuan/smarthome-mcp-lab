"""AWS IoT Core Bridge for local device control."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Union

from awscrt import mqtt
from awsiot import mqtt_connection_builder

from smarthome.bridge.config import IoTConfig
from smarthome.bridge.shadow_manager import ShadowManager
from smarthome.devices.tapo_bulb import MockTapoBulb, TapoBulb

logger = logging.getLogger(__name__)

# Reconnection settings (exponential backoff)
MIN_RECONNECT_DELAY_SEC = 1
MAX_RECONNECT_DELAY_SEC = 128


class IoTBridge:
    """Bridge between AWS IoT Core and local Tapo bulb.

    Handles:
    - MQTT connection to AWS IoT Core with TLS certificates
    - Subscribing to command topics and executing device actions
    - Publishing command responses
    - Updating Device Shadow with current state
    - Auto-reconnection with exponential backoff

    Topic structure:
    - Commands: smarthome/{device_id}/commands/{action}
    - Responses: smarthome/{device_id}/responses/{request_id}
    """

    def __init__(
        self,
        config: IoTConfig,
        bulb: Union[TapoBulb, MockTapoBulb],
    ):
        """Initialize the IoT Bridge.

        Args:
            config: IoT Core connection configuration
            bulb: TapoBulb or MockTapoBulb instance to control
        """
        self._config = config
        self._bulb = bulb
        self._connection: Optional[mqtt.Connection] = None
        self._shadow_manager: Optional[ShadowManager] = None
        self._running = False
        self._disabled = False
        self._reconnect_delay = MIN_RECONNECT_DELAY_SEC
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # Store event loop for thread-safe callbacks

        # Command topic prefix
        self._command_topic_prefix = f"smarthome/{config.device_id}/commands/"
        self._response_topic_prefix = f"smarthome/{config.device_id}/responses/"

        # Map of action names to bulb methods
        self._action_handlers: dict[str, Callable] = {
            "turn_on": self._handle_turn_on,
            "turn_off": self._handle_turn_off,
            "get_status": self._handle_get_status,
            "set_brightness": self._handle_set_brightness,
        }

    async def start(self) -> bool:
        """Start the bridge and connect to AWS IoT Core.

        Returns:
            True if connection succeeded, False otherwise
        """
        if self._disabled:
            logger.warning("Bridge is disabled due to previous failures")
            return False

        try:
            # Capture event loop for thread-safe callbacks from AWS SDK
            self._loop = asyncio.get_running_loop()
            self._connection = self._create_connection()

            # Set up connection callbacks
            connect_future = self._connection.connect()
            connect_future.result(timeout=10.0)

            logger.info(f"Connected to AWS IoT Core: {self._config.endpoint}")

            # Initialize shadow manager
            self._shadow_manager = ShadowManager(
                self._connection, self._config.thing_name
            )

            # Subscribe to command topics
            await self._subscribe_to_commands()

            # Subscribe to shadow delta for desired state changes
            await self._shadow_manager.subscribe_to_delta(self._on_shadow_delta)

            # Report initial state
            await self._report_current_state()

            self._running = True
            self._reconnect_delay = MIN_RECONNECT_DELAY_SEC
            return True

        except Exception as e:
            logger.error(f"Failed to start bridge: {e}")
            self._handle_connection_failure()
            return False

    async def stop(self) -> None:
        """Stop the bridge and disconnect from AWS IoT Core."""
        self._running = False

        if self._connection:
            try:
                disconnect_future = self._connection.disconnect()
                disconnect_future.result(timeout=5.0)
                logger.info("Disconnected from AWS IoT Core")
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._connection = None
                self._shadow_manager = None

    def _create_connection(self) -> mqtt.Connection:
        """Create MQTT connection with TLS certificates."""
        return mqtt_connection_builder.mtls_from_path(
            endpoint=self._config.endpoint,
            cert_filepath=str(self._config.cert_path),
            pri_key_filepath=str(self._config.key_path),
            ca_filepath=str(self._config.root_ca_path),
            client_id=self._config.thing_name,
            clean_session=False,
            keep_alive_secs=30,
            on_connection_interrupted=self._on_connection_interrupted,
            on_connection_resumed=self._on_connection_resumed,
        )

    def _on_connection_interrupted(self, connection, error, **kwargs):  # noqa: ARG002
        """Handle connection interruption."""
        logger.warning(f"Connection interrupted: {error}")

    def _on_connection_resumed(self, connection, return_code, session_present, **kwargs):  # noqa: ARG002
        """Handle connection resume after interruption."""
        logger.info(f"Connection resumed (session_present={session_present})")
        self._reconnect_delay = MIN_RECONNECT_DELAY_SEC

        # Re-report state after reconnection (thread-safe)
        self._schedule_coroutine(self._report_current_state())

    def _handle_connection_failure(self) -> None:
        """Handle connection failure with exponential backoff."""
        self._reconnect_delay = min(
            self._reconnect_delay * 2, MAX_RECONNECT_DELAY_SEC
        )

        if self._reconnect_delay >= MAX_RECONNECT_DELAY_SEC:
            logger.error("Max reconnection attempts reached, disabling bridge")
            self._disabled = True

    def _schedule_coroutine(self, coro) -> None:
        """Schedule a coroutine from a different thread (e.g., SDK callbacks).

        AWS SDK callbacks run in a separate thread, so we can't use
        asyncio.create_task() directly. This method safely schedules
        the coroutine to run on the main event loop.
        """
        if self._loop is None:
            logger.warning("Cannot schedule coroutine: no event loop stored")
            coro.close()  # Clean up unawaited coroutine to avoid RuntimeWarning
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _subscribe_to_commands(self) -> None:
        """Subscribe to all command topics."""
        topic = f"{self._command_topic_prefix}+"

        def on_message(topic: str, payload: bytes, **kwargs):  # noqa: ARG001
            self._schedule_coroutine(self._handle_command(topic, payload))

        subscribe_future, _ = self._connection.subscribe(
            topic=topic,
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=on_message,
        )
        subscribe_future.result(timeout=5.0)

        logger.info(f"Subscribed to command topic: {topic}")

    async def _handle_command(self, topic: str, payload: bytes) -> None:
        """Handle incoming command message.

        Args:
            topic: MQTT topic (smarthome/{device_id}/commands/{action})
            payload: JSON payload with request_id and parameters
        """
        try:
            # Extract action from topic
            action = topic.split("/")[-1]

            # Parse payload
            try:
                data = json.loads(payload.decode("utf-8"))
            except json.JSONDecodeError:
                data = {}

            request_id = data.get("request_id", str(uuid.uuid4()))
            parameters = data.get("parameters", {})

            logger.info(f"Received command: action={action}, request_id={request_id}")

            # Execute action
            handler = self._action_handlers.get(action)
            if handler:
                result = await handler(parameters)
                success = result.get("success", False)
                message = result.get("message", "")
                state = result.get("state", {})
            else:
                success = False
                message = f"Unknown action: {action}"
                state = await self._bulb.get_status()

            # Publish response
            await self._publish_response(request_id, success, message, state)

            # Update shadow with new state
            if success and self._shadow_manager:
                await self._shadow_manager.update_reported(
                    {
                        **state,
                        "bridge_connected": True,
                        "device_reachable": True,
                    }
                )

        except Exception as e:
            logger.error(f"Error handling command: {e}")
            request_id = data.get("request_id", "unknown") if "data" in dir() else "unknown"
            await self._publish_response(
                request_id,
                success=False,
                message=str(e),
                state={},
            )

    async def _handle_turn_on(self, _parameters: dict) -> dict[str, Any]:
        """Handle turn_on command."""
        return await self._bulb.turn_on()

    async def _handle_turn_off(self, _parameters: dict) -> dict[str, Any]:
        """Handle turn_off command."""
        return await self._bulb.turn_off()

    async def _handle_get_status(self, _parameters: dict) -> dict[str, Any]:
        """Handle get_status command."""
        state = await self._bulb.get_status()
        return {"success": True, "message": "Status retrieved", "state": state}

    async def _handle_set_brightness(self, parameters: dict) -> dict[str, Any]:
        """Handle set_brightness command."""
        brightness = parameters.get("brightness")
        if brightness is None:
            return {"success": False, "message": "brightness parameter required"}
        return await self._bulb.set_brightness(int(brightness))

    async def _publish_response(
        self, request_id: str, success: bool, message: str, state: dict[str, Any]
    ) -> None:
        """Publish command response to response topic."""
        if not self._connection:
            return

        topic = f"{self._response_topic_prefix}{request_id}"
        payload = json.dumps(
            {
                "request_id": request_id,
                "success": success,
                "message": message,
                "state": state,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        try:
            publish_future, _ = self._connection.publish(
                topic=topic,
                payload=payload.encode("utf-8"),
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )
            publish_future.result(timeout=5.0)
            logger.debug(f"Published response to {topic}")
        except Exception as e:
            logger.warning(f"Failed to publish response: {e}")

    def _on_shadow_delta(self, delta: dict[str, Any]) -> None:
        """Handle shadow delta (desired state changes).

        This is called when the cloud updates the desired state.
        """
        logger.info(f"Shadow delta received: {delta}")
        self._schedule_coroutine(self._apply_desired_state(delta))

    async def _apply_desired_state(self, desired: dict[str, Any]) -> None:
        """Apply desired state changes from shadow delta."""
        try:
            # Handle is_on state
            if "is_on" in desired:
                if desired["is_on"]:
                    await self._bulb.turn_on()
                else:
                    await self._bulb.turn_off()

            # Handle brightness
            if "brightness" in desired:
                await self._bulb.set_brightness(int(desired["brightness"]))

            # Report updated state
            await self._report_current_state()

        except Exception as e:
            logger.error(f"Failed to apply desired state: {e}")

    async def _report_current_state(self) -> None:
        """Report current device state to shadow."""
        if not self._shadow_manager:
            return

        try:
            state = await self._bulb.get_status()
            await self._shadow_manager.update_reported(
                {
                    **state,
                    "bridge_connected": True,
                    "device_reachable": True,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to report state: {e}")

    @property
    def is_running(self) -> bool:
        """Check if bridge is currently running."""
        return self._running

    @property
    def is_disabled(self) -> bool:
        """Check if bridge is disabled due to failures."""
        return self._disabled
