"""Dispatch tests for flex_radio_bot.bot()."""
from __future__ import annotations

import time

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
