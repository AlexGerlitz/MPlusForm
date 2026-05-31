# MPlusForm

MPlusForm is a World of Warcraft addon and optional desktop sync pipeline for verified Mythic+ post-run player summaries.

The in-game addon displays only server-approved snapshot data in player tooltips. SavedVariables and local combat logs are treated as untrusted input until the server validates and approves a run.

## Current Release

- Version: `1.4.2-rc10.7`
- Game: World of Warcraft Retail `12.0.5`
- CurseForge addon package: addon files only, no executable sync component
- Optional Windows sync: background Task Scheduler sync with local SSH tunnel support

## Repository Layout

- `MPlusForm.lua`, `MPlusForm.toc`, `Data/Snapshot.lua`: current addon package contents.
- `sync/`: optional desktop sync source.
- `windows/`: Windows installer and status scripts.
- `server_patch/`: server-side trust layer/reference integration files.
- `docs/`: CurseForge-facing English text.

## Safety Model

MPlusForm does not automate gameplay, inject into the game client, read game memory, press keys, or interact with protected game APIs. The addon writes normal SavedVariables and renders approved snapshot data in tooltips. The optional sync reads addon/log text files from disk and sends run evidence to the MPlusForm server for validation.

## License

All Rights Reserved. See `LICENSE`.

