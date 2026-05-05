"""
MQTT broker $SYS plugin overrides.

amqtt's built-in BrokerSysPlugin broadcasts on $SYS topics using the subscriber's
requested QoS when the publish QoS is unspecified. If a subscriber requests QoS 1,
the broker will wait for PUBACKs and can emit noisy TimeoutError logs when the
subscriber is backgrounded/offline.

This module provides a drop-in replacement that forces QoS 0 for $SYS broadcasts
to keep them best-effort and avoid PUBACK timeout noise.
"""

from __future__ import annotations

from amqtt.plugins.sys.broker import BrokerSysPlugin


class BrokerSysPluginQos0(BrokerSysPlugin):
    """BrokerSysPlugin that forces QoS 0 for $SYS broadcasts."""

    async def _broadcast_sys_topic(self, topic_basename: str, data: bytes) -> None:
        await self.context.broadcast_message(topic_basename, data, qos=0)
