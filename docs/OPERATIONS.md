# Operations

Day-to-day running of the bot in production. Read this before you leave the
station unattended for a contest weekend.

## Files and where they live

| Path (Linux)                          | Path (macOS)                                    | Purpose                                             | Mode |
|---------------------------------------|-------------------------------------------------|-----------------------------------------------------|------|
| `/etc/meshcore/flex_radio_bot.json`   | `~/.config/flexradio/flex_radio_bot.json`       | Bot config (contains local key or Vault parameters) | 0600 |
| `/var/log/flex_radio_bot.log`         | `~/Library/Logs/flex_radio_bot.log`             | Audit log + rotation                                | 0640 |
| (within Remote-Terminal-for-MeshCore) | same                                            | Bot source, pasted into the UI                      | —    |

Both paths are auto-selected by the bot based on `platform.system()`. Override
either with the `FLEX_BOT_CONFIG` environment variable (config) or the
`log_path` config key (log).

The bot does not have its own service unit — it runs inside Remote-Terminal-
for-MeshCore's process. If that crashes, the bot is gone.

## Service management

### Linux (systemd)

Make sure Remote-Terminal-for-MeshCore has a unit with `Restart=on-failure`:

```ini
# /etc/systemd/system/remote-terminal.service  (example)
[Unit]
Description=Remote Terminal for MeshCore
After=network.target

[Service]
ExecStart=/usr/local/bin/remote-terminal
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now remote-terminal
```

### macOS (launchd)

Create a LaunchAgent plist so the process restarts on failure and survives
login. Replace `YOUR_USER` with your actual username (`whoami`).

```xml
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
```

```bash
# Load (enable + start):
launchctl load ~/Library/LaunchAgents/com.meshcore.remote-terminal.plist

# Stop / start without unloading:
launchctl stop  com.meshcore.remote-terminal
launchctl start com.meshcore.remote-terminal

# Disable permanently:
launchctl unload ~/Library/LaunchAgents/com.meshcore.remote-terminal.plist
```

## Adding or removing an operator

The config file hot-reloads on mtime change. To add an operator:

```bash
# macOS
$EDITOR ~/.config/flexradio/flex_radio_bot.json
# Linux
sudo $EDITOR /etc/meshcore/flex_radio_bot.json
# add the 64-hex pubkey to allowed_sender_keys, save
```

The bot picks up the change on the next message. Test with `!flex help`
from the new identity (no auth needed, but confirms reachability), then
`!flex status` (also no auth), then a mutating command.

To remove an operator: delete their key from the list, save. Same hot-reload
behavior. The next command from that identity will get `[FLEX] unauthorized`.

## Reading the audit log

The log path is platform-selected (or overridden by `log_path` in config):

- macOS: `~/Library/Logs/flex_radio_bot.log`
- Linux: `/var/log/flex_radio_bot.log`

It rotates at 1 MB with 3 backups. Format:

```
2026-05-20 14:32:11,234 INFO ON pulse by w8mej ok=True
2026-05-20 14:35:47,891 INFO status by w8mej: relay=closed flex=up
2026-05-20 19:01:03,442 WARNING UNAUTHORIZED unknown key=deadbeef... cmd=on
2026-05-20 19:01:03,558 WARNING UNAUTHORIZED unknown key=deadbeef... cmd=kill
```

Things to look for:

- **Repeated UNAUTHORIZED** from the same key. Could be a peer with an
  outdated copy of an old allowlist. Could be probing — note the key.
- **A successful command you didn't send.** Investigate immediately. Either
  another authorized operator did something (ask them), or your allowlist is
  stale and contains a key whose private side has been compromised.
- **`relay error` in clusters.** Either Wi-Fi is flaky to the TYWB or the
  Tuya key rotated unexpectedly (re-pair attempt?).
- **Vault connectivity errors.** If Vault is enabled, the log will capture failures to retrieve the secret from the server (e.g. invalid token, server unreachable, or incorrect secret path/key).

## Routine maintenance

### Quarterly

- Run `sudo python3 flex_setup.py --scan-only` to confirm the TYWB still
  responds and to catch firmware version drift.
- Skim the audit log for unexplained entries.
- Check disk space; the log directory should never balloon, but verify.

### Annually

- Rotate `tuya_local_key` by re-pairing the TYWB. Update the config or your Vault secret store.
- If using Vault, rotate the Vault API token or update the file specified in `vault_token_path` according to your organization's security policy.
- Review the allowlist. Remove any operators whose key you no longer
  recognize or who have left the group.

### After any change to the Wi-Fi network

- The TYWB may have re-associated cleanly, or it may need re-pairing.
- The TYWB's IP may have changed; if you used a static IP in `tuya_address`,
  either re-discover with `"Auto"` or update.

## Backup and recovery

The only thing you can't easily reconstruct is the `tuya_local_key` (or your Vault storage backup).
Everything else (config schema, source) is in this repository.

Recommended backup:

```bash
# Linux — encrypt the config to your YubiKey-backed PGP key
cat /etc/meshcore/flex_radio_bot.json | \
    gpg --encrypt --recipient YOUR_KEY_ID > flex_radio_bot.json.gpg

# macOS
cat ~/.config/flexradio/flex_radio_bot.json | \
    gpg --encrypt --recipient YOUR_KEY_ID > flex_radio_bot.json.gpg
```

If you are using HashiCorp Vault, verify your Vault server's snapshot/backup strategies so the secret key can be restored if the Vault instance experiences hardware failures.

If you lose the local key entirely: re-pair the TYWB, run the wizard,
re-run `flex_setup.py --from-wizard` (or populate it to your new Vault instance). Five minutes of downtime if your Smart Life account is intact.

## Upgrading

```bash
cd ~/MeshcoreFlexRadioPower
git pull
# Diff flex_radio_bot.py against the version pasted into Remote-Terminal-
# for-MeshCore; copy/paste the new contents over the old.
# Bot will reload its config + module on next message.
```

Pre-1.0, breaking config-schema changes will be documented in
[`CHANGELOG.md`](../CHANGELOG.md). Read it before upgrading.

## Emergency stop

If you ever need to make absolutely sure the bot cannot actuate the relay:

1. **Disable the bot** in Remote-Terminal-for-MeshCore's UI (one click).
2. **Or unplug the TYWB.** No power, no control, no key-down.
3. **Or remove the RCA pigtail** from the Flex. The radio reverts to
   front-panel-only operation.

Option 3 is the one you want for a long contest weekend when you'll be at
the radio anyway: zero attack surface, zero compromise on functionality.

## Identifying when transmitting

This bot doesn't touch PTT or the audio path; it just controls AC mains via
the Flex's own clean-shutdown logic. FCC identification (47 CFR §97.119) is
your responsibility as licensee whenever the station transmits. Don't extend
this bot to key the radio without first thinking through automated ID.
