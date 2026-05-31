# Windows Scripts

Windows helper scripts for installing and operating the optional MPlusForm sync.

Main entry points:

- `install_all.ps1`: installs the addon and sync.
- `install_sync_task.ps1`: installs silent background sync and the local SSH tunnel task.
- `status.ps1`: prints sync/task status.
- `run_once.ps1`: runs one sync pass.
- `uninstall.ps1`: removes scheduled tasks.

The SSH tunnel task uses a hidden Windows Script Host launcher so users do not get a visible `ssh.exe` console window during normal use.

