r"""How a map is lit: its light sources and what they do to its faces (Fable's brief 6).

    python tools/mapgen_light_profile.py MAP.bsp [MAP.bsp ...]

Sources, read from the entity text and the texinfo: the sun and sky keys of worldspawn; point lights (count, value,
colour, how many are targeted spots or styled); emitting faces by texture (count, value, area, the texture's own
mean colour - what the light tool emits in). Result, read from the lighting lump per drawn face: level (mean of the
largest channel), tint (G/R, B/R), contrast inside a face (max luxel over mean), and how these spread over the map
(percentiles by luxel), split by orientation.
"""
from __future__ import annotations

import math
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

GAME = Path(r"O:\Claude2\q2pro-release\baseq2")


def lump(d, i):
    return struct.unpack_from("<ii", d, 8 + 8 * i)


def pak_read(name: str):
    p = GAME / name
    if p.is_file():
        return p.read_bytes()
    for pak in sorted(GAME.glob("*.pak")):
        with pak.open("rb") as f:
            head = f.read(12)
            if head[:4] != b"PACK":
                continue
            ofs, ln = struct.unpack_from("<ii", head, 4)
            f.seek(ofs)
            table = f.read(ln)
            for i in range(ln // 64):
                if table[i * 64:i * 64 + 56].split(b"\0")[0].decode("latin-1").lower() == name.lower():
                    o, s = struct.unpack_from("<ii", table, i * 64 + 56)
                    f.seek(o)
                    return f.read(s)
    return None


_PAL = None


def texture_colour(name: str):
    global _PAL
    if _PAL is None:
        pcx = pak_read("pics/colormap.pcx")
        _PAL = pcx[-768:] if pcx else b""
    d = pak_read(f"textures/{name}.wal")
    if not d or not _PAL:
        return None
    w, h = struct.unpack_from("<II", d, 32)
    ofs = struct.unpack_from("<I", d, 40)[0]
    c = Counter(d[ofs:ofs + w * h])
    t = sum(c.values()) or 1
    return tuple(sum(_PAL[i * 3 + k] * v for i, v in c.items()) / t for k in range(3))


def pct(values, weights, q):
    pairs = sorted(zip(values, weights))
    total = sum(weights) or 1
    run = 0.0
    for v, w in pairs:
        run += w
        if run >= q * total:
            return v
    return pairs[-1][0] if pairs else 0.0


def profile(path: Path) -> None:
    d = path.read_bytes()
    eo, en = lump(d, 0)
    ents = d[eo:eo + en].decode("latin-1")
    blocks = re.findall(r"\{([^{}]*)\}", ents)
    kv = [dict(re.findall(r'"([^"]*)" "([^"]*)"', b)) for b in blocks]
    world = next((e for e in kv if e.get("classname") == "worldspawn"), {})
    print(f"=== {path.name}")
    print("  worldspawn light keys:", {k: v for k, v in world.items() if k.startswith("_") or k in ("sky", "light")})
    lights = [e for e in kv if e.get("classname", "").startswith("light")]
    vals = Counter(int(float(e.get("light", e.get("_light", "300")))) for e in lights)
    cols = Counter(e.get("_color", "(white)") for e in lights)
    print(f"  point lights: {len(lights)}; values {sorted(vals.items())[:12]}; colours {cols.most_common(5)};"
          f" spots {sum(1 for e in lights if 'target' in e or '_cone' in e)}, styled {sum(1 for e in lights if 'style' in e)}")
    vo, vn = lump(d, 2)
    verts = [struct.unpack_from("<3f", d, vo + i * 12) for i in range(vn // 12)]
    eo2, en2 = lump(d, 11)
    edges = [struct.unpack_from("<2H", d, eo2 + i * 4) for i in range(en2 // 4)]
    so, sn = lump(d, 12)
    se = struct.unpack_from(f"<{sn // 4}i", d, so)
    po, pn_ = lump(d, 1)
    planes = [struct.unpack_from("<4f", d, po + i * 20) for i in range(pn_ // 20)]
    to, tn = lump(d, 5)
    tex = []
    for i in range(tn // 76):
        vecs = struct.unpack_from("<8f", d, to + i * 76)
        flags, value = struct.unpack_from("<ii", d, to + i * 76 + 32)
        tex.append((vecs, flags, value, d[to + i * 76 + 40:to + i * 76 + 72].split(b"\0")[0].decode("latin-1")))
    lo, ln = lump(d, 7)
    light = d[lo:lo + ln]
    fo, fn = lump(d, 6)
    emit = defaultdict(lambda: [0, 0.0])
    floor_area = 0.0
    level, gr, br, peak, wts, kinds = [], [], [], [], [], []
    for i in range(fn // 20):
        pnum, side, fe, ne, ti, s0, s1, s2, s3, lofs = struct.unpack_from("<HhiHh4Bi", d, fo + i * 20)
        vecs, flags, value, name = tex[ti]
        pts = []
        for k in range(ne):
            e = se[fe + k]
            pts.append(verts[edges[e][0]] if e >= 0 else verts[edges[-e][1]])
        # area by the fan
        area = 0.0
        for k in range(1, len(pts) - 1):
            a = [pts[k][j] - pts[0][j] for j in range(3)]
            b = [pts[k + 1][j] - pts[0][j] for j in range(3)]
            c = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
            area += 0.5 * math.sqrt(c[0] ** 2 + c[1] ** 2 + c[2] ** 2)
        if flags & 1 and value > 0:
            emit[(name, value, "sky" if flags & 4 else "warp" if flags & 8 else "panel")][0] += 1
            emit[(name, value, "sky" if flags & 4 else "warp" if flags & 8 else "panel")][1] += area
        if flags & 0x8C or lofs < 0 or s0 == 255:
            continue
        nz = planes[pnum][2] * (-1 if side else 1)
        if nz > 0.7:
            floor_area += area
        smin = [min(p[0] * vecs[a * 4] + p[1] * vecs[a * 4 + 1] + p[2] * vecs[a * 4 + 2] + vecs[a * 4 + 3]
                    for p in pts) for a in range(2)]
        smax = [max(p[0] * vecs[a * 4] + p[1] * vecs[a * 4 + 1] + p[2] * vecs[a * 4 + 2] + vecs[a * 4 + 3]
                    for p in pts) for a in range(2)]
        w = int(math.ceil(smax[0] / 16) - math.floor(smin[0] / 16)) + 1
        h = int(math.ceil(smax[1] / 16) - math.floor(smin[1] / 16)) + 1
        n = w * h
        if n <= 0 or lofs + n * 3 > len(light):
            continue
        lux = light[lofs:lofs + n * 3]
        r, g, b = sum(lux[0::3]) / n, sum(lux[1::3]) / n, sum(lux[2::3]) / n
        top = max(r, g, b)
        level.append(top)
        gr.append(g / r if r > 1 else 1.0)
        br.append(b / r if r > 1 else 1.0)
        peak.append(max(max(lux[k], lux[k + 1], lux[k + 2]) for k in range(0, n * 3, 3)) / top if top > 1 else 1.0)
        wts.append(n)
        kinds.append("floors" if nz > 0.7 else "ceilings" if nz < -0.7 else "sides")
    print(f"  emitting faces ({sum(v[0] for v in emit.values())}):")
    for (name, value, kind), (count, area) in sorted(emit.items(), key=lambda x: -x[1][1])[:8]:
        c = texture_colour(name)
        print(f"    {kind:5s} {name:26s} value {value:5d}  {count:4d} faces  {area:9.0f} sq"
              + (f"  texture colour R {c[0]:.0f} G {c[1]:.0f} B {c[2]:.0f}" if c else ""))
    print(f"  floor area {floor_area:.0f} sq: one point light per {floor_area / max(1, len(lights)):.0f} sq of floor")

    def row(label, sel):
        lv = [level[i] for i in sel]
        w = [wts[i] for i in sel]
        if not lv:
            return
        print(f"  {label:9s} level p10 {pct(lv, w, .1):5.0f}  p50 {pct(lv, w, .5):5.0f}  p90 {pct(lv, w, .9):5.0f} |"
              f" G/R p50 {pct([gr[i] for i in sel], w, .5):.2f}  B/R p10 {pct([br[i] for i in sel], w, .1):.2f}"
              f" p50 {pct([br[i] for i in sel], w, .5):.2f} p90 {pct([br[i] for i in sel], w, .9):.2f} |"
              f" peak/mean in a face p50 {pct([peak[i] for i in sel], w, .5):.2f} p90 {pct([peak[i] for i in sel], w, .9):.2f}")
    row("all", range(len(level)))
    for kind in ("sides", "floors", "ceilings"):
        row(kind, [i for i in range(len(level)) if kinds[i] == kind])


# ---- a room against the light round its door (row 408, Fable's brief 6 decision 4) ------------------------------
REF_RADIUS = 512.0          # the dig's DIG_LIGHT_REF_RADIUS
LEVEL_BAND = (0.8, 1.25)
TINT_BAND = 0.15
CONTRAST_SHARE = 0.8
CEILING_OVER_FLOOR = 1.15
_LIT = {}


def lit_faces(path: Path) -> list:
    """Every lit face of model zero: middle, kind (sides/floors/ceilings), R G B sums, luxels, and its own
    peak/mean - as the generator's `lit_faces` reads them."""
    key = (str(path), path.stat().st_mtime)
    if key in _LIT:
        return _LIT[key]
    d = path.read_bytes()
    vo, vn = lump(d, 2)
    verts = [struct.unpack_from("<3f", d, vo + i * 12) for i in range(vn // 12)]
    eo, en = lump(d, 11)
    edges = [struct.unpack_from("<2H", d, eo + i * 4) for i in range(en // 4)]
    so, sn = lump(d, 12)
    se = struct.unpack_from(f"<{sn // 4}i", d, so)
    po, pn_ = lump(d, 1)
    planes = [struct.unpack_from("<4f", d, po + i * 20) for i in range(pn_ // 20)]
    to, tn = lump(d, 5)
    tex = [(struct.unpack_from("<8f", d, to + i * 76), struct.unpack_from("<i", d, to + i * 76 + 32)[0])
           for i in range(tn // 76)]
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
        pts = []
        for k in range(ne):
            e = se[fe + k]
            pts.append(verts[edges[e][0]] if e >= 0 else verts[edges[-e][1]])
        smin = [min(q[0] * vecs[a * 4] + q[1] * vecs[a * 4 + 1] + q[2] * vecs[a * 4 + 2] + vecs[a * 4 + 3]
                    for q in pts) for a in range(2)]
        smax = [max(q[0] * vecs[a * 4] + q[1] * vecs[a * 4 + 1] + q[2] * vecs[a * 4 + 2] + vecs[a * 4 + 3]
                    for q in pts) for a in range(2)]
        w = int(math.ceil(smax[0] / 16) - math.floor(smin[0] / 16)) + 1
        h = int(math.ceil(smax[1] / 16) - math.floor(smin[1] / 16)) + 1
        n = w * h
        if n <= 0 or lofs + n * 3 > len(light):
            continue
        lux = light[lofs:lofs + n * 3]
        sums = (sum(lux[0::3]), sum(lux[1::3]), sum(lux[2::3]))
        tops = bytes(max(lux[k], lux[k + 1], lux[k + 2]) for k in range(0, n * 3, 3))
        top = max(sums) / n
        peak = max(max(lux[k], lux[k + 1], lux[k + 2]) for k in range(0, n * 3, 3))
        nz = planes[pnum][2] * (-1 if side else 1)
        box = [min(q[a] for q in pts) for a in range(3)] + [max(q[a] for q in pts) for a in range(3)]
        out.append({"c": [sum(q[a] for q in pts) / ne for a in range(3)], "box": box,
                    "kind": 1 if nz > 0.7 else 2 if nz < -0.7 else 0, "sum": sums, "n": n, "tops": tops,
                    "peak": peak / top if top > 1 else 1.0})
    _LIT[key] = out
    return out


def summary(faces: list) -> dict:
    """Mean R G B by kind (0 sides, 1 floors, 2 ceilings, 3 all), levels (largest channel), tint, contrast p50."""
    s = [[0.0, 0.0, 0.0] for _ in range(4)]
    n = [0] * 4
    for f in faces:
        for k in (f["kind"], 3):
            for c in range(3):
                s[k][c] += f["sum"][c]
            n[k] += f["n"]
    rgb = [[s[k][c] / n[k] if n[k] else 0.0 for c in range(3)] for k in range(4)]
    allc = rgb[3]
    return {"rgb": rgb, "n": n, "level": [max(x) for x in rgb],
            "gr": allc[1] / allc[0] if allc[0] > 1 else 1.0, "br": allc[2] / allc[0] if allc[0] > 1 else 1.0,
            "contrast": pct([f["peak"] for f in faces], [f["n"] for f in faces], 0.5) if faces else 1.0}


LAST = {}       # the last call's reference and room summaries, for a caller that corrects (mapgen_room_light.py)


def room_against_door(cand: Path, donor: Path, box: list, doors: list) -> tuple[bool, str]:
    """A dug room (its box) against the donor's light within REF_RADIUS of its doors: level by orientation, tint,
    contrast, and its ceiling no brighter than its floor unless the reference's is."""
    # only what the dig built: a face the donor draws in the same place is the donor's own light (row 408: mg_q3t2's
    # tunnel box holds the donor's ceilings over lava at 196, which read as the tunnel's)
    old_faces = {(f["kind"], tuple(round(v) for v in f["box"])) for f in lit_faces(donor)}
    # the reference is what stands beside the room IN THIS MAP - the donor's own faces round its doors as this map's
    # light pass lit them. Measured on mg_cor: that pass lights cor's own faces B/R 0.12 where cor.bsp reads 0.82 (its
    # sky, golden, carries the light), and the PO saw the golden courtyard through the door of a room lit white
    near = [f for f in lit_faces(cand)
            if (f["kind"], tuple(round(v) for v in f["box"])) in old_faces
            and any(sum((f["c"][a] - p[a]) ** 2 for a in range(3)) <= REF_RADIUS ** 2 for p in doors)]
    inside = [f for f in lit_faces(cand)
              if all(box[a] - 1 <= f["box"][a] and f["box"][a + 3] <= box[a + 3] + 1 for a in range(3))
              and (f["kind"], tuple(round(v) for v in f["box"])) not in old_faces]
    if not near or not inside:
        return True, f"no light to compare ({len(near)} donor faces near, {len(inside)} in the room)"
    ref, room = summary(near), summary(inside)
    LAST.clear()
    LAST.update(ref=ref, room=room)
    bad = []
    names = ("sides", "floors", "ceilings")
    levels = []
    for k in (0, 1, 2):
        if ref["n"][k] and room["n"][k]:
            levels.append(f"{names[k]} {room['level'][k]:.0f}/{ref['level'][k]:.0f}")
    # row 408: the room's level as a whole against its door's. By orientation the door's light is an open courtyard's
    # - sky on its floors, 117 against walls 68 and ceilings 42 at mg_q3t2's first annex - which no closed room lit by
    # point lights reads (its ceiling follows its floor through the bounce: measured 54/55, 85/79, 121/106); the
    # orientations are said, and the ceiling may not stand clearly over the floor
    r = room["level"][3] / ref["level"][3] if ref["level"][3] > 1 else 1.0
    if not LEVEL_BAND[0] <= r <= LEVEL_BAND[1]:
        bad.append(f"level x{r:.2f}")
    if room["n"][1] and room["n"][2] and room["level"][2] > CEILING_OVER_FLOOR * room["level"][1]             and not (ref["n"][1] and ref["n"][2] and ref["level"][2] > ref["level"][1]):
        bad.append("ceiling brighter than floor")
    if abs(room["gr"] - ref["gr"]) > TINT_BAND or abs(room["br"] - ref["br"]) > TINT_BAND:
        bad.append(f"tint G/R {room['gr']:.2f} B/R {room['br']:.2f} against {ref['gr']:.2f} {ref['br']:.2f}")
    if room["contrast"] < CONTRAST_SHARE * ref["contrast"]:
        bad.append(f"flat (contrast {room['contrast']:.2f} against {ref['contrast']:.2f})")
    # row 410 (brief 7 decision 4): across the room, p10..p90 of the largest channel against its door's - REPORTED,
    # not judged, until the numbers after the faithful pass are in; and the door as the DONOR lights it (decision 3:
    # with a faithful pass the two references should agree)
    rs, ds = spread(inside), spread(near)
    even = rs[2] < SPREAD_SHARE * ds[2]
    theirs = [f for f in lit_faces(donor)
              if any(sum((f["c"][a] - p[a]) ** 2 for a in range(3)) <= REF_RADIUS ** 2 for p in doors)]
    dref = summary(theirs) if theirs else None
    LAST.update(spread=(rs, ds), even=even, donor_ref=dref)
    return not bad, (f"all {room['level'][3]:.0f}/{ref['level'][3]:.0f}, " + ", ".join(levels)
                     + f"; tint {room['br']:.2f}/{ref['br']:.2f}; contrast"
                     f" {room['contrast']:.2f}/{ref['contrast']:.2f}" + (" - " + "; ".join(bad) if bad else "")
                     + f" | spread p10..p90 {rs[0]}..{rs[1]} against {ds[0]}..{ds[1]}"
                     f" (x{rs[2]:.1f}/{ds[2]:.1f}{', EVEN' if even else ''})"
                     + (f"; the donor's door {dref['level'][3]:.0f} tint {dref['br']:.2f}" if dref else ""))


def room_against_source(cand: Path, source: Path, box: list, src_box: list) -> tuple[bool, str]:
    """Brief 11 step 1: a room CARRIED whole from a map (a «room-copy» of the base, a «room-of» the second map) against
    the same room in the map it came from - its level, tint, contrast and ceiling over floor as there. Its door's light
    is a corridor's: measured on q2dm1's first map, copies with 0 lamps of their own came out x1.8 their door, copies
    with 2..3 lamps x0.5 or off-tint, while each read like its original. The faces in BOX (the copy, new to the map)
    against the faces of SOURCE within SRC_BOX."""
    inside = [f for f in lit_faces(cand)
              if all(box[a] - 1 <= f["box"][a] and f["box"][a + 3] <= box[a + 3] + 1 for a in range(3))]
    there = [f for f in lit_faces(source)
             if all(src_box[a] - 1 <= f["box"][a] and f["box"][a + 3] <= src_box[a + 3] + 1 for a in range(3))]
    if not inside or not there:
        return True, f"no light to compare ({len(there)} faces of the original, {len(inside)} of the copy)"
    ref, room = summary(there), summary(inside)
    LAST.clear()
    LAST.update(ref=ref, room=room)
    bad = []
    r = room["level"][3] / ref["level"][3] if ref["level"][3] > 1 else 1.0
    if not LEVEL_BAND[0] <= r <= LEVEL_BAND[1]:
        bad.append(f"level x{r:.2f}")
    if abs(room["gr"] - ref["gr"]) > TINT_BAND or abs(room["br"] - ref["br"]) > TINT_BAND:
        bad.append(f"tint G/R {room['gr']:.2f} B/R {room['br']:.2f} against {ref['gr']:.2f} {ref['br']:.2f}")
    if room["contrast"] < CONTRAST_SHARE * ref["contrast"]:
        bad.append(f"flat (contrast {room['contrast']:.2f} against {ref['contrast']:.2f})")
    return not bad, (f"all {room['level'][3]:.0f}/{ref['level'][3]:.0f} against its original; tint"
                     f" {room['br']:.2f}/{ref['br']:.2f}; contrast {room['contrast']:.2f}/{ref['contrast']:.2f}"
                     + (" - " + "; ".join(bad) if bad else ""))


SPREAD_SHARE = 0.5          # brief 7 decision 4: the room's p90/p10 not under half its door's


def spread(faces: list) -> tuple:
    """p10, p90 of the largest channel over the faces' luxels, and p90/p10 (p10 held at 1 or more)."""
    t = sorted(b"".join(f["tops"] for f in faces))
    if not t:
        return 0, 0, 1.0
    p10, p90 = t[len(t) // 10], t[len(t) * 9 // 10]
    return p10, p90, p90 / max(1, p10)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    for a in sys.argv[1:]:
        profile(Path(a))


# ---- a light pass faithful to the donor (row 410, Fable's brief 7 decision 1) -----------------------------------
BURNT = 250                 # a luxel's largest channel at or over this reads white
BURNT_SLACK = 1.0           # points of burnt share over the donor's
P90_BAND = (0.8, 1.25)
CHANNEL_BAND = (0.8, 1.25)


def faithful(cand: Path, donor: Path) -> tuple[bool, str, list]:
    """The faces both maps draw (same orientation, same box to the unit), per orientation and as a whole: each
    channel's luxel-weighted mean against the donor's, the burnt share (largest channel >= BURNT), p90 of the largest
    channel. The three-channel mean of row 405 let a pass 1.8 times redder than cor's agree with it (brief 7)."""
    theirs = {(f["kind"], tuple(round(v) for v in f["box"])): f for f in lit_faces(donor)}
    pairs = [(f, theirs[(f["kind"], tuple(round(v) for v in f["box"]))]) for f in lit_faces(cand)
             if (f["kind"], tuple(round(v) for v in f["box"])) in theirs]
    rows, bad = [], []
    for k, name in ((0, "sides"), (1, "floors"), (2, "ceilings"), (None, "all")):
        sel = [(a, b) for a, b in pairs if k is None or a["kind"] == k]
        if not sel:
            continue
        ours = [sum(a["sum"][c] for a, b in sel) for c in range(3)]
        don = [sum(b["sum"][c] for a, b in sel) for c in range(3)]
        ratio = [ours[c] / don[c] if don[c] else 1.0 for c in range(3)]
        to = b"".join(a["tops"] for a, b in sel)
        td = b"".join(b["tops"] for a, b in sel)
        burnt_o = 100.0 * sum(1 for x in to if x >= BURNT) / max(1, len(to))
        burnt_d = 100.0 * sum(1 for x in td if x >= BURNT) / max(1, len(td))
        so, sd = sorted(to), sorted(td)
        p90o, p90d = so[len(so) * 9 // 10], sd[len(sd) * 9 // 10]
        p90r = p90o / p90d if p90d else 1.0
        rows.append({"kind": name, "faces": len(sel), "ratio": ratio, "burnt": (burnt_o, burnt_d),
                     "p90": (p90o, p90d), "p50": (so[len(so) // 2], sd[len(sd) // 2])})
        if any(not CHANNEL_BAND[0] <= r <= CHANNEL_BAND[1] for r in ratio):
            bad.append(f"{name} R/G/B x{ratio[0]:.2f}/{ratio[1]:.2f}/{ratio[2]:.2f}")
        if burnt_o > burnt_d + BURNT_SLACK:
            bad.append(f"{name} burnt {burnt_o:.1f}% against {burnt_d:.1f}%")
        if not P90_BAND[0] <= p90r <= P90_BAND[1]:
            bad.append(f"{name} p90 {p90o}/{p90d}")
    said = "; ".join(f"{r['kind']} R/G/B {r['ratio'][0]:.2f}/{r['ratio'][1]:.2f}/{r['ratio'][2]:.2f} burnt"
                     f" {r['burnt'][0]:.1f}/{r['burnt'][1]:.1f}% p50 {r['p50'][0]}/{r['p50'][1]} p90"
                     f" {r['p90'][0]}/{r['p90'][1]}" for r in rows)
    return not bad, said + (" - " + "; ".join(bad) if bad else ""), rows
