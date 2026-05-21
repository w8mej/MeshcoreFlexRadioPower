# Security Policy

## Reporting a vulnerability

If you find a security issue in `MeshcoreFlexRadioPower`, **please do not open a
public GitHub issue**. Instead, contact the maintainer privately:

- Email: `security@haxx.ninja` (PGP key on request)
- Or use [GitHub Private Vulnerability Reporting](https://github.com/w8mej/MeshcoreFlexRadioPower/security/advisories/new)

You can expect:

- An acknowledgement within 72 hours.
- A coordinated disclosure timeline negotiated based on severity. Default is
  90 days from confirmed reproduction.
- Credit in the [CHANGELOG](CHANGELOG.md) and a CVE if appropriate.

## Scope

In scope:

- `flex_radio_bot.py` — anything that lets an unauthorized mesh peer cause
  the bot to actuate the relay, leak the `tuya_local_key`, or escape the
  10-second timeout in a way that destabilizes Remote-Terminal-for-MeshCore.
- `flex_setup.py` — credential handling, file permissions on the generated
  config, anything that exposes `tuya_local_key` to other local users.
- Supply chain — pinning, integrity verification of dependencies.

Out of scope:

- Vulnerabilities in `tinytuya`, Remote-Terminal-for-MeshCore, or MeshCore
  itself — please report those to the respective upstream projects.
- Physical access to the relay or the Pi.
- Social-engineering an operator into adding a malicious public key to the
  allowlist. Operate your allowlist hygienically.
- Lost or compromised MeshCore identity keys — that's an operator concern.

## Threat model

See [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) for the detailed threat
model, including adversary capabilities, trust boundaries, and the rationale
behind each control.

## Supported versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |

Only the latest minor version receives security fixes. Pre-1.0, this project
may issue breaking changes in any minor release.
