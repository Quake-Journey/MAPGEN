"""Fable's review of brief 6 on the installed maps: per room - its lights (count, values, colour), the share of its
luxels burnt out (any channel >= 250) against the door's, the darkest tenth, ceiling against floor."""
import math
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\alexy\mgwt\tools")
import mapgen_delivery_gates as gates  # noqa: E402

T = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\MapgenStudio\temp")
MAPS = Path(r"O:\Claude2\q2pro-release\baseq2\maps")
W = Path(r"C:\Users\alexy\AppData\Local\Temp\claude\o--Claude2\a185a67c-53dc-4f53-90fe-763193d6a5fd\scratchpad\review")


def lump(d, i):
    return struct.unpack_from("<ii", d, 8 + 8 * i)


def luxels(path):
    d = path.read_bytes()
    vo, vn = lump(d, 2)
    verts = [struct.unpack_from("<3f", d, vo + i * 12) for i in range(vn // 12)]
    eo, en = lump(d, 11)
    edges = [struct.unpack_from("<2H", d, eo + i * 4) for i in range(en // 4)]
    so, sn = lump(d, 12)
    se = struct.unpack_from(f"<{sn // 4}i", d, so)
    po, pn = lump(d, 1)
    planes = [struct.unpack_from("<4f", d, po + i * 20) for i in range(pn // 20)]
    to, tn = lump(d, 5)
    tex = [(struct.unpack_from("<8f", d, to + i * 76), struct.unpack_from("<i", d, to + i * 76 + 32)[0]) for i in range(tn // 76)]
    lo, ln = lump(d, 7)
    light = d[lo:lo + ln]
    mo, _ = lump(d, 13)
    first, count = struct.unpack_from("<ii", d, mo + 40)
    fo, _ = lump(d, 6)
    out = []
    for i in range(first, first + count):
        pnum, side, fe, ne, ti, s0, s1, s2, s3, lofs = struct.unpack_from("<HhiHh4Bi", d, fo + i * 20)
        vecs, flags = tex[ti]
        if flags & 0x8C or lofs < 0 or s0 == 255 or ne < 3:
            continue
        pts = [verts[edges[e][0]] if e >= 0 else verts[edges[-e][1]] for e in (se[fe + k] for k in range(ne))]
        smin = [min(q[0] * vecs[a * 4] + q[1] * vecs[a * 4 + 1] + q[2] * vecs[a * 4 + 2] + vecs[a * 4 + 3] for q in pts) for a in range(2)]
        smax = [max(q[0] * vecs[a * 4] + q[1] * vecs[a * 4 + 1] + q[2] * vecs[a * 4 + 2] + vecs[a * 4 + 3] for q in pts) for a in range(2)]
        w = int(math.ceil(smax[0] / 16) - math.floor(smin[0] / 16)) + 1
        h = int(math.ceil(smax[1] / 16) - math.floor(smin[1] / 16)) + 1
        n = w * h
        if n <= 0 or lofs + n * 3 > len(light):
            continue
        lux = light[lofs:lofs + n * 3]
        tops = [max(lux[k], lux[k + 1], lux[k + 2]) for k in range(0, n * 3, 3)]
        nz = planes[pnum][2] * (-1 if side else 1)
        box = [min(q[a] for q in pts) for a in range(3)] + [max(q[a] for q in pts) for a in range(3)]
        out.append({"box": box, "c": [sum(q[a] for q in pts) / ne for a in range(3)], "tops": tops,
                    "kind": 1 if nz > 0.7 else 2 if nz < -0.7 else 0})
    eo2, en2 = lump(d, 0)
    return out, d[eo2:eo2 + en2].decode("latin-1")


def stats(fs):
    tops = sorted(t for f in fs for t in f["tops"])
    if not tops:
        return "none"
    burnt = 100.0 * sum(1 for t in tops if t >= 250) / len(tops)
    dark = 100.0 * sum(1 for t in tops if t < 16) / len(tops)
    return f"burnt {burnt:4.1f}% dark {dark:4.1f}% p10 {tops[len(tops) // 10]:3d} p50 {tops[len(tops) // 2]:3d} p90 {tops[len(tops) * 9 // 10]:3d}"


for name, job, donor in (("mg_q3t2", "mg_q3t2_20261004_135018", "q3t2"), ("mg_cor", "mg_cor_20261004_163759", "cor")):
    cand, ents = luxels(MAPS / f"{name}.bsp")
    don, dents = luxels(MAPS / f"{donor}.bsp")
    old = {(f["kind"], tuple(round(v) for v in f["box"])) for f in don}
    dl = set(re.findall(r'"origin" "[^"]*"', " ".join(re.findall(r'\{[^{}]*"classname" "light"[^{}]*\}', dents))))
    print(f"== {name}: whole donor {stats(don)}")
    for d in gates.static_digs(T / job / "job", W / name):
        b = d["box"]
        room = [f for f in cand if all(b[a] - 1 <= f["box"][a] and f["box"][a + 3] <= b[a + 3] + 1 for a in range(3))
                and (f["kind"], tuple(round(v) for v in f["box"])) not in old]
        doors = [d["from"]] if d.get("own_room_end") == "to" else [d["from"], d["to"]]
        near = [f for f in cand if (f["kind"], tuple(round(v) for v in f["box"])) in old
                and any(sum((f["c"][a] - p[a]) ** 2 for a in range(3)) <= 512 ** 2 for p in doors)]
        lamps = []
        for e in re.findall(r'\{[^{}]*"classname" "light"[^{}]*\}', ents):
            o = re.search(r'"origin" "(\S+) (\S+) (\S+)"', e)
            if o and o.group(0) not in dl and all(b[a] <= float(o.group(a + 1)) <= b[a + 3] for a in range(3)):
                lamps.append(int(float(re.search(r'"light" "([\d.]+)"', e).group(1))))
        floor_area = (b[3] - b[0]) * (b[4] - b[1])
        print(f"  {d.get('shape'):11s} {[round(v) for v in b[:3]]}: {len(lamps)} lights {sorted(set(lamps))}, one per {floor_area / max(1, len(lamps)):.0f} sq")
        print(f"      room {stats(room)}")
        print(f"      door {stats(near)}")
