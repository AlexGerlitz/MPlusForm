# Install addon

## CurseForge

The recommended user install path is the official CurseForge addon package.

The addon package should contain addon files only, not the optional desktop sync runtime.

## GitHub release package

A GitHub release package may also be provided for testing. It should include only:

- `MPlusForm.toc`
- `MPlusForm.lua`
- `Data/Snapshot.lua`
- required addon documentation

## First check

After installation, start World of Warcraft and run:

```text
/mpf status
```

Expected result: the addon prints its version, capture mode, queue status, and snapshot status.
