"""MQTT broker module for OwnTracks support."""

from app.mqtt.auth import DjangoAuthPlugin, authenticate_user, check_topic_access, get_auth_config
from app.mqtt.broker import MQTTBroker
from app.mqtt.commands import Command, CommandPublisher, CommandType, get_command_topic, parse_device_id
from app.mqtt.handlers import (
    OwnTracksMessageHandler,
    extract_location_data,
    extract_lwt_data,
    extract_transition_data,
    parse_owntracks_message,
    parse_owntracks_topic,
)
from app.mqtt.plugin import OwnTracksPlugin

__all__ = [
    "MQTTBroker",
    "OwnTracksMessageHandler",
    "OwnTracksPlugin",
    "parse_owntracks_message",
    "parse_owntracks_topic",
    "extract_location_data",
    "extract_lwt_data",
    "extract_transition_data",
    "DjangoAuthPlugin",
    "authenticate_user",
    "check_topic_access",
    "get_auth_config",
    "Command",
    "CommandType",
    "CommandPublisher",
    "get_command_topic",
    "parse_device_id",
]
