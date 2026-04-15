"""Notification service — fan-out daemon events to external channels.

Channels (Telegram, webhooks, etc.) register themselves and receive
events as they happen. The service is intentionally fire-and-forget:
a channel failure never blocks the daemon.
"""

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("llmflows.notifications")


@runtime_checkable
class NotificationChannel(Protocol):
    """Interface for notification delivery channels."""

    subscribed_events: list[str]

    def send(self, event: str, payload: dict[str, Any]) -> None: ...


class NotificationService:
    """Dispatches daemon events to registered channels."""

    def __init__(self):
        self.channels: list[NotificationChannel] = []

    def register(self, channel: NotificationChannel) -> None:
        self.channels.append(channel)
        logger.info("Registered notification channel: %s", type(channel).__name__)

    def notify(self, event: str, payload: dict[str, Any]) -> None:
        """Emit an event to all channels that subscribe to it."""
        for channel in self.channels:
            if event not in channel.subscribed_events:
                continue
            try:
                channel.send(event, payload)
            except Exception:
                logger.warning(
                    "Notification channel %s failed for event %s",
                    type(channel).__name__, event, exc_info=True,
                )
