# macOS Porting Proposal

**Branch:** `apples`  
**Date:** 2026-06-30  
**Scope:** Everything required to run FlexPowerMesh flawlessly on macOS instead of (or in addition to) a Linux Raspberry Pi.

---

## Background

The project was written and documented with a Raspberry Pi running Raspberry Pi OS (Debian-based Linux) as the sole host. Every assumption in the code, docs, and CI reflects that: paths under `/etc` and `/var/log`, `systemd` service management, pip's `--break-system-packages` flag, and a Linux-only OS classifier in `pyproject.toml`. This document enumerates every change needed to make the project work correctly on macOS with no regressions on Linux.

---

## Summary of Changes

| # | File / Area | Change |
|---|-------------|--------|
| 1 | `flex_radio_bot.py` | Default config and log paths |
| 2 | `flex_setup.py` | Default config path + install instructions in docstring |
| 3 | `pyproject.toml` | OS classifier + add macOS to supported platforms |
| 4 | `Makefile` | Portable venv setup target |
| 5 | `requirements.txt` | No change needed (tinytuya is cross-platform) |
| 6 | `.github/workflows/ci.yml` | Add `macos-latest` runner |
| 7 | `docs/HARDWARE.md` | Remove Pi-only language, generalize host requirements |
| 8 | `docs/OPERATIONS.md` | Systemd section → platform-aware; add launchd plist for macOS |
| 9 | `docs/TROUBLESHOOTING.md` | Add macOS-specific networking notes |
| 10 | `examples/flex_config.example.json` | Platform-relative path comments |
| 11 | `README.md` | Installation section + path examples |
| 12 | `tests/conftest.py` | No change needed (already uses `tmp_path`) |

---

## Detailed Change Specifications

---

### 1. `flex_radio_bot.py` — Default Paths

**Problem:** The default config path is hardcoded to `/etc/meshcore/flex_radio_bot.json` and the default log path in `_load_config()` defaults to `/var/log/flex_radio_bot.log`.

On macOS:
- `/etc` is a symlink to `/private/etc`. Writing there requires `sudo` and violates macOS norms.
- `/var/log` is `/private/var/log`. Writing there also requires `sudo` and is reserved for Apple system logs; third-party daemons must not write here by convention.

**Fix:** Make the default paths platform-aware at module load time.

```python
# In flex_radio_bot.py, replace the DEFAULT_CONFIG_PATH block at the top with:

import platform as _platform

if _platform.system() == "Darwin":
    # macOS: user-owned locations that work without sudo.
    # XDG-style under ~/.config for the config file;
    # ~/Library/Logs for the log (the macOS convention for per-user daemons).
    _DEFAULT_CONFIG_DIR  = Path.home() / ".config" / "flexradio"
    _DEFAULT_LOG_PATH    = str(Path.home() / "Library" / "Logs" / "flex_radio_bot.log")
else:
    # Linux / Raspberry Pi OS — original defaults preserved.
    _DEFAULT_CONFIG_DIR  = Path("/etc/meshcore")
    _DEFAULT_LOG_PATH    = "/var/log/flex_radio_bot.log"

DEFAULT_CONFIG_PATH = os.environ.get(
    "FLEX_BOT_CONFIG",
    str(_DEFAULT_CONFIG_DIR / "flex_radio_bot.json"),
)
```

In `_load_config()`, change the `log_path` default line from:
```python
cfg.setdefault("log_path", "/var/log/flex_radio_bot.log")
```
to:
```python
cfg.setdefault("log_path", _DEFAULT_LOG_PATH)
```

The `FLEX_BOT_CONFIG` environment-variable override already works on both platforms — no further changes needed for that escape hatch.

---

### 2. `flex_setup.py` — Default Config Path + Docstring

**Problem:** `DEFAULT_CONFIG_PATH = Path("/etc/meshcore/flex_radio_bot.json")` is hardcoded at the top.
The module docstring says "Run this once on the Pi" and install instructions include `--break-system-packages` (a Debian-only flag that is invalid on macOS/Homebrew Python).

**Fix A — Platform-aware default path:**

```python
# Replace the hardcoded DEFAULT_CONFIG_PATH with:
import platform as _platform
from pathlib import Path

if _platform.system() == "Darwin":
    DEFAULT_CONFIG_PATH = Path.home() / ".config" / "flexradio" / "flex_radio_bot.json"
else:
    DEFAULT_CONFIG_PATH = Path("/etc/meshcore/flex_radio_bot.json")
```

**Fix B — Docstring / install instructions:**

Replace:
```
Run this once on the Pi to:
...
Prereqs
-------
  sudo pip3 install tinytuya --break-system-packages
```

With:
```
Run this once on your host machine to:
...
Prereqs
-------
  # macOS (Homebrew Python or system Python — use a venv):
  python3 -m venv .venv && source .venv/bin/activate
  pip install tinytuya

  # Raspberry Pi / Debian Linux:
  sudo pip3 install tinytuya --break-system-packages
  # (or use a venv; see above)
```

**Fix C — `write_config` success message:**

The final `print()` says "Restart Remote-Terminal-for-MeshCore so the bot reloads." This is fine to keep but should be updated to mention the platform-appropriate service restart command (see §8).

---

### 3. `pyproject.toml` — OS Classifier

**Problem:** The project declares:
```toml
"Operating System :: POSIX :: Linux",
```
This causes the package to be tagged Linux-only on PyPI, preventing macOS users from finding it.

**Fix:** Replace with both classifiers:
```toml
"Operating System :: POSIX :: Linux",
"Operating System :: MacOS :: MacOS X",
```

---

### 4. `Makefile` — Portable Dev Setup

**Problem:** `make install` runs `pip install -r requirements.txt` directly. On macOS with a Homebrew or system Python this will fail with `externally-managed-environment` unless the user is already in a venv.

**Fix:** Add a `venv` target and adjust the other targets to be venv-aware:

```makefile
VENV   := .venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv
	$(PIP) install -r requirements.txt

dev: venv
	$(PIP) install -e ".[dev]"

test:
	$(VENV)/bin/pytest

lint:
	$(VENV)/bin/ruff check .

format:
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache .coverage htmlcov $(VENV)
	find . -type d -name __pycache__ -exec rm -rf {} +
```

This works identically on Linux and macOS. Users who already manage their own venv can still run `pip install -e ".[dev]"` directly.

---

### 5. `requirements.txt` — No Change Required

`tinytuya` is a pure-Python package that works on macOS. No change needed.

---

### 6. `.github/workflows/ci.yml` — Add macOS Runner

**Problem:** Both the `lint` and `test` jobs run on `ubuntu-latest` only. macOS-specific path behavior (e.g., `Path.home() / ".config"`) is not exercised in CI.

**Fix A — Add `macos-latest` to the test matrix:**

```yaml
test:
  runs-on: ${{ matrix.os }}
  strategy:
    fail-fast: false
    matrix:
      os: [ubuntu-latest, macos-latest]
      python-version: ["3.9", "3.10", "3.11", "3.12"]
```

**Fix B — The `syntax-only-setup` job** can also add `macos-latest` with minimal cost:

```yaml
syntax-only-setup:
  runs-on: ${{ matrix.os }}
  strategy:
    matrix:
      os: [ubuntu-latest, macos-latest]
      python-version: ["3.9", "3.12"]
```

The lint job can remain on `ubuntu-latest` — formatting checks are OS-agnostic.

---

### 7. `docs/HARDWARE.md` — Generalize Host Language

**Problem:** The bill of materials table includes:

> Raspberry Pi 3B+/4/5 on the same LAN | Hosts Remote-Terminal-for-MeshCore

The network layout diagram also labels the host box "Raspberry Pi".

**Fix:** Change the BOM row to:

> Any LAN-connected host (Raspberry Pi, Mac mini, laptop, NUC, …) | Hosts Remote-Terminal-for-MeshCore

Update the ASCII diagram host box:

```
   ┌──────────────────┐
   │  Host machine    │
   │  (Pi, Mac, NUC)  │
   │  Remote-Terminal │
   │  flex_radio_bot  │
   └──────────────────┘
```

Change the power-supply row:

> 5 V USB power supply (or Pi USB port) | Powers the TYWB

to:

> 5 V USB power supply | Powers the TYWB

The technical content (wiring, REM jack behavior, UDP broadcast requirement) is hardware-agnostic and needs no changes.

---

### 8. `docs/OPERATIONS.md` — Service Management (systemd → launchd)

**Problem:** The operations doc says:

> Make sure Remote-Terminal-for-MeshCore has a systemd unit (or equivalent) with `Restart=on-failure`.

This is meaningless on macOS, which uses `launchd`.

**Fix A — Updated paths table (add macOS column):**

| Path (Linux) | Path (macOS) | Purpose |
|---|---|---|
| `/etc/meshcore/flex_radio_bot.json` | `~/.config/flexradio/flex_radio_bot.json` | Bot config |
| `/var/log/flex_radio_bot.log` | `~/Library/Logs/flex_radio_bot.log` | Audit log |

Both paths can be overridden via the `FLEX_BOT_CONFIG` env var and `log_path` config key.

**Fix B — Add a "Service management" section with launchd instructions:**

```markdown
### macOS (launchd)

Create a LaunchAgent plist so the process restarts on failure and survives login:

    <!-- ~/Library/LaunchAgents/com.meshcore.remote-terminal.plist -->
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
      "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
        <key>Label</key>
        <string>com.meshcore.remote-terminal</string>
        <key>ProgramArguments</key>
        <array>
            <string>/usr/local/bin/remote-terminal</string>
        </array>
        <key>KeepAlive</key>
        <true/>
        <key>RunAtLoad</key>
        <true/>
        <key>StandardOutPath</key>
        <string>/Users/YOUR_USER/Library/Logs/remote-terminal.log</string>
        <key>StandardErrorPath</key>
        <string>/Users/YOUR_USER/Library/Logs/remote-terminal-error.log</string>
        <key>EnvironmentVariables</key>
        <dict>
            <key>FLEX_BOT_CONFIG</key>
            <string>/Users/YOUR_USER/.config/flexradio/flex_radio_bot.json</string>
        </dict>
    </dict>
    </plist>

Load it with:

    launchctl load ~/Library/LaunchAgents/com.meshcore.remote-terminal.plist

    # Stop / start:
    launchctl stop  com.meshcore.remote-terminal
    launchctl start com.meshcore.remote-terminal

    # Disable permanently:
    launchctl unload ~/Library/LaunchAgents/com.meshcore.remote-terminal.plist

Replace YOUR_USER with your actual username (whoami).
```

**Fix C — Backup command update:** Change the backup command to show both platforms:

```bash
# Linux
cat /etc/meshcore/flex_radio_bot.json | \
    gpg --encrypt --recipient YOUR_KEY_ID > flex_radio_bot.json.gpg

# macOS
cat ~/.config/flexradio/flex_radio_bot.json | \
    gpg --encrypt --recipient YOUR_KEY_ID > flex_radio_bot.json.gpg
```

---

### 9. `docs/TROUBLESHOOTING.md` — macOS Networking Notes

**Problem:** The troubleshooting doc does not mention macOS-specific networking and firewall behavior that affects `tinytuya` discovery.

**Fix:** Add a macOS section covering the following four points:

1. **macOS Application Firewall:** When `tinytuya` first sends UDP broadcast packets, macOS may display a dialog asking whether to allow incoming connections for Python. Click "Allow." If it was dismissed as "Deny," go to System Settings → Network → Firewall → Options, find `python3`, and set it to "Allow incoming connections."

2. **UDP broadcast on macOS:** `tinytuya`'s `deviceScan()` uses UDP broadcast on port 6666/6667. These are unblocked by default on macOS unless Little Snitch or another third-party firewall is running. Verify with:
   ```bash
   sudo tcpdump -i en0 udp port 6666 &
   python3 -c "import tinytuya; print(tinytuya.deviceScan(False, 5))"
   ```

3. **TCP/6668 to the TYWB:** The control channel from `tinytuya` to the relay uses TCP port 6668. If the TYWB is on a separate VLAN, ensure your Mac can route to it. Check with:
   ```bash
   nc -zv <TYWB_IP> 6668
   ```

4. **SIP (System Integrity Protection):** SIP does not affect this application since we write only to `~/.config` and `~/Library/Logs`. No SIP-related workarounds are needed.

---

### 10. `examples/flex_config.example.json` — Platform Path Comments

**Problem:** The example config has `"log_path": "/var/log/flex_radio_bot.log"` with no guidance for macOS users.

**Fix:** Add comment keys (JSON does not support comments natively, so use `_comment_*` keys as the file already does not prohibit them) to document the platform-specific defaults:

```json
{
  "_comment_paths": "Config: Linux=/etc/meshcore/flex_radio_bot.json | macOS=~/.config/flexradio/flex_radio_bot.json",
  "_comment_log":   "Log:    Linux=/var/log/flex_radio_bot.log        | macOS=~/Library/Logs/flex_radio_bot.log",
  ...
  "log_path": "/var/log/flex_radio_bot.log"
}
```

The `log_path` value remains the Linux default since the example is authoritative for Pi deployments; macOS users can either rely on auto-detection or override this field in their own config.

---

### 11. `README.md` — Installation Section

**Problem:** The README installation path examples reference Pi/Linux paths only.

**Fix:** Add a "macOS Quick Start" subsection alongside the existing Linux instructions:

```markdown
### macOS

```bash
# 1. Clone and create a virtual environment
git clone https://github.com/w8mej/MeshcoreFlexRadioPower.git
cd MeshcoreFlexRadioPower
python3 -m venv .venv && source .venv/bin/activate
pip install tinytuya

# 2. Discover the MHCOZY relay and write a config
python3 flex_setup.py --from-wizard
# Config is written to ~/.config/flexradio/flex_radio_bot.json
# Log goes to ~/Library/Logs/flex_radio_bot.log

# 3. Drop flex_radio_bot.py into Remote-Terminal-for-MeshCore's "Python Bot" slot
# 4. Set up a LaunchAgent for auto-restart — see docs/OPERATIONS.md
```
```

---

### 12. `tests/conftest.py` — No Change Required

The test suite already uses pytest's `tmp_path` fixture for all file I/O and `monkeypatch.setenv` to override `FLEX_BOT_CONFIG`. All tests are OS-agnostic and pass on macOS without modification.

---

## Items That Do NOT Need Changing

| Item | Reason |
|---|---|
| `tinytuya` library usage | Pure-Python; UDP/TCP socket calls work identically on macOS |
| `socket.create_connection` in `_flex_ping` | Standard library; cross-platform |
| `threading.Lock`, `time.monotonic` | Cross-platform |
| `logging.handlers.RotatingFileHandler` | Cross-platform |
| `urllib.request` Vault calls | Cross-platform |
| Tuya protocol (v3.1–3.5) | LAN protocol; not OS-specific |
| Relay pulse timing (`time.sleep`) | Cross-platform |
| All tests | Already OS-agnostic |
| `SECURITY.md` / `CONTRIBUTING.md` | No platform-specific content |
| Vault integration | `http://127.0.0.1:8200` works identically with `brew install vault` |
| Apple Silicon vs. Intel | `tinytuya` has no native extensions; runs natively on both |

---

## Implementation Order

Apply changes in this order to minimize broken intermediate states:

1. **`flex_radio_bot.py`** — path defaults (§1). Tests pass immediately after.
2. **`flex_setup.py`** — path + docstring (§2). Verify with `python -m py_compile flex_setup.py`.
3. **`pyproject.toml`** — classifier (§3). Cosmetic; no runtime effect.
4. **`Makefile`** — venv target (§4). Verify `make dev && make test` works on macOS.
5. **`.github/workflows/ci.yml`** — macOS runner (§6). CI will confirm cross-platform correctness automatically.
6. **Documentation** — §7, §8, §9, §10, §11. No runtime effect; review for accuracy.

---

## Verification Steps (macOS)

After the code changes in §1 and §2:

```bash
# 1. Fresh venv
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Confirm default path resolves correctly on macOS
python3 -c "
import flex_radio_bot as f
import platform
assert platform.system() == 'Darwin'
assert '.config/flexradio' in f.DEFAULT_CONFIG_PATH, f.DEFAULT_CONFIG_PATH
print('Path OK:', f.DEFAULT_CONFIG_PATH)
"

# 3. Full test suite
pytest --cov=flex_radio_bot --cov-report=term-missing

# 4. Syntax-check setup script
python -m py_compile flex_setup.py flex_radio_bot.py
```

All existing tests pass without modification. No hardware is required.

---

## Open Questions / Out of Scope

- **Remote-Terminal-for-MeshCore itself:** Whether the upstream MeshCore tooling has a macOS build is outside the scope of this bot project.
- **Homebrew Vault:** If running a local Vault on macOS via `brew install vault`, the Vault URL (`http://127.0.0.1:8200`) is identical. No changes needed.
