# Troubleshooting

A symptom → cause → fix matrix for common failure modes. If you hit
something not listed here, please open an issue with the audit-log lines and
your `tinytuya` version.

## Bot-level

### `[FLEX] config missing or unreadable`

The bot can't open its config file. Default locations:

- macOS: `~/.config/flexradio/flex_radio_bot.json`
- Linux: `/etc/meshcore/flex_radio_bot.json`

Override either path with the `FLEX_BOT_CONFIG` env var.

- Wrong path? Set `FLEX_BOT_CONFIG` in the environment of the process running
  Remote-Terminal-for-MeshCore.
- Wrong permissions? Bot's user must be able to read mode-0600 file. If
  Remote-Terminal runs as a non-root user, either `chown` the config to that
  user or relax to mode 0640 with a matching group.
- Bad JSON? Validate with:
  ```bash
  # macOS
  python3 -m json.tool ~/.config/flexradio/flex_radio_bot.json
  # Linux
  python3 -m json.tool /etc/meshcore/flex_radio_bot.json
  ```

### `[FLEX] unauthorized`

Sender's 64-hex public key is not in `allowed_sender_keys`.

- For DMs, look at the bot's audit log (path depends on platform — see
  "Reading the audit log" in OPERATIONS.md):
  ```bash
  # macOS
  grep UNAUTHORIZED ~/Library/Logs/flex_radio_bot.log
  # Linux
  grep UNAUTHORIZED /var/log/flex_radio_bot.log
  ```
  The exact `key=...` value is logged. Add it to the config.
- For channel messages, this is expected — `sender_key` is always `None` in
  channels, so the allowlist can never match. Use a DM.

### `[FLEX] cooldown, try again in a few seconds`

Working as intended. Default cooldown is 3 s per sender. Adjust
`cooldown_seconds` in config if you really need it tighter.

### `[FLEX] control commands are DM-only`

You sent `!flex on` (or similar mutating command) in a channel.

- Send as a DM instead, **or**
- Set `allow_channel_control: true` in the config. **Not recommended** —
  channel messages are unauthenticated.

### `[FLEX] internal error`

Something blew up inside `_handle()` that wasn't a relay error.

- Check the audit log for the traceback (`~/Library/Logs/flex_radio_bot.log`
  on macOS, `/var/log/flex_radio_bot.log` on Linux).
- Open an issue with the traceback and what command you sent.

### Bot doesn't reply at all

- Bot disabled in Remote-Terminal-for-MeshCore? Check the UI.
- Hit the 10-second timeout? Check the host's logs. If yes, either Tuya is
  unreachable (LAN issue) or you have an unusually long pulse configured.
- Bot crashed and was disabled? Restart Remote-Terminal-for-MeshCore.

## Tuya / relay-level

### `[FLEX] relay error`

`tinytuya.set_status()` returned an `Error` key or threw.

Likely causes, in order of frequency:

1. **Wrong `tuya_local_key`** — typo, or the relay was re-paired since you
   last ran the wizard. Re-run `python3 -m tinytuya wizard` and update
   the config.
2. **Wrong `tuya_version`** — try `3.3`, `3.4`, or `3.5`. The MHCOZY TYWB
   shipped with both 3.3 and 3.4 firmwares depending on date of manufacture.
3. **TYWB is not on the LAN** — power, Wi-Fi association, or routing. Check
   the LED on the device: solid = connected, blinking = trying.
4. **Firewall blocking TCP/6668** — see `docs/HARDWARE.md` for the network
   layout.
5. **`tuya_address` is wrong** — try `"Auto"` to use broadcast discovery, or
   set a DHCP reservation for the TYWB and put its static IP in the config.

### `status: relay=?`

`_relay_get()` returned `None`. Same root causes as `relay error` above. Run
`sudo python3 flex_setup.py --device-id ... --local-key ... --test-only` to
diagnose interactively.

### Status says `relay=open` but the radio is on

Either:

- Someone (or something) used the front-panel button or another control
  path. This is the case where setting `flex_host` is helpful — the SmartSDR
  probe will also report `flex=up` and you'll know the radio is actually on.
- The Tuya `dps` channel mapping is non-standard. Run `flex_setup.py
  --test-only` and look at the raw `status:` printout. The relay state for
  channel N should be at `dps[str(N)]`. If your device uses different
  indices, file an issue with the output.

### Status says `relay=closed` but the radio is off

- Possibly a stuck or welded relay. With a multimeter on continuity mode,
  verify the relay actually opens. If it's welded, replace the TYWB.
- Or the RCA pigtail is broken. Buzz from `NO`/`COM` screws through to the
  RCA tip and shield.

## Hardware

### The radio doesn't react to `!flex on`

Walk through:

1. Does the relay click audibly when you send the command? If yes → hardware
   wiring problem. If no → Tuya problem (see above).
2. Is the RCA pigtail seated all the way? The Flex `REM` jack is well-
   labeled but tight on first install.
3. Is the front-panel power button working from the radio itself? If the
   button does nothing either, the radio has a power issue unrelated to this
   bot.
4. Try a longer short-pulse: bump `short_pulse_seconds` to 0.75 or 1.0.

### Short-press triggers a hard-off instead of a toggle

`short_pulse_seconds` is too long. Some Flex firmware draws the line at ~2 s.
Drop to 0.3 – 0.5 s.

### Long-press (`!flex kill`) doesn't force off

`long_pulse_seconds` is too short. Bump to 6.0 s. Don't exceed 8.5 s
or you'll race the bot's 10-second timeout.

## Setup script

### `flex_setup.py` can't find the device

- Host on a different subnet from the TYWB? `tinytuya.deviceScan()` is a UDP
  broadcast and won't cross subnets. Use `--address <IP>` instead.
- Host's firewall blocking UDP/6666 or UDP/6667? Open them.
- Smart Life app still has an exclusive cloud session? Force-close the app
  on your phone.

### `flex_setup.py` fails with "device_id ... not in devices.json"

Either you've never run `python3 -m tinytuya wizard`, or your `devices.json`
predates pairing this TYWB. Re-run the wizard, which produces a fresh
`devices.json`.

## macOS-specific

### macOS Application Firewall dialog blocks discovery

When `tinytuya` first sends UDP broadcast packets, macOS may pop up a dialog
asking whether to allow incoming connections for Python. Click **Allow**. If
you dismissed it as "Deny":

1. Open **System Settings → Network → Firewall → Options…**
2. Find `python3` (or the full path to your venv's Python).
3. Set it to **Allow incoming connections**.

### UDP broadcast not reaching the TYWB

`tinytuya`'s `deviceScan()` uses UDP broadcast on ports 6666/6667. These are
unblocked by default on macOS unless Little Snitch or another firewall is
running. Verify with:

```bash
sudo tcpdump -i en0 udp port 6666 &
python3 -c "import tinytuya; print(tinytuya.deviceScan(False, 5))"
```

If the TYWB is on a separate VLAN, `deviceScan` won't reach it. Set a static
IP on the device and use `--address <IP>` with `flex_setup.py` instead of
relying on broadcast auto-discovery.

### TCP/6668 connection refused

The `tinytuya` control channel uses TCP/6668. If the connection times out:

```bash
nc -zv <TYWB_IP> 6668
```

Check that macOS's firewall (and any third-party firewall) allows outbound
TCP to the TYWB's IP on port 6668.

### Config file location on macOS

The bot writes its config to `~/.config/flexradio/flex_radio_bot.json` on
macOS (not `/etc/meshcore/…` as the Linux docs state). Validate the file:

```bash
python3 -m json.tool ~/.config/flexradio/flex_radio_bot.json
```

### SIP (System Integrity Protection)

SIP does not affect this application — all writes go to user-owned
`~/.config` and `~/Library/Logs`. No workarounds are needed.
