local addonName = ...
local VERSION = "1.4.2-rc10.7-retail12-verified-tooltip-safe"
local RETAIL12_MIN_TOC = 120000
local CAPTURE_MODE_RETAIL12 = "retail12-logfile-sync-required"
local CAPTURE_MODE_NATIVE_LEGACY = "native-combat-log-legacy"

local function ensureDB()
  if type(MPlusFormDB) ~= "table" then MPlusFormDB = {} end
  if type(MPlusFormDB.uploadQueue) ~= "table" then MPlusFormDB.uploadQueue = {} end
  if type(MPlusFormDB.localRuns) ~= "table" then MPlusFormDB.localRuns = {} end
  if type(MPlusFormDB.settings) ~= "table" then MPlusFormDB.settings = {} end
  if MPlusFormDB.settings.tooltip == nil then MPlusFormDB.settings.tooltip = true end
  if MPlusFormDB.settings.tooltipDefaultVersion ~= VERSION then
    MPlusFormDB.settings.tooltip = true
    MPlusFormDB.settings.tooltipDefaultVersion = VERSION
  end
  if type(MPlusFormDB.eventCounters) ~= "table" then MPlusFormDB.eventCounters = {} end
  if type(MPlusFormDB.runtime) ~= "table" then MPlusFormDB.runtime = {} end
  return MPlusFormDB
end

ensureDB()

local frame = CreateFrame("Frame")
local activeRun = nil
local rosterByGUID = {}
local petOwnerByGUID = {}
local recentDeaths = {}

local REGION_BY_ID = { [1] = "US", [2] = "KR", [3] = "EU", [4] = "TW", [5] = "CN" }

local function wowTocVersion()
  if GetBuildInfo then
    local _, _, _, toc = GetBuildInfo()
    return tonumber(toc) or 0
  end
  return 0
end

local function retail12CombatLogBlocked()
  return wowTocVersion() >= RETAIL12_MIN_TOC
end

local function currentCaptureMode()
  if retail12CombatLogBlocked() then return CAPTURE_MODE_RETAIL12 end
  return CAPTURE_MODE_NATIVE_LEGACY
end

local function captureModeFlags()
  local blocked = retail12CombatLogBlocked()
  return {
    captureMode = currentCaptureMode(),
    tocVersion = wowTocVersion(),
    nativeCombatLog = not blocked,
    syncCombatLogRequired = blocked,
    detailsRequired = false,
    detailsPresent = _G.Details ~= nil,
    tooltipEnabled = not (MPlusFormDB and MPlusFormDB.settings and MPlusFormDB.settings.tooltip == false),
    publicTruth = "server-approved-snapshot-only",
    combatLogFile = "Logs\\WoWCombatLog.txt",
  }
end

local function tryEnableGameCombatLog()
  local result = {
    at = time(),
    available = LoggingCombat ~= nil,
    requested = false,
    ok = false,
    wasLogging = nil,
    error = nil,
    file = "Logs\\WoWCombatLog.txt",
  }
  if not LoggingCombat then
    result.error = "LoggingCombat API is not available"
    return result
  end
  local okState, state = pcall(LoggingCombat)
  if okState then result.wasLogging = state and true or false end
  if result.wasLogging then
    result.ok = true
    return result
  end
  result.requested = true
  local okStart, err = pcall(LoggingCombat, true)
  result.ok = okStart and true or false
  if not okStart then result.error = tostring(err) end
  return result
end

local function msg(text)
  if DEFAULT_CHAT_FRAME and DEFAULT_CHAT_FRAME.AddMessage then
    DEFAULT_CHAT_FRAME:AddMessage("|cff58d6ffMPlusForm|r " .. tostring(text))
  end
end

local function trimRealm(realm)
  realm = realm or GetRealmName() or "Unknown"
  return (realm:gsub("%s+", ""))
end

local function bumpCounter(name, amount)
  local db = ensureDB()
  db.eventCounters[name] = (tonumber(db.eventCounters[name]) or 0) + (amount or 1)
end

local function currentRegion()
  if GetCurrentRegionName then
    local name = GetCurrentRegionName()
    if name and name ~= "" then return name end
  end
  if GetCurrentRegion then return REGION_BY_ID[GetCurrentRegion()] or "EU" end
  return "EU"
end

local function unitNameRealm(unit)
  local name, realm = UnitFullName(unit)
  if not name then return nil end
  realm = trimRealm(realm)
  return name, realm, name .. "-" .. realm
end

local function playerSpec(unit)
  if unit ~= "player" or not GetSpecialization or not GetSpecializationInfo then return nil end
  local specIndex = GetSpecialization()
  if not specIndex then return nil end
  local _, specName = GetSpecializationInfo(specIndex)
  return specName
end

local function ensureRunPlayer(unit)
  if not activeRun or not UnitExists(unit) then return nil end
  local guid = UnitGUID(unit)
  local name, realm, nameRealm = unitNameRealm(unit)
  if not guid or not name then return nil end
  local _, classFile = UnitClass(unit)
  activeRun.players[guid] = activeRun.players[guid] or {
    name = name,
    realm = realm,
    nameRealm = nameRealm,
    class = classFile,
    spec = playerSpec(unit),
    totalDamage = 0,
    deaths = 0,
    interrupts = 0,
  }
  rosterByGUID[guid] = activeRun.players[guid]
  return activeRun.players[guid]
end

local function mapPet(ownerUnit, petUnit)
  if not activeRun or not UnitExists(ownerUnit) or not UnitExists(petUnit) then return end
  local owner = ensureRunPlayer(ownerUnit)
  local petGUID = UnitGUID(petUnit)
  if owner and petGUID then petOwnerByGUID[petGUID] = owner end
end

local function rebuildRoster()
  if activeRun then activeRun.rosterUpdates = (activeRun.rosterUpdates or 0) + 1 end
  wipe(rosterByGUID)
  wipe(petOwnerByGUID)
  ensureRunPlayer("player")
  mapPet("player", "pet")
  if IsInRaid() then
    for i = 1, 40 do
      ensureRunPlayer("raid" .. i)
      mapPet("raid" .. i, "raidpet" .. i)
    end
  else
    for i = 1, 4 do
      ensureRunPlayer("party" .. i)
      mapPet("party" .. i, "partypet" .. i)
    end
  end
end

local function summarizePlayers()
  local players, totalDamage, deaths, interrupts = {}, 0, 0, 0
  if activeRun and activeRun.players then
    for guid, player in pairs(activeRun.players) do
      local damage = math.floor(player.totalDamage or 0)
      local pDeaths = tonumber(player.deaths or 0) or 0
      local pInterrupts = tonumber(player.interrupts or 0) or 0
      totalDamage = totalDamage + damage
      deaths = deaths + pDeaths
      interrupts = interrupts + pInterrupts
      table.insert(players, {
        guid = guid,
        nameRealm = player.nameRealm,
        class = player.class,
        spec = player.spec,
        totalDamage = damage,
        deaths = pDeaths,
        interrupts = pInterrupts,
      })
    end
  end
  table.sort(players, function(a, b) return (a.totalDamage or 0) > (b.totalDamage or 0) end)
  return players, totalDamage, deaths, interrupts
end

local function updateCaptureDebug(reason)
  local db = ensureDB()
  local players, totalDamage, deaths, interrupts = summarizePlayers()
  local duration = 0
  if activeRun and activeRun.startedMono then duration = math.max(0, GetTime() - activeRun.startedMono) end
  local snapshot = {
    reason = reason,
    at = time(),
    active = activeRun ~= nil,
    version = VERSION,
    captureMode = currentCaptureMode(),
    flags = captureModeFlags(),
    dungeon = activeRun and activeRun.dungeonName or nil,
    dungeonId = activeRun and activeRun.dungeonId or nil,
    keyLevel = activeRun and activeRun.keyLevel or nil,
    startedAt = activeRun and activeRun.startedAt or nil,
    durationSec = duration,
    playersSeen = #players,
    totalDamage = totalDamage,
    deaths = deaths,
    interrupts = interrupts,
    combatEvents = activeRun and activeRun.combatEvents or 0,
    damageEvents = activeRun and activeRun.damageEvents or 0,
    deathEvents = activeRun and activeRun.deathEvents or 0,
    interruptEvents = activeRun and activeRun.interruptEvents or 0,
    ignoredOutsideEvents = activeRun and activeRun.ignoredOutsideEvents or 0,
    unmatchedDamage = activeRun and activeRun.unmatchedDamage or 0,
    rosterUpdates = activeRun and activeRun.rosterUpdates or 0,
    players = players,
  }
  db.lastCapture = snapshot
  if activeRun then db.lastRunCandidate = snapshot end
end

local function challengeInfo()
  local mapId, mapName, keyLevel = 0, "Unknown", 0
  if C_ChallengeMode then
    if C_ChallengeMode.GetActiveChallengeMapID then
      mapId = C_ChallengeMode.GetActiveChallengeMapID() or 0
    end
    if mapId ~= 0 and C_ChallengeMode.GetMapUIInfo then
      local ok, name = pcall(C_ChallengeMode.GetMapUIInfo, mapId)
      if ok and name and name ~= "" then mapName = name end
    end
    if C_ChallengeMode.GetActiveKeystoneInfo then
      local ok, level = pcall(C_ChallengeMode.GetActiveKeystoneInfo)
      if ok and type(level) == "number" then keyLevel = level end
    end
  end
  return mapId, mapName, keyLevel
end

local function currentInstanceId()
  local _, instanceType, _, _, _, _, _, instanceID = GetInstanceInfo()
  return instanceID or 0, instanceType or "none"
end

local function startRun()
  ensureDB()
  bumpCounter("challengeStart")
  local mapId, mapName, keyLevel = challengeInfo()
  local _, realm = unitNameRealm("player")
  local instanceID, instanceType = currentInstanceId()
  local logState = tryEnableGameCombatLog()
  activeRun = {
    startedAt = time(),
    startedMono = GetTime(),
    region = currentRegion(),
    realm = trimRealm(realm),
    dungeonId = mapId,
    dungeonName = mapName,
    keyLevel = keyLevel,
    instanceID = instanceID,
    instanceType = instanceType,
    captureMode = currentCaptureMode(),
    captureFlags = captureModeFlags(),
    combatLogFile = "Logs\\WoWCombatLog.txt",
    gameCombatLog = logState,
    players = {},
    ignoredOutsideEvents = 0,
    unmatchedDamage = 0,
    combatEvents = 0,
    damageEvents = 0,
    deathEvents = 0,
    interruptEvents = 0,
    rosterUpdates = 0,
  }
  wipe(recentDeaths)
  rebuildRoster()
  updateCaptureDebug("challenge_start")
  msg("capture started: " .. mapName .. " +" .. tostring(keyLevel) .. " mode=" .. currentCaptureMode())
  if retail12CombatLogBlocked() then msg("Retail 12 safe mode: Sync watches WoWCombatLog.txt as anti-AltF4 evidence") end
end

local function appendLocalRun(queued)
  table.insert(MPlusFormDB.localRuns, 1, queued)
  while #MPlusFormDB.localRuns > 20 do table.remove(MPlusFormDB.localRuns) end
end


local function detailsMetaSnapshot(label)
  local snap = { label = label, at = time(), detailsPresent = _G.Details ~= nil }
  if not _G.Details then return snap end
  local okLast, last = pcall(function() return _G.Details.LastMythicPlusData end)
  if okLast and type(last) == "table" then
    snap.hasLastMythicPlusData = true
    snap.lastMapId = last.mapId or last.mapID or last.mapChallengeModeID
    snap.lastLevel = last.level or last.keyLevel or last.challengeLevel
    snap.lastElapsed = last.elapsedTime or last.duration or last.time
  end
  local okSegs, segs = pcall(function()
    if _G.Details.GetCombatSegments then return _G.Details:GetCombatSegments() end
    return nil
  end)
  if okSegs and type(segs) == "table" then
    snap.segmentCount = #segs
  end
  return snap
end

local function scheduleDetailsDebug(runId)
  if not C_Timer or not C_Timer.After then return end
  MPlusFormDB.detailsDebug = MPlusFormDB.detailsDebug or {}
  local delays = { 15, 90, 180 }
  for _, delay in ipairs(delays) do
    C_Timer.After(delay, function()
      MPlusFormDB.detailsDebug[runId .. ":" .. tostring(delay)] = detailsMetaSnapshot("after_" .. tostring(delay))
    end)
  end
end

local function queueRun(completed)
  if not activeRun then return end
  ensureDB()
  bumpCounter(completed and "challengeCompleted" or "challengeReset")
  rebuildRoster()
  local completedAt = time()
  local duration = math.max(1, GetTime() - activeRun.startedMono)
  local runId = string.format("%s:%s:%s:%d:%d", activeRun.region, activeRun.realm, activeRun.dungeonId, activeRun.keyLevel, activeRun.startedAt)
  local players = {}
  local totalDamage, totalDeaths, totalInterrupts = 0, 0, 0
  for _, player in pairs(activeRun.players) do
    local damage = math.floor(player.totalDamage or 0)
    local deaths = player.deaths or 0
    local interrupts = player.interrupts or 0
    totalDamage = totalDamage + damage
    totalDeaths = totalDeaths + deaths
    totalInterrupts = totalInterrupts + interrupts
    table.insert(players, {
      nameRealm = player.nameRealm,
      name = player.name,
      realm = player.realm,
      class = player.class,
      spec = player.spec,
      totalDamage = damage,
      deaths = deaths,
      interrupts = interrupts,
    })
  end
  table.sort(players, function(a, b) return (a.totalDamage or 0) > (b.totalDamage or 0) end)
  local localWarnings = {}
  local retail12Mode = retail12CombatLogBlocked()
  if #players ~= 5 then table.insert(localWarnings, "player_count_not_5") end
  if retail12Mode then
    table.insert(localWarnings, "awaiting_sync_combatlog_enrichment")
  else
    if totalDamage <= 0 then table.insert(localWarnings, "zero_total_damage") end
    if activeRun.combatEvents <= 0 then table.insert(localWarnings, "zero_combat_events") end
  end
  local queued = {
    schemaVersion = "mplusform_run_v1",
    addonVersion = VERSION,
    client = {
      addon = "MPlusForm",
      addonVersion = VERSION,
      capture = activeRun.captureMode or currentCaptureMode(),
      detailsRequired = false,
      requiresSyncCombatLogParser = retail12Mode,
    },
    id = runId,
    status = "pending",
    createdAt = completedAt,
    run = {
      runId = runId,
      region = activeRun.region,
      realm = activeRun.realm,
      dungeon = activeRun.dungeonName,
      dungeonId = activeRun.dungeonId,
      keyLevel = activeRun.keyLevel,
      durationSec = duration,
      completed = completed and true or false,
      startedAt = activeRun.startedAt,
      completedAt = completedAt,
      players = players,
      flags = {
        nativeCombatLog = not retail12Mode,
        captureMode = activeRun.captureMode or currentCaptureMode(),
        syncCombatLogRequired = retail12Mode,
        combatLogFile = activeRun.combatLogFile or "Logs\\WoWCombatLog.txt",
        gameCombatLog = activeRun.gameCombatLog,
        detailsRequired = false,
        detailsPresent = _G.Details ~= nil,
        ignoredOutsideEvents = activeRun.ignoredOutsideEvents or 0,
        unmatchedDamage = activeRun.unmatchedDamage or 0,
        combatEvents = activeRun.combatEvents or 0,
        damageEvents = activeRun.damageEvents or 0,
        deathEvents = activeRun.deathEvents or 0,
        interruptEvents = activeRun.interruptEvents or 0,
        rosterUpdates = activeRun.rosterUpdates or 0,
        localWarnings = localWarnings,
      },
    },
    debug = {
      version = VERSION,
      totalDamage = totalDamage,
      totalDeaths = totalDeaths,
      totalInterrupts = totalInterrupts,
      playersSeen = #players,
      localWarnings = localWarnings,
    },
  }
  table.insert(MPlusFormDB.uploadQueue, queued)
  appendLocalRun(queued)
  msg("queued run: " .. activeRun.dungeonName .. " +" .. tostring(activeRun.keyLevel) .. " players=" .. tostring(#players))
  MPlusFormDB.lastQueuedRun = { runId = runId, players = #players, dungeon = activeRun.dungeonName, keyLevel = activeRun.keyLevel, at = completedAt, warnings = localWarnings, captureMode = activeRun.captureMode or currentCaptureMode() }
  if #localWarnings > 0 then MPlusFormDB.lastLocalWarning = table.concat(localWarnings, ",") end
  updateCaptureDebug(completed and "queued_completed" or "queued_reset")
  scheduleDetailsDebug(runId)
  activeRun = nil
end

local DAMAGE_AMOUNT_INDEX = {
  SWING_DAMAGE = 12,
  RANGE_DAMAGE = 15,
  SPELL_DAMAGE = 15,
  SPELL_PERIODIC_DAMAGE = 15,
  DAMAGE_SHIELD = 15,
  DAMAGE_SPLIT = 15,
}

local function sourcePlayer(sourceGUID)
  return (sourceGUID and rosterByGUID[sourceGUID]) or (sourceGUID and petOwnerByGUID[sourceGUID])
end

local function inCapturedInstance()
  if not activeRun then return false end
  local instanceID = currentInstanceId()
  return instanceID == 0 or activeRun.instanceID == 0 or instanceID == activeRun.instanceID
end

local function onCombatLog()
  if not activeRun then return end
  activeRun.combatEvents = (activeRun.combatEvents or 0) + 1
  if not inCapturedInstance() then
    activeRun.ignoredOutsideEvents = (activeRun.ignoredOutsideEvents or 0) + 1
    return
  end
  local info = { CombatLogGetCurrentEventInfo() }
  local subevent = info[2]
  local sourceGUID = info[4]
  local destGUID = info[8]

  if subevent == "SPELL_INTERRUPT" then
    local source = sourcePlayer(sourceGUID)
    if source then
      source.interrupts = (source.interrupts or 0) + 1
      activeRun.interruptEvents = (activeRun.interruptEvents or 0) + 1
    end
    return
  end

  if subevent == "UNIT_DIED" then
    local dest = destGUID and rosterByGUID[destGUID]
    if dest then
      local now = GetTime()
      if not recentDeaths[destGUID] or now - recentDeaths[destGUID] > 2 then
        dest.deaths = (dest.deaths or 0) + 1
        activeRun.deathEvents = (activeRun.deathEvents or 0) + 1
        recentDeaths[destGUID] = now
      end
    end
    return
  end

  local amountIndex = DAMAGE_AMOUNT_INDEX[subevent]
  if not amountIndex then return end
  local amount = tonumber(info[amountIndex]) or 0
  if amount <= 0 then return end
  local source = sourcePlayer(sourceGUID)
  if source then
    source.totalDamage = (source.totalDamage or 0) + amount
    activeRun.damageEvents = (activeRun.damageEvents or 0) + 1
  else
    activeRun.unmatchedDamage = (activeRun.unmatchedDamage or 0) + amount
  end
  if (activeRun.combatEvents or 0) % 100 == 0 then updateCaptureDebug("combat_sample") end
end



local function fmtDps(v)
  v = tonumber(v) or 0
  if v >= 1000000 then return string.format("%.2fM", v / 1000000) end
  if v >= 1000 then return string.format("%.1fk", v / 1000) end
  return tostring(math.floor(v))
end

local function normalizeSnapshotKey(value)
  return tostring(value or ""):gsub("%s+", ""):lower()
end

local function confidenceLabel(value)
  local n = tonumber(value)
  if not n then return tostring(value or "low") end
  if n >= 80 then return "High (" .. tostring(math.floor(n)) .. ")" end
  if n >= 50 then return "Medium (" .. tostring(math.floor(n)) .. ")" end
  return "Low (" .. tostring(math.floor(n)) .. ")"
end

local function snapshotLookupByNameRealm(name, realm)
  if not name or name == "" then return nil end
  local snapshot = MPlusFormSnapshot or {}
  realm = trimRealm(realm)
  local region = currentRegion()
  local regionCode = region
  if GetCurrentRegion then
    regionCode = REGION_BY_ID[GetCurrentRegion()] or region
  end
  local candidates = {
    normalizeSnapshotKey(name .. "-" .. realm),
    normalizeSnapshotKey(name .. "-" .. realm .. "-" .. region),
    normalizeSnapshotKey(name .. "-" .. realm .. "-" .. regionCode),
    normalizeSnapshotKey(currentRegion() .. "-" .. realm .. "-" .. name),
    normalizeSnapshotKey(realm .. "-" .. name),
    normalizeSnapshotKey(name),
  }
  local profile = nil
  for _, key in ipairs(candidates) do
    profile = snapshot[key] or (snapshot.profiles and snapshot.profiles[key])
    if profile then break end
  end
  if not profile then return nil end
  if profile.serverApproved ~= true or profile.rejected == true or profile.confidence == "rejected" then return nil end
  return profile
end

local function safeTooltipAppend(tooltip)
  ensureDB()
  if not tooltip or (MPlusFormDB.settings and MPlusFormDB.settings.tooltip == false) then return end
  if not tooltip.AddLine or not tooltip.AddDoubleLine then return end
  local ok, name, unit = pcall(function()
    if tooltip.GetUnit then
      local n, u = tooltip:GetUnit()
      return n, u
    end
  end)
  if not ok then return end
  local realm
  if unit and UnitExists(unit) then
    name, realm = unitNameRealm(unit)
  elseif name and name:find("-") then
    local n, r = name:match("^([^%-]+)%-(.+)$")
    name, realm = n, r
  else
    realm = GetRealmName()
  end
  local profile = snapshotLookupByNameRealm(name, realm)
  if not profile then return end
  local keyMin = tonumber(profile.keyMin or profile.key_min or (profile.keyRange and profile.keyRange[1]) or 0) or 0
  local keyMax = tonumber(profile.keyMax or profile.key_max or (profile.keyRange and profile.keyRange[2]) or 0) or 0
  local last5Count = tonumber(profile.last5Count or profile.last5_count or 0) or 0
  local interrupts = tonumber(profile.interruptsAvg or profile.avgInterrupts or profile.avg_interrupts or 0) or 0
  local deaths = tonumber(profile.deathsAvg or profile.avgDeaths or profile.avg_deaths or 0) or 0
  tooltip:AddLine(" ")
  tooltip:AddLine("MPlusForm Verified", 0.35, 0.85, 1.0)
  tooltip:AddDoubleLine("Last verified keys", tostring(last5Count), 1,1,1, 1,1,1)
  tooltip:AddDoubleLine("Key range", string.format("+%d - +%d", keyMin, keyMax), 1,1,1, 1,1,1)
  tooltip:AddDoubleLine("Avg DPS", fmtDps(profile.avgDps or profile.last5AvgDps or profile.last5_avg_dps), 1,1,1, 1,1,1)
  tooltip:AddDoubleLine("Interrupts", string.format("%.1f", interrupts), 1,1,1, 1,1,1)
  tooltip:AddDoubleLine("Deaths", string.format("%.1f", deaths), 1,1,1, 1,1,1)
  tooltip:AddDoubleLine("Confidence", confidenceLabel(profile.confidence), 1,1,1, 1,1,1)
  tooltip:AddLine("Source: MPlusForm server snapshot", 0.65, 0.65, 0.65)
  if tooltip.Show then tooltip:Show() end
end

local tooltipHooked = false

local function safeTooltipCallback(tooltip)
  local ok, err = pcall(safeTooltipAppend, tooltip)
  if not ok then
    ensureDB()
    MPlusFormDB.lastTooltipError = { message = tostring(err), at = time(), version = VERSION }
  end
end

local function registerTooltip()
  ensureDB()
  if MPlusFormDB.settings.tooltipUserDisabled == true then
    MPlusFormDB.settings.tooltip = false
    MPlusFormDB.tooltipRegistered = "disabled_by_user"
    return
  end
  MPlusFormDB.settings.tooltip = true
  if tooltipHooked then
    MPlusFormDB.tooltipRegistered = "enabled_safe_tooltip_pcall"
    return
  end
  if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType and Enum.TooltipDataType.Unit then
    local ok, err = pcall(function()
      TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Unit, function(tooltip)
        safeTooltipCallback(tooltip)
      end)
    end)
    if ok then
      tooltipHooked = true
      MPlusFormDB.tooltipRegistered = "enabled_safe_tooltipdata_pcall"
      return
    end
    MPlusFormDB.tooltipRegistered = "tooltipdata_register_failed_safe"
    MPlusFormDB.lastTooltipError = { message = tostring(err), at = time(), version = VERSION }
  end
  if GameTooltip and GameTooltip.HookScript then
    local ok, err = pcall(function()
      GameTooltip:HookScript("OnTooltipSetUnit", safeTooltipCallback)
    end)
    if ok then
      tooltipHooked = true
      MPlusFormDB.tooltipRegistered = "enabled_safe_tooltip_pcall"
      return
    end
    MPlusFormDB.tooltipRegistered = "tooltip_register_failed_safe"
    MPlusFormDB.lastTooltipError = { message = tostring(err), at = time(), version = VERSION }
  else
    MPlusFormDB.tooltipRegistered = "tooltip_api_unavailable"
  end
end

local function queueStats()
  local pending, sent = 0, 0
  for _, entry in ipairs(MPlusFormDB.uploadQueue or {}) do
    if entry.status == "sent" or entry.sent then sent = sent + 1 else pending = pending + 1 end
  end
  return pending, sent
end

local function snapshotStats()
  local meta = MPlusFormSnapshotMeta or {}
  return tostring(meta.profileCount or meta.profiles or 0), tostring(meta.generatedAt or 0)
end

SLASH_MPLUSFORM1 = "/mpf"
SLASH_MPLUSFORM2 = "/mplusform"
SlashCmdList.MPLUSFORM = function(input)
  input = (input or ""):lower()
  local pending, sent = queueStats()
  if input == "wipe" then
    MPlusFormDB.uploadQueue = {}
    MPlusFormDB.localRuns = {}
    msg("local queue wiped")
  elseif input == "queue" then
    msg("queue pending=" .. pending .. " sent=" .. sent .. " localRuns=" .. #(MPlusFormDB.localRuns or {}))
  elseif input == "snapshot" then
    local profiles, generatedAt = snapshotStats()
    msg("snapshot profiles=" .. profiles .. " generatedAt=" .. generatedAt)
  elseif input == "local" then
    local last = MPlusFormDB.localRuns and MPlusFormDB.localRuns[1]
    if last and last.run then
      msg("last local: " .. tostring(last.run.dungeon) .. " +" .. tostring(last.run.keyLevel) .. " players=" .. tostring(last.run.players and #last.run.players or 0) .. " status=" .. tostring(last.status))
    else
      msg("no local runs yet")
    end
  elseif input == "forcequeue" then
    if activeRun then
      queueRun(false)
      msg("active capture force-queued as incomplete")
    else
      msg("no active capture to force-queue")
    end
  elseif input == "tooltip off" then
    MPlusFormDB.settings.tooltipUserDisabled = true
    MPlusFormDB.settings.tooltip = false
    msg("tooltip off")
  elseif input == "tooltip on" then
    MPlusFormDB.settings.tooltipUserDisabled = false
    MPlusFormDB.settings.tooltip = true
    registerTooltip()
    msg("tooltip on: server-approved snapshot only")
  elseif input == "syncnow" or input == "save" or input == "uploadnow" then
    if activeRun then
      msg("active key is still capturing; do not reload yet. Wait for queued run message, or use /mpf forcequeue only for failed/incomplete tests.")
      return
    end
    msg("syncnow: reloading UI now to flush SavedVariables. Windows Sync can upload immediately after reload.")
    if C_Timer and C_Timer.After then
      C_Timer.After(0.5, function() if ReloadUI then ReloadUI() end end)
    elseif ReloadUI then
      ReloadUI()
    else
      msg("ReloadUI API unavailable; type /reload manually.")
    end
  elseif input == "status" or input == "" then
    registerTooltip()
    local profiles, generatedAt = snapshotStats()
    local lastCapture = MPlusFormDB.lastCapture or {}
    msg("v" .. VERSION .. " pending=" .. pending .. " sent=" .. sent .. " active=" .. tostring(activeRun ~= nil))
    msg("snapshot profiles=" .. profiles .. " generatedAt=" .. generatedAt .. " tooltip=" .. tostring(MPlusFormDB.tooltipRegistered or "not_registered"))
    msg("lastCapture reason=" .. tostring(lastCapture.reason or "none") .. " players=" .. tostring(lastCapture.playersSeen or 0) .. " combatEvents=" .. tostring(lastCapture.combatEvents or 0))
    msg("captureMode=" .. currentCaptureMode() .. " toc=" .. tostring(wowTocVersion()) .. " Details optional=" .. tostring(_G.Details ~= nil))
    if retail12CombatLogBlocked() then msg("CLEU disabled: Sync must parse Logs\\WoWCombatLog.txt; server-truth snapshot only") else msg("native capture ON for legacy build; server-truth snapshot only") end
    msg("commands: /mpf queue | /mpf snapshot | /mpf local | /mpf syncnow | /mpf forcequeue | /mpf tooltip on/off | /mpf wipe")
  else
    msg("commands: /mpf status | /mpf queue | /mpf snapshot | /mpf local | /mpf syncnow | /mpf forcequeue | /mpf tooltip on/off | /mpf wipe")
  end
end

local function handleEvent(event, arg1)
  if event == "ADDON_LOADED" and arg1 == addonName then
    ensureDB()
    MPlusFormDB.lastLoaded = { version = VERSION, at = time(), captureMode = currentCaptureMode(), tocVersion = wowTocVersion() }
    MPlusFormDB.runtime = captureModeFlags()
    registerTooltip()
  elseif event == "CHALLENGE_MODE_START" then
    startRun()
  elseif event == "CHALLENGE_MODE_COMPLETED" then
    queueRun(true)
  elseif event == "CHALLENGE_MODE_RESET" then
    if activeRun then queueRun(false) end
  elseif event == "PLAYER_ENTERING_WORLD" or event == "GROUP_ROSTER_UPDATE" or event == "UNIT_PET" then
    if activeRun then rebuildRoster() end
    if activeRun then updateCaptureDebug("roster_or_world_update") end
  elseif event == "PLAYER_LOGOUT" then
    if activeRun then updateCaptureDebug("player_logout_active_capture") end
  elseif event == "COMBAT_LOG_EVENT_UNFILTERED" then
    if not retail12CombatLogBlocked() then onCombatLog() end
  end
end

frame:SetScript("OnEvent", function(_, event, arg1)
  local ok, err = pcall(handleEvent, event, arg1)
  if not ok then
    ensureDB()
    MPlusFormDB.lastAddonError = { event = event, message = tostring(err), at = time(), version = VERSION }
  end
end)

frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("GROUP_ROSTER_UPDATE")
frame:RegisterEvent("UNIT_PET")
frame:RegisterEvent("PLAYER_LOGOUT")
frame:RegisterEvent("CHALLENGE_MODE_START")
frame:RegisterEvent("CHALLENGE_MODE_COMPLETED")
frame:RegisterEvent("CHALLENGE_MODE_RESET")

local cleuRegistered = false
if not retail12CombatLogBlocked() then
  frame:RegisterEvent("COMBAT_LOG_EVENT_UNFILTERED")
  cleuRegistered = true
end

ensureDB()
registerTooltip()
MPlusFormDB.runtime = captureModeFlags()
MPlusFormDB.runtime.cleuRegistered = cleuRegistered
