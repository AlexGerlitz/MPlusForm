# Install optional sync

The desktop sync component is optional. Use it only if you want to submit run evidence for server approval and receive updated verified snapshot data.

## Recommended public flow

Public releases should use a documented HTTPS API endpoint.

1. Install the addon from CurseForge or an official release package.
2. Start World of Warcraft once with MPlusForm enabled.
3. Run the sync installer from an official release package.
4. Check sync status with the provided status script.
5. Run `/mpf status` in game after the first approved snapshot update.

## Development flow

Local tunnel mode is for development or private beta testing. It should not be the default public user path.

## What sync reads

- The configured `MPlusForm.lua` SavedVariables file.
- The configured `WoWCombatLog.txt` text file.

## What sync writes

- Local sync logs and state under the user's local app data directory.
- Approved `Snapshot.lua` and `Snapshot.json` files into the addon Data folder.

## Troubleshooting

See `docs/TROUBLESHOOTING.md`.
