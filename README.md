# MPlusForm

[![Public Verification](https://github.com/AlexGerlitz/MPlusForm/actions/workflows/public-verification.yml/badge.svg?branch=main)](https://github.com/AlexGerlitz/MPlusForm/actions/workflows/public-verification.yml)

MPlusForm is a validation-boundary and desktop-automation proof project: untrusted local files,
an optional Python sync pipeline, server-side approval, generated public snapshots, Windows
operations scripts, and clear trust-model documentation.

The current domain package is a Lua addon plus optional Python sync pipeline for verified
post-run summaries. The engineering signal is the trust boundary, not the domain-specific UI.

The addon displays only server-approved snapshot data in player tooltips. Local SavedVariables and combat-log files are treated as untrusted input until the server validates and approves a run.

Profile / contact route: [DriveDesk AI Operator proof route](https://alexgerlitz.github.io/AlexGerlitz/drivedesk-proof-route.html),
[LinkedIn message route](https://www.linkedin.com/in/alex-gerlitz-a659ab3bb/),
[PDF resume](https://alexgerlitz.github.io/AlexGerlitz/output/pdf/alex-gerlitz-remote-ai-automation-resume.pdf),
[portfolio](https://alexgerlitz.github.io/AlexGerlitz/),
[enterprise readiness](https://alexgerlitz.github.io/AlexGerlitz/enterprise-readiness.html), and
[inbound brief](https://alexgerlitz.github.io/AlexGerlitz/intake-brief.html).

## 60-Second Reviewer Snapshot

This repository is public proof for trust-model, validation-boundary, desktop automation, and
operational documentation work.

The domain-specific UI is not the main engineering signal. The useful signal is the shape of the
system: untrusted local files, optional client sync, server-side validation, approved public
snapshots, Windows install/operate scripts, and clear user-facing docs.

| What to check | Why it matters |
| --- | --- |
| [Trust model](docs/TRUST_MODEL.md) | Shows how untrusted local evidence is separated from approved public snapshots. |
| [Sync client](sync/mplusform_sync_service.py) | Shows the Python boundary for local file reading, API submission, and snapshot download. |
| [Windows operations](windows/README.md) | Shows install/status/sync/uninstall workflows for a non-developer environment. |
| [Server trust layer](server_patch/mplusform_trust_layer.py) | Shows the reference validation boundary on the server side. |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Shows operational handoff and failure-mode documentation. |
| [Public verification gate](scripts/verify_public.sh) | Checks the public package contract, Python syntax, Lua syntax when available, and required proof docs. |

Best-fit evidence:

- validation ownership: untrusted client files stay separate from server-approved data;
- automation ownership: optional Python sync plus Windows Task Scheduler scripts;
- packaging discipline: addon package and optional sync component are documented separately;
- documentation ownership: install, uninstall, trust model, privacy, and troubleshooting docs.

## Current release

- Version: `1.4.2-rc10.7`
- Game: World of Warcraft Retail `12.0.5`
- CurseForge addon package: addon files only, no executable sync component
- Optional Windows sync: background Task Scheduler sync with local tunnel/development support
- License: Apache-2.0 for source code, with project branding reserved separately

## Why MPlusForm exists

Mythic+ groups often need quick context about a player's recent performance, but local addon data can be edited. MPlusForm uses a conservative trust model:

1. The addon records normal post-run metadata and renders approved public snapshots.
2. The optional sync client reads normal addon SavedVariables and WoW combat-log text files from disk.
3. The server validates submitted evidence.
4. Only server-approved snapshot profiles are shown in-game.

MPlusForm is not a replacement for Raider.IO, Details, Warcraft Logs, or Blizzard's own systems. It is a small, transparent, open-source layer for verified post-run summaries in tooltips.

## Safety model

MPlusForm does **not**:

- automate gameplay;
- press keys or move the mouse;
- use input hooks;
- read World of Warcraft process memory;
- inject into the game client;
- modify the game client;
- interact with protected gameplay APIs;
- include an executable sync component in the CurseForge addon package.

The optional sync client only reads documented local text files used by the addon pipeline, submits run evidence to the configured MPlusForm API, and downloads server-approved public snapshot files back into the addon `Data` folder.

## Repository layout

- `MPlusForm.lua`, `MPlusForm.toc`, `Data/Snapshot.lua` - addon package contents.
- `sync/` - optional desktop sync client source.
- `windows/` - Windows helper scripts for installing and operating sync.
- `server_patch/` - reference server-side trust-layer integration files.
- `docs/` - install, trust-model, privacy, troubleshooting, and release documentation.
- `OPENAI_OSS_APPLICATION.md` - prepared open-source project application text.

## Installing the addon

Install MPlusForm from the official CurseForge project page or from a GitHub release package that contains only addon files.

After installing, load into World of Warcraft and run:

```text
/mpf status
```

The addon should report its version, capture mode, queue status, and snapshot status.

## Optional sync

The desktop sync component is optional. It is used when a player wants to submit post-run evidence for server approval and receive updated verified snapshot data.

Read:

- `docs/INSTALL_SYNC.md`
- `docs/TRUST_MODEL.md`
- `docs/UNINSTALL_SYNC.md`
- `docs/TROUBLESHOOTING.md`

Public releases should use a documented HTTPS API endpoint. Local SSH tunnel support is a development/private-beta convenience and should not be presented as the normal public installation path.

## Development

This project currently includes Lua addon code, Python sync-client code, PowerShell Windows helper scripts, and reference server integration files.

General development rules:

- Do not commit secrets, private keys, `.env`, local config, logs, runtime zips, or generated executables.
- Keep the CurseForge addon package free of executable sync files.
- Keep public wording focused on transparent run verification, not anti-cheat claims.
- Treat all client-side files as untrusted until server validation.
- Prefer small, reviewable pull requests.

## Contributing

Contributions are welcome. Start with `CONTRIBUTING.md`, `SECURITY.md`, `PRIVACY.md`, and `docs/TRUST_MODEL.md`.

Good first contribution areas:

- documentation improvements;
- installer diagnostics;
- sync troubleshooting;
- tests for combat-log parsing;
- safer error messages;
- release checklist improvements.

## Branding and trademarks

The source code is licensed under Apache-2.0. The MPlusForm name, logo, and branding are not licensed for confusing or misleading reuse. See `TRADEMARKS.md`.

## License

Copyright 2026 Alex Gerlitz.

Licensed under the Apache License, Version 2.0. See `LICENSE` and `NOTICE`.
