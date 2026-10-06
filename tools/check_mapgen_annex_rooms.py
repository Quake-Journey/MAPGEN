r"""An annex is not one room (ledger row 412, Fable's brief 9 D3).

The PO, 05.10: «У нас теперь в каждую карту будут вот такие квадратные комнаты с оружием или армором по середине
клепаться? ... Где разнообразие?» Until row 412 every annex was one square room - a dais of two tiers in its middle
with the pickup on it, two trim bands. Now each room's parts are drawn: its footprint (square, long along the wall,
long away from it), its floor (flat; a rim along three walls; a gallery along the far wall with steps up), where its
pickup stands (the dais; the floor near the far wall; the gallery; between two columns), its columns (0, 2, 4) and
its trims (both bands, the lintel's, none). The plan says what it drew for each room ("dig annex pattern: ...").

On q2dm1 (seed 1020, ambition 80) and q3t2 (seed 45, ambition 90):
* no two annexes of one map share footprint, floor and pickup place;
* each annex, applied alone and compiled, is sealed (no leak) and is the room the plan declared - a dais exactly when
  the pickup stands on it, the rim, the gallery and its steps, the columns where they were drawn - and its pickup has
  floor under it and air around it.
RED: the same generator with the room's pattern taken out (`g_annex_pattern`, a sandbox copy): the declared parts
are not there - the case above goes red.

    python tools/check_mapgen_annex_rooms.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from check_mapgen_dig import DIG_EDIT, bsp_tree, compile_map, drive, tree_solid  # noqa: E402
from check_mapgen_recut import build_driver  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

REPO = TOOLS.parent
DONORS = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\MapgenStudio\engine\donors")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\annex_rooms")
CASES = [("q2dm1", "1020", "80"), ("q3t2", "45", "90")]
NUM = r"(-?\d+(?:\.\d+)?)"
PATTERN = re.compile(r"^  dig annex pattern: footprint (\d+) x (\d+), floor (\w+), pickup ([\w-]+), columns (\d+),"
                     r" trims (\d+)$", re.M)
ROOM = re.compile(r"^  dig annex: room " + " ".join([NUM] * 3) + r" \.\. " + " ".join([NUM] * 3)
                  + " off " + " ".join([NUM] * 3) + r" through (\d+) of wall(?:, built in air)?$", re.M)
MOVE = re.compile(r"^  dig annex moves: (\S+) from " + " ".join([NUM] * 3) + " to " + " ".join([NUM] * 3) + "$",
                  re.M)
FAILED = TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED, TOTAL
    TOTAL += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def annexes(text: str) -> list[dict]:
    pats = PATTERN.findall(text)
    rooms = [[float(v) for v in m.groups()] for m in ROOM.finditer(text)]
    moves = [(m.group(1), [float(v) for v in m.groups()[1:]]) for m in MOVE.finditer(text)]
    out = []
    for p, r, mv in zip(pats, rooms, moves):
        room, host = r[:6], r[6:9]
        mid = [0.5 * (room[0] + room[3]), 0.5 * (room[1] + room[4]), host[2]]
        edit = next((m.group(1) for m in DIG_EDIT.finditer(text) if m.group(9) == "annex"
                     and [float(m.group(k)) for k in range(3, 9)] == host + mid), None)
        out.append({"foot": (int(p[0]), int(p[1])), "floor": p[2], "pickup": p[3], "columns": int(p[4]),
                    "trims": int(p[5]), "room": room, "host": host, "edit": edit, "cls": mv[0], "to": mv[1][3:]})
    return out


def parts(tree, an: dict) -> dict:
    """What the compiled room holds, probed in the tree at the places the pattern puts its parts."""
    r, host = an["room"], an["host"]
    f, c = r[2], r[5]
    al = 0 if not (r[0] <= host[0] <= r[3]) else 1          # the axis the room goes away from its door along
    ac = 1 - al
    mid = [0.5 * (r[0] + r[3]), 0.5 * (r[1] + r[4])]
    dirn = 1.0 if mid[al] > host[al] else -1.0
    far = r[3 + al] if dirn > 0 else r[al]
    deep, wide = r[3 + al] - r[al], r[3 + ac] - r[ac]

    def at(a: float, cc: float, z: float) -> tuple:
        p = [0.0, 0.0, z]
        p[al], p[ac] = a, cc
        return tuple(p)

    def solid(a, cc, z):
        return tree_solid(tree, at(a, cc, z))

    got = {
        "dais": solid(mid[al], mid[ac], f + 8) and solid(mid[al], mid[ac], f + 24) and not solid(mid[al], mid[ac], f + 40),
        "rim": solid(far - dirn * 32, mid[ac], f + 8) and not solid(far - dirn * 32, mid[ac], f + 24),
        "gallery": solid(far - dirn * 64, mid[ac], f + 40) and not solid(far - dirn * 64, mid[ac], f + 56)
                   and solid(far - dirn * (128 + 16), r[ac] + 64, f + 24),
        "pair": all(solid(mid[al] + dirn * 0.25 * deep, mid[ac] + s * 96, f + 64) for s in (-1, 1)),
        "columns": all(solid(mid[al] if an["columns"] == 2 else r[al] + (r[3 + al] - r[al]) * k / 3,
                             r[ac] + 0.25 * wide if side == 0 else r[3 + ac] - 0.25 * wide, f + 64)
                       for side in (0, 1)
                       for k in ((1,) if an["columns"] == 2 else (1, 2))) if an["columns"] else False,
    }
    to = an["to"]
    # something to stand on within 48 under it (a floor 16 thick may have the old map's air under it), air around it
    got["pickup"] = (not tree_solid(tree, (to[0], to[1], to[2]))
                     and any(tree_solid(tree, (to[0], to[1], to[2] - dz)) for dz in range(4, 52, 4))
                     and not tree_solid(tree, (to[0], to[1], to[2] + 24)))
    return got


def matches(an: dict, got: dict) -> list[str]:
    """What of the declared room is not there (empty: it is the room the plan said)."""
    want = {"dais": an["pickup"] == "dais", "rim": an["floor"] == "rim", "gallery": an["floor"] == "gallery",
            "pair": an["pickup"] == "columns"}
    wrong = [k for k, v in want.items() if got[k] != v]
    if an["columns"] and an["pickup"] != "columns" and not got["columns"]:
        wrong.append("columns")
    if not got["pickup"]:
        wrong.append("pickup stand")
    return wrong


def run(exe: Path, work: Path, tag: str) -> dict[str, list]:
    out = {}
    for donor, seed, amb in CASES:
        text = drive(exe, DONORS / f"{donor}.bsp", "--seed", seed, "--ambition", amb, "--annex-capped", "--list")
        rooms = annexes(text)
        results = []
        for k, an in enumerate(rooms):
            if an["edit"] is None:
                results.append((an, None, "no edit found for it"))
                continue
            mp = work / f"{tag}_{donor}_{k}.map"
            said_out = drive(exe, DONORS / f"{donor}.bsp", "--seed", seed, "--ambition", amb, "--annex-capped", "--apply", an["edit"],
                             "--out", str(mp))
            # row 412: an annex the builder itself declines (a sky lift it cannot lay, ...) is the transaction's to
            # refuse, not a room drawn wrong - said, and not judged by its pattern
            refused = re.search(r"^declined: (.*)$", said_out, re.M)
            if re.search(r"^apply \d+: OK, changed no", said_out, re.M):
                results.append((an, None, "declined: " + (refused.group(1) if refused else "?")))
                continue
            bsp = mp.with_suffix(".bsp")
            bsp.unlink(missing_ok=True)
            log = compile_map(mp)
            if "leaked" in log or not bsp.is_file():
                results.append((an, None, "leaked" if "leaked" in log else "no bsp"))
                continue
            results.append((an, parts(bsp_tree(bsp), an), ""))
        out[donor] = results
    return out


def said(an: dict) -> str:
    return (f"{an['foot'][0]}x{an['foot'][1]} {an['floor']}, pickup {an['pickup']}, columns {an['columns']},"
            f" trims {an['trims']} ({an['cls']})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    (a.work / "bin").mkdir(parents=True, exist_ok=True)
    exe = build_driver(REPO, a.work / "bin")
    green = run(exe, a.work, "green")
    for donor, results in green.items():
        rooms = [an for an, _, _ in results]
        keys = [(an["foot"], an["floor"], an["pickup"]) for an in rooms]
        check(f"{donor}: annexes dealt, and no two share footprint, floor and pickup place",
              len(rooms) >= 2 and len(set(keys)) == len(keys), "; ".join(said(an) for an in rooms))
        built = [r for r in results if not r[2].startswith("declined")]
        check(f"{donor}: two annexes or more built", len(built) >= 2,
              f"{len(built)} of {len(results)}; " + "; ".join(f"«{said(an)}» {why}" for an, _, why in results
                                                             if why.startswith("declined")))
        for an, got, why in results:
            if why.startswith("declined"):
                print(f"  note  {donor}: the annex «{said(an)}» the builder declines - {why}", flush=True)
                continue
            if an["edit"] is None:
                # folded into a wing with the annex facing it (row 324): one dig of two rooms, not an annex of its own
                print(f"  note  {donor}: the annex «{said(an)}» was joined into a wing", flush=True)
                continue
            check(f"{donor}: the annex «{said(an)}» compiles sealed and is the room the plan declared",
                  got is not None and not matches(an, got), why or ", ".join(matches(an, got)) or "as declared")
    if not a.no_red:
        before = hash_tree(REPO)
        box = Sandbox(REPO, "annexrooms")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            line = b"static const bool g_annex_pattern = true;"
            if check("RED: the room's pattern is where the mutation says", data.count(line) == 1):
                target.write_bytes(data.replace(line, b"static const bool g_annex_pattern = false;", 1))
                (a.work / "red_bin").mkdir(parents=True, exist_ok=True)
                red = run(build_driver(box.root, a.work / "red_bin"), a.work, "red")
                bad = [(an, got) for res in red.values() for an, got, _ in res[:2] if got is not None]
                check("RED: with the pattern taken out the rooms are not the rooms declared - the case above goes red",
                      bool(bad) and all(matches(an, got) for an, got in bad),
                      "; ".join(f"{said(an)}: missing {', '.join(matches(an, got))}" for an, got in bad[:3]))
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    print(f"{TOTAL - FAILED}/{TOTAL} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
