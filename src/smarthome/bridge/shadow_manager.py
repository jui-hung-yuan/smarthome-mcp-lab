"""AWS IoT Device Shadow manager."""

import logging
from typing import Any, Callable, Optional

from awscrt.mqtt import Connection, QoS
from awsiot import iotshadow

logger = logging.getLogger(__name__)


class ShadowManager:
    """Manages Device Shadow operations for state synchronization.

    Handles:
    - Reporting current device state to the shadow
    - Subscribing to delta updates (desired vs reported differences)
    - Shadow versioning for conflict resolution
    """

    def __init__(self, connection: Connection, thing_name: str):
        """Initialize shadow manager.

        Args:
            connection: MQTT connection to AWS IoT Core
            thing_name: IoT Thing name for shadow operations
        """
        self._connection = connection
        self._thing_name = thing_name
        self._shadow_client: Optional[iotshadow.IotShadowClient] = None
        self._delta_callback: Optional[Callable[[dict], None]] = None
        self._current_version: Optional[int] = None

    def _get_client(self) -> iotshadow.IotShadowClient:
        """Lazily create the shadow client."""
        if self._shadow_client is None:
            self._shadow_client = iotshadow.IotShadowClient(self._connection)
        return self._shadow_client

    async def update_reported(self, state: dict[str, Any]) -> bool:
        """Update the reported state in the device shadow.

        Args:
            state: Device state to report (is_on, brightness, color_temp, etc.)

        Returns:
            True if update succeeded, False otherwise
        """
        try:
            client = self._get_client()

            request = iotshadow.UpdateShadowRequest(
                thing_name=self._thing_name,
                state=iotshadow.ShadowState(reported=state),
            )

            future = client.publish_update_shadow(request, qos=QoS.AT_LEAST_ONCE)
            future.result(timeout=5.0)

            logger.debug(f"Shadow updated with reported state: {state}")
            return True

        except Exception as e:
            logger.warning(f"Failed to update shadow: {type(e).__name__}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False

    async def subscribe_to_delta(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> bool:
        """Subscribe to shadow delta updates.

        Delta updates are published when desired state differs from reported state.

        Args:
            callback: Function called with delta state dict when updates arrive

        Returns:
            True if subscription succeeded, False otherwise
        """
        try:
            client = self._get_client()
            self._delta_callback = callback

            def on_delta(response: iotshadow.ShadowDeltaUpdatedEvent):
                if response.state:
                    logger.info(f"Shadow delta received: {response.state}")
                    if response.version:
                        self._current_version = response.version
                    if self._delta_callback:
                        self._delta_callback(response.state)

            request = iotshadow.ShadowDeltaUpdatedSubscriptionRequest(
                thing_name=self._thing_name
            )

            future, _ = client.subscribe_to_shadow_delta_updated_events(
                request=request,
                qos=QoS.AT_LEAST_ONCE,
                callback=on_delta,
            )
            future.result(timeout=5.0)

            logger.info(f"Subscribed to shadow delta for {self._thing_name}")
            return True

        except Exception as e:
            logger.warning(f"Failed to subscribe to shadow delta: {type(e).__name__}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False

    async def get_shadow(self) -> Optional[dict[str, Any]]:
        """Get the current shadow state.

        Returns:
            Shadow state dict with 'desired' and 'reported' keys, or None on failure
        """
        try:
            client = self._get_client()

            request = iotshadow.GetShadowRequest(thing_name=self._thing_name)

            result = {"state": None}

            def on_accepted(response: iotshadow.GetShadowResponse):
                nonlocal result
                if response.state:
                    result["state"] = {
                        "desired": response.state.desired,
                        "reported": response.state.reported,
                    }
                if response.version:
                    self._current_version = response.version

            def on_rejected(response: iotshadow.ErrorResponse):
                logger.warning(f"Get shadow rejected: {response.message}")

            # Subscribe to get responses
            accepted_future, _ = client.subscribe_to_get_shadow_accepted(
                request=iotshadow.GetShadowSubscriptionRequest(
                    thing_name=self._thing_name
                ),
                qos=QoS.AT_LEAST_ONCE,
                callback=on_accepted,
            )
            accepted_future.result(timeout=5.0)

            rejected_future, _ = client.subscribe_to_get_shadow_rejected(
                request=iotshadow.GetShadowSubscriptionRequest(
                    thing_name=self._thing_name
                ),
                qos=QoS.AT_LEAST_ONCE,
                callback=on_rejected,
            )
            rejected_future.result(timeout=5.0)

            # Publish get request
            publish_future = client.publish_get_shadow(request, qos=QoS.AT_LEAST_ONCE)
            publish_future.result(timeout=5.0)

            # Give time for response
            import asyncio
            await asyncio.sleep(1.0)

            return result["state"]

        except Exception as e:
            logger.warning(f"Failed to get shadow: {e}")
            return None

    @property
    def version(self) -> Optional[int]:
        """Current shadow version for optimistic locking."""
        return self._current_version
