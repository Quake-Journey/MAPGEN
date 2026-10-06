r"""How a lit map's light compares with its donor's, face by face (row 405, Fable's brief 5 section 7).

    python tools/mapgen_light_ratio.py CANDIDATE.bsp DONOR.bsp [--digs DIGS.json]

The mean of a lighting lump hides a black room under a bright courtyard, so this reads every drawn face (not sky,
warp or nodraw): its lightmap's extents from its texinfo axes (16 units a luxel, as the engine allocates them), the
luxels at its `lightofs`, their mean and their maximum. Faces the two maps share - the same texture and the same box
to the unit - give the ratio of the candidate's mean to the donor's per orientation (floors: normal z > 0.7,
ceilings: < -0.7, sides: the rest), each weighted by its luxels. With --digs (the delivery gates' digs.json for
this map) every accepted dig's box: its faces' mean and their dark share (max < 8).

Prints one line per orientation, `ratio floors 0.75 (n faces)`, the candidate's dark share against the donor's,
and one line per dig box.
"""
from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

SKY, WARP, NODRAW = 0x4, 0x8, 0x80


def lump(d: bytes, i: int) -> tuple[int, int]:
    return struct.unpack_from("<ii", d, 8 + 8 * i)


def faces(path: Path) -> list[dict]:
    d = path.read_bytes()
    po, pn = lump(d, 1)
    planes = [struct.unpack_from("<4f", d, po + i * 20) for i in range(pn // 20)]
    vo, vn = lump(d, 2)
    verts = [struct.unpack_from("<3f", d, vo + i * 12) for i in range(vn // 12)]
    eo, en = lump(d, 11)
    edges = [struct.unpack_from("<2H", d, eo + i * 4) for i in range(en // 4)]
    so, sn = lump(d, 12)
    surfedges = struct.unpack_from(f"<{sn // 4}i", d, so)
    to, tn = lump(d, 5)
    texinfo = []
    for i in range(tn // 76):
        vecs = struct.unpack_from("<8f", d, to + i * 76)
        flags, value = struct.unpack_from("<ii", d, to + i * 76 + 32)
        name = d[to + i * 76 + 40:to + i * 76 + 72].split(b"\0")[0].decode("latin-1")
        texinfo.append((vecs, flags, name))
    lo, ln = lump(d, 7)
    light = d[lo:lo + ln]
    fo, fn = lump(d, 6)
    out = []
    for i in range(fn // 20):
        planenum, side, fe, ne, ti, s0, s1, s2, s3, lofs = struct.unpack_from("<HhiHh4Bi", d, fo + i * 20)
        vecs, flags, name = texinfo[ti]
        if flags & (SKY | WARP | NODRAW) or lofs < 0 or s0 == 255:
            continue
        pts = []
        for k in range(ne):
            e = surfedges[fe + k]
            pts.append(verts[edges[e][0]] if e >= 0 else verts[edges[-e][1]])
        if len(pts) < 3:
            continue
        smin = [min(p[0] * vecs[a * 4] + p[1] * vecs[a * 4 + 1] + p[2] * vecs[a * 4 + 2] + vecs[a * 4 + 3]
                    for p in pts) for a in range(2)]
        smax = [max(p[0] * vecs[a * 4] + p[1] * vecs[a * 4 + 1] + p[2] * vecs[a * 4 + 2] + vecs[a * 4 + 3]
                    for p in pts) for a in range(2)]
        w = int(math.ceil(smax[0] / 16) - math.floor(smin[0] / 16)) + 1
        h = int(math.ceil(smax[1] / 16) - math.floor(smin[1] / 16)) + 1
        n = w * h * 3
        if w <= 0 or h <= 0 or lofs + n > len(light):
            continue
        lux = light[lofs:lofs + n]
        nz = planes[planenum][2] * (-1 if side else 1)
        box = tuple(round(min(p[a] for p in pts)) for a in range(3)) + \
            tuple(round(max(p[a] for p in pts)) for a in range(3))
        out.append({"name": name, "box": box, "mean": sum(lux) / n, "max": max(lux), "lux": n // 3,
                    "kind": "floors" if nz > 0.7 else "ceilings" if nz < -0.7 else "sides"})
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cand, donor = faces(Path(sys.argv[1])), faces(Path(sys.argv[2]))
    digs = []
    if "--digs" in sys.argv:
        raw = json.loads(Path(sys.argv[sys.argv.index("--digs") + 1]).read_text(encoding="utf-8"))
        digs = next(iter(raw.values())) if isinstance(raw, dict) else raw
    theirs = {(f["name"], f["box"]): f for f in donor}
    for kind in ("sides", "floors", "ceilings"):
        num = den = 0.0
        count = 0
        for f in cand:
            g = theirs.get((f["name"], f["box"]))
            if f["kind"] != kind or not g:
                continue
            num += f["mean"] * f["lux"]
            den += g["mean"] * f["lux"]
            count += 1
        print(f"ratio {kind} {num / den if den else 0.0:.2f} ({count} faces)")
    for label, fs in (("candidate", cand), ("donor", donor)):
        dark = sum(1 for f in fs if f["max"] < 8)
        print(f"dark {label} {100.0 * dark / max(1, len(fs)):.1f} % of {len(fs)} faces, mean "
              f"{sum(f['mean'] * f['lux'] for f in fs) / max(1, sum(f['lux'] for f in fs)):.1f}")
    for i, dig in enumerate(digs):
        segs = dig.get("segs") or dig.get("boxes") or []
        boxes = [s if isinstance(s, list) and len(s) == 6 else s.get("lo", []) + s.get("hi", []) for s in segs]
        inside = [f for f in cand if any(all(b[a] - 1 <= f["box"][a] and f["box"][a + 3] <= b[a + 3] + 1
                                             for a in range(3)) for b in boxes if len(b) == 6)]
        if inside:
            mean = sum(f["mean"] * f["lux"] for f in inside) / max(1, sum(f["lux"] for f in inside))
            dark = sum(1 for f in inside if f["max"] < 8)
            print(f"dig {i} {dig.get('shape', '')}: {len(inside)} faces, mean {mean:.1f}, dark {100.0 * dark / len(inside):.1f} %")
    return 0


if __name__ == "__main__":
    sys.exit(main())
