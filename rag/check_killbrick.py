"""
EFAR - Killbrick eval checker (offline, no Supabase/Modal needed).

Usage:
  python rag/check_killbrick.py evals/killbrick/golden_claude.luau
  python rag/check_killbrick.py evals/killbrick/bad_efar_turn1.luau
  python rag/check_killbrick.py                      # checks both shipped goldens

Checks the 6-point killbrick checklist (see evals/killbrick/checklist.txt)
plus the shared validation.py warnings. Exit 0 only if golden passes 6/6
with zero killbrick warnings AND bad sample fails (proves the checker
discriminates — guards against a vacuous all-pass).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validation import validate_answer

CHECKS = [
    ("placement",
     "Script parented to part (script.Parent is the tile)",
     re.compile(r"script\.Parent"),
     None),
    ("touched",
     "Connects BasePart.Touched",
     re.compile(r"\.Touched\s*:\s*Connect\s*\("),
     None),
    ("character",
     "Resolves limb hit -> character (hit.Parent chain or FindFirstAncestorOfClass)",
     re.compile(r"FindFirstAncestorOfClass\s*\(\s*[\"']Model[\"']\s*\)|hit\s*.\s*Parent|otherPart\s*.\s*Parent"),
     None),
    ("player_filter",
     "Only real players via GetPlayerFromCharacter (and no WhichIsA HumanoidRootPart)",
     re.compile(r"GetPlayerFromCharacter"),
     re.compile(r'FindFirstChildWhichIsA\s*\(\s*["\']HumanoidRootPart["\']\s*\)')),
    ("kill",
     "Instant kill via Health = 0",
     re.compile(r"\.Health\s*=\s*0"),
     None),
    ("debounce",
     "Per-player debounce table (no global Touched attribute gate)",
     re.compile(r"debounce\s*\[\s*player\s*\]"),
     re.compile(r"GetAttribute\s*\(\s*[\"']Touched[\"']\s*\)")),
]


def check_file(path):
    text = Path(path).read_text(encoding="utf-8")
    results = []
    for cid, desc, pass_re, fail_re in CHECKS:
        if fail_re and fail_re.search(text):
            results.append((cid, False, f"forbidden pattern: {fail_re.pattern}"))
        elif pass_re.search(text):
            results.append((cid, True, "ok"))
        else:
            results.append((cid, False, f"missing: {pass_re.pattern}"))
    warnings = [w for w in validate_answer(text)]
    return results, warnings


def main(argv):
    root = Path(__file__).resolve().parent.parent
    if len(argv) > 1:
        targets = argv[1:]
    else:
        targets = [
            str(root / "evals" / "killbrick" / "golden_claude.luau"),
            str(root / "evals" / "killbrick" / "bad_efar_turn1.luau"),
        ]
    overall_ok = True
    summary = {}
    for t in targets:
        results, warnings = check_file(t)
        passed = sum(1 for _, ok, _ in results if ok)
        summary[t] = (passed, len(results), len(warnings))
        print(f"\n{'=' * 60}\n{t}\n{'=' * 60}")
        for cid, ok, msg in results:
            print(f"  [{'PASS' if ok else 'FAIL'}] {cid}: {msg}")
        print(f"  checklist: {passed}/{len(results)}")
        if warnings:
            print("  validation warnings:")
            for w in warnings:
                print(f"    - {w}")
        else:
            print("  validation warnings: none")

    # Discrimination gate on the default pair: golden must be 6/6 clean,
    # bad sample must fail checklist AND raise killbrick warnings.
    if len(argv) == 1:
        g_pass, g_total, g_warn = summary[targets[0]]
        b_pass, b_total, b_warn = summary[targets[1]]
        print(f"\n{'=' * 60}\nGATE\n{'=' * 60}")
        gate_ok = (g_pass == g_total and g_warn == 0 and (b_pass < b_total or b_warn > 0))
        print(f"  golden {g_pass}/{g_total} warn={g_warn} | bad {b_pass}/{b_total} warn={b_warn}")
        print(f"  GATE: {'PASS' if gate_ok else 'FAIL'}")
        overall_ok = gate_ok
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
