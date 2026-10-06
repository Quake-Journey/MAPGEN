"""How a map's liquid SHORE is shaped, and where its water meets air.

Two reports per map:

  shore  - the OUTLINE of the liquid's upward surface faces: boundary edges (used
           by one surface face only) classified as axis-aligned or diagonal, with
           their lengths. That is the shape the PO photographs - a staircase is
           all axis edges, q2dm1's own pool is not. (The first version counted
           VERTICAL liquid faces instead and found none on q2dm1 or mg_water: the
           compiler draws no liquid face against solid, so a sound pool has none.)
  air    - every vertical liquid face, and the contents three units outside it.
           Air there is water standing in the air: the gate's question, with the
           coordinates it does not print.

    python probe_shore.py <map.bsp> [<map.bsp> ...]
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bsp_reader import Bsp  # noqa: E402

LIQUID = ("bluwter", "sewer1", "tlava1_3", "water", "slime", "lava")


def lump(data, i):
    off, size = struct.unpack_from("<ii", data, 8 + 8 * i)
    return data[off:off + size]


def report(path, box=None):
    data = path.read_bytes()
    planes, verts = lump(data, 1), lump(data, 2)
    texinfo, faces = lump(data, 5), lump(data, 6)
    edges, surfedges = lump(data, 11), lump(data, 12)
    names = [texinfo[76 * i + 40:76 * i + 72].split(b"\0")[0].decode("latin1")
             for i in range(len(texinfo) // 76)]
    bsp = Bsp(path)

    def vert(i):
        return struct.unpack_from("<3f", verts, 12 * i)

    def face_verts(first, count):
        out = []
        for k in range(count):
            se, = struct.unpack_from("<i", surfedges, 4 * (first + k))
            a, b = struct.unpack_from("<2H", edges, 4 * abs(se))
            out.append(a if se >= 0 else b)
        return out

    edge_use = {}
    surface_faces = 0
    vertical = []
    for f in range(len(faces) // 20):
        planenum, side, first, count, ti, _s, _l = struct.unpack_from(
            "<Hhihh4si", faces, 20 * f)
        if not (0 <= ti < len(names)):
            continue
        base = names[ti].split("/")[-1].lower()
        if not base.startswith(LIQUID):
            continue
        nx, ny, nz, _d = struct.unpack_from("<4f", planes, 20 * planenum)
        if side:
            nx, ny, nz = -nx, -ny, -nz
        idx = face_verts(first, count)
        if nz > 0.7:
            surface_faces += 1
            for k in range(len(idx)):
                key = tuple(sorted((idx[k], idx[(k + 1) % len(idx)])))
                edge_use[key] = edge_use.get(key, 0) + 1
        elif abs(nz) < 0.3:
            pts = [vert(i) for i in idx]
            c = [sum(p[a] for p in pts) / len(pts) for a in range(3)]
            outside = bsp.contents(c[0] + 3 * nx, c[1] + 3 * ny, c[2] + 3 * nz)
            diag = max(abs(nx), abs(ny)) <= 0.99
            vertical.append((c, nx, ny, outside, diag, base))

    axis_n = diag_n = 0
    axis_len = diag_len = 0.0
    dirs = {}
    for (a, b), used in edge_use.items():
        if used != 1:
            continue
        pa, pb = vert(a), vert(b)
        # only the shore of the flood asked about: the donor's own pool shares
        # the map, and counted with ours it made the staircase look 39 per cent
        # diagonal when every diagonal edge in it was q2dm1's
        if box:
            mx, my = 0.5 * (pa[0] + pb[0]), 0.5 * (pa[1] + pb[1])
            if not (box[0] <= mx <= box[2] and box[1] <= my <= box[3]):
                continue
        dx, dy = pb[0] - pa[0], pb[1] - pa[1]
        length = math.hypot(dx, dy)
        if length < 0.5:
            continue
        if abs(dx) < 0.02 * length or abs(dy) < 0.02 * length:
            axis_n += 1
            axis_len += length
        else:
            diag_n += 1
            diag_len += length
            ang = round(math.degrees(math.atan2(dy, dx))) % 180
            dirs[ang] = dirs.get(ang, 0) + 1

    print(f"=== {path.parent.name}/{path.name} ===")
    total = axis_len + diag_len
    share = 100.0 * diag_len / total if total else 0.0
    print(f"  shore: {surface_faces} surface faces; outline {axis_n} axis edges"
          f" ({axis_len:.0f} u) and {diag_n} diagonal ({diag_len:.0f} u),"
          f" {share:.0f} per cent of its length diagonal")
    if dirs:
        print("    diagonal directions: " + ", ".join(
            f"{a} deg x{n}" for a, n in sorted(dirs.items())))
    air = [v for v in vertical if v[3] == 0]
    print(f"  air: {len(vertical)} vertical liquid faces, {len(air)} with AIR"
          f" outside")
    for c, nx, ny, _o, diag, base in air[:12]:
        kind = "DIAGONAL" if diag else "axis"
        print(f"    {c[0]:7.1f} {c[1]:7.1f} {c[2]:6.1f}  normal {nx:+.2f}"
              f" {ny:+.2f}  {kind}  {base}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    args = sys.argv[1:]
    box = None
    if "--box" in args:
        i = args.index("--box")
        box = [float(v) for v in args[i + 1:i + 5]]
        del args[i:i + 5]
        print(f"(shore counted inside {box[0]:.0f} {box[1]:.0f} .."
              f" {box[2]:.0f} {box[3]:.0f} only)")
    for arg in args:
        report(Path(arg), box)
    return 0


if __name__ == "__main__":
    sys.exit(main())
