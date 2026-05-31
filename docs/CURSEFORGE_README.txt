MPlusForm
=========

MPlusForm adds verified Mythic+ post-run statistics to player tooltips.

The addon displays server-approved performance summaries such as recent verified keys,
average damage per second, interrupts, deaths, and confidence level.

The addon itself does not automate gameplay, does not interact with combat decisions,
does not read memory, does not modify the game client, and does not communicate with
other players in-game.

Public tooltip data comes only from the bundled or downloaded server-approved snapshot
in Data/Snapshot.lua. Local SavedVariables are treated as untrusted draft input.

Optional Sync Companion
-----------------------

MPlusForm can be used with an optional external Windows sync companion. The companion is
distributed separately from this CurseForge addon package.

The sync companion reads Blizzard-generated SavedVariables and combat log text files from
disk after gameplay, submits completed-run evidence to the MPlusForm backend, and downloads
a server-approved snapshot back into the addon Data folder.

This CurseForge package contains only the World of Warcraft addon files.

Commands
--------

/mpf status
/mpf snapshot
/mpf local
/mpf syncnow
/mpf tooltip on
/mpf tooltip off
/mpf wipe

Privacy and Trust
-----------------

MPlusForm is designed around server-approved public data. SavedVariables and local files
are not trusted as public truth. The tooltip only displays profiles that are present in
the approved snapshot.

