"""What a DELIVERED map's moving parts look like, read out of the compiled file.

    python tools/check_mapgen_static.py [--digs DIGS.json] MAP.bsp [MAP.bsp ...]
    python tools/check_mapgen_static.py --red DIR     the controlled RED

`--digs` names the passages dug into each map - {"mg_20.bsp": [{"box": [x0, y0,
z0, x1, y1, z1], "from": [x, y, z], "to": [x, y, z]}, ...]} - which the file
itself cannot say; `tools/mapgen_round.py deliver` writes it from the ledgers.
An entry may carry "own_room_end": "to" when that end is the middle of the dig's
own room - an annex's (ledger row 334) - and no mouth is asked there.

No game is launched and nothing is drawn: every question here is a question about
the geometry the compiler wrote, asked with the file's own planes, faces and BSP
tree. It exists because the PO found, by looking, three defects that every guard
of 2026-09-11 had passed:

  «стёкла дрожат, рассыпаются на пиксели»  - a pane whose edge faces lay ON the
      reveal the window was cut with (coplanar brush-model and world faces, 768
      and 512 square units of them in the delivered mg_glass);
  «пропадают их части»                     - the middle pane of a row sitting in
      solid rock on both faces, because the grid put the wall back over it;
  a lift you have to JUMP onto             - every dig's lowered deck 21 units
      above the floor beside it (pmove climbs 18), and one hanging 149 units
      over the floor of the room its shaft had opened into.

So, per map:

  PANES   every brush model with a translucent face, and every translucent world
          face: eight thick; not one face coplanar with a world face over more
          than a square unit; AIR on both faces of the pane's middle, so there is
          something to look through; and a pane that moves (a `func_door`) inside
          the world's solid for its whole open position - in its housing, not in
          the air.
  LIFTS   every `func_plat`: its lowered deck within a step of the floor on at
          least one side of it, and rock (not a room) under it.
  SOUNDS  every glass `target_speaker` in air, where a positioned sound is heard.
  DIGS    every passage named in `--digs`: a MOUTH at each of its two ends - a
          patch of its box's faces with air on both sides of it, beside the spot
          and at a player's height over that spot's floor (or the hole in the
          floor for a hatch) - and no lamp texture drawn dark inside it.

The PO found the fourth, in 2026-09-12's test: «вырытый тоннель упирается в
непроходимое препятствие» - a tunnel open at the bottom and closed at the top by
32 units of wall, on four maps - and on its walls «оформление странное кругами»,
q2dm1's ceiling lamp `e2u3/ceil1_14` tiled over 80 faces with its light taken off.

The RED: `--red DIR` runs the same questions on the files that were delivered on
2026-09-11 11:41 and kept as evidence, and it must FAIL on each of the three
defects above; and on `round6/mg_tunnels_closed_top.bsp` (delivered 19:57, with
its `.digs.json`) it must find the closed top and the dark lamp. A guard that
passes on them is not a guard.
"""
from __future__ import annotations

import json
import math
import re
import struct
import sys
from collections import defaultdict, deque
from pathlib import Path

KV = re.compile(r'"([^"]*)"\s*"([^"]*)"')
SURF_TRANS = 0x30
CONTENTS_SOLID = 0x1
PANE_THICK = 8.0
STEP = 18.0

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


class Bsp:
    def __init__(self, path: Path):
        d = path.read_bytes()
        self.d = d
        ident, ver = struct.unpack_from("<4si", d, 0)
        if ident != b"IBSP" or ver != 38:
            raise ValueError(f"{path}: not a Quake II BSP")
        self.lumps = [struct.unpack_from("<ii", d, 8 + 8 * i) for i in range(19)]
        o, n = self.lumps[0]
        text = d[o:o + n].decode("latin1")
        self.ents = [dict(KV.findall(b)) for b in re.findall(r"\{([^}]*)\}", text)]
        self.planes = self._arr(1, "<ffffi", 20)
        self.verts = self._arr(2, "<fff", 12)
        self.nodes = self._arr(4, "<iii3h3hHH", 28)
        self.texinfo = []
        o, n = self.lumps[5]
        for i in range(n // 76):
            r = struct.unpack_from("<8fii32si", d, o + 76 * i)
            self.texinfo.append((r[8], r[10].split(b"\0")[0].decode("latin1")))
        self.faces = self._arr(6, "<HhihhBBBBi", 20)
        self.leafs = self._arr(8, "<ihh3h3hHHHH", 28)
        self.edges = self._arr(11, "<HH", 4)
        self.surfedges = [x[0] for x in self._arr(12, "<i", 4)]
        self.models = self._arr(13, "<3f3f3fiii", 48)

    def _arr(self, lump, fmt, size):
        o, n = self.lumps[lump]
        return [struct.unpack_from(fmt, self.d, o + size * i)
                for i in range(n // size)]

    def face_verts(self, fi):
        f = self.faces[fi]
        out = []
        for k in range(f[2], f[2] + f[3]):
            e = self.surfedges[k]
            out.append(self.verts[self.edges[abs(e)][0 if e >= 0 else 1]])
        return out

    def face_plane(self, fi):
        f = self.faces[fi]
        p = self.planes[f[0]]
        if f[1]:
            return (-p[0], -p[1], -p[2]), -p[3]
        return (p[0], p[1], p[2]), p[3]

    def face_flags(self, fi):
        return self.texinfo[self.faces[fi][4]][0]

    def model_faces(self, mi):
        m = self.models[mi]
        return range(m[10], m[10] + m[11])

    def model_box(self, mi):
        m = self.models[mi]
        return list(m[0:3]), list(m[3:6])

    def solid(self, p) -> bool:
        node = self.models[0][9]
        while node >= 0:
            n = self.nodes[node]
            pl = self.planes[n[0]]
            node = n[1] if (p[0] * pl[0] + p[1] * pl[1] + p[2] * pl[2]
                            - pl[3]) >= 0 else n[2]
        return bool(self.leafs[-(node + 1)][0] & CONTENTS_SOLID)

    def floor_below(self, x, y, z, reach=256.0):
        """The height of the first solid under (x, y, z); z itself when it is
        already solid, None when there is none within reach."""
        if self.solid((x, y, z)):
            return z
        step = 1.0
        h = z
        while h > z - reach:
            h -= step
            if self.solid((x, y, h)):
                return h + step
        return None


def _project(poly, normal):
    ax = max(range(3), key=lambda i: abs(normal[i]))
    u, v = [i for i in range(3) if i != ax]
    return [(p[u], p[v]) for p in poly]


def _area(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _clip(subject, clipper):
    out = subject
    for i in range(len(clipper)):
        a, b = clipper[i], clipper[(i + 1) % len(clipper)]
        inp, out = out, []
        if not inp:
            break

        def inside(p):
            return ((b[0] - a[0]) * (p[1] - a[1])
                    - (b[1] - a[1]) * (p[0] - a[0])) >= -1e-6

        def cross(p, q):
            den = ((a[0] - b[0]) * (p[1] - q[1]) - (a[1] - b[1]) * (p[0] - q[0]))
            if abs(den) < 1e-12:
                return q
            t = ((a[0] - p[0]) * (p[1] - q[1]) - (a[1] - p[1]) * (p[0] - q[0])) / den
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

        s = inp[-1]
        for e in inp:
            if inside(e):
                if not inside(s):
                    out.append(cross(s, e))
                out.append(e)
            elif inside(s):
                out.append(cross(s, e))
            s = e
    return out


def overlap(pa, pb, normal) -> float:
    a = _project(pa, normal)
    b = _project(pb, normal)
    if _area(a) < 0:
        a.reverse()
    if _area(b) < 0:
        b.reverse()
    r = _clip(a, b)
    return abs(_area(r)) if len(r) >= 3 else 0.0


def movedir(angle: str):
    a = int(float(angle or "0"))
    if a == -1:
        return (0.0, 0.0, 1.0)
    if a == -2:
        return (0.0, 0.0, -1.0)
    r = math.radians(a)
    return (round(math.cos(r), 6), round(math.sin(r), 6), 0.0)


def plane_key(normal, dist):
    return (round(abs(normal[0]), 3), round(abs(normal[1]), 3),
            round(abs(normal[2]), 3), round(abs(dist), 1))


MOUTH_CELL = 16.0
MOUTH_MIN_CELLS = 16          # 64 x 64: a player's width and more
# How far the way in may be from the spot the passage was laid from: an anchor
# (128), a cell (128) and the room the spot stands in - the same neighbourhood
# the transaction's dead-end gate walks (MAPGEN_TXN_WAY_REACH).
MOUTH_REACH = 384.0


def dig_mouths(b: Bsp, box) -> list:
    """The open patches of a passage box's six faces: 16-unit cells with no
    solid 8 inside the face and 8 outside it, clustered per face."""
    found = []
    for axis in range(3):
        u, v = (axis + 1) % 3, (axis + 2) % 3
        nu = max(1, int(round((box[3 + u] - box[u]) / MOUTH_CELL)))
        nv = max(1, int(round((box[3 + v] - box[v]) / MOUTH_CELL)))
        for side in (0, 1):
            face = box[3 + axis] if side else box[axis]
            sgn = 1.0 if side else -1.0
            cells = set()
            for iu in range(nu):
                for iv in range(nv):
                    p = [0.0, 0.0, 0.0]
                    p[u] = box[u] + (iu + 0.5) * MOUTH_CELL
                    p[v] = box[v] + (iv + 0.5) * MOUTH_CELL
                    p[axis] = face - sgn * 8.0
                    q = list(p)
                    q[axis] = face + sgn * 8.0
                    if not b.solid(p) and not b.solid(q):
                        cells.add((iu, iv))
            while cells:
                start = cells.pop()
                comp = {start}
                todo = deque([start])
                while todo:
                    a, c = todo.popleft()
                    for t in ((a + 1, c), (a - 1, c), (a, c + 1), (a, c - 1)):
                        if t in cells:
                            cells.remove(t)
                            comp.add(t)
                            todo.append(t)
                if len(comp) < MOUTH_MIN_CELLS:
                    continue
                lo = [0.0, 0.0, 0.0]
                hi = [0.0, 0.0, 0.0]
                lo[axis] = hi[axis] = face
                lo[u] = box[u] + min(c[0] for c in comp) * MOUTH_CELL
                hi[u] = box[u] + (max(c[0] for c in comp) + 1) * MOUTH_CELL
                lo[v] = box[v] + min(c[1] for c in comp) * MOUTH_CELL
                hi[v] = box[v] + (max(c[1] for c in comp) + 1) * MOUTH_CELL
                found.append({"axis": axis, "cells": len(comp), "lo": lo, "hi": hi})
    return found


def mouth_serves(m: dict, spot) -> bool:
    """Is this patch the way in for somebody standing at `spot` (a floor)?"""
    dx = max(m["lo"][0] - spot[0], 0.0, spot[0] - m["hi"][0])
    dy = max(m["lo"][1] - spot[1], 0.0, spot[1] - m["hi"][1])
    if math.hypot(dx, dy) > MOUTH_REACH:
        return False
    if m["axis"] == 2:                        # a hole in a floor: a hatch
        return abs(m["lo"][2] - spot[2]) <= 16.0
    return m["lo"][2] < spot[2] + 72.0 and m["hi"][2] > spot[2] + 8.0


def judge(path: Path, digs=None) -> dict:
    """Every finding for one map, as {question: [what failed]}."""
    b = Bsp(path)
    bad = defaultdict(list)
    counts = defaultdict(int)
    world_by_plane = defaultdict(list)
    for fi in b.model_faces(0):
        world_by_plane[plane_key(*b.face_plane(fi))].append(fi)

    by_model = {}
    for e in b.ents:
        if e.get("model", "").startswith("*"):
            by_model[int(e["model"][1:])] = e

    # ---- PANES that move or are owned by an entity ------------------------
    for mi, e in sorted(by_model.items()):
        faces = list(b.model_faces(mi))
        if not any(b.face_flags(f) & SURF_TRANS for f in faces):
            continue
        counts["panes"] += 1
        lo, hi = b.model_box(mi)
        size = [hi[a] - lo[a] for a in range(3)]
        thin = min(range(3), key=lambda a: size[a])
        tag = f"*{mi} {e.get('classname')} at {[round(v) for v in lo]}"
        if size[thin] > PANE_THICK + 0.5:
            bad["pane thickness"].append(f"{tag}: {size[thin]:.0f} thick")
        # z-fight: any face of the pane lying on a world face
        worst = 0.0
        for f in faces:
            n, dist = b.face_plane(f)
            pv = b.face_verts(f)
            for wf in world_by_plane.get(plane_key(n, dist), []):
                worst = max(worst, overlap(pv, b.face_verts(wf), n))
        if worst > 1.0:
            bad["pane coplanar with the world"].append(
                f"{tag}: {worst:.0f} square units of one face on a world face")
        # the hole: air on both faces of the middle
        mid = [(lo[a] + hi[a]) / 2 for a in range(3)]
        for off in (size[thin] / 2 + 2.0, 40.0):
            for sgn in (-1, 1):
                p = list(mid)
                p[thin] += sgn * off
                if b.solid(p):
                    bad["pane in rock"].append(
                        f"{tag}: solid {sgn * off:+.0f} off its middle")
        # a door opens into its housing, not into the air
        if e.get("classname") == "func_door":
            md = movedir(e.get("angle"))
            lip = float(e.get("lip", "8") or "8")
            travel = sum(abs(md[a]) * size[a] for a in range(3)) - lip
            elo = [lo[a] + md[a] * travel for a in range(3)]
            ehi = [hi[a] + md[a] * travel for a in range(3)]
            other = [a for a in range(3) if a != thin]
            seen = 0
            for fu in (0.15, 0.5, 0.85):
                for fv in (0.15, 0.5, 0.85):
                    p = [0.0, 0.0, 0.0]
                    p[thin] = (elo[thin] + ehi[thin]) / 2
                    p[other[0]] = elo[other[0]] + fu * (ehi[other[0]] - elo[other[0]])
                    p[other[1]] = elo[other[1]] + fv * (ehi[other[1]] - elo[other[1]])
                    if not b.solid(p):
                        seen += 1
            if seen:
                bad["open pane in the air"].append(
                    f"{tag}: {seen} of 9 samples of the open pane are in air")

    # ---- world windows: something to see through on both faces ------------
    for fi in b.model_faces(0):
        if not b.face_flags(fi) & SURF_TRANS:
            continue
        pv = b.face_verts(fi)
        n, _ = b.face_plane(fi)
        if abs(_area(_project(pv, n))) < 32 * 32:
            continue                          # an edge of the pane, not a face
        counts["world glass faces"] += 1
        c = [sum(p[a] for p in pv) / len(pv) for a in range(3)]
        p = [c[a] + n[a] * 2.0 for a in range(3)]
        if b.solid(p):
            bad["world window against rock"].append(
                f"face {fi} at {[round(v) for v in c]}: rock right behind it")

    # ---- LIFTS -------------------------------------------------------------
    for mi, e in sorted(by_model.items()):
        if e.get("classname") != "func_plat":
            continue
        counts["lifts"] += 1
        lo, hi = b.model_box(mi)
        h = float(e.get("height", "0") or "0")
        lip = float(e.get("lip", "8") or "8")
        travel = h if h else (hi[2] - lo[2]) - lip
        low_top = hi[2] - travel
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        tag = f"*{mi} func_plat, deck lowered to {low_top:.0f}"
        entries = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            px = cx + dx * ((hi[0] - lo[0]) / 2 + 24.0)
            py = cy + dy * ((hi[1] - lo[1]) / 2 + 24.0)
            f = b.floor_below(px, py, low_top + 40.0, 300.0)
            entries.append(f)
        if not any(f is not None and abs(f - low_top) <= STEP for f in entries):
            bad["lift you cannot step onto"].append(
                f"{tag}; the floor beside it is at "
                + ", ".join("none" if f is None else f"{f:.0f}" for f in entries))
        #
        # «A lift hanging over a room» is NOT asked any more. It was: the floor
        # straight under the lowered deck within 24. MEASURED on the sweep of
        # 2026-09-11 18:40, it refused q2dm1's accepted stairs-to-lift at 1280
        # 1408 in all five maps - a short lift from the landing at 832 whose
        # shaft stands open over the room at 768, which is how a lift in an
        # open shaft looks. The defect it was written for (the 11:41 mg_tunnels
        # `*5`, lowered to 660 over 511) is also a lift nobody can step onto,
        # and the question above refuses that one.
        #
        # And the deck's own top eight units, at its lowered stop, are AIR.
        #
        # A deck sunk into the floor is a machine whose body sweeps through the
        # world, and the transaction's clearance gate
        # (`MapGenMovers_MeasureClearance`, held to the donor's worst) refuses
        # it as REJECTED_BLOCKED_MACHINE. MEASURED 2026-09-11 16:00: every dig
        # with a lift was refused that way in the fidelity runs once the decks
        # were lowered flush with the floor.
        #
        seen = sunk = 0
        x = lo[0] + 6.0
        while x < hi[0] - 4.0:
            y = lo[1] + 6.0
            while y < hi[1] - 4.0:
                for z in (low_top - 6.0, low_top - 2.0):
                    seen += 1
                    if b.solid((x, y, z)):
                        sunk += 1
                y += 16.0
            x += 16.0
        if sunk:
            bad["lift deck sunk into the floor"].append(
                f"{tag}: {sunk} of {seen} samples of its lowered deck in rock")

    # ---- SOUNDS ------------------------------------------------------------
    for e in b.ents:
        if e.get("classname") != "target_speaker" or "brkglas" not in e.get("noise", ""):
            continue
        counts["glass speakers"] += 1
        org = [float(v) for v in e.get("origin", "0 0 0").split()]
        if b.solid(org):
            bad["speaker in rock"].append(f"{e.get('targetname')} at {e.get('origin')}")

    # ---- DIGS: open at both ends, and no lamp worn dark ---------------------
    lit = {name for flags, name in b.texinfo if flags & 0x1 and not flags & 0x4}
    for dig in digs or []:
        box = [float(v) for v in dig["box"]]
        counts["digs"] += 1
        tag = (f"dig {box[0]:.0f} {box[1]:.0f} {box[2]:.0f} .. {box[3]:.0f}"
               f" {box[4]:.0f} {box[5]:.0f}")
        mouths = dig_mouths(b, box)
        ends = [(k, dig[k]) for k in ("from", "to") if dig.get(k)]
        if ends:
            for which, spot in ends:
                # row 334: an annex's far end is the middle of its own room - in a
                # room of 768 384 or more from its doorway - and has no mouth
                if dig.get("own_room_end") == which:
                    continue
                spot = [float(v) for v in spot]
                if not any(mouth_serves(m, spot) for m in mouths):
                    bad["dig closed at an end"].append(
                        f"{tag}: no way in beside its {'upper' if which == 'from' else 'lower'}"
                        f" end {spot[0]:.0f} {spot[1]:.0f} {spot[2]:.0f}"
                        f" ({len(mouths)} open patch(es) elsewhere)")
        elif len(mouths) < 2:
            bad["dig closed at an end"].append(
                f"{tag}: {len(mouths)} open patch(es) on its faces")
        dark = 0
        names = set()
        for fi in b.model_faces(0):
            flags, name = b.texinfo[b.faces[fi][4]]
            # SURF_SKY (0x4) is drawn with and without SURF_LIGHT in the same
            # map - q2dm1 has both - and a passage's bounding box takes in the
            # courtyard's sky. It is not a lamp anybody tiled on a wall.
            if flags & 0x5 or name not in lit:
                continue
            pv = b.face_verts(fi)
            c = [sum(p[a] for p in pv) / len(pv) for a in range(3)]
            if all(box[a] - 8.0 <= c[a] <= box[3 + a] + 8.0 for a in range(3)):
                dark += 1
                names.add(name)
        if dark:
            bad["dig wears a lamp"].append(
                f"{tag}: {dark} face(s) of {', '.join(sorted(names))} - a texture"
                f" this map draws as a light - drawn dark")
    return {"bad": bad, "counts": counts}


QUESTIONS = ("pane thickness", "pane coplanar with the world", "pane in rock",
             "open pane in the air", "world window against rock",
             "lift you cannot step onto", "lift deck sunk into the floor",
             "speaker in rock", "dig closed at an end", "dig wears a lamp")


def run(paths: list[Path], digs: dict) -> None:
    for p in paths:
        r = judge(p, digs.get(p.name))
        c = r["counts"]
        print(f"== {p.name}: {c['panes']} moving/owned panes,"
              f" {c['world glass faces']} world glass faces, {c['lifts']} lifts,"
              f" {c['glass speakers']} glass speakers, {c['digs']} digs")
        for q in QUESTIONS:
            got = r["bad"].get(q, [])
            check(f"{p.name}: {q} - none", not got, "; ".join(got[:3]))


def red(folder: Path) -> None:
    """The files delivered 2026-09-11 11:41, kept for exactly this: the guard has
    to find each defect the PO found in them."""
    want = {
        "mg_glass.bsp": ("pane coplanar with the world", "pane in rock"),
        "mg_tunnels.bsp": ("lift you cannot step onto",),
        # the trial of 2026-09-11 15:50, decks lowered flush into the floor
        "tunnels_flush_decks.bsp": ("lift deck sunk into the floor",),
    }
    # the delivery of 2026-09-11 19:57, kept with the passages it was dug with
    want["round6/mg_tunnels_closed_top.bsp"] = ("dig closed at an end",
                                               "dig wears a lamp")
    for name, questions in want.items():
        path = folder / name
        if not check(f"RED evidence {name} is there", path.is_file(), str(path)):
            continue
        sidecar = path.with_suffix(".digs.json")
        digs = (json.loads(sidecar.read_text(encoding="utf-8"))
                if sidecar.is_file() else None)
        r = judge(path, digs)
        for q in questions:
            got = r["bad"].get(q, [])
            check(f"RED {name}: the guard finds «{q}»", bool(got),
                  "; ".join(got[:2]) if got else "it passed a file the PO rejected")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    digs = {}
    if len(args) >= 2 and args[0] == "--digs":
        digs = json.loads(Path(args[1]).read_text(encoding="utf-8"))
        args = args[2:]
    if args[0] == "--red":
        red(Path(args[1]))
    else:
        run([Path(a) for a in args], digs)
    print(f"\n{CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
