"""Gateway services — channel integrations (Telegram, Slack, etc.)."""

from .channel import Channel, ChannelManager

__all__ = [
    "Channel",
    "ChannelManager",
]
