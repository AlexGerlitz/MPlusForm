# MPlusForm MacBook Handoff

Дата: 2026-06-02

Этот репозиторий содержит текущий рабочий набор MPlusForm для продолжения работы с MacBook.

## Что главное

- CurseForge addon уже вынесен отдельно и должен оставаться addon-only.
- Sync вынесен в отдельный Windows companion setup.
- Public users не должны получать SSH-ключи или SSH tunnel credentials.
- Для публичного запуска нужен HTTPS API endpoint. Private tunnel mode оставлен только для контролируемого теста.

## Главные файлы

- `MPlusForm.lua`, `MPlusForm.toc`, `Data/Snapshot.lua` - текущий addon source.
- `sync/mplusform_sync_service.py` - sync service source.
- `windows/install_sync_task.ps1` - sync-only Task Scheduler installer.
- `INSTALL_MPLUSFORM_SYNC.cmd` - простая точка входа для Windows users.
- `docs/SYNC_SETUP_EN.txt` - английский текст для сайта/доков про sync.
- `artifacts/rc10.7/MPlusForm-1.4.2-rc10.7-CurseForge.zip` - final CurseForge addon zip.
- `artifacts/rc10.7/MPlusFormSyncSetup_1.4.2_rc10.7_Windows.zip` - sync-only Windows setup zip для сайта.
- `artifacts/rc10.7/MPlusForm_FINAL_INSTALL_1.4.2_rc10.7_Windows_plus_VPS_patch.zip` - full private/test package.
- `artifacts/SHA256SUMS.txt` - hashes for release artifacts.

## Что давать пользователям

Для обычного пользователя:

1. Install MPlusForm from CurseForge.
2. Download `MPlusFormSyncSetup_1.4.2_rc10.7_Windows.zip` from the official MPlusForm site.
3. Extract it and run `INSTALL_MPLUSFORM_SYNC.cmd`.

Для public launch setup должен запускаться примерно так:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\INSTALL_MPLUSFORM_SYNC.ps1 -NoTunnelTask -ServerUrl https://YOUR_API_HOST
```

Private tunnel mode:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\INSTALL_MPLUSFORM_SYNC.ps1 -ServerUrl http://127.0.0.1:8015 -SshAlias mplus-moscow
```

## Что не коммитить

- SSH private keys.
- `%APPDATA%\MPlusFormSync\config.json`.
- `%LOCALAPPDATA%\MPlusFormSync\state.json`.
- Sync logs.
- Real user SavedVariables.
- Real user combat logs.
- Real downloaded player snapshot data from a local WoW install.

## VPS copy

Artifacts were also uploaded to:

```text
/root/mplusform_artifacts/
```

MacBook download example:

```bash
scp mplus-moscow:/root/mplusform_artifacts/MPlusFormSyncSetup_1.4.2_rc10.7_Windows.zip .
```

## Current artifact hashes

```text
c4d31597d9a49bca38bcec52afab3388226a7fec15f4dc38a5a059e3673bd8c7  artifacts/legacy/rc10.6_private/MPlusFormSyncSetup_PRIVATE_1.4.2_rc10.6_WithTunnel.exe
110a7b20d84cc1868250d929e9bec366e6c82ee9eb66dc541d66b5e38c7639e2  artifacts/rc10.7/MPlusForm_FINAL_INSTALL_1.4.2_rc10.7_Windows_plus_VPS_patch.zip
ff905fecd17318d22a9747d17b3a1b50b61481aea3cfe18c3da790105ebe167c  artifacts/rc10.7/MPlusForm-1.4.2-rc10.7-CurseForge.zip
0a72aecde891440a080add489f9148b30a6fba7356f3da4eb22e10c099924b44  artifacts/rc10.7/MPlusFormSyncSetup_1.4.2_rc10.7_Windows.zip
```

