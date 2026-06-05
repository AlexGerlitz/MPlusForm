# Open-source project application

## Project summary

MPlusForm is an open-source World of Warcraft addon and optional desktop sync client for verified Mythic+ post-run summaries.

The addon displays only server-approved snapshot data in player tooltips. The project treats local SavedVariables and combat-log files as untrusted until a server-side validation layer approves a run.

Repository: https://github.com/AlexGerlitz/MPlusForm

## Problem

Mythic+ groups often need fast context about a player's recent run history. Local addon data can be edited, copied, or lost, so purely local statistics are not a strong trust signal.

MPlusForm addresses this by separating local evidence collection from public display. The addon can collect normal post-run metadata, the optional sync client can submit run evidence, and the server decides what becomes an approved public snapshot.

## Current status

- Public GitHub repository
- Apache-2.0 source-code license
- CurseForge-approved addon release
- Retail addon package separated from optional desktop sync
- Server-approved snapshot model implemented
- Windows sync prototype implemented
- Privacy, security, install, and trust-model documentation in progress

## Six-month plan

1. Finish open-source packaging, documentation, licensing, and release hygiene.
2. Improve beta onboarding, troubleshooting, screenshots, and installer diagnostics.
3. Harden the server-side validation and rejection-reason workflow.
4. Simplify the public sync setup around a documented HTTPS API mode.
5. Add tests, examples, and contributor-friendly development workflows.
6. Prepare a season-ready public release with clear docs and community feedback.
