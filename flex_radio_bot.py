"""
flex_radio_bot.py — Remote-Terminal-for-MeshCore bot for FlexRadio power control
via an MHCOZY TYWB Tuya Wi-Fi relay wired to the FLEX-8000 REM jack.

Drop this whole file into the Remote-Terminal-for-MeshCore "Python Bot" slot.

Wiring assumption
-----------------
    MHCOZY relay channel N: COM ──┐
                                  ├── RCA pigtail ── FLEX REM jack
                                  NO ───────────────────┘
The relay is treated as MOMENTARY by this bot (we pulse from Python),
so leave the channel mode in the Smart Life app set to "Self-locking".

Commands (must be sent as a DM unless noted)
--------------------------------------------
    !flex on            short pulse  (toggle radio on)
    !flex off           short pulse  (clean shutdown via SmartSDR)
    !flex kill          long pulse   (hard power-off, ~5s)
    !flex relay on      raw: close relay and leave closed
    !flex relay off     raw: open relay and leave open
    !flex status        read relay state + LAN reachability (also OK in channel)
    !flex help          usage (also OK in channel)

Config
------
Reads /etc/meshcore/flex_radio_bot.json (override via FLEX_BOT_CONFIG env var).
See flex_config.example.json for the schema. The setup script flex_setup.py
generates one for you.

Security
--------
- Allowlist of sender public keys; everything else gets a quiet "unauthorized".
- Per-sender 3-second cooldown to suppress fat-fingered double sends.
- Audit log to /var/log/flex_radio_bot.log (override in config).
- Channel messages only get read-only commands. Power control is DM-only.
- Module-level state is intentional: persists between bot() invocations within
  the same Remote-Terminal process, resets on restart (fail-safe default).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import socket
import threading
import time
from pathlib import Path

# tinytuya is the only third-party dep. Install on the Pi:
#   sudo pip3 install tinytuya --break-system-packages
# (or use a venv; whatever your Remote-Terminal-for-MeshCore install uses).
try:
    import tinytuya  # type: ignore
except ImportError:  # pragma: no cover
    tinytuya = None


# ---------------------------------------------------------------------------
# Module-level state (survives between bot() calls within the same process)
# ---------------------------------------------------------------------------

_STATE_LOCK = threading.Lock()
_CONFIG: dict | None = None
_CONFIG_MTIME: float = 0.0
_LAST_CMD_AT: dict[str, float] = {}        # sender_key -> unix ts
_LOGGER: logging.Logger | None = None
_RELAY_LOCK = threading.Lock()             # serialize relay I/O
_VAULT_LOCAL_KEY: str | None = None        # cache Vault key dynamically


# Platform-aware default paths so the bot runs without sudo on macOS.
if platform.system() == "Darwin":
    _DEFAULT_CONFIG_DIR = Path.home() / ".config" / "flexradio"
    _DEFAULT_LOG_PATH = str(Path.home() / "Library" / "Logs" / "flex_radio_bot.log")
else:
    _DEFAULT_CONFIG_DIR = Path("/etc/meshcore")
    _DEFAULT_LOG_PATH = "/var/log/flex_radio_bot.log"

DEFAULT_CONFIG_PATH = os.environ.get(
    "FLEX_BOT_CONFIG",
    str(_DEFAULT_CONFIG_DIR / "flex_radio_bot.json"),
)


# ---------------------------------------------------------------------------
# Config + logging
# ---------------------------------------------------------------------------

def _load_config() -> dict | None:
    """
    Load and hot-reload the configuration file from disk.

    This function monitors the modification time (mtime) of the configuration file.
    If the file has not changed since the last load, it returns the cached configuration.
    If the file has changed, it parses the JSON content, applies sensible default values,
    normalizes the allowed sender public keys to lowercase, and caches the result.

    Returns:
        dict: The normalized configuration dictionary, or None if the file is missing,
              unreadable, or contains invalid JSON.
    """
    global _CONFIG, _CONFIG_MTIME, _VAULT_LOCAL_KEY
    path = Path(DEFAULT_CONFIG_PATH)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _CONFIG is not None and mtime == _CONFIG_MTIME:
        return _CONFIG
    try:
        with path.open("r") as fh:
            cfg = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None

    # Normalize: lowercase hex keys, sane defaults
    cfg.setdefault("allowed_sender_keys", [])
    cfg["allowed_sender_keys"] = {
        k.lower().strip() for k in cfg["allowed_sender_keys"] if k
    }
    cfg.setdefault("relay_channel", 1)        # which switch on the 4ch board
    cfg.setdefault("short_pulse_seconds", 0.5)
    cfg.setdefault("long_pulse_seconds", 5.0)
    cfg.setdefault("cooldown_seconds", 3.0)
    cfg.setdefault("tuya_version", 3.4)
    cfg.setdefault("tuya_address", "Auto")    # "Auto" → broadcast discovery
    cfg.setdefault("flex_host", None)         # optional: hostname/IP of Flex for ping
    cfg.setdefault("flex_smartsdr_port", 4992)
    cfg.setdefault("log_path", _DEFAULT_LOG_PATH)
    cfg.setdefault("allow_channel_control", False)
    cfg.setdefault("use_vault", False)
    cfg.setdefault("vault_url", "http://127.0.0.1:8200")
    cfg.setdefault("vault_token", None)
    cfg.setdefault("vault_token_path", None)
    cfg.setdefault("vault_secret_path", "v1/secret/data/flexradio")
    cfg.setdefault("vault_secret_key", "tuya_local_key")

    _CONFIG = cfg
    _CONFIG_MTIME = mtime
    _VAULT_LOCAL_KEY = None  # Clear cache on reload to force refetching from Vault if config changed
    return cfg


def _logger(cfg: dict) -> logging.Logger:
    """
    Retrieve or initialize the bot's thread-safe rotating file logger.

    If a logger has not been initialized yet, this function creates a logger named
    'flex_radio_bot' that writes to the file path specified in `cfg["log_path"]`.
    It configures a RotatingFileHandler to cap logs at 1,000,000 bytes (1MB) and preserves
    up to 3 backup logs. If the log path is unwritable (e.g., due to permissions),
    it gracefully falls back to logging to standard error/stdout.

    Args:
        cfg (dict): The active configuration dictionary containing "log_path".

    Returns:
        logging.Logger: The configured Logger instance.
    """
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    log = logging.getLogger("flex_radio_bot")
    log.setLevel(logging.INFO)
    log.propagate = False
    try:
        handler = logging.handlers.RotatingFileHandler(
            cfg["log_path"], maxBytes=1_000_000, backupCount=3
        )
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    log.addHandler(handler)
    _LOGGER = log
    return log


# ---------------------------------------------------------------------------
# Relay operations
# ---------------------------------------------------------------------------

def _fetch_from_vault(cfg: dict, log: logging.Logger) -> str | None:
    """
    Retrieve the Tuya local key from a HashiCorp Vault server.

    This uses standard library urllib.request to fetch the secret to avoid
    introducing heavy third-party dependencies (like hvac) in the bot context.

    Args:
        cfg (dict): The active configuration dictionary.
        log (logging.Logger): The active logger.

    Returns:
        str | None: The retrieved local key, or None on failure.
    """
    url = cfg.get("vault_url")
    secret_path = cfg.get("vault_secret_path")
    secret_key = cfg.get("vault_secret_key", "tuya_local_key")

    if not url or not secret_path:
        log.error("Vault enabled but vault_url or vault_secret_path is not configured")
        return None

    # Retrieve token
    token = cfg.get("vault_token")
    if not token and cfg.get("vault_token_path"):
        try:
            token_path = Path(cfg["vault_token_path"])
            token = token_path.read_text().strip()
        except OSError as e:
            log.error("Failed to read Vault token from %s: %s", cfg["vault_token_path"], e)
            return None

    if not token:
        token = os.environ.get("VAULT_TOKEN")

    if not token:
        log.error("Vault enabled but no token found in config, token_path, or VAULT_TOKEN env var")
        return None

    base_url = url.rstrip("/")
    path = secret_path.lstrip("/")
    full_url = f"{base_url}/{path}"

    import urllib.error
    import urllib.request

    req = urllib.request.Request(full_url)
    req.add_header("X-Vault-Token", token)
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=3.0) as response:
            res_data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        log.error("Failed to fetch secret from Vault at %s: %s", full_url, e)
        return None

    try:
        data = res_data.get("data", {})
        if "data" in data and isinstance(data["data"], dict):
            # KV V2
            secret_value = data["data"].get(secret_key)
        else:
            # KV V1
            secret_value = data.get(secret_key)

        if not secret_value:
            log.error("Secret key %r not found in Vault response at %s", secret_key, full_url)
            return None

        return str(secret_value)
    except Exception as e:
        log.error("Failed to parse Vault response from %s: %s", full_url, e)
        return None


def _new_device(cfg: dict):
    """
    Instantiate a new TinyTuya OutletDevice for local communication.

    This function creates a new instance of tinytuya.OutletDevice using the device ID,
    local key, protocol version, and IP address from the configuration. This operation
    is cheap and performed on-demand per request to avoid holding stale TCP connections
    and to automatically adapt to dynamic IP address discovery.

    Args:
        cfg (dict): The active configuration dictionary.

    Returns:
        tinytuya.OutletDevice: An un-connected Tuya OutletDevice.

    Raises:
        RuntimeError: If the tinytuya library is not installed or Vault retrieval fails.
    """
    if tinytuya is None:
        raise RuntimeError("tinytuya not installed")

    local_key = cfg.get("tuya_local_key")
    if cfg.get("use_vault"):
        global _VAULT_LOCAL_KEY
        if _VAULT_LOCAL_KEY is None:
            log = _logger(cfg)
            _VAULT_LOCAL_KEY = _fetch_from_vault(cfg, log)
        if _VAULT_LOCAL_KEY:
            local_key = _VAULT_LOCAL_KEY
        else:
            raise RuntimeError("Vault enabled but local_key could not be retrieved")

    if not local_key:
        raise RuntimeError("local_key is missing")

    d = tinytuya.OutletDevice(
        dev_id=cfg["tuya_device_id"],
        address=cfg.get("tuya_address") or "Auto",
        local_key=local_key,
        version=float(cfg["tuya_version"]),
        connection_timeout=3,
    )
    return d


def _relay_get(cfg: dict) -> bool | None:
    """
    Query the Tuya device over the local network to retrieve the current relay state.

    This function sends a status query command to the physical relay. It uses a
    module-level lock `_RELAY_LOCK` to serialize Tuya I/O operations and prevent concurrent
    requests from colliding.

    Args:
        cfg (dict): The active configuration dictionary containing Tuya credentials and channel.

    Returns:
        bool | None: True if the relay channel is closed (ON), False if it is open (OFF),
                    or None if the device is unreachable or fails to return status.
    """
    try:
        with _RELAY_LOCK:
            d = _new_device(cfg)
            status = d.status()
        if not isinstance(status, dict) or "dps" not in status:
            return None
        return bool(status["dps"].get(str(cfg["relay_channel"])))
    except Exception:
        return None


def _relay_set(cfg: dict, on: bool) -> bool:
    """
    Command the Tuya device to set the relay state to closed (ON) or open (OFF).

    This function sends a state transition request to the physical relay under `_RELAY_LOCK`.
    It checks the return payload from tinytuya to verify that no error code was returned.

    Args:
        cfg (dict): The active configuration dictionary containing Tuya credentials and channel.
        on (bool): True to close the relay, False to open it.

    Returns:
        bool: True if the relay state was successfully set, False otherwise.
    """
    try:
        with _RELAY_LOCK:
            d = _new_device(cfg)
            result = d.set_status(on, switch=cfg["relay_channel"])
        return isinstance(result, dict) and "Error" not in result
    except Exception:
        return False


def _relay_pulse(cfg: dict, seconds: float) -> bool:
    """
    Perform a momentary pulse on the relay by closing it and then opening it after a delay.

    This is the core actuation mechanism for toggling or shutting down the radio (which expects
    a momentary contact closure). The delay is bounded between 0.05 seconds and 8.5 seconds to
    ensure the overall execution does not exceed the 10-second Remote-Terminal bot timeout.

    Args:
        cfg (dict): The active configuration dictionary.
        seconds (float): The duration in seconds for which to hold the relay closed.

    Returns:
        bool: True if both setting the relay to True and resetting it to False succeeded,
              False otherwise.
    """
    if not _relay_set(cfg, True):
        return False
    # Sleep budget: caller must keep total < 10s (bot timeout).
    time.sleep(max(0.05, min(seconds, 8.5)))
    return _relay_set(cfg, False)


def _flex_ping(cfg: dict) -> bool:
    """
    Probe the FlexRadio to determine if it is currently powered on and reachable on the LAN.

    It performs a lightweight TCP connect check against the SmartSDR discovery port (default 4992)
    with a short 1.5-second timeout. If the connection succeeds, the radio is running SmartSDR.

    Args:
        cfg (dict): The active configuration dictionary containing "flex_host" and "flex_smartsdr_port".

    Returns:
        bool: True if the TCP connection was established successfully, False otherwise.
    """
    host = cfg.get("flex_host")
    if not host:
        return False
    port = int(cfg.get("flex_smartsdr_port", 4992))
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

HELP_TEXT = (
    "[FLEX] cmds (DM): !flex on | off | kill | relay on|off | status | help"
)


def _is_authorized(cfg: dict, sender_key: str | None) -> bool:
    """
    Verify whether the message sender's public key is in the allowed operators list.

    Args:
        cfg (dict): The active configuration dictionary.
        sender_key (str | None): The 64-character hex public key of the message sender.

    Returns:
        bool: True if the sender is authorized, False otherwise.
    """
    if not sender_key:
        return False
    return sender_key.lower() in cfg["allowed_sender_keys"]


def _cooldown_ok(sender_key: str, cooldown_s: float) -> bool:
    """
    Enforce a per-sender rate-limiting cooldown window to prevent rapid command re-entry.

    Uses `_STATE_LOCK` to safely access and update the `_LAST_CMD_AT` module-level dictionary
    which maps sender keys to their last executed command time.

    Args:
        sender_key (str): The sender's public key.
        cooldown_s (float): The minimum required delay in seconds between commands.

    Returns:
        bool: True if the cooldown has elapsed and the command can proceed, False if rate-limited.
    """
    now = time.monotonic()
    with _STATE_LOCK:
        last = _LAST_CMD_AT.get(sender_key, 0.0)
        if now - last < cooldown_s:
            return False
        _LAST_CMD_AT[sender_key] = now
    return True


def _handle(cfg, log, sender_name, sender_key, message, is_dm) -> str | None:
    """
    Parse the message and dispatch the appropriate command handler.

    This function extracts the subcommands from the incoming `!flex` string and enforces
    all access control policies:
    1. Help and status commands can be called in channels by anyone (read-only).
    2. Modifying commands (on, off, kill, relay) are rejected in public channels unless
       specifically enabled by the "allow_channel_control" config flag.
    3. Modifying commands require the sender's public key to be registered in the allowlist.
    4. Modifying commands enforce the per-sender rate-limiting cooldown.

    Args:
        cfg (dict): The current configuration dictionary.
        log (logging.Logger): The active logger.
        sender_name (str | None): The name of the sender, if available.
        sender_key (str | None): The sender's public key, if available.
        message (str): The raw message text.
        is_dm (bool): True if the message was received as a direct message (DM).

    Returns:
        str | None: The reply string to be sent back to the sender, or None if the message
                    is not a bot command.
    """
    text = (message or "").strip().lower()
    if not text.startswith("!flex"):
        return None

    parts = text.split()
    sub = parts[1] if len(parts) > 1 else "help"
    arg = parts[2] if len(parts) > 2 else None
    who = sender_name or (sender_key[:8] if sender_key else "channel")

    # Read-only commands are allowed in channel too.
    if sub == "help":
        return HELP_TEXT
    if sub == "status":
        state = _relay_get(cfg)
        flex_up = _flex_ping(cfg) if cfg.get("flex_host") else None
        bits = [
            "relay=" + ("closed" if state else "open" if state is False else "?"),
        ]
        if flex_up is not None:
            bits.append("flex=" + ("up" if flex_up else "down"))
        log.info("status by %s: %s", who, " ".join(bits))
        return "[FLEX] " + " ".join(bits)

    # Everything below mutates state.
    if not is_dm and not cfg.get("allow_channel_control", False):
        return "[FLEX] control commands are DM-only"

    if not _is_authorized(cfg, sender_key):
        log.warning("UNAUTHORIZED %s key=%s cmd=%s", who, sender_key, sub)
        return "[FLEX] unauthorized"

    if not _cooldown_ok(sender_key, cfg["cooldown_seconds"]):
        return "[FLEX] cooldown, try again in a few seconds"

    if sub == "on":
        ok = _relay_pulse(cfg, cfg["short_pulse_seconds"])
        log.info("ON pulse by %s ok=%s", who, ok)
        return "[FLEX] short-press sent" if ok else "[FLEX] relay error"

    if sub == "off":
        # "Off" = short press; SmartSDR (if running) will initiate clean
        # shutdown. Use !flex kill for a forced long-press.
        ok = _relay_pulse(cfg, cfg["short_pulse_seconds"])
        log.info("OFF pulse by %s ok=%s", who, ok)
        return "[FLEX] short-press sent (clean shutdown)" if ok else "[FLEX] relay error"

    if sub == "kill":
        ok = _relay_pulse(cfg, cfg["long_pulse_seconds"])
        log.info("KILL pulse by %s ok=%s", who, ok)
        return "[FLEX] long-press sent (hard off)" if ok else "[FLEX] relay error"

    if sub == "relay":
        if arg not in ("on", "off"):
            return "[FLEX] usage: !flex relay on|off"
        target = arg == "on"
        ok = _relay_set(cfg, target)
        log.info("relay %s by %s ok=%s", arg, who, ok)
        return f"[FLEX] relay {arg}" if ok else "[FLEX] relay error"

    return "[FLEX] unknown cmd. !flex help"


# ---------------------------------------------------------------------------
# Public entrypoint required by Remote-Terminal-for-MeshCore
# ---------------------------------------------------------------------------

def bot(**kwargs) -> str | list[str] | None:
    """
    The main execution entrypoint invoked by the Remote-Terminal-for-MeshCore system.

    This function is executed each time a message is received on the MeshCore network.
    It ignores outgoing messages and non-bot commands quickly to minimize processing.
    It performs on-demand config loading (hot-reloading if changed), sets up logging,
    and forwards the request to the central dispatch handler.

    Args:
        **kwargs: Arbitrary keyword arguments passed by the host system:
            - message_text (str): The body of the message received.
            - is_outgoing (bool): Whether the message was generated by this bot.
            - is_dm (bool): Whether the message is a direct message.
            - sender_name (str, optional): The name of the sender.
            - sender_key (str, optional): The 64-hex public key of the sender.

    Returns:
        str | list[str] | None: A single string or a list of strings representing the
                                responses to send back to the user, or None if no response
                                should be sent.
    """
    # Hard rule: never reply to our own outgoing messages.
    if kwargs.get("is_outgoing"):
        return None

    message = kwargs.get("message_text", "") or ""
    # Quick reject before doing any I/O.
    if "!flex" not in message.lower():
        return None

    cfg = _load_config()
    if cfg is None:
        # Fail closed but visible — the operator will notice.
        return "[FLEX] config missing or unreadable"

    log = _logger(cfg)

    is_dm = bool(kwargs.get("is_dm"))
    sender_name = kwargs.get("sender_name")
    sender_key = (kwargs.get("sender_key") or "").lower() or None

    try:
        return _handle(cfg, log, sender_name, sender_key, message, is_dm)
    except Exception as exc:
        log.exception("unhandled error: %s", exc)
        return "[FLEX] internal error"
