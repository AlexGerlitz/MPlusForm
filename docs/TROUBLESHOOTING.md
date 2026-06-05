# Troubleshooting

## `/mpf status` shows no snapshot profiles

This is normal on a fresh install. The placeholder snapshot contains zero profiles until an approved snapshot is downloaded.

## Sync cannot find World of Warcraft

Pass the WoW installation path to the installer or check that the addon is already installed under `_retail_/Interface/AddOns/MPlusForm`.

## Sync cannot find SavedVariables

Start World of Warcraft once with MPlusForm enabled, then log out or reload UI so the SavedVariables file is written.

## Combat log is missing

Make sure combat logging is enabled during a Mythic+ run. The sync client expects a configured `WoWCombatLog.txt` path.

## Snapshot download failed

Check the configured server URL, local network access, and sync logs. The addon can still run with the last available snapshot.

## Tooltip can be disabled

Use:

```text
/mpf tooltip off
```

To enable it again:

```text
/mpf tooltip on
```
