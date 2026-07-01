"""
Tests for macOS platform-aware path detection and mock relay/radio integration.

Covers:
- DEFAULT_CONFIG_PATH and _DEFAULT_LOG_PATH select the correct platform values.
- Simulating Linux behaviour via platform monkeypatching.
- Full bot dispatch cycle with a fully-mocked Tuya relay (no hardware needed).
- Config auto-creation in the macOS XDG-style directory.
"""
from __future__ import annotations

import json
import platform
import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _fresh_frb(monkeypatch, tmp_path, platform_name: str):
    """
    Import flex_radio_bot with module-level state reset and platform spoofed.

    Forces re-import so the platform detection block at module load time runs
    under the spoofed platform.system() value.
    """
    if "flex_radio_bot" in sys.modules:
        del sys.modules["flex_radio_bot"]

    monkeypatch.setattr(platform, "system", lambda: platform_name)

    cfg_file = tmp_path / "cfg.json"
    monkeypatch.setenv("FLEX_BOT_CONFIG", str(cfg_file))

    import flex_radio_bot as frb
    return frb, cfg_file


# ---------------------------------------------------------------------------
# Platform path detection
# ---------------------------------------------------------------------------

class TestMacOSPaths:
    def test_darwin_config_dir_under_dot_config(self, monkeypatch, tmp_path):
        """On Darwin _DEFAULT_CONFIG_DIR must be ~/.config/flexradio."""
        frb, _ = _fresh_frb(monkeypatch, tmp_path, "Darwin")
        assert frb._DEFAULT_CONFIG_DIR == Path.home() / ".config" / "flexradio"

    def test_darwin_log_path_under_library_logs(self, monkeypatch, tmp_path):
        """On Darwin _DEFAULT_LOG_PATH must be inside ~/Library/Logs."""
        frb, _ = _fresh_frb(monkeypatch, tmp_path, "Darwin")
        assert "Library/Logs" in frb._DEFAULT_LOG_PATH
        assert frb._DEFAULT_LOG_PATH.endswith("flex_radio_bot.log")

    def test_linux_config_dir_is_etc_meshcore(self, monkeypatch, tmp_path):
        """On Linux _DEFAULT_CONFIG_DIR must be /etc/meshcore."""
        frb, _ = _fresh_frb(monkeypatch, tmp_path, "Linux")
        assert frb._DEFAULT_CONFIG_DIR == Path("/etc/meshcore")

    def test_linux_log_path_is_var_log(self, monkeypatch, tmp_path):
        """On Linux _DEFAULT_LOG_PATH must be /var/log/flex_radio_bot.log."""
        frb, _ = _fresh_frb(monkeypatch, tmp_path, "Linux")
        assert frb._DEFAULT_LOG_PATH == "/var/log/flex_radio_bot.log"

    def test_env_var_overrides_platform_default(self, monkeypatch, tmp_path):
        """FLEX_BOT_CONFIG env var must win over the computed platform default."""
        override = str(tmp_path / "custom.json")
        monkeypatch.setenv("FLEX_BOT_CONFIG", override)
        if "flex_radio_bot" in sys.modules:
            del sys.modules["flex_radio_bot"]
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        import flex_radio_bot as frb
        assert frb.DEFAULT_CONFIG_PATH == override

    def test_log_path_default_applied_in_load_config(self, monkeypatch, tmp_path):
        """_load_config() must fall back to _DEFAULT_LOG_PATH when log_path is absent."""
        frb, cfg_file = _fresh_frb(monkeypatch, tmp_path, "Darwin")
        cfg_file.write_text(json.dumps({
            "tuya_device_id": "bf000000000000000000",
            "tuya_local_key": "0123456789abcdef",
        }))
        cfg = frb._load_config()
        assert cfg is not None
        assert cfg["log_path"] == frb._DEFAULT_LOG_PATH
        assert "Library/Logs" in cfg["log_path"]

    def test_log_path_config_key_overrides_default(self, monkeypatch, tmp_path):
        """An explicit log_path in config must override the platform default."""
        frb, cfg_file = _fresh_frb(monkeypatch, tmp_path, "Darwin")
        custom_log = str(tmp_path / "mylog.log")
        cfg_file.write_text(json.dumps({
            "tuya_device_id": "bf000000000000000000",
            "tuya_local_key": "0123456789abcdef",
            "log_path": custom_log,
        }))
        cfg = frb._load_config()
        assert cfg is not None
        assert cfg["log_path"] == custom_log


# ---------------------------------------------------------------------------
# Mock Tuya relay — stateful in-process stand-in for hardware
# ---------------------------------------------------------------------------

def _mock_tinytuya():
    """
    Return a mock tinytuya module whose OutletDevice shares relay state across
    all instances created within the same mock.

    The real tinytuya flow creates a fresh OutletDevice per operation but the
    physical device retains state.  We replicate that by capturing a single
    shared state dict in a closure.
    """
    shared_state: dict[str, bool] = {}

    class MockRelayDevice:
        def __init__(self, dev_id, address, local_key, version, **_kw):
            self.dev_id = dev_id
            self.address = address
            self.local_key = local_key
            self.version = version

        def status(self) -> dict:
            return {"dps": dict(shared_state)}

        def set_status(self, on: bool, switch: int = 1) -> dict:
            shared_state[str(switch)] = on
            return {"dps": {str(switch): on}}

    mod = types.SimpleNamespace()
    mod.OutletDevice = MockRelayDevice
    return mod


def _make_cfg(tmp_path: Path, **overrides) -> dict:
    base = {
        "tuya_device_id": "bf000000000000000000",
        "tuya_local_key": "0123456789abcdef",
        "tuya_address": "192.168.1.99",
        "tuya_version": 3.4,
        "relay_channel": 1,
        "short_pulse_seconds": 0.01,
        "long_pulse_seconds": 0.02,
        "cooldown_seconds": 0.0,
        "allowed_sender_keys": ["a" * 64],
        "flex_host": None,
        "flex_smartsdr_port": 4992,
        "log_path": str(tmp_path / "test.log"),
        "allow_channel_control": False,
        "use_vault": False,
    }
    base.update(overrides)
    return base


def _write_cfg(path: Path, cfg: dict) -> None:
    serialisable = dict(cfg)
    if isinstance(serialisable.get("allowed_sender_keys"), set):
        serialisable["allowed_sender_keys"] = list(serialisable["allowed_sender_keys"])
    path.write_text(json.dumps(serialisable))


KEY_OK = "a" * 64
KEY_NO = "b" * 64


@pytest.fixture
def mock_bot(monkeypatch, tmp_path):
    """
    Fresh flex_radio_bot with a stateful in-process mock relay.

    relay_get / relay_set go through the real code path but hit MockRelayDevice
    instead of a live TYWB, so state transitions are actually tracked.
    """
    if "flex_radio_bot" in sys.modules:
        del sys.modules["flex_radio_bot"]

    cfg_path = tmp_path / "flex_radio_bot.json"
    monkeypatch.setenv("FLEX_BOT_CONFIG", str(cfg_path))

    import flex_radio_bot as frb

    monkeypatch.setattr(frb, "tinytuya", _mock_tinytuya())
    monkeypatch.setattr(frb, "_flex_ping", lambda c: False)

    _write_cfg(cfg_path, _make_cfg(tmp_path))
    return frb, cfg_path


def _msg(**overrides) -> dict:
    base = {
        "sender_name": "w8mej",
        "sender_key": KEY_OK,
        "message_text": "",
        "is_dm": True,
        "is_outgoing": False,
        "channel_key": None,
        "channel_name": None,
        "sender_timestamp": None,
        "path": None,
        "path_bytes_per_hop": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Mock relay integration tests (no radio attached)
# ---------------------------------------------------------------------------

class TestMockRelayIntegration:
    def test_relay_starts_open(self, mock_bot):
        """Freshly initialised mock relay must report open (off) state."""
        frb, _ = mock_bot
        cfg = frb._load_config()
        assert frb._relay_get(cfg) is False

    def test_relay_set_on_then_off(self, mock_bot):
        """_relay_set True then False must toggle the mock relay state correctly."""
        frb, _ = mock_bot
        cfg = frb._load_config()
        assert frb._relay_set(cfg, True) is True
        assert frb._relay_get(cfg) is True
        assert frb._relay_set(cfg, False) is True
        assert frb._relay_get(cfg) is False

    def test_bot_on_command_short_pulse_and_relay_returns_open(self, mock_bot):
        """!flex on must return 'short-press' and leave relay open after the pulse."""
        frb, _ = mock_bot
        reply = frb.bot(**_msg(message_text="!flex on"))
        assert reply is not None
        assert "short-press" in reply
        cfg = frb._load_config()
        assert frb._relay_get(cfg) is False

    def test_bot_kill_long_pulse_and_relay_returns_open(self, mock_bot):
        """!flex kill must return 'long-press' confirmation and leave relay open."""
        frb, _ = mock_bot
        reply = frb.bot(**_msg(message_text="!flex kill"))
        assert reply is not None
        assert "long-press" in reply
        cfg = frb._load_config()
        assert frb._relay_get(cfg) is False

    def test_bot_relay_on_latches_closed(self, mock_bot):
        """!flex relay on must leave the relay persistently closed."""
        frb, _ = mock_bot
        reply = frb.bot(**_msg(message_text="!flex relay on"))
        assert reply == "[FLEX] relay on"
        cfg = frb._load_config()
        assert frb._relay_get(cfg) is True

    def test_bot_relay_off_opens_latched_relay(self, mock_bot):
        """!flex relay off must reopen a relay previously latched closed."""
        frb, _ = mock_bot
        frb.bot(**_msg(message_text="!flex relay on"))
        reply = frb.bot(**_msg(message_text="!flex relay off"))
        assert reply == "[FLEX] relay off"
        cfg = frb._load_config()
        assert frb._relay_get(cfg) is False

    def test_status_reports_open_by_default(self, mock_bot):
        """!flex status must report relay=open when no command has been sent."""
        frb, _ = mock_bot
        reply = frb.bot(**_msg(message_text="!flex status"))
        assert "relay=open" in reply

    def test_status_reports_closed_after_latch(self, mock_bot):
        """!flex status must report relay=closed after !flex relay on."""
        frb, _ = mock_bot
        frb.bot(**_msg(message_text="!flex relay on"))
        reply = frb.bot(**_msg(message_text="!flex status"))
        assert "relay=closed" in reply

    def test_unauthorized_key_does_not_change_relay(self, mock_bot):
        """Commands from an unauthorized key must be rejected without touching the relay."""
        frb, _ = mock_bot
        reply = frb.bot(**_msg(message_text="!flex on", sender_key=KEY_NO))
        assert "unauthorized" in reply
        cfg = frb._load_config()
        assert frb._relay_get(cfg) is False

    def test_channel_power_command_rejected_by_default(self, mock_bot):
        """!flex on in a channel must be rejected when allow_channel_control is False."""
        frb, _ = mock_bot
        reply = frb.bot(**_msg(
            message_text="!flex on",
            is_dm=False,
            channel_name="#radio",
            sender_key=KEY_OK,
        ))
        assert "DM-only" in reply

    def test_help_responds_without_auth_in_channel(self, mock_bot):
        """!flex help must respond to any sender including unauthenticated ones."""
        frb, _ = mock_bot
        reply = frb.bot(**_msg(
            message_text="!flex help",
            is_dm=False,
            sender_key=None,
            channel_name="#radio",
        ))
        assert reply is not None
        assert "!flex" in reply

    def test_new_device_uses_local_key_when_vault_disabled(self, mock_bot):
        """_new_device must use tuya_local_key from config when use_vault=False."""
        frb, _ = mock_bot
        cfg = frb._load_config()
        assert cfg["use_vault"] is False
        d = frb._new_device(cfg)
        assert d.local_key == "0123456789abcdef"

    def test_mock_device_status_returns_dps_dict(self, mock_bot):
        """MockRelayDevice.status() must return a dict containing a 'dps' key."""
        frb, _ = mock_bot
        cfg = frb._load_config()
        d = frb._new_device(cfg)
        s = d.status()
        assert isinstance(s, dict) and "dps" in s

    def test_off_command_is_short_pulse_clean_shutdown(self, mock_bot):
        """!flex off must behave identically to !flex on (short pulse, relay returns open)."""
        frb, _ = mock_bot
        reply = frb.bot(**_msg(message_text="!flex off"))
        assert "short-press" in reply
        cfg = frb._load_config()
        assert frb._relay_get(cfg) is False


# ---------------------------------------------------------------------------
# flex_setup.write_config — macOS directory creation
# ---------------------------------------------------------------------------

def _import_flex_setup(monkeypatch, platform_name: str):
    """
    Import flex_setup with tinytuya stubbed and platform spoofed.

    flex_setup.py calls sys.exit() at module level if tinytuya is missing,
    so we inject a minimal stub into sys.modules before importing.
    """
    stub = types.ModuleType("tinytuya")
    monkeypatch.setitem(sys.modules, "tinytuya", stub)
    monkeypatch.setattr(platform, "system", lambda: platform_name)
    if "flex_setup" in sys.modules:
        del sys.modules["flex_setup"]
    import flex_setup as fs
    return fs


class TestFlexSetupMacOS:
    def test_write_config_creates_nested_dirs_and_sets_mode_600(self, monkeypatch, tmp_path):
        """write_config must create missing parent dirs and chmod the file to 0600."""
        fs = _import_flex_setup(monkeypatch, "Darwin")

        target = tmp_path / "nested" / "dir" / "config.json"
        cfg = {"tuya_device_id": "bf000", "tuya_local_key": "abc123"}
        fs.write_config(target, cfg)

        assert target.exists()
        assert oct(target.stat().st_mode)[-3:] == "600"
        loaded = json.loads(target.read_text())
        assert loaded["tuya_device_id"] == "bf000"

    def test_write_config_produces_valid_json(self, monkeypatch, tmp_path):
        """write_config output must be valid JSON that round-trips cleanly."""
        fs = _import_flex_setup(monkeypatch, "Darwin")

        target = tmp_path / "out.json"
        cfg = {
            "tuya_device_id": "bftest",
            "tuya_local_key": "key123",
            "relay_channel": 1,
            "allowed_sender_keys": ["a" * 64],
        }
        fs.write_config(target, cfg)
        loaded = json.loads(target.read_text())
        assert loaded == cfg

    def test_macos_default_config_path_matches_proposal(self, monkeypatch, tmp_path):  # noqa: ARG002
        """On Darwin, flex_setup.DEFAULT_CONFIG_PATH must be ~/.config/flexradio/..."""
        fs = _import_flex_setup(monkeypatch, "Darwin")

        assert ".config" in str(fs.DEFAULT_CONFIG_PATH)
        assert "flexradio" in str(fs.DEFAULT_CONFIG_PATH)
        assert fs.DEFAULT_CONFIG_PATH.name == "flex_radio_bot.json"

    def test_linux_default_config_path_is_etc_meshcore(self, monkeypatch, tmp_path):  # noqa: ARG002
        """On Linux, flex_setup.DEFAULT_CONFIG_PATH must be /etc/meshcore/..."""
        fs = _import_flex_setup(monkeypatch, "Linux")

        assert str(fs.DEFAULT_CONFIG_PATH) == "/etc/meshcore/flex_radio_bot.json"
