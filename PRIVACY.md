# Privacy

MPlusForm has two parts: the addon and the optional desktop sync client.

## Addon

The addon stores local World of Warcraft SavedVariables and displays server-approved snapshot data in tooltips.

## Optional sync

The optional sync client reads the configured MPlusForm SavedVariables file and the configured WoW combat-log text file. It submits run evidence to the configured MPlusForm API and downloads approved snapshot files back into the addon Data folder.

## Data minimization

The project should collect only the data needed for verified Mythic+ run summaries. Client-side files are treated as untrusted until server validation.

## User control

Users can disable the tooltip with `/mpf tooltip off` and remove the optional sync using the uninstall documentation.
