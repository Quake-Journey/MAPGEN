r"""A room carried whole stands, and a tunnel wears the base's own wall pieces (ledger row 412).

The PO, 05.10, on mg_10_45d: «Вот такие висящие в воздухе куски архитектуры зачем? И почему лампочки в воздухе висят,
а не на потолке как положено», «нарыл тоннелей, а лампочек там нет», «по уровню раскинуты свечи на стенах, а в твоих
конструкциях их нет ... Нужно наследовать особенности украшений и ламп в архитектуре доноров», «украшения на стенах
могут быть не только светильниками». MEASURED on mg_10_45d: of the brushes a room of koldduel1 took, 5 of 48 and 2 of
81 touched nothing (its lamps and a beam); q3t2's tunnels hung no lamp at all (the ceiling panel is dropped for its
colour, row 408).

On q3t2 with koldduel1 the second map (seed 45, ambition 90), the generator's own box rooms not asked:
* the plan finds q3t2's wall pieces - a lamp among them (its torches);
* each room of koldduel1, applied alone and compiled, is sealed, and no brush wholly inside its room is cut off from
  the room's faces (the dig's shell) - every one is joined to them, brush to brush, bounds within one unit;
* the tunnels, applied alone, hang the base's wall pieces - a q3t2 flame (`q3t2/fla1`) more than the base has in one
  of them at least.
RED (a sandbox copy): what does not stand is let in, and no wall piece is hung - both cases above go red.

    python tools/check_mapgen_room_cut.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import itertools
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from check_mapgen_dig import DIG_EDIT, compile_map, drive  # noqa: E402
from check_mapgen_recut import build_driver  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

REPO = TOOLS.parent
DONORS = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\MapgenStudio\engine\donors")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\room_cut")
BASE, SECOND, SEED, AMBITION = "q3t2", "koldduel1", "45", "90"
NO_BOXES = ("--annex", "0", "0", "0", "0", "--storeys", "0")
NUM = r"(-?\d+(?:\.\d+)?)"
ROOM_OF = re.compile(r"^  dig room-of: \S+ room \d+ \([^)]*\) into " + " ".join([NUM] * 3) + r" \.\. "
                     + " ".join([NUM] * 3) + " off " + " ".join([NUM] * 3), re.M)
PIECES = re.compile(r"^  wall pieces of the base: (\d+) lamps, (\d+) ornaments", re.M)
FLAME = "q3t2/fla1"
FAILED = TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED, TOTAL
    TOTAL += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def world_brushes(path: Path, every: bool = False) -> list[tuple[list, list, set]]:
    """The world's brushes of a .map (`every`: and its entities' - q3t2's flames are func_walls): bounds (from the
    corners of their planes) and textures."""
    out, depth, ent, cur = [], 0, -1, None
    for ln in path.read_text(encoding="latin-1").splitlines():
        s = ln.strip()
        if s == "{":
            depth += 1
            if depth == 1:
                ent += 1
            else:
                cur = []
            continue
        if s == "}":
            if depth == 2 and (ent == 0 or every) and cur:
                b = bounds(cur)
                if b:
                    out.append((b[0], b[1], {t for _, t in cur}))
            depth -= 1
            continue
        if depth == 2 and s.startswith("("):
            pts = [tuple(float(v) for v in g.split()) for g in re.findall(r"\(([^)]*)\)", s)[:3]]
            cur.append((pts, s[s.rfind(")") + 1:].split()[0]))
    return out


def bounds(planes):
    eqs = []
    for (a, b, c), _ in planes:
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        ln = sum(x * x for x in n) ** 0.5
        if ln == 0:
            continue
        n = [x / ln for x in n]
        eqs.append((n, sum(n[i] * a[i] for i in range(3))))
    pts = []
    for (n1, d1), (n2, d2), (n3, d3) in itertools.combinations(eqs, 3):
        m = [n1, n2, n3]
        det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
               + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
        if abs(det) < 1e-6:
            continue
        d = [d1, d2, d3]
        p = []
        for k in range(3):
            mm = [r[:] for r in m]
            for r in range(3):
                mm[r][k] = d[r]
            p.append((mm[0][0] * (mm[1][1] * mm[2][2] - mm[1][2] * mm[2][1])
                      - mm[0][1] * (mm[1][0] * mm[2][2] - mm[1][2] * mm[2][0])
                      + mm[0][2] * (mm[1][0] * mm[2][1] - mm[1][1] * mm[2][0])) / det)
        sides = [sum(n[i] * p[i] for i in range(3)) - dd for n, dd in eqs]
        if all(s <= 0.05 for s in sides) or all(s >= -0.05 for s in sides):
            pts.append(p)
    if not pts:
        return None
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def flame_prints(path: Path) -> list:
    """Each flame brush's texture as it lies on it: per face, the texture coordinates of its corners (s = p.u/sx + u0,
    t = p.v/sy + v0), sorted - a copy turned and moved the right way has the very prints its source has."""
    out, depth, cur = [], 0, None
    for ln in path.read_text(encoding="latin-1").splitlines():
        s = ln.strip()
        if s == "{":
            depth += 1
            if depth == 2:
                cur = []
            continue
        if s == "}":
            if depth == 2 and cur and any(FLAME == x[1] for x in cur):
                out.append(_print(cur))
            depth -= 1
            continue
        if depth == 2 and s.startswith("("):
            pts = [tuple(float(v) for v in g.split()) for g in re.findall(r"\(([^)]*)\)", s)[:3]]
            axes = [[float(v) for v in g.split()] for g in re.findall(r"\[([^\]]*)\]", s)[:2]]
            tail = s[s.rfind("]") + 1:].split()
            cur.append(((pts, s[s.rfind(")") + 1:].split()[0]), s[s.rfind(")") + 1:].split()[0], axes,
                        float(tail[1]), float(tail[2])))
    return out


def _print(sides) -> tuple:
    planes = [x[0] for x in sides]
    eqs = []
    for (a, b, c), _ in planes:
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        ln = sum(x * x for x in n) ** 0.5
        n = [x / ln for x in n] if ln else n
        eqs.append((n, sum(n[i] * a[i] for i in range(3))))
    corners = []
    for (n1, d1), (n2, d2), (n3, d3) in itertools.combinations(eqs, 3):
        m = [n1, n2, n3]
        det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
               + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
        if abs(det) < 1e-6:
            continue
        d = [d1, d2, d3]
        p = []
        for k in range(3):
            mm = [r[:] for r in m]
            for r in range(3):
                mm[r][k] = d[r]
            p.append((mm[0][0] * (mm[1][1] * mm[2][2] - mm[1][2] * mm[2][1])
                      - mm[0][1] * (mm[1][0] * mm[2][2] - mm[1][2] * mm[2][0])
                      + mm[0][2] * (mm[1][0] * mm[2][1] - mm[1][1] * mm[2][0])) / det)
        sides_of = [sum(n[i] * p[i] for i in range(3)) - dd for n, dd in eqs]
        if all(x <= 0.05 for x in sides_of) or all(x >= -0.05 for x in sides_of):
            corners.append(p)
    faces = []
    for (n, dd), (_, tex, axes, sx, sy) in zip(eqs, sides):
        on = [p for p in corners if abs(sum(n[i] * p[i] for i in range(3)) - dd) < 0.1]
        # the corners as points - a corner met by a bevel plane too is found more than once, and how often is the
        # compiler's business, not the texture's
        st = sorted({(round(sum(p[i] * axes[0][i] for i in range(3)) / sx + axes[0][3]),
                      round(sum(p[i] * axes[1][i] for i in range(3)) / sy + axes[1][3])) for p in on})
        if st:
            faces.append(tuple(st))
    return tuple(sorted(set(faces)))


def same_print(a: tuple, b: tuple, slack: float = 1.5) -> bool:
    """Two brushes wear their texture alike: every corner's texture coordinates of one within `slack` texels of the
    other's, both ways (a corner on a half texel rounds either side)."""
    pa = {p for f in a for p in f}
    pb = {p for f in b for p in f}
    def near(p, s):
        return any(abs(p[0] - q[0]) <= slack and abs(p[1] - q[1]) <= slack for q in s)
    return all(near(p, pb) for p in pa) and all(near(q, pa) for q in pb)


def touch(a, b) -> bool:
    return all(a[0][i] - 1.0 <= b[1][i] and b[0][i] - 1.0 <= a[1][i] for i in range(3))


def cut_off(brushes, lo, hi) -> list:
    """The brushes wholly inside the room `lo..hi` joined to nothing outside it nor to its faces."""
    inside = [b for b in brushes if all(lo[i] - 1.0 <= b[0][i] and b[1][i] <= hi[i] + 1.0 for i in range(3))]
    held = [any(b[0][i] <= lo[i] + 1.0 or b[1][i] >= hi[i] - 1.0 for i in range(3)) for b in inside]
    outside = [b for b in brushes if not all(lo[i] - 1.0 <= b[0][i] and b[1][i] <= hi[i] + 1.0 for i in range(3))]
    for k, b in enumerate(inside):
        held[k] = held[k] or any(touch(b, o) for o in outside)
    grew = True
    while grew:
        grew = False
        for k, b in enumerate(inside):
            if not held[k] and any(held[j] and touch(b, inside[j]) for j in range(len(inside))):
                held[k] = grew = True
    return [b for k, b in enumerate(inside) if not held[k]]


def run(exe: Path, work: Path, tag: str) -> dict:
    bsp = DONORS / f"{BASE}.bsp"
    words = ("--seed", SEED, "--ambition", AMBITION, "--second", str(DONORS / f"{SECOND}.bsp")) + NO_BOXES
    text = drive(exe, bsp, *words, "--list")
    (work / f"{tag}_plan.txt").write_text(text, encoding="utf-8")
    base_map = work / f"{tag}_base.map"
    drive(exe, bsp, *words, "--out", str(base_map))
    base_flames = sum(1 for b in world_brushes(base_map, True) if FLAME in b[2]) if base_map.is_file() else -1
    base_prints = flame_prints(base_map) if base_map.is_file() else []
    pieces = PIECES.search(text)
    edits = [m for m in DIG_EDIT.finditer(text)]
    rooms = []
    for m in ROOM_OF.finditer(text):
        v = [float(x) for x in m.groups()]
        lo, hi, host = v[0:3], v[3:6], v[6:9]
        edit = next((e.group(1) for e in edits if e.group(9) == "room-of"
                     and [float(e.group(k)) for k in range(3, 6)] == host), None)
        if edit is None:
            rooms.append((lo, hi, None, "no edit found for it"))
            continue
        mp = work / f"{tag}_room_{edit}.map"
        drive(exe, bsp, *words, "--apply", edit, "--out", str(mp))
        out = mp.with_suffix(".bsp")
        out.unlink(missing_ok=True)
        log = compile_map(mp)
        sealed = "leaked" not in log and out.is_file()
        rooms.append((lo, hi, cut_off(world_brushes(mp), lo, hi), "" if sealed else "leaked or no bsp"))
    tunnels = []
    for e in edits:
        if e.group(9) in ("room-of", "room-copy", "annex") or len(tunnels) >= 4:
            continue
        mp = work / f"{tag}_tunnel_{e.group(1)}.map"
        drive(exe, bsp, *words, "--apply", e.group(1), "--out", str(mp))
        flames = sum(1 for b in world_brushes(mp, True) if FLAME in b[2]) if mp.is_file() else -1
        # row 412: each of its flame brushes wears the flame as one of the base's does (the PO: «ты сломал фонарь»)
        new = [p for p in flame_prints(mp) if not any(same_print(p, q) for q in base_prints)] if mp.is_file() else []
        tunnels.append((e.group(1), e.group(9), flames - base_flames, len(new)))
    return {"pieces": pieces.groups() if pieces else None, "rooms": rooms, "tunnels": tunnels,
            "base_flames": base_flames}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    (a.work / "bin").mkdir(parents=True, exist_ok=True)
    g = run(build_driver(REPO, a.work / "bin"), a.work, "green")
    check(f"{BASE}: the plan finds the base's wall pieces, a lamp among them", bool(g["pieces"]) and int(g["pieces"][0]) >= 1,
          f"{g['pieces'][0]} lamps, {g['pieces'][1]} ornaments" if g["pieces"] else "no wall pieces line")
    check(f"{BASE}: rooms of {SECOND} dealt", len(g["rooms"]) >= 1, f"{len(g['rooms'])} rooms")
    for lo, hi, off, why in g["rooms"]:
        check(f"{BASE}: the room of {SECOND} at {lo} .. {hi} compiles sealed and nothing in it is cut off",
              off is not None and not why and not off,
              why or (f"{len(off)} cut off: " + "; ".join(f"{[round(x) for x in b[0]]} {sorted(b[2])}" for b in off[:3])
                      if off else "all joined to its faces"))
    hung = [t for t in g["tunnels"] if t[2] > 0]
    check(f"{BASE}: a tunnel hangs the base's wall lamps ({FLAME} more than the base's {g['base_flames']})",
          bool(hung), "; ".join(f"edit {t[0]} {t[1]}: {t[2]:+d}" for t in g["tunnels"]))
    check(f"{BASE}: every flame hung wears its texture as the base's flames do - no scraps of the picture",
          bool(hung) and all(t[3] == 0 for t in hung),
          "; ".join(f"edit {t[0]}: {t[3]} of {t[2]} flame brushes unlike any of the base's" for t in g["tunnels"]))
    if not a.no_red:
        before = hash_tree(REPO)
        box = Sandbox(REPO, "roomcuttex")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry.c"
            data = target.read_bytes()
            lock = b"static const bool g_texture_lock = true;"
            if check("RED: the texture lock is where the mutation says", data.count(lock) == 1):
                target.write_bytes(data.replace(lock, b"static const bool g_texture_lock = false;", 1))
                (a.work / "red_tex_bin").mkdir(parents=True, exist_ok=True)
                r = run(build_driver(box.root, a.work / "red_tex_bin"), a.work, "redtex")
                check("RED: with the texture left where the source had it, a hung flame wears scraps - the case above"
                      " goes red", any(t[3] > 0 for t in r["tunnels"]),
                      "; ".join(f"edit {t[0]}: {t[3]} unlike" for t in r["tunnels"]))
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    if not a.no_red:
        before = hash_tree(REPO)
        box = Sandbox(REPO, "roomcut")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            stand = b"const uint32_t fell = room_cut_stands(cut, cut_lo, cut_hi, keep);"
            hang = b"if (!plan || !plan->num_piece_kinds || !donor || !g_wall_decor)"
            if check("RED: what stands and what is hung are where the mutation says",
                     data.count(stand) == 1 and data.count(hang) == 1):
                target.write_bytes(data.replace(stand, b"const uint32_t fell = 0u;", 1)
                                       .replace(hang, b"if (true)", 1))
                (a.work / "red_bin").mkdir(parents=True, exist_ok=True)
                r = run(build_driver(box.root, a.work / "red_bin"), a.work, "red")
                off = sum(len(o) for _, _, o, _ in r["rooms"] if o)
                check("RED: with what does not stand let in, a room holds pieces cut off - the case above goes red",
                      off > 0, f"{off} cut off in {len(r['rooms'])} rooms")
                check("RED: with no wall piece hung, no tunnel wears one - the case above goes red",
                      not any(t[2] > 0 for t in r["tunnels"]), "; ".join(f"edit {t[0]}: {t[2]:+d}" for t in r["tunnels"]))
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    print(f"{TOTAL - FAILED}/{TOTAL} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
