"""Inventory of the generator lane's scratch tree (`_agent_temp/claude`) before any cleanup.

    python tools/mapgen_scratch_inventory.py [--json OUT]

Fable's brief 2 (2026-10-02), step 0: «зачистить нужно вначале то что там старое и не нужное» - «именно то что
относится к генератору». Only `O:/Claude2/_agent_temp/claude/` is this lane's; `codex/`, `opentdm_x_*` and the other
roots belong to other sessions and are never listed here.

A folder is KEPT when (a) a tool, a guard or the source tree names it, (b) it holds the job of a map delivered to
the PO (by the evidence ledger's `round*/s3_*` mentions in delivery rows), or (c) it is one of the last two rounds.
Everything else is listed for the PO with its size; nothing is deleted by this tool.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT = Path(r"O:\Claude2\_agent_temp\claude")
LEDGER = REPO / "memory" / "project_mapgen1_evidence_ledger.md"


def size_of(p: Path) -> int:
    total = 0
    for dirpath, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def named_by_code() -> set[str]:
    """Top folders (and round folders) under ROOT that any file in tools/ or src/ names."""
    names: set[str] = set()
    rx = re.compile(r"_agent_temp[\\/]+claude[\\/]+([A-Za-z0-9_.-]+)(?:[\\/]+([A-Za-z0-9_.-]+))?")
    for base in (REPO / "tools", REPO / "src"):
        for path in base.rglob("*"):
            if path.suffix not in (".py", ".c", ".h", ".ps1", ".cmd", ".bat"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in rx.finditer(text):
                names.add(m.group(1))
                if m.group(2):
                    names.add(f"{m.group(1)}/{m.group(2)}")
    return names


def delivered_rounds() -> set[str]:
    """Rounds whose job made a map the PO was given: ledger rows naming an install or a delivery with round*/s3_*."""
    text = LEDGER.read_text(encoding="utf-8", errors="replace")
    keep: set[str] = set()
    for row in text.splitlines():
        if not row.startswith("| "):
            continue
        if not re.search(r"install|deliver|mg_20[a-z]?\b", row, re.I):
            continue
        for m in re.finditer(r"\b(round\d+)/(s3_\w+|s3)\b", row):
            keep.add(m.group(1))
    return keep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    code = named_by_code()
    delivered = delivered_rounds()
    rows = []
    rounds_dir = ROOT / "mapgen1-20260918"
    rounds = sorted((p for p in rounds_dir.iterdir() if p.is_dir() and re.match(r"round\d+", p.name)),
                    key=lambda p: int(re.match(r"round(\d+)", p.name).group(1)))
    last_two = {p.name for p in rounds[-2:]}
    for top in sorted(ROOT.iterdir()):
        if not top.is_dir():
            continue
        if top == rounds_dir:
            for r in sorted(rounds_dir.iterdir()):
                if not r.is_dir():
                    continue
                why = []
                if f"{top.name}/{r.name}" in code:
                    why.append("named by a tool or guard")
                if r.name in delivered:
                    why.append("job of a delivered map")
                if r.name in last_two:
                    why.append("one of the last two rounds")
                rows.append({"path": str(r), "bytes": size_of(r), "keep": bool(why), "why": why})
            continue
        why = ["named by a tool or guard"] if top.name in code else []
        rows.append({"path": str(top), "bytes": size_of(top), "keep": bool(why), "why": why})
    keep = sum(r["bytes"] for r in rows if r["keep"])
    drop = sum(r["bytes"] for r in rows if not r["keep"])
    for r in rows:
        print(f"{'KEEP' if r['keep'] else 'DROP'} {r['bytes'] / 2**20:9.1f} MB  {r['path']}"
              + (f"  ({'; '.join(r['why'])})" if r["why"] else ""))
    print(f"TOTAL keep {keep / 2**30:.2f} GB, drop {drop / 2**30:.2f} GB")
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
