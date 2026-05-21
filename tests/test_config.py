"""Config-loader tests for flex_radio_bot._load_config()."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def fresh_bot(monkeypatch, tmp_path):
    """
    Provide a fresh import of the `flex_radio_bot` module with isolated config.

    This fixture removes `flex_radio_bot` from `sys.modules` if already loaded, ensuring
    each test executes with an isolated, clean module-level state. It directs the
    config file loader path to a unique temporary file path managed by pytest.

    Args:
        monkeypatch (MonkeyPatch): Pytest utility to temporarily override env variables.
        tmp_path (Path): Pytest utility to manage temporary directories.

    Returns:
        tuple[ModuleType, Path]: A tuple containing the freshly-imported module and its
                                 associated temporary config file path.
    """
    cfg_path = tmp_path / "cfg.json"
    monkeypatch.setenv("FLEX_BOT_CONFIG", str(cfg_path))
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if "flex_radio_bot" in sys.modules:
        del sys.modules["flex_radio_bot"]
    import flex_radio_bot as frb
    return frb, cfg_path


def _write(path: Path, data: dict) -> None:
    """
    Serialize a dictionary as JSON and write it to the specified file path.

    Args:
        path (Path): Destination file path.
        data (dict): Dictionary containing configuration keys to write.
    """
    path.write_text(json.dumps(data))


# ---------------------------------------------------------------------------

def test_missing_file_returns_none(fresh_bot):
    """Verify that _load_config() returns None when the configuration file does not exist on disk."""
    frb, _ = fresh_bot
    assert frb._load_config() is None


def test_invalid_json_returns_none(fresh_bot):
    """Verify that _load_config() returns None when the configuration file contains corrupted or invalid JSON."""
    frb, path = fresh_bot
    path.write_text("{this is not json")
    assert frb._load_config() is None


def test_minimal_valid_config(fresh_bot):
    """Verify that _load_config() correctly parses a minimal valid configuration and applies standard default values."""
    frb, path = fresh_bot
    _write(path, {
        "tuya_device_id": "x", "tuya_local_key": "y",
    })
    cfg = frb._load_config()
    assert cfg is not None
    assert cfg["tuya_device_id"] == "x"
    # Defaults applied
    assert cfg["relay_channel"] == 1
    assert cfg["short_pulse_seconds"] == 0.5
    assert cfg["long_pulse_seconds"] == 5.0
    assert cfg["cooldown_seconds"] == 3.0
    assert cfg["tuya_version"] == 3.4
    assert cfg["tuya_address"] == "Auto"
    assert cfg["allow_channel_control"] is False


def test_allowed_keys_normalized_to_lowercase_set(fresh_bot):
    """Verify that allowed sender public keys are stripped, normalized to lowercase, and stored in a set."""
    frb, path = fresh_bot
    _write(path, {
        "tuya_device_id": "x", "tuya_local_key": "y",
        "allowed_sender_keys": ["AABBcc", "  DDEEff  ", ""],
    })
    cfg = frb._load_config()
    assert cfg["allowed_sender_keys"] == {"aabbcc", "ddeeff"}


def test_hot_reload_on_mtime_change(fresh_bot, monkeypatch):
    """Verify that the bot correctly hot-reloads the configuration when the file modification time changes on disk."""
    frb, path = fresh_bot
    _write(path, {
        "tuya_device_id": "x", "tuya_local_key": "y",
        "allowed_sender_keys": ["aa"],
    })
    cfg1 = frb._load_config()
    assert cfg1["allowed_sender_keys"] == {"aa"}

    # Touch mtime forward so the cache invalidates regardless of fs resolution
    import os
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 10))

    _write(path, {
        "tuya_device_id": "x", "tuya_local_key": "y",
        "allowed_sender_keys": ["bb"],
    })
    # Re-touch in case the second write reset mtime backwards in tmpfs.
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 20))
    cfg2 = frb._load_config()
    assert cfg2["allowed_sender_keys"] == {"bb"}


def test_no_reload_if_mtime_unchanged(fresh_bot):
    """Verify that the config loader returns the cached dictionary object if the file modification time is unchanged."""
    frb, path = fresh_bot
    _write(path, {"tuya_device_id": "x", "tuya_local_key": "y"})
    cfg1 = frb._load_config()
    cfg2 = frb._load_config()
    assert cfg1 is cfg2   # cache hit returns the same object
