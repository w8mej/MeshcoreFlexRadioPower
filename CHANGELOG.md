# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned

- Optional Vault-backed retrieval of `tuya_local_key` (no plaintext on disk).
- Second-channel RF sense input to confirm radio actually came up.
- TX interlock — refuse `!flex off`/`!flex kill` while SmartSDR reports active
  transmission.
- Optional MQTT bridge for status fan-out to a station dashboard.

## [0.1.0] - 2026-05-20

### Added

- Initial public release.
- `flex_radio_bot.py` — Remote-Terminal-for-MeshCore bot with command
  dispatch, sender-key allowlist, per-sender cooldown, audit logging, and
  hot-reloading JSON config.
- `flex_setup.py` — interactive CLI for LAN scan, Tuya credential validation,
  relay exercise, and config generation.
- `examples/flex_config.example.json` — annotated config schema.
- Documentation: hardware wiring guide, threat model, operations guide,
  troubleshooting matrix.
- Unit tests covering dispatch, authorization, cooldown, and config-loader
  edge cases.
- GitHub Actions CI: lint + test on Python 3.9 through 3.12.
- Dependabot config for `pip` and `github-actions` ecosystems.

[Unreleased]: https://github.com/w8mej/MeshcoreFlexRadioPower/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/w8mej/MeshcoreFlexRadioPower/releases/tag/v0.1.0
