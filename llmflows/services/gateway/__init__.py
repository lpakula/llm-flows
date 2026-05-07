"""Gateway services — channel integrations (Telegram, Slack, GitHub, etc.)."""

from .channel import Channel, ChannelManager

__all__ = [
    "Channel",
    "ChannelManager",
]
