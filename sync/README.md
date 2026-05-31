# MPlusForm Sync

Optional desktop sync component for MPlusForm.

The sync service reads MPlusForm SavedVariables and the WoW combat log from disk, submits run evidence to the configured MPlusForm API, and downloads the server-approved snapshot back into the addon `Data` folder.

No user token is required in the public Windows test flow. Production trust is enforced server-side.

The portable Python runtime and packaged Windows release zip are not committed to this repository. They are distributed separately as release artifacts.

