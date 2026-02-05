"""AWS IoT Core Bridge for local device control."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from awscrt import mqtt
from awsiot import mqtt_connection_builder

from smarthome.bridge.config import IoTConfig
from smarthome.bridge.device_registry import DeviceRegistry
from smarthome.bridge.shadow_manager import ShadowManager

logger = logging.getLogger(__name__)

# Disable bridge after this many consecutive failures
MAX_FAILURES = 3


class IoTBridge:
    """Bridge between AWS IoT Core and local smart home devices.

    Handles:
    - MQTT connection to AWS IoT Core with TLS certificates
    - Subscribing to command topics and executing device actions
    - Publishing command responses
    - Updating Device Shadow with current state
    - Auto-reconnection (handled by AWS SDK)

    Topic structure:
    - Commands: smarthome/{device_id}/commands/{action}
    - Responses: smarthome/{device_id}/responses/{request_id}

    Supports multiple devices via DeviceRegistry. Commands are routed to devices
    based on device_id extracted from the MQTT topic.
    """

    def __init__(
        self,
        config: IoTConfig,
        registry: DeviceRegistry,
    ):
        """Initialize the IoT Bridge.

        Args:
            config: IoT Core connection configuration
            registry: DeviceRegistry containing devices to control
        """
        self._config = config
        self._registry = registry
        self._connection: Optional[mqtt.Connection] = None
        self._shadow_manager: Optional[ShadowManager] = None
        self._running = False
        self._disabled = False
        self._failure_count = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # Store event loop for thread-safe callbacks

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
            self._failure_count = 0
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
        self._failure_count = 0

        # Re-report state after reconnection (thread-safe)
        self._schedule_coroutine(self._report_current_state())

    def _handle_connection_failure(self) -> None:
        """Handle connection failure. Disables bridge after MAX_FAILURES."""
        self._failure_count += 1

        if self._failure_count >= MAX_FAILURES:
            logger.error(f"Max failures ({MAX_FAILURES}) reached, disabling bridge")
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
        """Subscribe to command topics for all registered devices."""

        def on_message(topic: str, payload: bytes, **kwargs):  # noqa: ARG001
            self._schedule_coroutine(self._handle_command(topic, payload))

        # Subscribe to each device's command topic individually
        # This avoids requiring wildcard permissions in the IoT policy
        device_ids = self._registry.list_device_ids()
        for device_id in device_ids:
            topic = f"smarthome/{device_id}/commands/+"
            subscribe_future, _ = self._connection.subscribe(
                topic=topic,
                qos=mqtt.QoS.AT_LEAST_ONCE,
                callback=on_message,
            )
            subscribe_future.result(timeout=5.0)
            logger.info(f"Subscribed to command topic: {topic}")

        logger.info(f"Registered devices: {device_ids}")

    async def _handle_command(self, topic: str, payload: bytes) -> None:
        """Handle incoming command message.

        Args:
            topic: MQTT topic (smarthome/{device_id}/commands/{action})
            payload: JSON payload with request_id and parameters
        """
        # Extract device_id and action from topic
        # Topic format: smarthome/{device_id}/commands/{action}
        parts = topic.split("/")
        device_id = parts[1] if len(parts) >= 2 else "unknown"
        action = parts[-1]

        # Parse payload
        try:
            data = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            data = {}

        request_id = data.get("request_id", str(uuid.uuid4()))
        parameters = data.get("parameters", {})

        logger.info(
            f"Received command: device={device_id}, action={action}, request_id={request_id}"
        )

        try:
            # Look up device in registry
            device = self._registry.get(device_id)
            if device is None:
                await self._publish_response(
                    device_id,
                    request_id,
                    success=False,
                    message=f"Unknown device: {device_id}",
                    state={},
                )
                return

            # Execute action via device interface
            result = await device.execute(action, parameters)
            success = result.get("success", False)
            message = result.get("message", "")
            state = result.get("state", {})

            # Publish response
            await self._publish_response(device_id, request_id, success, message, state)

            # Update shadow with new state
            if success:
                await self._report_current_state()

        except Exception as e:
            logger.error(f"Error handling command: {e}")
            await self._publish_response(
                device_id,
                request_id,
                success=False,
                message=str(e),
                state={},
            )

    async def _publish_response(
        self,
        device_id: str,
        request_id: str,
        success: bool,
        message: str,
        state: dict[str, Any],
    ) -> None:
        """Publish command response to response topic."""
        if not self._connection:
            return

        topic = f"smarthome/{device_id}/responses/{request_id}"
        payload = json.dumps(
            {
                "request_id": request_id,
                "device_id": device_id,
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
        The delta may contain device-specific state nested under device IDs,
        or flat state that applies to all devices.
        """
        logger.info(f"Shadow delta received: {delta}")
        self._schedule_coroutine(self._apply_desired_state(delta))

    async def _apply_desired_state(self, desired: dict[str, Any]) -> None:
        """Apply desired state changes from shadow delta.

        Supports two formats:
        1. Per-device state: {"device-id-1": {"is_on": true}, "device-id-2": {...}}
        2. Flat state (applied to all devices): {"is_on": true, "brightness": 50}
        """
        try:
            # Check if delta contains device-specific state
            devices_updated = False
            for device_id in self._registry.list_device_ids():
                if device_id in desired:
                    # Per-device state
                    device = self._registry.get(device_id)
                    if device:
                        await device.apply_desired_state(desired[device_id])
                        devices_updated = True

            if not devices_updated:
                # Flat state - apply to all devices
                for device_id, device in self._registry.get_all().items():
                    await device.apply_desired_state(desired)

            # Report updated state
            await self._report_current_state()

        except Exception as e:
            logger.error(f"Failed to apply desired state: {e}")

    async def _report_current_state(self) -> None:
        """Report current state of all devices to shadow."""
        if not self._shadow_manager:
            return

        try:
            devices_state = {}
            for device_id, device in self._registry.get_all().items():
                state = await device.get_shadow_state()
                devices_state[device_id] = {
                    **state,
                    "device_reachable": True,
                }

            await self._shadow_manager.update_reported(
                {
                    "devices": devices_state,
                    "bridge_connected": True,
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
