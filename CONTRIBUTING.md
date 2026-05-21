# Contributing to MeshcoreFlexRadioPower

Thanks for your interest in improving this project. The bar for contributions
is "make it more useful to a ham operator without making it less safe."

## Ground rules

- **Security and correctness first, features second.** This project actuates
  AC mains and antenna systems. A bug here can mean a radio that won't come
  up before a contest, or worse, one that won't go down.
- **Keep the bot's surface small.** It runs inside another process with a
  10-second budget per message. Resist the urge to add background threads,
  long-running HTTP clients, or anything that wants to outlive a single
  `bot()` call.
- **Don't add cloud dependencies.** Local LAN control of the TYWB is a
  feature, not an accident. Cloud features go in a separate module behind an
  opt-in config flag.

## Setting up a dev environment

```bash
git clone git@github.com:w8mej/MeshcoreFlexRadioPower.git
cd MeshcoreFlexRadioPower
python3 -m venv .venv
source .venv/bin/activate
make dev
make test
make lint
```

You do not need a TYWB to run the test suite. Dispatch and config tests stub
out the relay layer.

## Submitting changes

1. Open an issue first for anything bigger than a typo fix. It avoids you
   doing work that won't be merged.
2. Branch from `main`. Keep commits focused and the history linear.
3. Write or update tests under `tests/` for any logic change.
4. Run `make lint test` locally before pushing.
5. Open a PR. CI must be green. Describe what changed and why.

## Style

- Ruff handles both lint and formatting; `make format` will fix most things.
- Type hints encouraged but not required everywhere. The hot path
  (`bot()` → dispatch) should be typed.
- Docstrings on public functions and on anything subtle. The reader is a ham
  operator at 0300 local — be kind.

## What's a good first PR?

- A new entry in the troubleshooting matrix from your own setup.
- Translations of operator-facing strings (`[FLEX] ...`).
- A vendor-id mapping for a non-MHCOZY Tuya relay you've tested.
- Better wiring photos for `docs/HARDWARE.md`.
