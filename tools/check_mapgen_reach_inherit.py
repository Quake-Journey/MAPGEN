"""Brief 16 D5 guard: a walk taken from the parent's walk where the edit could not reach is the walk of the whole map.

The PO, 10.10 (mg_10_6695, 2 h 42 min): «чему тогда там было работать 2 часа 42 минуты???» - 97 % of the run was the
reachability walk, taken whole after every compile. The walk now takes every place the edit could not have touched
from the parent's walk. This guard makes edits of the kinds the generator makes - a block on a floor, a brush taken
away, a step raised - to a map of the PO's, compiles each pair (`q2tool -bsp`, collision only), and has
`mapgen_reach_inherit_probe` walk the child from the parent and whole. Every pair must give the judge the same numbers
(component, traps, pickups, landmarks, starts, machines); the graph itself is reported, and the speed-up.

RED: `--red` makes the probe's inherited walk ignore the changed brushes (MAPGEN_INHERIT_RED=1): the block that cuts a
corridor must then come out different.

    python tools/check_mapgen_reach_inherit.py --map MAP --out DIR [--q2tool EXE] [--workers N] [--probe EXE]
"""
import argparse
import os
import re
import subprocess
import sys

FACE = re.compile(r"^\(\s*(\S+)\s+(\S+)\s+(\S+)\s*\)\s*\(\s*(\S+)\s+(\S+)\s+(\S+)\s*\)\s*\(\s*(\S+)\s+(\S+)\s+(\S+)\s*\)\s+(\S+)(.*)$")
NO_WINDOW = 0x08000000


def read_entities(text):
    """The .map as a list of entities, each (lines before the brushes, [brush lines])."""
    ents, depth, cur, brush = [], 0, None, None
    for line in text.splitlines():
        s = line.strip()
        if s == "{":
            depth += 1
            if depth == 1:
                cur = {"keys": [], "brushes": []}
            else:
                brush = []
            continue
        if s == "}":
            if depth == 2:
                cur["brushes"].append(brush)
                brush = None
            else:
                ents.append(cur)
                cur = None
            depth -= 1
            continue
        if depth == 1 and cur is not None:
            cur["keys"].append(line)
        elif depth == 2 and brush is not None:
            brush.append(line)
    return ents


def write_entities(ents, header):
    out = [header]
    for e in ents:
        out.append("{")
        out.extend(e["keys"])
        for b in e["brushes"]:
            out.append("{")
            out.extend(b)
            out.append("}")
        out.append("}")
    return "\n".join(out) + "\n"


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def brush_box(brush):
    """The box of the brush's corners: every three of its planes meet at a point, and the points inside all of them
    are its corners (the face points of a .map lie on its planes, not at its corners)."""
    planes = []
    for f in brush:
        m = FACE.match(f.strip())
        if not m:
            return None
        v = [float(x) for x in m.groups()[:9]]
        p0, p1, p2 = v[0:3], v[3:6], v[6:9]
        n = _cross(_sub(p0, p1), _sub(p2, p1))
        ln = _dot(n, n) ** 0.5
        if ln < 1e-9:
            return None
        n = [x / ln for x in n]
        planes.append((n, _dot(n, p1)))
    for sign in (1.0, -1.0):
        corners = []
        for i in range(len(planes)):
            for j in range(i + 1, len(planes)):
                for k in range(j + 1, len(planes)):
                    (a, da), (b, db), (c, dc) = planes[i], planes[j], planes[k]
                    bc = _cross(b, c)
                    det = _dot(a, bc)
                    if abs(det) < 1e-9:
                        continue
                    ca, ab = _cross(c, a), _cross(a, b)
                    x = [(da * bc[q] + db * ca[q] + dc * ab[q]) / det for q in range(3)]
                    if all(sign * (_dot(n, x) - d) <= 0.01 for n, d in planes):
                        corners.append(x)
        if corners:
            return ([min(p[q] for p in corners) for q in range(3)], [max(p[q] for p in corners) for q in range(3)])
    return None


def texture(brush):
    m = FACE.match(brush[0].strip())
    return m.group(10).lower() if m else ""


def shifted(brush, d):
    out = []
    for f in brush:
        m = FACE.match(f.strip())
        v = [float(x) for x in m.groups()[:9]]
        for i in range(9):
            v[i] += d[i % 3]
        pts = " ".join("( %g %g %g )" % (v[i], v[i + 1], v[i + 2]) for i in (0, 3, 6))
        out.append("%s %s%s" % (pts, m.group(10), m.group(11)))
    return out


def key(ent, name):
    for line in ent["keys"]:
        m = re.match(r'\s*"([^"]+)"\s+"([^"]*)"', line)
        if m and m.group(1) == name:
            return m.group(2)
    return None


def solid_small(brush):
    box = brush_box(brush)
    if not box or any(t in texture(brush) for t in ("sky", "clip", "trigger", "water", "lava", "slime", "hint", "skip")):
        return None
    size = [box[1][a] - box[0][a] for a in range(3)]
    return box if all(8 <= s <= 96 for s in size) else None


def variants(ents):
    """Edits of the generator's kinds, each a (name, entities) pair."""
    world = ents[0]
    spawns = [e for e in ents if key(e, "classname") == "info_player_deathmatch" and key(e, "origin")]
    small = [(i, b) for i, b in enumerate(world["brushes"]) if solid_small(b)]
    out = []
    # a block on the floor beside a start, a stride away (a block family edit)
    if spawns and small:
        sx, sy, sz = (float(x) for x in key(spawns[0], "origin").split())
        lo, hi = solid_small(small[0][1])
        d = [sx + 80 - (lo[0] + hi[0]) / 2, sy - (lo[1] + hi[1]) / 2, sz - 24 - lo[2]]
        e2 = [dict(e, brushes=list(e["brushes"])) for e in ents]
        e2[0]["brushes"].append(shifted(small[0][1], d))
        out.append(("block-by-start", e2))
    # a small brush taken away (what destruction and remodels do)
    if len(small) > 3:
        i = small[len(small) // 2][0]
        e2 = [dict(e, brushes=list(e["brushes"])) for e in ents]
        del e2[0]["brushes"][i]
        out.append(("brush-removed", e2))
    # a block in the middle of the second start's room
    if len(spawns) > 1 and small:
        sx, sy, sz = (float(x) for x in key(spawns[1], "origin").split())
        lo, hi = solid_small(small[0][1])
        d = [sx - 96 - (lo[0] + hi[0]) / 2, sy + 64 - (lo[1] + hi[1]) / 2, sz - 24 - lo[2]]
        e2 = [dict(e, brushes=list(e["brushes"])) for e in ents]
        e2[0]["brushes"].append(shifted(small[0][1], d))
        out.append(("block-second-room", e2))
    return out


def compile_bsp(q2tool, moddir, path):
    cmd = [q2tool, "-bsp", "-threads", "1", "-moddir", moddir, "-basedir", moddir, "-gamedir", moddir, path]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    bsp = path[:-4] + ".bsp"
    if r.returncode or not os.path.exists(bsp):
        sys.stderr.write(r.stdout[-2000:] + r.stderr[-2000:])
        raise SystemExit("compile failed: %s" % path)
    return bsp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--q2tool", default=r"O:\Claude2\MapgenStudio\engine\q2tool.exe")
    ap.add_argument("--moddir", default=r"O:\Claude2\q2pro-release\baseq2")
    ap.add_argument("--probe", required=True)
    ap.add_argument("--workers", default="8")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    text = open(a.map, encoding="utf-8", errors="replace").read()
    header = "\n".join(l for l in text.splitlines()[:5] if l.startswith("//"))
    ents = read_entities(text)
    parent_map = os.path.join(a.out, "parent.map")
    open(parent_map, "w", encoding="utf-8").write(write_entities(ents, header))
    parent = compile_bsp(a.q2tool, a.moddir, parent_map)
    bad = 0
    for name, e2 in variants(ents):
        if a.only and name != a.only:
            continue
        child_map = os.path.join(a.out, name + ".map")
        open(child_map, "w", encoding="utf-8").write(write_entities(e2, header))
        child = compile_bsp(a.q2tool, a.moddir, child_map)
        r = subprocess.run([a.probe, parent, child, a.workers], capture_output=True, text=True,
                           creationflags=NO_WINDOW)
        print("== %s (exit %d)" % (name, r.returncode))
        print(r.stdout.strip())
        if r.returncode >= 2:
            bad += 1
    print("FAIL" if bad else "PASS")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
