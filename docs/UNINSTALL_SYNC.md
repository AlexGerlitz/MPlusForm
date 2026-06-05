# Uninstall optional sync

Use this guide to remove the optional desktop sync component.

## Windows

1. Run `windows/uninstall.ps1` from the official sync package when available.
2. Confirm that scheduled tasks named `MPlusForm Sync` and `MPlusForm SSH Tunnel` are removed.
3. Remove local sync files from the MPlusFormSync app data folders if you no longer need logs or state.

## Addon files

Uninstalling sync does not require uninstalling the addon. The addon can remain installed and will continue to use the last available approved snapshot until updated or removed.

## Tooltip

You can disable tooltip output in game:

```text
/mpf tooltip off
```
