MPlusForm = MPlusForm or {}

local MAX_RUNS = 50
local MAX_PLAYER_RUNS = 20

local function EnsureDB()
    MPlusFormDB = MPlusFormDB or {}
    MPlusFormDB.version = MPlusForm.version or "unknown"
    MPlusFormDB.runs = MPlusFormDB.runs or {}
    MPlusFormDB.players = MPlusFormDB.players or {}
    return MPlusFormDB
end

function MPlusForm.SaveRun(run)
    local db = EnsureDB()

    table.insert(db.runs, 1, run)

    while #db.runs > MAX_RUNS do
        table.remove(db.runs)
    end
end

function MPlusForm.SavePlayerRun(playerKey, playerRun)
    if not playerKey or playerKey == "" then
        return
    end

    local db = EnsureDB()
    db.players[playerKey] = db.players[playerKey] or {}

    table.insert(db.players[playerKey], 1, playerRun)

    while #db.players[playerKey] > MAX_PLAYER_RUNS do
        table.remove(db.players[playerKey])
    end
end

function MPlusForm.GetPlayerRuns(playerKey)
    local db = EnsureDB()
    return db.players[playerKey] or {}
end
