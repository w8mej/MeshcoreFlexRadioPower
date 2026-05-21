"""Shared test fixtures and import-path setup."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add repo root to sys.path so `import flex_radio_bot` works regardless of cwd.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def config_dict():
    """
    Produce a complete and structurally valid dummy configuration dictionary.

    This configuration stubs out the necessary credentials for Tuya local relay
    communication and sets a valid allowed sender hex key. The rate-limiting cooldown
    is set to 0.0 seconds to prevent tests from blocking or failing due to timing.

    Returns:
        dict: A dictionary containing dummy Tuya credentials and standard bot settings.
    """
    return {
        "tuya_device_id": "bfdeadbeefcafedeadbe",
        "tuya_local_key": "0123456789abcdef",
        "tuya_address": "Auto",
        "tuya_version": 3.4,
        "relay_channel": 1,
        "short_pulse_seconds": 0.5,
        "long_pulse_seconds": 5.0,
        "cooldown_seconds": 0.0,         # disable cooldown in tests
        "allowed_sender_keys": ["a" * 64],
        "flex_host": None,
        "flex_smartsdr_port": 4992,
        "log_path": "/tmp/flex_radio_bot_test.log",
        "allow_channel_control": False,
    }


@pytest.fixture
def config_file(tmp_path, config_dict, monkeypatch):
    """
    Write a standard configuration dictionary to a temporary JSON file on disk.

    This fixture serializes the mock configuration, writes it to a temporary directory
    managed by pytest, and temporarily overrides the `FLEX_BOT_CONFIG` environment variable
    to point at this file, allowing the bot config loader to locate and parse it.

    Args:
        tmp_path (Path): Pytest fixture providing a temporary directory unique to the test.
        config_dict (dict): Mock configuration dictionary.
        monkeypatch (MonkeyPatch): Pytest utility to temporarily override env variables.

    Yields:
        Path: The file path to the temporary configuration file.
    """
    path = tmp_path / "flex_radio_bot.json"
    path.write_text(json.dumps(config_dict))
    monkeypatch.setenv("FLEX_BOT_CONFIG", str(path))
    yield path


@pytest.fixture
def bot_module(config_file, monkeypatch):
    """
    Fresh import of flex_radio_bot per test, with relay/network I/O stubbed.

    Returns the module; tests can override `_relay_get`, `_relay_set`,
    `_relay_pulse`, and `_flex_ping` as needed.
    """
    # Force a re-import so module-level caches (config, logger) start clean
    if "flex_radio_bot" in sys.modules:
        del sys.modules["flex_radio_bot"]
    import flex_radio_bot as frb

    # Default stubs: return success, no real I/O.
    monkeypatch.setattr(frb, "_relay_get", lambda c: False)
    monkeypatch.setattr(frb, "_relay_set", lambda c, on: True)
    monkeypatch.setattr(frb, "_relay_pulse", lambda c, s: True)
    monkeypatch.setattr(frb, "_flex_ping", lambda c: False)

    return frb


def make_msg(**overrides):
    """
    Construct a simulated keyword argument payload mirroring a Remote-Terminal-for-MeshCore message.

    This helper creates a full dictionary of message metadata (e.g., sender_name, sender_key,
    message_text, is_dm, is_outgoing) that the host system passes when invoking a python bot.
    The caller can selectively override any field to test different dispatch scenarios.

    Args:
        **overrides: Key-value pairs to set or modify in the returned payload.

    Returns:
        dict: A message payload structure suitable for unpacking as kwargs into `bot()`.
    """
    base = {
        "sender_name": None,
        "sender_key": None,
        "message_text": "",
        "is_dm": False,
        "channel_key": None,
        "channel_name": None,
        "sender_timestamp": None,
        "path": None,
        "is_outgoing": False,
        "path_bytes_per_hop": None,
    }
    base.update(overrides)
    return base
