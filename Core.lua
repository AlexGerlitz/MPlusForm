MPlusForm = MPlusForm or {}
MPlusForm.name = "MPlusForm"
MPlusForm.version = "0.1.0"

local frame = CreateFrame("Frame")

frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")

local function Print(message)
    DEFAULT_CHAT_FRAME:AddMessage("|cff00ff99MPlusForm|r: " .. tostring(message))
end

MPlusForm.Print = Print

local function CheckDetails()
    if _G.Details then
        Print("Details found. Data bridge ready.")
        return true
    end

    Print("Details not found. Install/enable Details to record Mythic+ performance.")
    return false
end

SLASH_MPLUSFORM1 = "/mpf"
SLASH_MPLUSFORM2 = "/mplusform"

SlashCmdList["MPLUSFORM"] = function(msg)
    msg = msg and msg:lower() or ""

    if msg == "status" or msg == "" then
        Print("Version: " .. MPlusForm.version)

        if MPlusFormDB then
            local runs = MPlusFormDB.runs and #MPlusFormDB.runs or 0
            Print("Saved runs: " .. runs)
        else
            Print("Database not initialized yet.")
        end

        CheckDetails()
        return
    end

    if msg == "details" then
        if MPlusForm.DebugDetails then
            MPlusForm.DebugDetails()
        else
            Print("Details bridge is not loaded.")
        end
        return
    end

    if msg == "reset" then
        MPlusFormDB = {
            version = MPlusForm.version,
            runs = {},
            players = {},
        }
        Print("Database reset.")
        return
    end

    Print("Commands: /mpf status, /mpf details, /mpf reset")
end

frame:SetScript("OnEvent", function(_, event, addonName)
    if event == "ADDON_LOADED" and addonName == "MPlusForm" then
        MPlusFormDB = MPlusFormDB or {}
        MPlusFormDB.version = MPlusForm.version
        MPlusFormDB.runs = MPlusFormDB.runs or {}
        MPlusFormDB.players = MPlusFormDB.players or {}
        Print("Loaded.")
    end

    if event == "PLAYER_LOGIN" then
        CheckDetails()
    end
end)
