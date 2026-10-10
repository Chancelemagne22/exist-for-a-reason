-- GOLDEN (Claude output, verified working first try, 2026-10-10)
-- Placement: Workspace > DeathTile (Part) > Script (regular server Script)
local Players = game:GetService("Players")

local tile = script.Parent
local COOLDOWN = 1 -- seconds before the same player can be killed again

-- Tracks players currently being handled (per-player debounce)
local debounce = {}

local function onTouched(hit)
	-- Find the character that owns the touching part
	local character = hit:FindFirstAncestorOfClass("Model")
	if not character then return end

	-- Only real players: the character must belong to a Player
	local player = Players:GetPlayerFromCharacter(character)
	if not player then return end

	-- Per-player debounce
	if debounce[player] then return end

	local humanoid = character:FindFirstChildOfClass("Humanoid")
	if not humanoid or humanoid.Health <= 0 then return end

	debounce[player] = true
	humanoid.Health = 0

	task.delay(COOLDOWN, function()
		debounce[player] = nil
	end)
end

tile.Touched:Connect(onTouched)

-- Clean up if a player leaves so the table doesn't hold stale entries
Players.PlayerRemoving:Connect(function(player)
	debounce[player] = nil
end)
