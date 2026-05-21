# MeshcoreFlexRadioPower

> Remote power control for FlexRadio 8000-series transceivers over a MeshCore
> LoRa mesh, via an MHCOZY TYWB Tuya Wi-Fi relay.

[![CI](https://github.com/w8mej/MeshcoreFlexRadioPower/actions/workflows/ci.yml/badge.svg)](https://github.com/w8mej/MeshcoreFlexRadioPower/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)

A small, security-conscious Python bot for
[Remote-Terminal-for-MeshCore](https://github.com/jkingsman/Remote-Terminal-for-MeshCore)
that lets authorized operators turn a FlexRadio on and off — and confirm its
state — from anywhere their MeshCore node can reach. The relay end is an
[MHCOZY TYWB](https://edge.flexradio.com/www/offload/20240325094526/MHCozy-WiFe-Remote-Instructions.pdf)
Tuya Wi-Fi switch wired into the back-panel `REM` jack.

```
    HT / portable node                  Pi + Remote-Terminal-for-MeshCore
   ┌──────────────────┐  LoRa (mesh)   ┌─────────────────────────────────┐
   │  "!flex on"  ────┼───────────────▶│  flex_radio_bot.py              │
   │                  │                │       │                         │
   │  "[FLEX] ok" ◀───┼────────────────│       ▼  tinytuya (local LAN)   │
   └──────────────────┘                │  MHCOZY TYWB ──RCA──▶ Flex REM  │
                                       └─────────────────────────────────┘
```

Why this exists: you want to bring a remote HF station up from the field
without depending on the public internet, a cloud service, or a phone app —
just the mesh you already have on the air.

---

## Features

- **Local-only control path.** Uses [`tinytuya`](https://github.com/jasonacox/tinytuya)
  for direct LAN control of the TYWB. No Tuya cloud round-trip; works during
  ISP outages.
- **Pulse semantics, not self-lock.** Treats the relay as momentary and pulses
  it from Python, so a single device gives you both `!flex on` (short press)
  and `!flex kill` (long press / hard off). Relay defaults to OPEN at boot —
  fail-safe.
- **Allowlist on public key.** Power commands require a 64-hex `sender_key`
  that's on the configured allowlist. Unsigned channel messages cannot pass.
- **DM-only by default.** Channel mode only exposes read-only `!flex status`
  and `!flex help`. Mutation requires a direct message.
- **Per-sender cooldown** to suppress fat-finger doubles.
- **Audit log** with rotation (`/var/log/flex_radio_bot.log` by default).
- **Hot-reload config** on file mtime change. Edit the allowlist without
  bouncing Remote-Terminal-for-MeshCore.
- **Optional state sense.** If you give the bot the Flex's hostname, it'll
  probe SmartSDR's discovery port to corroborate radio-up state.

---

## Quick start

```bash
git clone git@github.com:w8mej/MeshcoreFlexRadioPower.git
cd MeshcoreFlexRadioPower

# 1. Install dependency on the Pi
sudo pip3 install -r requirements.txt --break-system-packages

# 2. Pair the TYWB with the Smart Life / Tuya Smart app (one-time)
#    https://www.tuya.com/  (or the Smart Life app)

# 3. Pull the local_key from a Tuya developer account
python3 -m tinytuya wizard

# 4. Discover the relay and write /etc/meshcore/flex_radio_bot.json
sudo python3 flex_setup.py --from-wizard \
    --channel 1 \
    --flex-host flex-8600.local \
    --add-key <YOUR_64_HEX_MESHCORE_PUBKEY>

# 5. In Remote-Terminal-for-MeshCore: New Python Bot →
#    paste the contents of flex_radio_bot.py → Enable.
```

The setup script will exercise the relay (short pulse, then optionally a long
press) so you can confirm wiring before flying blind from the mesh.

See [`docs/HARDWARE.md`](docs/HARDWARE.md) for the wiring diagram and parts
list, and [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) for the threat
model.

---

## Commands

| Command           | Where     | Auth needed | Effect                                                    |
|-------------------|-----------|-------------|-----------------------------------------------------------|
| `!flex on`        | DM only   | yes         | 500 ms pulse — short press, toggles radio on              |
| `!flex off`       | DM only   | yes         | 500 ms pulse — SmartSDR (if running) does a clean shutdown|
| `!flex kill`      | DM only   | yes         | 5 s pulse — forced hard power off                         |
| `!flex relay on`  | DM only   | yes         | Close relay and leave it closed (raw)                     |
| `!flex relay off` | DM only   | yes         | Open relay (raw)                                          |
| `!flex status`    | DM or ch  | no          | Relay state + (optional) SmartSDR TCP probe               |
| `!flex help`      | DM or ch  | no          | Usage summary                                             |

DM-only restrictions on the mutation commands can be relaxed via the
`allow_channel_control` config flag — **not recommended**.

---

## Why an MHCOZY TYWB?

It's the relay FlexRadio themselves [document for their REM-ON use case](https://edge.flexradio.com/www/offload/20240325094526/MHCozy-WiFe-Remote-Instructions.pdf).
Cheap (~$15), dry contact (no voltage on the Flex side), USB-powered so it
runs off the same supply as the Pi, and supports the Tuya local-LAN protocol
so we don't have to talk to the cloud. The four-channel variant gives you
spare relays for things like a remote antenna switch or a 12 V coffee maker
that you didn't budget for.

---

## Repository layout

```
MeshcoreFlexRadioPower/
├── flex_radio_bot.py          The bot. Paste into Remote-Terminal-for-MeshCore.
├── flex_setup.py              CLI: discover, pair-check, write config, test relay.
├── examples/
│   └── flex_config.example.json
├── docs/
│   ├── HARDWARE.md            Parts list, wiring diagram, Flex REM behaviour.
│   ├── SECURITY_MODEL.md      Threat model + mitigations.
│   ├── TROUBLESHOOTING.md     Symptom → cause table, common gotchas.
│   └── OPERATIONS.md          Day-to-day ops, log rotation, key rotation.
├── tests/                     Unit tests for dispatch + config logic.
├── .github/                   CI workflow, issue templates, dependabot.
├── README.md                  You are here.
├── SECURITY.md                Disclosure policy.
├── CONTRIBUTING.md            How to send patches.
├── CHANGELOG.md               Versioned change history.
├── LICENSE                    MIT.
├── Makefile                   `make test`, `make lint`, `make package`.
├── requirements.txt           Runtime deps (tinytuya).
└── pyproject.toml             Tooling config (ruff, pytest).
```

---

## Operating constraints (read these)

- **The bot runs inside Remote-Terminal-for-MeshCore's process** and is
  invoked once per received message with a 10-second timeout. The long-press
  command (`!flex kill`) holds the relay closed for 5 s, well under the limit;
  don't extend pulse durations past 8.5 s.
- **Bots process all messages, including their own** — the bot drops any
  message where `is_outgoing=True`, which is the project's recommended
  pattern. Don't remove that guard.
- **Channel messages have `sender_key=None`** in MeshCore. The allowlist can
  therefore never be satisfied from a channel, which is the intended behavior.
- **The `tuya_local_key` rotates if you re-pair the TYWB in Smart Life.**
  Re-run `python3 -m tinytuya wizard` and `flex_setup.py --from-wizard`.

---

## Regulatory note

Powering a transceiver on or off is not transmission; FCC remote-control
rules (47 CFR §97.213) attach to control-of-transmissions, not to the AC mains
switch. That said, the licensee remains responsible for the station whenever
it is transmitting. If you wire this bot up to a key-down or PTT path
(don't), the rules and your insurance both get more interesting.

---

## License

MIT. See [`LICENSE`](LICENSE).

## Acknowledgements

- [Remote-Terminal-for-MeshCore](https://github.com/jkingsman/Remote-Terminal-for-MeshCore)
  for the bot-host environment.
- [`tinytuya`](https://github.com/jasonacox/tinytuya) for the local Tuya
  protocol library that makes this whole thing possible without a cloud
  dependency.
- The MeshCore project and its operators.

73,
**John Menerick / w8mej**

