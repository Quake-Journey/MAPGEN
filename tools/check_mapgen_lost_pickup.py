"""Does the transaction refuse a map whose game strips a pickup at spawn, or whose lift runs into a spawn - and only that?

The PO, 2026-09-14, on mg_20e: «Не нашел где теперь лежит chaingun». The file had
it, where q2dm1 has it; the map's own server freed it at spawn - `droptofloor:
weapon_chaingun startsolid at (1400 1280 784)` - and the jacket armour, a box of
bullets and three armour shards with it, each inside the resting deck of a dig's
lift (ledger row 302). And on mg_20f: «лифт ... упирается в место респавна и не
поднимается из за этого выше» - a dig dealt to q2dm1's spawn spot dug the floor
from under the spawn, and at the top of its travel the lift's rider met the
spawn's pad (ledger rows 306 and 307).

This asks `MapGenTransaction_PickupsLostAtSpawn` and
`MapGenTransaction_SpawnsInMoverColumns` - the questions REJECTED_LOST_PICKUP and
REJECTED_BLOCKED_SPAWN are decided by - through `tools/mapgen_lost_pickup_oracle.c`,
on copies kept beside the corpus, each checked against the digest its row
declared:

    q2dm1: no pickup lost, no spawn blocked;
    mg_20e: exactly the six pickups its own game freed, each inside a resting lift;
    ai1, the showcase the PO praised: the chaingun, two boxes of bullets and slugs;
    mg_20f: exactly the spawn at 1888 736 536, in func_plat *14's column;
    mg_20g, mg_20f with that spawn moved: nothing.

Then two controlled REDs, each in a disposable sandbox (the shared tree is hashed
before and after): every mover swept where it was drawn instead of where it rests
- mg_20e's six vanish; and the column without the rider's height - mg_20f's
blocked spawn vanishes. Each is a case above going red.

    python tools/check_mapgen_lost_pickup.py [--work DIR] [--skip-red]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as guard  # noqa: E402
from check_mapgen_transaction import SOURCES as TXN_SOURCES  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\lostpickup_guard")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\lostpickup")
MAPS = {
    "q2dm1": (Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp"),
              "2345b0b4a955adb5"),
    "mg_20e": (CORPUS / "mg_20e.bsp", "9abbebaa5f3b1d88"),
    "ai1": (CORPUS / "ai1.bsp", "687bec93866b1f17"),
    # row 307
    "mg_20f": (CORPUS / "mg_20f.bsp", "1da4779a3e01aeaa"),
    "mg_20g": (CORPUS / "mg_20g.bsp", "f3753f328a8671f1"),
}
# What mg_20e's own dedicated server logged at spawn, 2026-09-14 19:44.
MG_20E_FREED = {
    ("weapon_chaingun", (1400, 1280, 784)),
    ("item_armor_jacket", (1336, 1352, 784)),
    ("ammo_bullets", (1336, 1280, 784)),
    ("item_armor_shard", (416, 1192, 784)),
    ("item_armor_shard", (416, 1232, 784)),
    ("item_armor_shard", (416, 1272, 784)),
}
# What ai1's own dedicated server logged at spawn (ledger row 303).
AI1_FREED = {
    ("weapon_chaingun", (1400, 1280, 784)),
    ("ammo_bullets", (1336, 1280, 784)),
    ("ammo_bullets", (1336, 1352, 784)),
    ("ammo_slugs", (1960, 160, 656)),
}
# The spawn the PO's lift ran into on mg_20f (ledger row 306).
MG_20F_BLOCKED = {("info_player_deathmatch", (1888, 736, 536))}

# The oracle links everything the transaction does, with its own main.
SOURCES = [s for s in TXN_SOURCES if s != "tools/mapgen_transaction_driver.c"] \
    + ["tools/mapgen_lost_pickup_oracle.c"]

COUNT = re.compile(r"^(\d+) pickups lost at spawn", re.M)
LINE = re.compile(r"^  (\S+) at (-?\d+) (-?\d+) (-?\d+) inside (.+)$", re.M)
SPAWN_COUNT = re.compile(r"^(\d+) spawns blocked by movers", re.M)
SPAWN_LINE = re.compile(r"^  (\S+) at (-?\d+) (-?\d+) (-?\d+) in the column of (.+)$", re.M)
TXN = "src/mapgen/mapgen_transaction.c"
REDS = [
    ("every mover swept where it was drawn, not where it rests",
     b"MapGenMovers_Displacement(movers, m, 0)", b"NULL", "mg_20e",
     "mg_20e's six vanish",
     lambda lost, blocked: not (set(lost) & MG_20E_FREED)),
    ("the column a mover carries its rider through, without the rider's height",
     b"#define MAPGEN_TXN_RIDER_HEIGHT 56.0f", b"#define MAPGEN_TXN_RIDER_HEIGHT 0.0f", "mg_20f",
     "mg_20f's blocked spawn vanishes",
     lambda lost, blocked: not (set(blocked) & MG_20F_BLOCKED)),
]

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


def build(root: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in SOURCES] + ["-o", str(out), "-lm"],
        capture_output=True, text=True)
    if run.returncode == 0 and out.is_file():
        return ""
    errs = [ln for ln in run.stderr.splitlines() if "error" in ln.lower()]
    return "\n".join(errs) if errs else run.stderr[-1500:]


def ask(exe: Path, bsp: Path) -> tuple[int, dict, int, dict, str]:
    run = guard.run([str(exe), str(bsp)], capture_output=True, text=True, timeout=600)
    text = ((run.stdout or "") + (run.stderr or "")).strip()
    m, s = COUNT.search(text), SPAWN_COUNT.search(text)
    lost = {(c, (int(x), int(y), int(z))): inside for c, x, y, z, inside in LINE.findall(text)}
    blocked = {(c, (int(x), int(y), int(z))): mover for c, x, y, z, mover in SPAWN_LINE.findall(text)}
    return (int(m.group(1)) if m else -1), lost, (int(s.group(1)) if s else -1), blocked, text


def show(found: dict) -> str:
    return "; ".join(f"{c} at {o}: {i}" for (c, o), i in sorted(found.items())[:8]) or "none"


def red() -> None:
    before = hash_tree(REPO)
    box = Sandbox(REPO, "lostpickup")
    try:
        target = box.root / TXN
        for what, anchor, broken, name, then, holds in REDS:
            print(f"=== controlled RED: {what}")
            box.restore(TXN)
            data = target.read_bytes()
            if not check("the line to break is where the mutation says",
                         data.count(anchor) == 1, f"{data.count(anchor)} occurrences"):
                continue
            target.write_bytes(data.replace(anchor, broken, 1))
            red_exe = box.root / "lost_pickup_red.exe"
            err = build(box.root, red_exe)
            if not check("the mutated tree still compiles", not err, err):
                continue
            n, lost, b, blocked, text = ask(red_exe, MAPS[name][0])
            check(f"RED: {then} - a case above goes red", n >= 0 and b >= 0 and holds(lost, blocked),
                  f"lost: {show(lost)}; blocked: {show(blocked)}")
    finally:
        box.dispose()
        check("the shared worktree was never opened for writing", hash_tree(REPO) == before)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    print("=== the maps the questions are asked of")
    for name, (path, prefix) in MAPS.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"
        check(f"{name} is the copy its row declared", digest.startswith(prefix),
              f"{path} {digest[:16]}")
    if FAILED:
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1

    exe = a.work / "lost_pickup_oracle.exe"
    err = build(REPO, exe)
    if not check("the oracle builds with the transaction's own sources", not err, err):
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1

    print("=== pickups the game frees at spawn (row 302)")
    n, lost, b, blocked, text = ask(exe, MAPS["q2dm1"][0])
    check("q2dm1 loses no pickup at spawn", n == 0, text[-300:])
    check("q2dm1 has no spawn a mover runs into", b == 0, show(blocked))
    n, lost, b, blocked, text = ask(exe, MAPS["mg_20e"][0])
    check("mg_20e loses exactly the six its own game freed",
          n == 6 and set(lost) == MG_20E_FREED, show(lost))
    check("... each inside a lift where it rests",
          bool(lost) and all(i.startswith("func_plat ") and i.endswith("where it rests")
                             for i in lost.values()), show(lost))
    n, lost, b, blocked, text = ask(exe, MAPS["ai1"][0])
    check("ai1 loses the chaingun, two boxes of bullets and the slugs",
          n == 4 and set(lost) == AI1_FREED, show(lost))

    print("=== spawns a carrying mover runs into (row 307)")
    n, lost, b, blocked, text = ask(exe, MAPS["mg_20f"][0])
    check("mg_20f blocks exactly the spawn the PO's lift ran into",
          b == 1 and set(blocked) == MG_20F_BLOCKED, show(blocked))
    check("... in func_plat *14's column", list(blocked.values()) == ["func_plat *14"], show(blocked))
    check("mg_20f loses no pickup at spawn", n == 0, show(lost))
    n, lost, b, blocked, text = ask(exe, MAPS["mg_20g"][0])
    check("mg_20g, that spawn moved, blocks no spawn and loses no pickup", n == 0 and b == 0,
          f"lost: {show(lost)}; blocked: {show(blocked)}")

    if not a.skip_red:
        red()

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
