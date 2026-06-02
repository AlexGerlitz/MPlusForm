MPlusForm Sync Companion Setup PRIVATE 1.4.2-rc10.6

Это отдельный Windows .exe установщик для текущего приватного теста.
Он НЕ предназначен для загрузки на CurseForge.

Что делает двойной клик:
1. Распаковывает встроенный пакет во временную папку Windows.
2. Ставит addon MPlusForm в найденный World of Warcraft retail AddOns.
3. Ставит MPlusForm Sync в %LOCALAPPDATA%\MPlusFormSync.
4. Создаёт config в %APPDATA%\MPlusFormSync\config.json.
5. Создаёт silent background task: MPlusForm Sync.
6. Создаёт SSH tunnel task: MPlusForm SSH Tunnel с alias mplus-moscow.
7. Запускает проверку CHECK_WINDOWS.ps1.

Ожидаемый WoW path сначала пробуется:
G:\World of Warcraft
Потом стандартные Program Files пути.

Важно:
- EXE unsigned, поэтому Windows SmartScreen может предупреждать.
- Для production нужно собирать и подписывать Companion installer отдельно через GitHub Releases/сайт.
- CurseForge zip должен оставаться чистым addon zip без EXE/Python/Sync.

После установки в игре:
/reload
/mpf status

После ключа:
/mpf syncnow

Логи:
%LOCALAPPDATA%\MPlusFormSync\logs\installer.log
%LOCALAPPDATA%\MPlusFormSync\logs\sync.log
