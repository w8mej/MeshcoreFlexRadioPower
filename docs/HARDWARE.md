# Hardware

This page covers the physical side of the system: what to buy, how to wire
it, and how the FlexRadio's `REM` jack behaves so you can configure pulse
durations sensibly.

## Bill of materials

| Item                                    | Purpose                            | Approx. cost |
|-----------------------------------------|------------------------------------|--------------|
| MHCOZY TYWB (1ch, 2ch, or 4ch)          | Wi-Fi-controlled dry-contact relay | $12–$20      |
| RCA male → bare-wire pigtail            | Connects relay COM/NO to Flex REM  | $4           |
| 5 V USB power supply                    | Powers the TYWB                    | (have one)   |
| Any LAN-connected host (Pi, Mac, NUC, …) | Hosts Remote-Terminal-for-MeshCore | (have one)   |
| Optional: 12 V DC source                | TYWB also accepts 7–32 V DC        | —            |

The four-channel TYWB is the version FlexRadio documents. Even if you only
need one channel today, the spares are useful for things like a remote
antenna switch, a tuner bypass, or a remote outlet for a coffee maker.

## Wiring

The TYWB exposes each channel as a dry-contact SPDT relay:

```
   ┌─────────────────────────────┐
   │       MHCOZY TYWB           │
   │                             │
   │  Ch1: [ NO ][ COM ][ NC ]   │
   │  Ch2: [ NO ][ COM ][ NC ]   │
   │  Ch3: [ NO ][ COM ][ NC ]   │
   │  Ch4: [ NO ][ COM ][ NC ]   │
   │                             │
   │   USB 5V in  /  Wi-Fi       │
   └─────────────────────────────┘
```

For the Flex REM jack:

```
   MHCOZY Ch1 COM  ───┐
                      ├──── inner conductor of RCA pigtail
   MHCOZY Ch1 NO   ───┘                    │
                                           │
                                           ▼
                              ┌──────────────────────┐
                              │   Flex  REM  jack    │
                              └──────────────────────┘
```

Strip the RCA pigtail's two wires, twist or ferrule them, and screw the
inner-conductor wire to `NO` and the shield/outer wire to `COM` (or vice
versa — it's a dry contact, either order works). Use the `NC` terminal only
if you want an inverse-sense behavior, which you don't.

**Why `NO` (Normally Open) and not `NC`:** at boot, after a power outage, or
if the TYWB ever loses Wi-Fi and resets, the relay defaults to open. Open =
no contact = no button-press to the radio. That's fail-safe — the radio
won't toggle without an explicit command.

## How the Flex REM jack behaves

The `REM` input on the FLEX-8000 series mimics the front-panel power button.
Closing the contact to ground is electrically equivalent to pressing the
button:

| Closure duration | Effect (matches the front-panel button)                |
|------------------|--------------------------------------------------------|
| ~0.1 – 1 s       | Short press — toggles power on, or polite shutdown via SmartSDR if it's running |
| ~4 s and longer  | Long press — forced hard power-off                     |

That's why `flex_radio_bot.py` defaults to **0.5 s** for `!flex on` and
`!flex off`, and **5 s** for `!flex kill`. You can adjust these in the
config:

```json
{
  "short_pulse_seconds": 0.5,
  "long_pulse_seconds": 5.0
}
```

If your radio is sluggish to respond to short presses (older firmware, or a
long power-up cycle delaying SmartSDR registration), bump `short_pulse_seconds`
to 0.75 or 1.0. Don't go above ~3 s on the short pulse or you risk it being
interpreted as a long press on some firmware.

## Network layout

```
   ┌──────────────────┐         ┌──────────────────┐
   │ Host machine     │ Wi-Fi   │  MHCOZY TYWB     │
   │ (Pi, Mac, NUC)   │◀───────▶│  (Tuya 3.4)      │
   │ Remote-Terminal  │  LAN    │                  │
   │ flex_radio_bot   │         └─────────┬────────┘
   └──────────────────┘                   │ dry contact
                                          ▼
                                  ┌──────────────────┐
                                  │ FlexRadio 6XXX   │
                                  │  REM jack        │
                                  └──────────────────┘
```

Both the host and the TYWB must be on the same Layer 2 segment for `tinytuya`
broadcast discovery to work. If you've VLANed your IoT gear off (good
instinct), either:

1. Put the host on the IoT VLAN too, or
2. Give the TYWB a DHCP reservation and put its IP in the config as
   `tuya_address` instead of `"Auto"`. Then make sure the firewall permits
   TCP/6668 from the host to the TYWB.

## Selecting the relay channel

If you bought the 4-channel TYWB and you're only using channel 1, set
`relay_channel: 1` in the config. Channels are 1-indexed in the Tuya `dps`
map and physically labeled K1–K4 on the board.

## Reset procedure

If the TYWB ever forgets its Wi-Fi (router changed, network rebuild, etc):
hold any of the K1–K4 buttons for ~6 s until the indicator LED rapid-blinks,
then re-pair via the Smart Life app. **The `tuya_local_key` will change.**
Re-run:

```bash
python3 -m tinytuya wizard
sudo python3 flex_setup.py --from-wizard
```
