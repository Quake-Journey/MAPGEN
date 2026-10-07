"""The colour of the light: mean R, G, B of the luxels inside each accepted dig's box against the rest of the map,
and what the lamps in the box are (classname light keys, emitting textures)."""
import math
import re
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"C:\Users\alexy\mgwt\tools")
import mapgen_delivery_gates as gates  # noqa: E402

T = Path(r"O:\Claude2\MapgenStudio\temp")
MAPS = Path(r"O:\Claude2\q2pro-release\baseq2\maps")


def lump(d, i):
    return struct.unpack_from("<ii", d, 8 + 8 * i)


def faces(path):
    d = path.read_bytes()
    vo, vn = lump(d, 2)
    verts = [struct.unpack_from("<3f", d, vo + i * 12) for i in range(vn // 12)]
    eo, en = lump(d, 11)
    edges = [struct.unpack_from("<2H", d, eo + i * 4) for i in range(en // 4)]
    so, sn = lump(d, 12)
    se = struct.unpack_from(f"<{sn // 4}i", d, so)
    to, tn = lump(d, 5)
    tex = []
    for i in range(tn // 76):
        vecs = struct.unpack_from("<8f", d, to + i * 76)
        flags, value = struct.unpack_from("<ii", d, to + i * 76 + 32)
        name = d[to + i * 76 + 40:to + i * 76 + 72].split(b"\0")[0].decode("latin-1")
        tex.append((vecs, flags, value, name))
    lo, ln = lump(d, 7)
    light = d[lo:lo + ln]
    fo, fn = lump(d, 6)
    out = []
    for i in range(fn // 20):
        pn, side, fe, ne, ti, s0, s1, s2, s3, lofs = struct.unpack_from("<HhiHh4Bi", d, fo + i * 20)
        vecs, flags, value, name = tex[ti]
        pts = []
        for k in range(ne):
            e = se[fe + k]
            pts.append(verts[edges[e][0]] if e >= 0 else verts[edges[-e][1]])
        box = [min(p[a] for p in pts) for a in range(3)] + [max(p[a] for p in pts) for a in range(3)]
        rgb = None
        if not flags & 0x8C and lofs >= 0 and s0 != 255:
            smin = [min(p[0] * vecs[a * 4] + p[1] * vecs[a * 4 + 1] + p[2] * vecs[a * 4 + 2] + vecs[a * 4 + 3]
                        for p in pts) for a in range(2)]
            smax = [max(p[0] * vecs[a * 4] + p[1] * vecs[a * 4 + 1] + p[2] * vecs[a * 4 + 2] + vecs[a * 4 + 3]
                        for p in pts) for a in range(2)]
            w = int(math.ceil(smax[0] / 16) - math.floor(smin[0] / 16)) + 1
            h = int(math.ceil(smax[1] / 16) - math.floor(smin[1] / 16)) + 1
            n = w * h
            if n > 0 and lofs + n * 3 <= len(light):
                lux = light[lofs:lofs + n * 3]
                rgb = (sum(lux[0::3]), sum(lux[1::3]), sum(lux[2::3]), n)
        out.append({"name": name, "flags": flags, "value": value, "box": box, "rgb": rgb})
    eo2, en2 = lump(d, 0)
    return out, d[eo2:eo2 + en2].decode("latin-1")


def tint(fs):
    r = sum(f["rgb"][0] for f in fs)
    g = sum(f["rgb"][1] for f in fs)
    b = sum(f["rgb"][2] for f in fs)
    n = max(1, sum(f["rgb"][3] for f in fs))
    return f"R {r / n:.0f} G {g / n:.0f} B {b / n:.0f} (B/R {b / max(1, r):.2f})"


for label, bsp, job, donor in (("mg_q3t2", MAPS / "mg_q3t2.bsp", T / "mg_q3t2_20261004_022305" / "job", MAPS / "q3t2.bsp"),
                               ("mg_cor", MAPS / "mg_cor.bsp", T / "mg_cor_20261004_025038" / "job", MAPS / "cor.bsp")):
    fs, ents = faces(bsp)
    dfs, dents = faces(donor)
    lit = [f for f in fs if f["rgb"]]
    print(f"== {label}: donor {tint([f for f in dfs if f['rgb']])}")
    dl = re.findall(r"\{[^{}]*\"classname\" \"light\"[^{}]*\}", dents)
    print(f"   donor: {len(dl)} light entities, with _color {sum(1 for e in dl if '_color' in e)};"
          f" emitting textures {Counter((f['name'], f['value']) for f in dfs if f['flags'] & 1).most_common(6)}")
    for d in gates.accepted_digs(job):
        b = d["box"]
        inside = [f for f in lit if all(b[a] - 1 <= f["box"][a] and f["box"][a + 3] <= b[a + 3] + 1 for a in range(3))]
        allin = [f for f in fs if all(b[a] - 1 <= f["box"][a] and f["box"][a + 3] <= b[a + 3] + 1 for a in range(3))]
        lamps = []
        for e in re.findall(r"\{[^{}]*\"classname\" \"light\"[^{}]*\}", ents):
            o = re.search(r'"origin" "([-\d.]+) ([-\d.]+) ([-\d.]+)"', e)
            if o and all(b[a] <= float(o.group(a + 1)) <= b[a + 3] for a in range(3)):
                lamps.append((re.search(r'"light" "(\d+)"', e) or [0, "?"])[1] + ("c" if "_color" in e else ""))
        print(f"   {d.get('shape')} {[round(v) for v in b[:3]]}: {tint(inside)}; textures"
              f" {Counter(f['name'] for f in allin).most_common(4)}; emitting"
              f" {Counter((f['name'], f['value']) for f in allin if f['flags'] & 1).most_common(3)}; lamps {Counter(lamps)}")
