# Trust model

MPlusForm separates local evidence from public display.

## Principle

Client-side files are useful evidence, but they are not authoritative by default. SavedVariables and combat-log files can be edited, copied, deleted, or uploaded late, so the server must validate submitted runs before they appear in public snapshots.

## Data flow

1. The addon records local post-run metadata.
2. The optional sync client reads configured local text files.
3. The sync client submits run evidence to the configured API.
4. The server validates the evidence.
5. The server publishes approved snapshot files.
6. The addon displays only approved snapshot profiles in tooltips.

## Public tooltip rule

The addon should display only profiles marked as server approved. Rejected, incomplete, or untrusted data must not be shown as verified public truth.

## Sync role

The sync client is a transport and parsing helper. It is not a trust authority. The server remains responsible for validation, deduplication, rejection reasons, and approved snapshot generation.

## Safety boundaries

The project should not add gameplay automation, game memory reading, game-client modification, input hooks, or protected gameplay API automation.
