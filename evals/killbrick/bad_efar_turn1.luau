-- BAD (EFAR Turn 1, 2026-10-10) — NEVER KILLS, WRONG PLACEMENT
-- Claimed placement: ServerScriptService > DeathTile (Script)
-- Bug 1: script.Parent is ServerScriptService, which has no Touched event.
-- Bug 2: FindFirstChildWhichIsA("HumanoidRootPart") is invalid —
--   "HumanoidRootPart" is an instance NAME, not a class, so it always
--   returns nil and the Health = 0 line never runs.
-- Bug 3: global attribute debounce blocks ALL players on one touch.
-- Bug 4: NPC check is false (NPCs DO have HumanoidRootPart); correct
--   filter is Players:GetPlayerFromCharacter(character).

-- Configuration
local RESET_TIME = 0.5 -- Seconds before the part can be touched again

-- Get the part from the script's parent (the DeathTile part)
local part = script.Parent

-- Find the Humanoid of the part being touched
local function damagePlayer(otherPart)
	-- Ensure the touched part is a BasePart
	if not otherPart:IsA("BasePart") then
		return
	end

	-- Find the Humanoid inside the touched part's parent
	local humanoid = otherPart.Parent:FindFirstChildWhichIsA("Humanoid")

	-- Only kill real players (HumanoidRootPart + Humanoid), not NPCs or loose parts
	if humanoid and humanoid.Parent:FindFirstChildWhichIsA("HumanoidRootPart") then
		-- Apply instant death
		humanoid.Health = 0
	end
end

-- Connect the Touched event with a debounce mechanism using Instance Attributes
part.Touched:Connect(function(otherPart)
	-- Check if the part has already been hit recently (Debounce)
	if part:GetAttribute("Touched") then
		return
	end

	-- Execute damage logic
	damagePlayer(otherPart)

	-- Set attribute to true to prevent multiple hits per touch
	part:SetAttribute("Touched", true)

	-- Wait for the reset time, then clear the attribute
	task.wait(RESET_TIME)
	part:SetAttribute("Touched", false)
end)
