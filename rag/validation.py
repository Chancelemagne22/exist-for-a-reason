"""
EFAR - Shared post-generation validation (single source of truth).

Imported by both rag/ask.py (CLI) and rag/app.py (Streamlit) so the two
frontends can never diverge again (see audit B14/B15).

Covers:
  1. Pathfinding hallucinations (original set: PathStatus, Blocked,
     ComputeAsync void, GetWaypoints, deprecated methods).
  2. Kill-brick hallucinations (added 2026-10-10 from evals/killbrick/):
     invalid FindFirstChildWhichIsA("HumanoidRootPart"), script.Parent =
     ServerScriptService with .Touched, global attribute debounce, and
     missing GetPlayerFromCharacter on "only real players" prompts.

This is a fallback safety net, not a replacement for good
retrieval/prompting. It catches KNOWN failure patterns only — expand the
sets below as new failure patterns turn up on new test questions.
"""

import re

VALID_PATHSTATUS_VALUES = {
    "Success", "NoPath", "ClosestNoPath", "ClosestOutOfRange",
    "FailStartNotEmpty", "FailFinishNotEmpty", "Unknown",
}
VALID_PATH_EVENTS = {"Blocked"}
DEPRECATED_PATHFINDING_METHODS = {
    "FindPathAsync", "ComputeRawPathAsync", "ComputeSmoothPathAsync",
    "CheckOcclusionAsync", "GetPointCoordinates",
}


def _validate_pathfinding(answer):
    warnings = []

    for method in DEPRECATED_PATHFINDING_METHODS:
        if re.search(rf"\b{re.escape(method)}\s*\(", answer):
            warnings.append(
                f"Uses '{method}', which is DEPRECATED. Check the reference docs "
                f"for the recommended replacement."
            )

    for match in re.finditer(r"Enum\.PathStatus\.(\w+)", answer):
        value = match.group(1)
        if value not in VALID_PATHSTATUS_VALUES:
            warnings.append(
                f"Uses 'Enum.PathStatus.{value}', which is not a real PathStatus value. "
                f"Valid values: {', '.join(sorted(VALID_PATHSTATUS_VALUES))}."
            )

    for match in re.finditer(r"\bpath\.(\w+):Connect\s*\(", answer, re.IGNORECASE):
        event = match.group(1)
        if event not in VALID_PATH_EVENTS:
            warnings.append(
                f"Connects to 'path.{event}', which is not a documented Path event. "
                f"Valid events: {', '.join(sorted(VALID_PATH_EVENTS))}."
            )

    if re.search(r"local\s+\w+(?:\s*,\s*\w+)*\s*=\s*[\w.]*:ComputeAsync\s*\(", answer):
        warnings.append(
            "Captures a return value from ':ComputeAsync()', but this method returns "
            "nothing (void). Check Path.Status after calling it instead."
        )

    creates_path = re.search(r":CreatePath\s*\(", answer) or re.search(r":ComputeAsync\s*\(", answer)
    uses_waypoints = re.search(r":GetWaypoints\s*\(", answer)
    if creates_path and not uses_waypoints:
        warnings.append(
            "Calls CreatePath/ComputeAsync but never calls GetWaypoints() - the path "
            "may not actually be followed (check for a single MoveTo() straight to "
            "the target instead of waypoint-by-waypoint movement)."
        )

    return warnings


def _validate_killbrick(answer):
    """Kill-brick / deathtile checks from evals/killbrick/ (2026-10-10)."""
    warnings = []

    # 1. FindFirstChildWhichIsA("HumanoidRootPart") is INVALID:
    # "HumanoidRootPart" is an instance NAME, not a class. WhichIsA always
    # returns nil -> the kill line never runs (EFAR Turn 1 zero-kill bug).
    if re.search(r'FindFirstChildWhichIsA\s*\(\s*["\']HumanoidRootPart["\']\s*\)', answer):
        warnings.append(
            "Calls FindFirstChildWhichIsA(\"HumanoidRootPart\"), but "
            "\"HumanoidRootPart\" is an instance NAME, not a class — this always "
            "returns nil so the kill never fires. Use "
            "character:FindFirstChild(\"HumanoidRootPart\") for the name check, or "
            "better: Players:GetPlayerFromCharacter(character) to filter real players."
        )

    # 2. script.Parent as the kill part while the placement says
    # ServerScriptService: SSS has no Touched event, so part.Touched:Connect
    # errors and nothing fires (EFAR Turn 1 placement contradiction).
    mentions_sss = re.search(r"ServerScriptService", answer) is not None
    uses_parent_part = re.search(r"local\s+\w+\s*=\s*script\.Parent", answer) is not None
    uses_touched = re.search(r"\.Touched\s*:\s*Connect\s*\(", answer) is not None
    if mentions_sss and uses_parent_part and uses_touched:
        warnings.append(
            "Placement says ServerScriptService but code does "
            "`local part = script.Parent` + `part.Touched:Connect` — "
            "ServerScriptService has no Touched event. Parent the server Script "
            "as a CHILD of the kill Part (Workspace > DeathTile > Script) so "
            "script.Parent is the part."
        )

    # 3. Global attribute debounce (single shared flag for all players):
    # Player A touches -> Player B is invincible for RESET_TIME. Prefer a
    # per-player table + task.delay (non-yielding) + PlayerRemoving cleanup.
    if re.search(r"GetAttribute\s*\(\s*[\"']Touched[\"']\s*\)", answer) and re.search(
        r"SetAttribute\s*\(\s*[\"']Touched[\"']\s*,", answer
    ):
        warnings.append(
            "Uses a single shared `Touched` attribute as the debounce — one "
            "player's touch blocks EVERY player on the tile. Use a per-player "
            "table instead: `local debounce = {}` + `if debounce[player] then "
            "return end` + `task.delay(COOLDOWN, function() debounce[player] = "
            "nil end)`."
        )

    # 4. "Only real players" prompt but no GetPlayerFromCharacter: a bare
    # Humanoid check also kills NPCs/dummies (which HAVE Humanoids and
    # HumanoidRootParts). Only GetPlayerFromCharacter reliably excludes them.
    if re.search(r"\.Touched\s*:\s*Connect\s*\(", answer) and re.search(
        r"FindFirstChild(OfClass|WhichIsA)\s*\(\s*[\"']Humanoid[\"']\s*\)", answer
    ):
        if "GetPlayerFromCharacter" not in answer:
            warnings.append(
                "Checks for a Humanoid but never calls "
                "Players:GetPlayerFromCharacter(character) — NPCs and dummies "
                "also have Humanoids, so they will be killed too. Add: `local "
                "player = Players:GetPlayerFromCharacter(character); if not "
                "player then return end`."
            )

    return warnings


def validate_answer(answer):
    """
    Scan generated Lua code for known hallucination/deprecation patterns.
    Returns a list of warning strings (empty if nothing suspicious found).
    """
    return _validate_pathfinding(answer) + _validate_killbrick(answer)


def post_validate_and_clean(response_text: str) -> tuple:
    """
    Scans the LLM response, extracts Luau code blocks, auto-corrects
    micro-quirks (.magnitude/.unit/wait), and returns
    (cleaned_text, audit_log). Plain log strings — callers add their own
    icons (emoji for CLI, :material: for Streamlit).
    """
    audit_log = []

    def process_code_block(match):
        prefix = match.group(1)  # e.g. "```lua\n" or "```luau\n"
        code = match.group(2)
        suffix = match.group(3)  # "```"

        if re.search(r'\.magnitude\b', code):
            code = re.sub(r'\.magnitude\b', '.Magnitude', code)
            audit_log.append("Auto-corrected legacy `.magnitude` to PascalCase `.Magnitude`")

        if re.search(r'\.unit\b', code):
            code = re.sub(r'\.unit\b', '.Unit', code)
            audit_log.append("Auto-corrected legacy `.unit` to PascalCase `.Unit`")

        if re.search(r'(?<!task\.)\bwait\(', code):
            code = re.sub(r'(?<!task\.)\bwait\(', 'task.wait(', code)
            audit_log.append("Upgraded deprecated global `wait()` to performance-optimized `task.wait()`")

        if "CharacterAdded:Wait()" in code:
            audit_log.append(
                "LINT WARNING: Detected server-side `CharacterAdded:Wait()`. "
                "If a player leaves right as this fires, the server thread will hang indefinitely."
            )

        return f"{prefix}{code}{suffix}"

    code_block_pattern = r'(```lu[au]a\r?\n)(.*?)(```)'

    cleaned_text = re.sub(
        code_block_pattern,
        process_code_block,
        response_text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    return cleaned_text, audit_log
