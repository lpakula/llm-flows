"""Channel abstraction for gateway integrations.

Each channel (Telegram, Slack, etc.) implements the Channel protocol,
providing bidirectional communication: inbound messages from users
and outbound notifications from the daemon.
"""

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("llmflows.gateway")


@runtime_checkable
class Channel(Protocol):
    """Bidirectional channel: receives messages + sends notifications."""

    name: str
    subscribed_events: list[str]

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def send(self, event: str, payload: dict[str, Any]) -> None: ...


class ChannelManager:
    """Manages channel lifecycle and fans out daemon events."""

    def __init__(self):
        self.channels: list[Channel] = []

    def register(self, channel: Channel) -> None:
        self.channels.append(channel)
        logger.info("Registered channel: %s", channel.name)

    def start_all(self) -> None:
        for channel in self.channels:
            try:
                channel.start()
                logger.info("Started channel: %s", channel.name)
            except Exception:
                logger.exception("Failed to start channel: %s", channel.name)

    def stop_all(self) -> None:
        for channel in self.channels:
            try:
                channel.stop()
                logger.info("Stopped channel: %s", channel.name)
            except Exception:
                logger.exception("Failed to stop channel: %s", channel.name)

    def restart_all(self, new_channels: list[Channel]) -> None:
        """Stop existing channels, replace with new ones, and start them."""
        self.stop_all()
        self.channels.clear()
        for ch in new_channels:
            self.register(ch)
        self.start_all()

    def notify(self, event: str, payload: dict[str, Any]) -> None:
        """Emit an event to all channels that subscribe to it."""
        for channel in self.channels:
            if event not in channel.subscribed_events:
                continue
            try:
                channel.send(event, payload)
            except Exception:
                logger.warning(
                    "Channel %s failed for event %s",
                    channel.name, event, exc_info=True,
                )
