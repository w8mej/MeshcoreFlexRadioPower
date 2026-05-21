# Security Model

This document is the threat model for `MeshcoreFlexRadioPower`. It exists so that
when you (or a reviewer) ask "why does the bot do X this way," there's a
written answer.

## What we're protecting

In rough order of importance:

1. **The radio's physical state.** Don't let an attacker key down our
   transmitter, brick it via repeated thermal cycling, or interfere with an
   in-progress contact.
2. **The `tuya_local_key`.** It's the only credential between an attacker
   on our LAN and the relay. If it leaks, anyone on the LAN can flap the
   relay independent of the bot.
3. **The audit log.** We want forensic traceability after-the-fact for any
   unauthorized actuation.
4. **Operator availability.** The bot must not crash the Remote-Terminal-
   for-MeshCore host process or block its message pump.

## Trust boundaries

```
   ┌─────────────────────────────────────────────────────────────────┐
   │                       UNTRUSTED                                 │
   │   ┌─────────┐   ┌─────────┐   ┌──────────────┐                  │
   │   │ Mesh    │   │ Channel │   │ TYWB Wi-Fi   │                  │
   │   │ peers   │   │ msgs    │   │ network      │                  │
   │   └────┬────┘   └────┬────┘   └──────┬───────┘                  │
   └────────┼─────────────┼───────────────┼──────────────────────────┘
            │             │               │
            │ allowlist   │ DM-only       │ tinytuya local LAN
            ▼             ▼               ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │                        TRUSTED                                  │
   │   Pi host  +  Remote-Terminal-for-MeshCore  +  flex_radio_bot   │
   │     │                                              │            │
   │     ▼ config file (mode 0600)                      ▼ audit log  │
   │   /etc/meshcore/flex_radio_bot.json    /var/log/flex_radio_bot.log
   └─────────────────────────────────────────────────────────────────┘
```

Anything outside the inner box is treated as untrusted input.

## Adversaries and capabilities

### A1 — Mesh peer with a non-allowlisted identity

**Goal:** actuate the relay anyway.

**Mitigations:**
- 64-hex `sender_key` must appear in `allowed_sender_keys`.
- DMs only, so channel-mode `sender_key = None` cannot pass.
- Even if A1 spoofs a `sender_name`, the name is never used for
  authorization — only for the audit log.
- Unauthorized commands are logged at WARN with the actual `sender_key`
  observed.

### A2 — Authorized operator with a fat finger

**Goal:** not actually adversarial, but capable of causing damage by sending
the same command three times in a row.

**Mitigations:**
- Per-sender 3-second cooldown (`cooldown_seconds`, configurable).
- Distinct commands for "polite off" (`!flex off`) and "kill" (`!flex kill`)
  so the destructive one requires intent.
- Long-pulse duration capped at 8.5 s server-side regardless of config, so a
  misconfigured config can't blow the 10-second `bot()` budget.

### A3 — Compromised LAN peer

**Goal:** flap the relay without going through the bot.

**Mitigations (partial):**
- We use Tuya protocol v3.4 by default, which is AES-encrypted on the wire
  with per-device keys.
- The `tuya_local_key` is stored in a 0600 config file. Only `root` (or the
  user that owns Remote-Terminal-for-MeshCore) can read it.
- We **cannot** prevent A3 from issuing valid Tuya commands directly if they
  have the key. That's a limitation of the protocol. Mitigations are
  operational: segregate the TYWB on an IoT VLAN if you have one, and
  monitor the TYWB's own LED behavior.

### A4 — Local user on the Pi

**Goal:** read the `tuya_local_key` from disk.

**Mitigations:**
- Config file mode 0600.
- Log file mode 0640.
- `flex_setup.py` writes the file atomically (`tmp` → `rename`) so it never
  appears with permissive interim modes.
- `tuya_local_key` is never logged. (Verify if you modify the logger.)

A non-root local user with `CAP_DAC_OVERRIDE` or `sudo` is out of scope.

### A5 — Compromised Tuya cloud / MITM during setup

**Goal:** capture the local key during the wizard exchange.

**Mitigations:**
- We document, but do not perform, the cloud round-trip. The wizard runs once,
  on an operator-trusted machine, in a controlled environment.
- Once the local key is in hand, normal operation never touches the cloud.
- Re-pairing rotates the key. If a compromise is suspected, re-pair.

### A6 — Supply-chain compromise of `tinytuya`

**Goal:** ship malicious code into the bot's process.

**Mitigations:**
- `requirements.txt` pins a minimum version; in production, pin an exact
  version with a hash via `pip install --require-hashes`.
- Dependabot watches for advisories on the dependency.
- CI runs lint + tests on every PR.

## What we explicitly do not defend against

- **Physical access** to the Pi, the TYWB, or the radio. If someone is in
  the shack, all bets are off.
- **A compromised MeshCore identity.** If an operator's private key is
  exfiltrated from their HT, the attacker effectively *is* that operator.
  Operators rotate their identity keys themselves and remove old keys from
  the allowlist.
- **Denial of service against MeshCore.** Mesh jamming, repeater flooding,
  or LoRa noise floor attacks are out of scope.
- **The radio's own software.** SmartSDR, fpgaImage, etc. are upstream.

## Hardening recommendations

Beyond the defaults:

1. **Pin the dependency exactly** in production:
   ```
   tinytuya==1.13.2  --hash=sha256:...
   ```
2. **Segregate the TYWB on an IoT VLAN.** Allow only the Pi's IP to reach
   TCP/6668 on the relay.
3. **Use a hardware key for MeshCore.** If your MeshCore client supports
   external key storage, use it.
4. **Set `flex_host`** so `!flex status` includes the SmartSDR probe.
   It's a useful tripwire — if status says `relay=open` but `flex=up`,
   something else turned the radio on.
5. **Rotate `tuya_local_key`** annually by re-pairing the TYWB.
6. **Review the audit log** when you spot an unexpected state. The log
   contains every command with the requesting `sender_key`.

## Future work

- Store `tuya_local_key` in HashiCorp Vault, fetched at bot startup with a
  short-lived token. Eliminates the on-disk plaintext.
- Optional message signing/nonces inside the command payload for defense in
  depth on top of MeshCore's transport security.
- Hardware deadman: a watchdog timer on a second relay channel that
  force-opens the main relay if it hasn't been kicked in N minutes.
