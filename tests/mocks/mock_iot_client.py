"""Mock MQTT client for IoT Bridge unit tests."""

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from unittest.mock import MagicMock


@dataclass
class MockPublishResult:
    """Result of a mock publish operation."""

    topic: str
    payload: bytes
    qos: int


@dataclass
class MockSubscription:
    """A recorded subscription."""

    topic: str
    qos: int
    callback: Callable


@dataclass
class MockMqttConnection:
    """Mock MQTT connection that simulates AWS IoT Core behavior.

    Attributes:
        connected: Whether the connection is active
        published_messages: List of all published messages
        subscriptions: Dict of topic patterns to callbacks
        simulate_connect_failure: Set to True to simulate connection failures
        simulate_publish_failure: Set to True to simulate publish failures
    """

    connected: bool = False
    published_messages: list[MockPublishResult] = field(default_factory=list)
    subscriptions: dict[str, MockSubscription] = field(default_factory=dict)
    simulate_connect_failure: bool = False
    simulate_publish_failure: bool = False
    _on_interrupted: Optional[Callable] = None
    _on_resumed: Optional[Callable] = None

    def connect(self) -> Future:
        """Simulate connection to AWS IoT Core."""
        future = Future()
        if self.simulate_connect_failure:
            future.set_exception(Exception("Simulated connection failure"))
        else:
            self.connected = True
            future.set_result({"session_present": False})
        return future

    def disconnect(self) -> Future:
        """Simulate disconnection."""
        future = Future()
        self.connected = False
        future.set_result(None)
        return future

    def subscribe(
        self,
        topic: str,
        qos: int,
        callback: Callable,
    ) -> tuple[Future, int]:
        """Subscribe to a topic pattern.

        Args:
            topic: Topic pattern (can include + and # wildcards)
            qos: QoS level
            callback: Function called with (topic, payload, **kwargs)

        Returns:
            Tuple of (future, packet_id)
        """
        future = Future()
        self.subscriptions[topic] = MockSubscription(topic, qos, callback)
        future.set_result({"qos": qos})
        return future, 1

    def publish(
        self,
        topic: str,
        payload: bytes,
        qos: int,
    ) -> tuple[Future, int]:
        """Publish a message.

        Args:
            topic: Topic to publish to
            payload: Message payload
            qos: QoS level

        Returns:
            Tuple of (future, packet_id)
        """
        future = Future()
        if self.simulate_publish_failure:
            future.set_exception(Exception("Simulated publish failure"))
        else:
            self.published_messages.append(MockPublishResult(topic, payload, qos))
            future.set_result(None)
        return future, 1

    def simulate_message(self, topic: str, payload: bytes) -> None:
        """Simulate receiving a message from the broker.

        Finds matching subscriptions and calls their callbacks.

        Args:
            topic: Topic the message was received on
            payload: Message payload
        """
        for pattern, subscription in self.subscriptions.items():
            if self._topic_matches(pattern, topic):
                subscription.callback(topic, payload)

    def simulate_connection_interrupted(self, error: Exception) -> None:
        """Simulate a connection interruption."""
        self.connected = False
        if self._on_interrupted:
            self._on_interrupted(self, error)

    def simulate_connection_resumed(self) -> None:
        """Simulate connection being resumed after interruption."""
        self.connected = True
        if self._on_resumed:
            self._on_resumed(self, 0, False)

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        """Check if a topic matches a pattern with MQTT wildcards.

        Args:
            pattern: Pattern that may contain + (single level) or # (multi level)
            topic: Actual topic to match

        Returns:
            True if topic matches pattern
        """
        pattern_parts = pattern.split("/")
        topic_parts = topic.split("/")

        for i, pattern_part in enumerate(pattern_parts):
            if pattern_part == "#":
                # # matches rest of topic
                return True
            if i >= len(topic_parts):
                return False
            if pattern_part == "+":
                # + matches single level
                continue
            if pattern_part != topic_parts[i]:
                return False

        return len(pattern_parts) == len(topic_parts)

    def get_published_to(self, topic_prefix: str) -> list[MockPublishResult]:
        """Get all messages published to topics matching a prefix."""
        return [m for m in self.published_messages if m.topic.startswith(topic_prefix)]

    def clear_published(self) -> None:
        """Clear all recorded published messages."""
        self.published_messages.clear()


class MockShadowClient:
    """Mock IoT Shadow client for testing shadow operations."""

    def __init__(self):
        self.reported_states: list[dict] = []
        self.desired_state: dict[str, Any] = {}
        self._delta_callback: Optional[Callable] = None
        self._get_accepted_callback: Optional[Callable] = None
        self._get_rejected_callback: Optional[Callable] = None

    def publish_update_shadow(self, request, qos: int) -> Future:
        """Record a shadow update request."""
        future = Future()
        if request.state and request.state.reported:
            self.reported_states.append(dict(request.state.reported))
        future.set_result(None)
        return future

    def subscribe_to_shadow_delta_updated_events(
        self,
        request,
        qos: int,
        callback: Callable,
    ) -> tuple[Future, int]:
        """Subscribe to shadow delta events."""
        future = Future()
        self._delta_callback = callback
        future.set_result(None)
        return future, 1

    def subscribe_to_get_shadow_accepted(
        self,
        request,
        qos: int,
        callback: Callable,
    ) -> tuple[Future, int]:
        """Subscribe to get shadow accepted events."""
        future = Future()
        self._get_accepted_callback = callback
        future.set_result(None)
        return future, 1

    def subscribe_to_get_shadow_rejected(
        self,
        request,
        qos: int,
        callback: Callable,
    ) -> tuple[Future, int]:
        """Subscribe to get shadow rejected events."""
        future = Future()
        self._get_rejected_callback = callback
        future.set_result(None)
        return future, 1

    def publish_get_shadow(self, request, qos: int) -> Future:
        """Publish a get shadow request and trigger the accepted callback."""
        future = Future()
        future.set_result(None)

        # Simulate async response
        if self._get_accepted_callback:
            response = MagicMock()
            response.state = MagicMock()
            response.state.desired = self.desired_state
            response.state.reported = (
                self.reported_states[-1] if self.reported_states else {}
            )
            response.version = len(self.reported_states)
            self._get_accepted_callback(response)

        return future

    def simulate_delta(self, delta: dict[str, Any]) -> None:
        """Simulate receiving a shadow delta update."""
        if self._delta_callback:
            response = MagicMock()
            response.state = delta
            response.version = len(self.reported_states) + 1
            self._delta_callback(response)

    def get_last_reported(self) -> Optional[dict]:
        """Get the most recent reported state."""
        return self.reported_states[-1] if self.reported_states else None
