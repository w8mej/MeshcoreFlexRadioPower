"""Dispatch tests for flex_radio_bot.bot()."""
from __future__ import annotations

import json
import time

import pytest

from .conftest import make_msg

KEY_OK = "a" * 64
KEY_NO = "b" * 64


# --- ignore / no-op paths ---------------------------------------------------

def test_own_outgoing_message_ignored(bot_module):
    """Verify that messages marked as outgoing (sent by the bot itself) are ignored without any processing."""
    out = bot_module.bot(**make_msg(message_text="!flex on", is_outgoing=True))
    assert out is None


def test_non_flex_message_ignored(bot_module):
    """Verify that any message that does not contain the prefix '!flex' is quickly ignored without side effects."""
    out = bot_module.bot(**make_msg(message_text="hello there"))
    assert out is None


def test_empty_message_ignored(bot_module):
    """Verify that empty messages are silently ignored."""
    out = bot_module.bot(**make_msg(message_text=""))
    assert out is None


# --- help / status (no auth needed) -----------------------------------------

def test_help_in_channel(bot_module):
    """Verify that the standard !flex help usage message is returned when requested in a public channel."""
    out = bot_module.bot(**make_msg(
        message_text="!flex help", is_dm=False, channel_name="#radio"
    ))
    assert "!flex" in out and "help" in out


def test_status_in_channel_no_auth(bot_module):
    """Verify that public status requests return status info successfully without requiring authorization."""
    out = bot_module.bot(**make_msg(
        message_text="!flex status", is_dm=False, channel_name="#radio"
    ))
    assert out.startswith("[FLEX]") and "relay=" in out


def test_status_includes_flex_ping_when_configured(bot_module, monkeypatch):
    """Verify that status responses include the FlexRadio ping state when the radio host is configured."""
    # Re-config with a flex_host present
    cfg = bot_module._load_config()
    cfg["flex_host"] = "flex-8600.local"
    monkeypatch.setattr(bot_module, "_flex_ping", lambda c: True)
    out = bot_module.bot(**make_msg(message_text="!flex status", is_dm=True, sender_key=KEY_OK))
    assert "flex=up" in out


# --- DM-only enforcement ----------------------------------------------------

def test_on_in_channel_rejected(bot_module):
    """Verify that potentially mutating commands like '!flex on' are rejected with a DM-only error when sent in a channel."""
    out = bot_module.bot(**make_msg(
        message_text="!flex on", is_dm=False, channel_name="#radio"
    ))
    assert "DM-only" in out


def test_kill_in_channel_rejected(bot_module):
    """Verify that '!flex kill' commands are rejected with a DM-only error when sent in a public channel."""
    out = bot_module.bot(**make_msg(
        message_text="!flex kill", is_dm=False, channel_name="#radio"
    ))
    assert "DM-only" in out


def test_allow_channel_control_flag(bot_module):
    """Verify that modifying commands bypass the DM-only check when 'allow_channel_control' is enabled in the configuration."""
    cfg = bot_module._load_config()
    cfg["allow_channel_control"] = True
    # No sender_key in channel → still unauthorized, but not DM-blocked
    out = bot_module.bot(**make_msg(
        message_text="!flex on", is_dm=False, channel_name="#radio", sender_key=None
    ))
    assert "unauthorized" in out


# --- Authorization ----------------------------------------------------------

def test_unauthorized_key(bot_module):
    """Verify that commands sent by unauthorized public keys are rejected with an 'unauthorized' message."""
    out = bot_module.bot(**make_msg(
        message_text="!flex on", is_dm=True, sender_key=KEY_NO, sender_name="impostor"
    ))
    assert "unauthorized" in out


def test_authorized_short_press(bot_module):
    """Verify that authorized operators can successfully actuate the relay short pulse command."""
    out = bot_module.bot(**make_msg(
        message_text="!flex on", is_dm=True, sender_key=KEY_OK, sender_name="w8mej"
    ))
    assert "short-press" in out


def test_authorized_long_press_kill(bot_module):
    """Verify that authorized operators can successfully actuate the relay long pulse (hard kill) command."""
    out = bot_module.bot(**make_msg(
        message_text="!flex kill", is_dm=True, sender_key=KEY_OK, sender_name="w8mej"
    ))
    assert "long-press" in out and "hard off" in out


def test_case_insensitive_key_match(bot_module):
    """Verify that authorization check is case-insensitive with respect to the sender's public key."""
    out = bot_module.bot(**make_msg(
        message_text="!flex on", is_dm=True, sender_key=KEY_OK.upper(), sender_name="w8mej"
    ))
    assert "short-press" in out


# --- Raw relay commands -----------------------------------------------------

def test_relay_on_raw(bot_module):
    """Verify that authorized operators can command raw/sustained relay closure (ON)."""
    out = bot_module.bot(**make_msg(
        message_text="!flex relay on", is_dm=True, sender_key=KEY_OK
    ))
    assert out == "[FLEX] relay on"


def test_relay_off_raw(bot_module):
    """Verify that authorized operators can command raw/sustained relay opening (OFF)."""
    out = bot_module.bot(**make_msg(
        message_text="!flex relay off", is_dm=True, sender_key=KEY_OK
    ))
    assert out == "[FLEX] relay off"


def test_relay_invalid_arg(bot_module):
    """Verify that calling the raw relay command with invalid arguments returns a usage error."""
    out = bot_module.bot(**make_msg(
        message_text="!flex relay maybe", is_dm=True, sender_key=KEY_OK
    ))
    assert "usage" in out


def test_unknown_subcommand(bot_module):
    """Verify that invalid/unknown '!flex' subcommands return an unknown command notification."""
    out = bot_module.bot(**make_msg(
        message_text="!flex transmogrify", is_dm=True, sender_key=KEY_OK
    ))
    assert "unknown" in out


# --- Error propagation ------------------------------------------------------

def test_relay_error_surfaces(bot_module, monkeypatch):
    """Verify that relay actuation failures are caught and surfaced to the operator as a relay error."""
    monkeypatch.setattr(bot_module, "_relay_pulse", lambda c, s: False)
    out = bot_module.bot(**make_msg(
        message_text="!flex on", is_dm=True, sender_key=KEY_OK
    ))
    assert "relay error" in out


def test_relay_status_unknown_when_get_fails(bot_module, monkeypatch):
    """Verify that status requests show the relay state as unknown ('relay=?') if query execution fails."""
    monkeypatch.setattr(bot_module, "_relay_get", lambda c: None)
    out = bot_module.bot(**make_msg(message_text="!flex status", is_dm=True, sender_key=KEY_OK))
    assert "relay=?" in out


# --- Cooldown ---------------------------------------------------------------

def test_cooldown_blocks_rapid_repeat(bot_module):
    """Verify that rapid successive commands from the same sender are blocked by the cooldown rate-limiter."""
    cfg = bot_module._load_config()
    cfg["cooldown_seconds"] = 1.0

    msg = make_msg(message_text="!flex on", is_dm=True, sender_key=KEY_OK)
    first = bot_module.bot(**msg)
    second = bot_module.bot(**msg)
    assert "short-press" in first
    assert "cooldown" in second


def test_cooldown_expires(bot_module):
    """Verify that a sender can issue another command successfully once the cooldown window has elapsed."""
    cfg = bot_module._load_config()
    cfg["cooldown_seconds"] = 0.1

    msg = make_msg(message_text="!flex on", is_dm=True, sender_key=KEY_OK)
    first = bot_module.bot(**msg)
    time.sleep(0.15)
    second = bot_module.bot(**msg)
    assert "short-press" in first
    assert "short-press" in second


# --- Vault Integration Tests ------------------------------------------------

class MockVaultResponse:
    def __init__(self, data: dict):
        self._data = data

    def read(self):
        return json.dumps(self._data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def test_vault_retrieval_kv_v2_success(bot_module, monkeypatch):
    """Verify that _new_device() successfully retrieves local_key from a KV v2 Vault engine."""
    cfg = bot_module._load_config()
    cfg["use_vault"] = True
    cfg["vault_url"] = "http://127.0.0.1:8200"
    cfg["vault_token"] = "test-token"
    cfg["vault_secret_path"] = "v1/secret/data/flexradio"
    cfg["vault_secret_key"] = "tuya_local_key"

    payload = {
        "data": {
            "data": {
                "tuya_local_key": "vaulted_local_key_v2"
            }
        }
    }

    called_url = []
    called_headers = {}

    def mock_urlopen(req, timeout=3.0):
        called_url.append(req.full_url)
        called_headers.update(req.headers)
        return MockVaultResponse(payload)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    # We also mock tinytuya.OutletDevice so it doesn't fail on connection/broadcast
    class MockDevice:
        def __init__(self, dev_id, address, local_key, version, connection_timeout):
            self.dev_id = dev_id
            self.address = address
            self.local_key = local_key
            self.version = version

    import types
    mock_tinytuya = types.SimpleNamespace()
    mock_tinytuya.OutletDevice = MockDevice
    monkeypatch.setattr(bot_module, "tinytuya", mock_tinytuya)

    d = bot_module._new_device(cfg)
    assert d.local_key == "vaulted_local_key_v2"
    assert called_url == ["http://127.0.0.1:8200/v1/secret/data/flexradio"]
    # Check that X-Vault-Token was passed in headers (case-insensitive key comparison)
    headers_lower = {k.lower(): v for k, v in called_headers.items()}
    assert headers_lower.get("x-vault-token") == "test-token"


def test_vault_retrieval_kv_v1_success(bot_module, monkeypatch):
    """Verify that _new_device() successfully retrieves local_key from a KV v1 Vault engine."""
    cfg = bot_module._load_config()
    cfg["use_vault"] = True
    cfg["vault_url"] = "http://127.0.0.1:8200"
    cfg["vault_token"] = "test-token"
    cfg["vault_secret_path"] = "v1/secret/flexradio"
    cfg["vault_secret_key"] = "custom_key"

    payload = {
        "data": {
            "custom_key": "vaulted_local_key_v1"
        }
    }

    def mock_urlopen(req, timeout=3.0):
        return MockVaultResponse(payload)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    class MockDevice:
        def __init__(self, dev_id, address, local_key, version, connection_timeout):
            self.local_key = local_key

    import types
    mock_tinytuya = types.SimpleNamespace()
    mock_tinytuya.OutletDevice = MockDevice
    monkeypatch.setattr(bot_module, "tinytuya", mock_tinytuya)

    d = bot_module._new_device(cfg)
    assert d.local_key == "vaulted_local_key_v1"


def test_vault_token_path_success(bot_module, monkeypatch, tmp_path):
    """Verify that Vault token is read correctly from a file path when vault_token is omitted."""
    token_file = tmp_path / "token.txt"
    token_file.write_text("file-based-token\n")

    cfg = bot_module._load_config()
    cfg["use_vault"] = True
    cfg["vault_url"] = "http://127.0.0.1:8200"
    cfg["vault_token_path"] = str(token_file)
    cfg["vault_secret_path"] = "v1/secret/flexradio"

    payload = {"data": {"tuya_local_key": "abc"}}

    called_headers = {}

    def mock_urlopen(req, timeout=3.0):
        called_headers.update(req.headers)
        return MockVaultResponse(payload)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    class MockDevice:
        def __init__(self, dev_id, address, local_key, version, connection_timeout):
            self.local_key = local_key

    import types
    mock_tinytuya = types.SimpleNamespace()
    mock_tinytuya.OutletDevice = MockDevice
    monkeypatch.setattr(bot_module, "tinytuya", mock_tinytuya)

    d = bot_module._new_device(cfg)
    assert d.local_key == "abc"
    headers_lower = {k.lower(): v for k, v in called_headers.items()}
    assert headers_lower.get("x-vault-token") == "file-based-token"


def test_vault_token_env_fallback(bot_module, monkeypatch):
    """Verify that Vault falls back to the VAULT_TOKEN environment variable if no token is in config."""
    monkeypatch.setenv("VAULT_TOKEN", "env-token")

    cfg = bot_module._load_config()
    cfg["use_vault"] = True
    cfg["vault_url"] = "http://127.0.0.1:8200"
    cfg["vault_secret_path"] = "v1/secret/flexradio"

    payload = {"data": {"tuya_local_key": "def"}}
    called_headers = {}

    def mock_urlopen(req, timeout=3.0):
        called_headers.update(req.headers)
        return MockVaultResponse(payload)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    class MockDevice:
        def __init__(self, dev_id, address, local_key, version, connection_timeout):
            self.local_key = local_key

    import types
    mock_tinytuya = types.SimpleNamespace()
    mock_tinytuya.OutletDevice = MockDevice
    monkeypatch.setattr(bot_module, "tinytuya", mock_tinytuya)

    d = bot_module._new_device(cfg)
    assert d.local_key == "def"
    headers_lower = {k.lower(): v for k, v in called_headers.items()}
    assert headers_lower.get("x-vault-token") == "env-token"


def test_vault_failures_fail_closed(bot_module, monkeypatch):
    """Verify that Vault retrieval failures cause _new_device() to fail closed (raise RuntimeError)."""
    cfg = bot_module._load_config()
    cfg["use_vault"] = True
    cfg["vault_url"] = "http://127.0.0.1:8200"
    cfg["vault_token"] = "test-token"
    cfg["vault_secret_path"] = "v1/secret/flexradio"

    # 1. Connection error / Exception raised
    def mock_urlopen_fail(req, timeout=3.0):
        raise RuntimeError("network down")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_fail)

    import types
    mock_tinytuya = types.SimpleNamespace()
    monkeypatch.setattr(bot_module, "tinytuya", mock_tinytuya)

    with pytest.raises(RuntimeError, match="Vault enabled but local_key could not be retrieved"):
        bot_module._new_device(cfg)

    # 2. Key not in response
    payload_missing_key = {"data": {"wrong_key": "some_value"}}
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout=3.0: MockVaultResponse(payload_missing_key))

    # Reset cache to force refetch
    bot_module._VAULT_LOCAL_KEY = None
    with pytest.raises(RuntimeError, match="Vault enabled but local_key could not be retrieved"):
        bot_module._new_device(cfg)

    # 3. Missing token entirely
    bot_module._VAULT_LOCAL_KEY = None
    cfg["vault_token"] = None
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="Vault enabled but local_key could not be retrieved"):
        bot_module._new_device(cfg)


def test_vault_caching_and_cache_invalidation(bot_module, monkeypatch):
    """Verify that the Vault secret is cached in memory, and refetched only on configuration hot-reload."""
    cfg = bot_module._load_config()
    cfg["use_vault"] = True
    cfg["vault_url"] = "http://127.0.0.1:8200"
    cfg["vault_token"] = "test-token"
    cfg["vault_secret_path"] = "v1/secret/flexradio"

    class MockDevice:
        def __init__(self, dev_id, address, local_key, version, connection_timeout):
            self.local_key = local_key

    import types
    mock_tinytuya = types.SimpleNamespace()
    mock_tinytuya.OutletDevice = MockDevice
    monkeypatch.setattr(bot_module, "tinytuya", mock_tinytuya)

    payload = {"data": {"tuya_local_key": "cached_key"}}
    call_count = 0

    def mock_urlopen(req, timeout=3.0):
        nonlocal call_count
        call_count += 1
        return MockVaultResponse(payload)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    # First call: hits Vault
    d1 = bot_module._new_device(cfg)
    assert d1.local_key == "cached_key"
    assert call_count == 1

    # Second call: uses cache, call_count remains 1
    d2 = bot_module._new_device(cfg)
    assert d2.local_key == "cached_key"
    assert call_count == 1

    # Simulate hot-reload by invalidating the module cache
    bot_module._VAULT_LOCAL_KEY = None

    # Third call: hits Vault again
    d3 = bot_module._new_device(cfg)
    assert d3.local_key == "cached_key"
    assert call_count == 2
