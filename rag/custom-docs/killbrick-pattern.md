# Kill-brick pattern (custom game doc — ingested by chunk_docs.py)

Synonyms: deathtile, death tile, kill brick, killbrick, lava brick, obby kill.

## Placement

Server Script MUST be a CHILD of the kill Part:

```
Workspace
└── DeathTile (Part)
    └── Script
```

`script.Parent` is then the part. NEVER put a `local part = script.Parent`
+ `part.Touched` script in ServerScriptService (no Touched event there).
Parts have NO "Script field" in the Properties window — parenting in
Explorer IS the connection.

## Canonical pattern

```luau
local Players = game:GetService("Players")

local tile = script.Parent
local COOLDOWN = 1
local debounce = {}

local function onTouched(hit)
	local character = hit:FindFirstAncestorOfClass("Model")
	if not character then return end
	local player = Players:GetPlayerFromCharacter(character)
	if not player then return end
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

Players.PlayerRemoving:Connect(function(player)
	debounce[player] = nil
end)
```

## Why

- `Touched` gives a LIMB part (LowerLeg, Arm, ...), not the character.
  Resolve via `FindFirstAncestorOfClass("Model")`.
- NPCs/dummies also have Humanoids AND HumanoidRootParts — only
  `Players:GetPlayerFromCharacter` reliably filters real players.
- NEVER `FindFirstChildWhichIsA("HumanoidRootPart")`: HumanoidRootPart is
  an instance NAME, not a class — always returns nil, kill never fires.
- Touched fires once per limb: debounce MUST be per-player (table +
  task.delay), never a single shared boolean/attribute (blocks all players).
