"""
Runtime configuration for the server.

This module provides access to runtime configuration that is passed
from the shell script via a JSON config file. This approach avoids
using environment variables for port configuration.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Config file location (relative to project root)
CONFIG_FILE = Path(__file__).parent.parent / ".runtime-config.json"


def get_runtime_config() -> dict[str, Any]:
    """
    Read runtime configuration from the JSON config file.

    Returns:
        Configuration dictionary with keys like 'mqtt_port', 'http_port'

    Falls back to defaults if config file doesn't exist.
    """
    defaults = {
        "http_port": 8080,
        "mqtt_port": 1883,
    }

    if not CONFIG_FILE.exists():
        logger.debug("Runtime config file not found, using defaults")
        return defaults

    try:
        with CONFIG_FILE.open() as f:
            config = json.load(f)
            logger.debug("Loaded runtime config: %s", config)
            return {**defaults, **config}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read runtime config: %s", e)
        return defaults


def write_runtime_config(config: dict[str, Any]) -> None:
    """
    Write runtime configuration to the JSON config file.

    This is called by the shell script (via a Python helper) to set
    the configuration before starting Daphne.

    Args:
        config: Configuration dictionary to write
    """
    with CONFIG_FILE.open("w") as f:
        json.dump(config, f, indent=2)
    logger.debug("Wrote runtime config: %s", config)


def update_runtime_config(key: str, value: Any) -> None:
    """
    Update a single value in the runtime config.

    Reads existing config, updates the key, and writes back.

    Args:
        key: Configuration key to update
        value: New value for the key
    """
    config = get_runtime_config()
    config[key] = value
    write_runtime_config(config)


def cleanup_runtime_config() -> None:
    """Remove the runtime config file."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
        logger.debug("Removed runtime config file")


def get_mqtt_port() -> int:
    """
    Get MQTT port from runtime configuration.

    Returns:
        Port number (>= 0 means enabled, < 0 means disabled)
    """
    config = get_runtime_config()
    return int(config.get("mqtt_port", 1883))


def get_actual_mqtt_port() -> int | None:
    """
    Get the actual MQTT port after OS allocation.

    Returns:
        The actual port number if set, None otherwise
    """
    config = get_runtime_config()
    return config.get("actual_mqtt_port")


def get_http_port() -> int:
    """
    Get HTTP port from runtime configuration.

    Returns:
        Port number (>= 0 means enabled, < 0 means disabled)
    """
    config = get_runtime_config()
    return int(config.get("http_port", 8080))


def get_actual_http_port() -> int | None:
    """
    Get the actual HTTP port after OS allocation.

    Returns:
        The actual port number if set, None otherwise
    """
    config = get_runtime_config()
    return config.get("actual_http_port")
