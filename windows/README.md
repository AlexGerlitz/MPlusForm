# Windows Scripts

Windows helper scripts for installing and operating the optional MPlusForm sync.

Main entry points:

- `../INSTALL_MPLUSFORM_SYNC.ps1`: recommended sync-only setup after the addon is installed from CurseForge.
- `install_sync_task.ps1`: installs silent background sync and the local SSH tunnel task.
- `status.ps1`: prints sync/task status.
- `run_once.ps1`: runs one sync pass.
- `uninstall.ps1`: removes scheduled tasks.

The SSH tunnel task uses a hidden Windows Script Host launcher so users do not get a visible `ssh.exe` console window during normal use.

`install_addon.ps1` and `install_all.ps1` are legacy helpers for private full packages. Public users should install the addon through CurseForge and then run the sync-only setup.
