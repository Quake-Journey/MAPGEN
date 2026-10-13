"""Debris standing on nothing (the PO 08.10, quake231: «куски архитектуры с верху висят в воздухе под небом»).

    python tools/mapgen_floating_debris_probe.py <map.map>

Reads a finished map's source only - it builds and compiles nothing. Every detail brush of the world is one piece
the destroy pass laid (a chunk, a slab, a crater's rim). Under each, the middle of its foot is looked at: rock - a
world brush that is no detail, no sky, no hint (the map's own detail counts as rock) - within 8 below it holds it up; a piece lying only on other pieces is held when one of those is. What nothing holds is printed with how far
below its middle the rock is and whether that rock is the sky.
"""
import itertools
import re
import sys
from collections import defaultdict

import numpy as np

DETAIL = 0x08000000
SKY = 0x4
LIQUID = 0x8 | 0x10 | 0x20
PLANE = re.compile(r"\(\s*([-\d.e]+) ([-\d.e]+) ([-\d.e]+)\s*\)\s*\(\s*([-\d.e]+) ([-\d.e]+) ([-\d.e]+)\s*\)\s*"
                   r"\(\s*([-\d.e]+) ([-\d.e]+) ([-\d.e]+)\s*\)\s*(\S+)\s*\[[^\]]*\]\s*\[[^\]]*\]\s*"
                   r"([-\d.e]+) ([-\d.e]+) ([-\d.e]+)(?: (-?\d+) (-?\d+) (-?\d+))?")
CELL = 128.0


def world_brushes(text):
    """The first entity's brushes: (normals, dists, contents, flags-or, textures)."""
    depth, brushes, cur = 0, [], None
    for line in text.splitlines():
        s = line.strip()
        if s == "{":
            depth += 1
            if depth == 2:
                cur = []
            continue
        if s == "}":
            if depth == 2 and cur:
                brushes.append(cur)
            depth -= 1
            if depth == 0 and brushes:
                return brushes
            continue
        if depth == 2:
            m = PLANE.match(s)
            if m:
                cur.append(m)
    return brushes


def build(planes):
    n, d, contents, flags, tex = [], [], 0, 0, []
    for m in planes:
        p = np.array([float(x) for x in m.groups()[:9]]).reshape(3, 3)
        nn = np.cross(p[0] - p[1], p[2] - p[1])
        ln = np.linalg.norm(nn)
        if ln < 1e-9:
            continue
        nn /= ln
        n.append(nn)
        d.append(float(nn @ p[1]))
        if m.group(14) is not None:
            contents |= int(m.group(14))
            flags |= int(m.group(15))
        tex.append(m.group(10).lower())
    n, d = np.array(n), np.array(d)
    verts = []
    for i, j, k in itertools.combinations(range(len(n)), 3):
        a = np.array([n[i], n[j], n[k]])
        if abs(np.linalg.det(a)) < 1e-6:
            continue
        v = np.linalg.solve(a, np.array([d[i], d[j], d[k]]))
        if np.all(n @ v - d <= 0.05):
            verts.append(v)
    if len(verts) < 4:
        return None
    verts = np.array(verts)
    return dict(n=n, d=d, contents=contents, flags=flags, tex=tex, v=verts, lo=verts.min(0), hi=verts.max(0))


def main():
    text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    raw = world_brushes(text)
    bs = [b for b in (build(p) for p in raw) if b]
    grid = defaultdict(list)
    for i, b in enumerate(bs):
        hint = all(t.endswith("hint") or t.endswith("skip") for t in b["tex"])
        # a piece of debris: detail, one skin on every side (a chunk and a slab are built so), and tilted or turned
        # somewhere - a carve's leftover of the map's own detail keeps its axial sides and its several textures
        b["piece"] = bool(b["contents"] & DETAIL) and len(set(b["tex"])) == 1 and "clip" not in b["tex"][0] and             any(abs(abs(x).max() - 1.0) > 1e-3 for x in b["n"])
        b["detail"] = bool(b["contents"] & DETAIL)
        b["sky"] = bool(b["flags"] & SKY)
        b["rock"] = not b["detail"] and not hint and not (b["contents"] & LIQUID) and \
            (b["contents"] == 0 or b["contents"] & 1)
        for gx in range(int(b["lo"][0] // CELL), int(b["hi"][0] // CELL) + 1):
            for gy in range(int(b["lo"][1] // CELL), int(b["hi"][1] // CELL) + 1):
                grid[(gx, gy)].append(i)

    def at(p, self):
        """0 air, 1 rock, 2 sky, (3, j) a piece"""
        found = 0
        for j in grid.get((int(p[0] // CELL), int(p[1] // CELL)), ()):
            if j == self:
                continue
            b = bs[j]
            if not (b["rock"] or b["detail"]):
                continue
            if np.any(p < b["lo"] - 0.5) or np.any(p > b["hi"] + 0.5) or np.any(b["n"] @ p - b["d"] > 0.5):
                continue
            if b["detail"] and not b["piece"]:
                return 1                    # the map's own detail holds a stone as well as rock does
            if b["piece"]:
                found = found or (3, j)
            else:
                return 2 if b["sky"] else 1
        return found

    held, on = {}, {}
    pieces = [i for i, b in enumerate(bs) if b["piece"]]
    for i in pieces:
        b = bs[i]
        mid = b["v"].mean(0)
        low = b["v"][b["v"][:, 2] <= b["lo"][2] + 1.0]
        # the middle of its foot: a corner over a wall's edge holds no stone whose middle is over the sky (13 on
        # mg_10_6669 had a corner on rock and their middles on a sky brush's top)
        probes = [low.mean(0)]
        state = 0
        for v in probes:
            h = mid[:2] - v[:2]
            ln = np.linalg.norm(h)
            q = v.copy()
            if ln > 1e-6:
                q[:2] += h / ln * min(2.0, ln)
            for dz in (1.0, 3.0, 5.0, 8.0):
                w = at(np.array([q[0], q[1], q[2] - dz]), i)
                if w == 1:
                    state = 1
                    break
                if w == 2:
                    state = 2           # the first thing under it is a sky's top: the rock under a thin sky lid
                    break               # holds it no more than the sky does
                if isinstance(w, tuple):
                    on.setdefault(i, w[1])
            if state == 1:
                break
        held[i] = state
    for _ in range(8):
        for i in pieces:
            if held[i] != 1 and i in on and held.get(on[i]) == 1:
                held[i] = 1
    lost = [i for i in pieces if held[i] != 1]
    for i in lost:
        b = bs[i]
        c = b["v"].mean(0)
        drop, kind = None, "nothing"
        for dz in range(0, 2048, 4):
            w = at(np.array([c[0], c[1], b["lo"][2] - dz]), i)
            if w in (1, 2):
                drop, kind = dz, "sky" if w == 2 else "rock"
                break
        print(f"floating {i}: {len(b['n'])} sides at {c[0]:.0f} {c[1]:.0f} {b['lo'][2]:.0f} "
              f"size {b['hi'][0]-b['lo'][0]:.0f} {b['hi'][1]-b['lo'][1]:.0f} {b['hi'][2]-b['lo'][2]:.0f}; "
              f"{'on the sky; ' if held[i] == 2 else ''}{kind} {drop if drop is not None else '-'} below; "
              f"{bs[i]['tex'][0]}")
    print(f"pieces {len(pieces)}, held {len(pieces) - len(lost)}, on nothing "
          f"{sum(1 for i in lost if held[i] == 0)}, on the sky {sum(1 for i in lost if held[i] == 2)}")
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
