MPlusForm = MPlusForm or {}

function MPlusForm.HasDetails()
    return _G.Details ~= nil
end

local function SafeCall(fn, ...)
    if type(fn) ~= "function" then
        return nil
    end

    local ok, result = pcall(fn, ...)
    if not ok then
        return nil
    end

    return result
end

function MPlusForm.DebugDetails()
    if not MPlusForm.HasDetails() then
        MPlusForm.Print("Details is not available.")
        return
    end

    MPlusForm.Print("Details object exists.")

    if type(_G.Details.GetCombatSegments) == "function" then
        local segments = SafeCall(_G.Details.GetCombatSegments, _G.Details)
        if type(segments) == "table" then
            MPlusForm.Print("Details segments found: " .. tostring(#segments))
        else
            MPlusForm.Print("Details segments are not readable yet.")
        end
    else
        MPlusForm.Print("Details:GetCombatSegments() is not available in this version.")
    end
end
