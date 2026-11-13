"""Forms of the scripted pieces (the PO 13.11, after the first try: «я просил тебя подойти творчески к вопросу движущихся
конструкций и делать вариации ... молот - он должен варьироваться, не быть одной формы ... серп например ... двойной
молот, может молот, на котором что то интересное еще есть»; «закрывающиеся комнаты чтобы были разных размеров и формы
(и не повторялись из карты в карту)»; «буры ... что тоннели в землю роют»; «я хочу чтобы каждая генерация вносила чего
то интересное и новое»).

A piece's brush here is a `prism`: a convex polygon in the plane across an axis, extruded along it - any convex shape
the game can hold as one brush (a blade, a fan, a spike, a cog's tooth, an octagon). The world builder makes it from its
planes (mapgen_scratch_pieces.world), the Studio's scheme from its faces (SchemeShows). Each form is drawn from the
plan's own random numbers - its shape, its sizes, its parts - so no two maps hold the same piece.
"""
from __future__ import annotations

import math


def prism(axis: str, poly, lo: float, hi: float, role: str = "trim", contents: int = 1, note: str = "") -> dict:
    """A convex polygon `poly` [(a, b) ...] across `axis` ('x': a=y, b=z; 'y': a=x, b=z; 'z': a=x, b=y), from `lo` to
    `hi` along it."""
    # whole units: a plane through whole points is the same plane after the generator turns the map into its source and
    # back (a test map of 13.11: cogs' teeth and an auger's flights at tenths - «8 planes have no counterpart», the run
    # refused at its base)
    pts = []
    for a, b in poly:
        p = [int(round(float(a))), int(round(float(b)))]
        if not pts or abs(p[0] - pts[-1][0]) + abs(p[1] - pts[-1][1]) >= 1:
            pts.append(p)
    if len(pts) > 2 and abs(pts[0][0] - pts[-1][0]) + abs(pts[0][1] - pts[-1][1]) < 1:
        pts.pop()
    # three corners in a line after the rounding are one edge
    out = []
    for i, q in enumerate(pts):
        a_, c_ = pts[i - 1], pts[(i + 1) % len(pts)]
        if (q[0] - a_[0]) * (c_[1] - a_[1]) - (q[1] - a_[1]) * (c_[0] - a_[0]) != 0:
            out.append(q)
    lo_, hi_ = int(round(min(lo, hi))), int(round(max(lo, hi)))
    if hi_ - lo_ < 2:
        hi_ = lo_ + 2
    return {"prism": {"axis": axis, "poly": out if len(out) >= 3 else pts, "lo": lo_, "hi": hi_},
            "role": role, "contents": contents, "note": note}


def nice_oct(ca: float, cb: float, r: float) -> list:
    """Eight whole points round (ca, cb) at about `r`, counter-clockwise from the +a axis: on the axes at R and on the
    diagonals at 2/3 R each way (R a multiple of three), so every side runs 1:2 or 2:1. A face of a moving piece on such
    a side has a small whole normal, which the engine's round trip of the finished map writes back exactly - a cog's
    teeth at any angle came back off their planes (the test map mg_new_368_mach5: «walls covered differently», 435
    permille of a cog's face, a candidate refused)."""
    R = max(3, 3 * int(round(r / 3)))
    S = 2 * R // 3
    a, b = int(round(ca)), int(round(cb))
    return [(a + R, b), (a + S, b + S), (a, b + R), (a - S, b + S), (a - R, b), (a - S, b - S), (a, b - R), (a + S, b - S)]


NICE_DIRS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))


def flat_oct(ca: float, cb: float, r: float) -> list:
    """Eight whole points round (ca, cb): a square of half side R with its corners cut at 45 degrees, s = 0.41 R along
    each side from the middle - sides on the axes and on the diagonals, counter-clockwise from (R, -s)."""
    R = max(4, int(round(r)))
    s = max(2, int(round(R * 0.414)))
    if (R + s) % 2:
        s += 1                                   # the diagonal sides' middles on whole points
    a, b = int(round(ca)), int(round(cb))
    return [(a + R, b - s), (a + R, b + s), (a + s, b + R), (a - s, b + R), (a - R, b + s), (a - R, b - s), (a - s, b - R),
            (a + s, b - R)]


def ngon(cx: float, cy: float, r: float, n: int, start: float = 0.0) -> list:
    return [(cx + r * math.cos(start + 2 * math.pi * k / n), cy + r * math.sin(start + 2 * math.pi * k / n)) for k in range(n)]


def thin_bar(a, b, half: float) -> list:
    """A thin rectangle along the segment a -> b, `half` either side."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / ln * half, dx / ln * half
    return [(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)]


def inset(poly, d: float) -> list:
    """A convex polygon moved in by `d` (out for a negative `d`): each vertex along its corner's bisector."""
    n = len(poly)
    cx = sum(p[0] for p in poly) / n
    cy = sum(p[1] for p in poly) / n
    out = []
    for i in range(n):
        x, y = poly[i]
        ln = math.hypot(x - cx, y - cy) or 1.0
        out.append((x - (x - cx) / ln * d * 1.25, y - (y - cy) / ln * d * 1.25))
    return out


# ------------------------------------------------------------------------------------------------- the pendulum («молот»)
PENDULUM_FORMS = ("hammer", "sledge", "spiked", "axe", "labrys", "sickle", "mace", "saw", "anchor")
FORM_RU = {"hammer": "молот", "sledge": "двуглавая кувалда", "spiked": "молот с шипами", "axe": "топор",
           "labrys": "двойной топор", "sickle": "серп", "mace": "булава", "saw": "дисковая пила", "anchor": "якорь"}
ROD_STYLES = ("rod", "fork", "chain")


# the RED: a pendulum drawn at any angle, its corners rounded to whole units one by one - two parts' faces on one line
# came out 0.06 apart, and the engine's round trip of the finished map merged them (the test map mg_new_368_mach5:
# «4 of 822 planes carrying donor surfaces have no counterpart», a candidate refused); MAPGEN_OLD_PENDULUM_TURN=1
OLD_PENDULUM_TURN = __import__("os").environ.get("MAPGEN_OLD_PENDULUM_TURN") == "1"
EXACT_REST = (math.degrees(math.atan2(3, 4)), math.degrees(math.atan2(4, 3)))     # 36.87 and 53.13 degrees: 3-4-5
# the RED: a head standing past its arm's end (a sickle 60 under it); MAPGEN_OLD_HEAD_BELOW=1 for a process
OLD_HEAD_BELOW = __import__("os").environ.get("MAPGEN_OLD_HEAD_BELOW") == "1"
# the RED: a saw's and a cog's teeth with their feet at 0.95..0.96 of the radius - the foot's edge a unit or less off the
# rim's own, two faces nearly one, which the engine's round trip merged (the test map mg_new_368_mach5: a cog's
# «walls covered differently», a candidate refused); MAPGEN_OLD_NEAR_FACES=1 for a process
OLD_NEAR_FACES = __import__("os").environ.get("MAPGEN_OLD_NEAR_FACES") == "1"


def exact_rest(deg: float) -> float:
    """The rest angle a pendulum is drawn at (its sign kept): one whose sine and cosine are fifths (3/5, 4/5), so a
    point five whole units in any way from the pivot lands on whole units turned - every face of the head exact."""
    if OLD_PENDULUM_TURN:
        return deg
    a = min(EXACT_REST, key=lambda x: (abs(x - abs(deg)), x))
    return a if deg >= 0 else -a


def pendulum(form: str, rod: str, axis: str, pu: float, pz: float, arm: float, rest_deg: float, mid: float, rnd,
             _fit: bool = True) -> list:
    """The parts of a pendulum hanging from (pu, pz) in the swing plane (u across the bridge, z up) at `rest_deg` to
    the +u side: its rod (one, a fork of two, or a chain of links) and its head - each a prism along the swing `axis`
    about `mid`. The head's sizes are drawn from `rnd` too: the same form is never twice the same. The angle is one of
    `EXACT_REST` and the parts' sizes along and across the arm whole fives: the corners land on whole units exactly."""
    st0 = rnd.getstate() if hasattr(rnd, "getstate") else None
    th = math.radians(rest_deg)
    d = (math.sin(th), -math.cos(th))             # down the arm
    sg = -1.0 if rest_deg > 0 else 1.0
    t = (sg * math.cos(th), sg * math.sin(th))    # across it, the way it swings to (its blade's edge leads)
    L = arm
    exact = not OLD_PENDULUM_TURN and abs(abs(rest_deg) - exact_rest(rest_deg) * (1 if rest_deg >= 0 else -1)) < 1e-6
    if exact:
        f5 = (3, 4) if abs(abs(rest_deg) - EXACT_REST[0]) < 1e-6 else (4, 3)     # (sin, cos) x 5
        sn = f5[0] if rest_deg > 0 else -f5[0]
        d = (sn / 5, -f5[1] / 5)
        t = (sg * f5[1] / 5, sg * abs(sn) / 5)

    def P(s, w):
        if exact:
            s, w = 5 * round(s / 5), 5 * round(w / 5)
            return (round(pu) + int(round(s * d[0] + w * t[0])), round(pz) + int(round(s * d[1] + w * t[1])))
        return (pu + s * d[0] + w * t[0], pz + s * d[1] + w * t[1])

    def part(poly_sw, half, off=0.0, role="trim"):
        pts = [P(s, w) for s, w in poly_sw]
        area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
        if exact and abs(area) < 2:
            return None                      # a part the fives made flat: none
        return prism(axis, pts, mid + off - half, mid + off + half, role, 1, f"pendulum {form}")

    def sector(s0, w0, r, a0, a1, n=6):
        """A fan from (s0, w0): the angles from the arm's way toward the swing's (degrees)."""
        pts = [(s0, w0)]
        for k in range(n + 1):
            a = math.radians(a0 + (a1 - a0) * k / n)
            pts.append((s0 + r * math.cos(a), w0 + r * math.sin(a)))
        return pts
    parts = []
    head = {"hammer": 46, "sledge": 46, "spiked": 46, "axe": 70, "labrys": 70, "sickle": 60, "mace": 72, "saw": 112,
            "anchor": 64}[form]
    rod_end = L - head * 0.55
    # the rod
    if rod == "fork":
        gap = rnd.choice((10, 14, 18))
        for off in (-gap, gap):
            parts.append(part([(0, -4), (rod_end, -4), (rod_end, 4), (0, 4)], 3, off))
        parts.append(part([(rod_end - 10, -6), (rod_end, -6), (rod_end, 6), (rod_end - 10, 6)], gap + 3))
    elif rod == "chain":
        n = max(3, int(rod_end // 40))
        step = rod_end / n
        for k in range(n):
            s0, s1 = k * step + 3, (k + 1) * step - 3
            w = 6 if k % 2 == 0 else 4
            parts.append(part([(s0, -w), (s1, -w), (s1, w), (s0, w)], 8 if k % 2 == 0 else 3))
    else:
        parts.append(part([(0, -5), (rod_end, -5), (rod_end, 5), (0, 5)], 5))
    # the head
    k = rnd.uniform(0.85, 1.2)
    if form in ("hammer", "spiked"):
        hl, hw = 44 * k, rnd.choice((52, 60, 68)) * k
        parts.append(part([(L - hl, -hw), (L, -hw), (L, hw), (L - hl, hw)], rnd.choice((20, 24, 28))))
        if form == "spiked":
            n = rnd.choice((2, 3))
            for i in range(n):
                s0 = L - hl + (i + 0.15) * hl / n
                s1 = L - hl + (i + 0.85) * hl / n
                parts.append(part([(s0, hw), (s1, hw), ((s0 + s1) / 2, hw + 26 * k)], 7))
                parts.append(part([(s0, -hw), ((s0 + s1) / 2, -hw - 18 * k), (s1, -hw)], 6))
    elif form == "sledge":
        hl, hw, bw = 46 * k, 76 * k, 30 * k
        parts.append(part([(L - hl, -hw), (L, -hw), (L, -hw + bw), (L - hl, -hw + bw)], 26))
        parts.append(part([(L - hl, hw - bw), (L, hw - bw), (L, hw), (L - hl, hw)], 26))
        parts.append(part([(L - hl * 0.72, -hw + bw), (L - hl * 0.28, -hw + bw), (L - hl * 0.28, hw - bw), (L - hl * 0.72, hw - bw)], 14))
    elif form == "axe":
        r = 70 * k
        parts.append(part(sector(L - r * 0.9, 0, r, 30, 150), 4))
        parts.append(part([(L - r * 0.9 - 12, -10), (L - r * 0.9 + 12, -10), (L - r * 0.9 + 12, 10), (L - r * 0.9 - 12, 10)], 10))
    elif form == "labrys":
        r = 62 * k
        parts.append(part(sector(L - r * 0.8, 0, r, 30, 150), 4))
        parts.append(part(sector(L - r * 0.8, 0, r, 210, 330), 4))
        parts.append(part([(L - r * 0.8 - 14, -10), (L - r * 0.8 + 14, -10), (L - r * 0.8 + 14, 10), (L - r * 0.8 - 14, 10)], 10))
    elif form == "sickle":
        R, wdt = 82 * k, 20 * k
        cs, cw = L - 30 * k, -34 * k
        a0, a1 = rnd.choice(((10, 125), (0, 115), (20, 140)))
        n = 6
        for i in range(n):
            q0 = math.radians(a0 + (a1 - a0) * i / n)
            q1 = math.radians(a0 + (a1 - a0) * (i + 1) / n)
            w_ = wdt * (1 - 0.55 * i / n)
            parts.append(part([(cs + R * math.cos(q0), cw + R * math.sin(q0)), (cs + R * math.cos(q1), cw + R * math.sin(q1)),
                               (cs + (R - w_) * math.cos(q1), cw + (R - w_) * math.sin(q1)),
                               (cs + (R - w_) * math.cos(q0), cw + (R - w_) * math.sin(q0))], 4))
        parts.append(part([(rod_end - 6, -12), (L - 30 * k + 4, -12), (L - 30 * k + 4, 12), (rod_end - 6, 12)], 8))
    elif form == "mace":
        r = 30 * k
        c = L - r - 4
        parts.append(part([(c + r * math.cos(a), r * math.sin(a)) for a in [math.pi / 8 + k_ * math.pi / 4 for k_ in range(8)]],
                          r * 0.9))
        n = rnd.choice((6, 8))
        for i in range(n):
            a = 2 * math.pi * i / n + math.pi / n
            base = [(c + r * 0.85 * math.cos(a - 0.3), r * 0.85 * math.sin(a - 0.3)),
                    (c + (r + 30 * k) * math.cos(a), (r + 30 * k) * math.sin(a)),
                    (c + r * 0.85 * math.cos(a + 0.3), r * 0.85 * math.sin(a + 0.3))]
            parts.append(part(base, 6))
    elif form == "saw":
        r = 54 * k
        c = L - r
        teeth = rnd.choice((12, 16))
        parts.append(part([(c + r * math.cos(2 * math.pi * i / 16), r * math.sin(2 * math.pi * i / 16)) for i in range(16)], 3))
        for i in range(teeth):
            a = 2 * math.pi * i / teeth
            b_ = a + 2 * math.pi / teeth * 0.7
            # the tooth's foot well inside the disc (at 0.96 r its edge ran 0.5 off the disc's own, two faces nearly one)
            fr = 0.96 if OLD_NEAR_FACES else 0.8
            parts.append(part([(c + r * fr * math.cos(a), r * fr * math.sin(a)),
                               (c + (r + 14) * math.cos(a + 0.08), (r + 14) * math.sin(a + 0.08)),
                               (c + r * fr * math.cos(b_), r * fr * math.sin(b_))], 3))
        parts.append(part([(c - 12, -12), (c + 12, -12), (c + 12, 12), (c - 12, 12)], 10))
    elif form == "anchor":
        R, wdt = 58 * k, 16
        cs = L - R
        for side in (1, -1):
            for i in range(4):
                q0 = math.radians(10 + 22 * i)
                q1 = math.radians(10 + 22 * (i + 1))
                pts = [(cs + R * math.cos(q0), side * R * math.sin(q0)), (cs + R * math.cos(q1), side * R * math.sin(q1)),
                       (cs + (R - wdt) * math.cos(q1), side * (R - wdt) * math.sin(q1)),
                       (cs + (R - wdt) * math.cos(q0), side * (R - wdt) * math.sin(q0))]
                parts.append(part(pts if side > 0 else list(reversed(pts)), 6))
            tip = math.radians(10 + 22 * 4)
            parts.append(part([(cs + R * math.cos(tip), side * R * math.sin(tip)),
                               (cs + (R + 14) * math.cos(tip + 0.2), side * (R + 14) * math.sin(tip + 0.2)),
                               (cs + (R - wdt) * math.cos(tip), side * (R - wdt) * math.sin(tip))], 6))
        parts.append(part([(rod_end - 10, -6), (L, -6), (L, 6), (rod_end - 10, 6)], 6))
        parts.append(part([(rod_end * 0.55 - 6, -40), (rod_end * 0.55 + 6, -40), (rod_end * 0.55 + 6, 40), (rod_end * 0.55 - 6, 40)], 6))
    parts = [p for p in parts if p]
    # the head's lowest point at the arm's end, never under it: a sickle's blade, a mace's spikes, a saw's teeth stood
    # up to 60 past it - into the bridge at the bottom of the swing (the PO 13.11's sweep found no place for a sickle).
    # Drawn again with the arm shorter by that much, the same draws
    if _fit and not OLD_HEAD_BELOW and st0 is not None:
        a_, c_ = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}[axis]
        lowest = max((q[0] - pu) * d[0] + (q[1] - pz) * d[1] for p_ in parts for q in p_["prism"]["poly"])
        if lowest > L + 1:
            rnd.setstate(st0)
            # once, with the fives' rounding to spare
            return pendulum(form, rod, axis, pu, pz, arm - (lowest - L) - 6, rest_deg, mid, rnd, _fit=False)
    return parts


# ------------------------------------------------------------------------------------------------- the drill («бур»)
DRILL_RIGS = ("tower", "aframe", "cross", "gantry")


def drill_auger(cx: float, cy: float, z0: float, z1: float, r: float, flights: int, starts: int, rnd) -> list:
    """An auger about the vertical through (cx, cy) from `z0` (under the floor: it bores into it) to `z1`: its shaft (an
    octagon) and its helical flights - thin blades stacked round it, each turned on from the last (one, two or three
    starts) - prisms along z."""
    if not OLD_NEAR_FACES:
        return _drill_auger_nice(cx, cy, z0, z1, r, flights, starts)
    parts = [prism("z", ngon(cx, cy, max(8, r * 0.28), 8, math.pi / 8), z0, z1 + 24, "trim", 1, "drill shaft")]
    turns = (z1 - z0) / max(16, (z1 - z0) / max(1, flights))
    n = max(6, int(turns * 8))
    dz = (z1 - z0) / n
    for st in range(starts):
        for i in range(n):
            a = 2 * math.pi * (i / 8.0 + st / starts)
            a1 = a + 2 * math.pi / 8 * 0.9
            z = z0 + i * dz
            poly = [(cx + r * 0.25 * math.cos(a), cy + r * 0.25 * math.sin(a)), (cx + r * math.cos(a), cy + r * math.sin(a)),
                    (cx + r * math.cos(a1), cy + r * math.sin(a1)), (cx + r * 0.25 * math.cos(a1), cy + r * 0.25 * math.sin(a1))]
            parts.append(prism("z", poly, z, z + max(4, dz * 0.45), "trim", 1, "drill flight"))
    # the bit: a cone of three tiers under it
    for i, (rr, h) in enumerate(((r * 0.7, 10), (r * 0.45, 10), (r * 0.2, 12))):
        parts.append(prism("z", ngon(cx, cy, rr, 8, math.pi / 8), z0 - 10 * (i + 1), z0 - 10 * i, "trim", 1, "drill bit"))
    return parts


def _drill_auger_nice(cx: float, cy: float, z0: float, z1: float, r: float, flights: int, starts: int) -> list:
    """The auger of `nice_oct`s: its shaft one, each flight the eighth of a ring between the shaft and the rim's
    octagons, stacked an eighth on, the bit three of them smaller and smaller."""
    shaft = nice_oct(cx, cy, max(9, r * 0.28))
    inner = shaft                                 # the flights stand on the shaft's sides, none inside it
    rim = nice_oct(cx, cy, r)
    parts = [prism("z", shaft, z0, z1 + 24, "trim", 1, "drill shaft")]
    turns = (z1 - z0) / max(16, (z1 - z0) / max(1, flights))
    n = max(6, int(turns * 8))
    dz = (z1 - z0) / n
    for st in range(starts):
        off = int(round(8 * st / starts))
        for i in range(n):
            k = (i + off) % 8
            z = z0 + i * dz
            poly = [inner[k], rim[k], rim[(k + 1) % 8], inner[(k + 1) % 8]]
            parts.append(prism("z", poly, z, z + max(4, dz * 0.45), "trim", 1, "drill flight"))
    for i, rr in enumerate((r * 0.7, r * 0.45, r * 0.2)):
        parts.append(prism("z", nice_oct(cx, cy, max(3, rr)), z0 - 10 * (i + 1), z0 - 10 * i, "trim", 1, "drill bit"))
    return parts


def nice_ring(ca: float, cb: float, r_in: float, r_out: float, axis: str, lo: float, hi: float, note: str) -> list:
    """A ring of eight pieces between two `nice_oct`s (a collar round an auger)."""
    a_, b_ = nice_oct(ca, cb, r_in), nice_oct(ca, cb, r_out)
    return [prism(axis, [a_[k], b_[k], b_[(k + 1) % 8], a_[(k + 1) % 8]], lo, hi, "trim", 1, note) for k in range(8)]


def _beam(x0: float, y0: float, x1: float, y1: float) -> list:
    """A rectangle in plan from corner to corner (a beam along an axis)."""
    return [(min(x0, x1), min(y0, y1)), (max(x0, x1), min(y0, y1)), (max(x0, x1), max(y0, y1)), (min(x0, x1), max(y0, y1))]


def drill_rig(kind: str, cx: float, cy: float, z: float, top: float, half: float) -> list:
    """The rig over a drill: a four-post tower, an A-frame of two legs each side, a cross frame (four posts on the
    sides, two beams crossing over the auger) or a gantry across - its legs standing on the floor, its crown over the
    auger held as people's are: beams framed between the posts' heads, a cap on the legs' tops (the test map
    mg_new_368_mach5: a tower's crown on its posts' corners alone - «in the air at 736 608 326»;
    tools/mapgen_map_survey.py hanging_brushes' rule)."""
    out = []
    w = 6
    if OLD_RIGS:
        return _drill_rig_old(kind, cx, cy, z, top, half)
    if kind == "tower":
        # four posts to the crown's top, the crown a frame of beams between their heads and one across over the auger
        q = w / math.sqrt(2)                       # a post's half side (a square turned with its sides on the axes)
        for sx in (-1, 1):
            for sy in (-1, 1):
                out.append(prism("z", ngon(cx + sx * half, cy + sy * half, w, 4, math.pi / 4), z, top + 12, "trim", 1, "drill rig"))
        for sy in (-1, 1):
            out.append(prism("z", _beam(cx - half + q - 1, cy + sy * half - 4, cx + half - q + 1, cy + sy * half + 4),
                             top, top + 12, "trim", 1, "drill crown"))
        for sx in (-1, 1):
            out.append(prism("z", _beam(cx + sx * half - 4, cy - half + q - 1, cx + sx * half + 4, cy + half - q + 1),
                             top, top + 12, "trim", 1, "drill crown"))
        out.append(prism("z", _beam(cx - half + 3, cy - 5, cx + half - 3, cy + 5), top, top + 12, "trim", 1, "drill crown"))
        for zz in (z + (top - z) * 0.45,):
            for sy in (-1, 1):
                out.append(prism("z", thin_bar((cx - half, cy + sy * half), (cx + half, cy + sy * half), 3), zz, zz + 6, "trim", 1, "drill brace"))
    elif kind == "aframe":
        for sy in (-1, 1):
            for sx in (-1, 1):
                out.append(prism("y", thin_bar((cx + sx * half * 1.6, z), (cx + sx * 8, top), w), cy + sy * half - w, cy + sy * half + w,
                                 "trim", 1, "drill leg"))
        out.append(prism("z", [(cx - 16, cy - half - w), (cx + 16, cy - half - w), (cx + 16, cy + half + w), (cx - 16, cy + half + w)],
                         top, top + 12, "trim", 1, "drill crown"))
    elif kind == "cross":
        # four posts on the sides, clear of the auger, and two beams crossing over it, each between a pair's heads
        e = half * 1.3
        for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            out.append(prism("z", _beam(cx + sx * e - w, cy + sy * e - w, cx + sx * e + w, cy + sy * e + w), z, top + 12,
                             "trim", 1, "drill leg"))
        out.append(prism("z", _beam(cx - e + w - 1, cy - 5, cx + e - w + 1, cy + 5), top, top + 12, "trim", 1, "drill crown"))
        out.append(prism("z", _beam(cx - 5, cy - e + w - 1, cx + 5, cy + e - w + 1), top, top + 12, "trim", 1, "drill crown"))
    else:   # gantry: two posts and a beam across between their heads
        out.append(prism("z", [(cx - half * 1.4 + w - 1, cy - 10), (cx + half * 1.4 - w + 1, cy - 10),
                               (cx + half * 1.4 - w + 1, cy + 10), (cx - half * 1.4 + w - 1, cy + 10)], top, top + 12,
                         "trim", 1, "drill crown"))
        for sx in (-1, 1):
            out.append(prism("z", [(cx + sx * half * 1.4 - w, cy - 12), (cx + sx * half * 1.4 + w, cy - 12),
                                   (cx + sx * half * 1.4 + w, cy + 12), (cx + sx * half * 1.4 - w, cy + 12)], z, top + 12,
                             "trim", 1, "drill leg"))
    return out


# the RED: 3.68's first rigs (a tower's and a gantry's crown on their posts' corners, a tripod's legs of posts stepping
# in - «in the air» by the finished map's check); MAPGEN_OLD_RIGS=1 for a process
OLD_RIGS = __import__("os").environ.get("MAPGEN_OLD_RIGS") == "1"


def _drill_rig_old(kind: str, cx: float, cy: float, z: float, top: float, half: float) -> list:
    out = []
    w = 6
    if kind == "tower":
        for sx in (-1, 1):
            for sy in (-1, 1):
                out.append(prism("z", ngon(cx + sx * half, cy + sy * half, w, 4, math.pi / 4), z, top, "trim", 1, "drill rig"))
        out.append(prism("z", [(cx - half - w, cy - half - w), (cx + half + w, cy - half - w), (cx + half + w, cy + half + w),
                               (cx - half - w, cy + half + w)], top, top + 12, "trim", 1, "drill crown"))
        for zz in (z + (top - z) * 0.45,):
            for sy in (-1, 1):
                out.append(prism("z", thin_bar((cx - half, cy + sy * half), (cx + half, cy + sy * half), 3), zz, zz + 6, "trim", 1, "drill brace"))
    elif kind == "aframe":
        for sy in (-1, 1):
            for sx in (-1, 1):
                out.append(prism("y", thin_bar((cx + sx * half * 1.6, z), (cx + sx * 8, top), w), cy + sy * half - w, cy + sy * half + w,
                                 "trim", 1, "drill leg"))
        out.append(prism("z", [(cx - 16, cy - half - w), (cx + 16, cy - half - w), (cx + 16, cy + half + w), (cx - 16, cy + half + w)],
                         top, top + 12, "trim", 1, "drill crown"))
    elif kind in ("tripod", "cross"):
        for i in range(3):
            a = 2 * math.pi * i / 3 + math.pi / 6
            fx, fy = cx + half * 1.5 * math.cos(a), cy + half * 1.5 * math.sin(a)
            # a leg from its foot to the crown: a thin bar in the vertical plane through foot and centre
            ln = math.hypot(fx - cx, fy - cy) or 1.0
            ux, uy = (fx - cx) / ln, (fy - cy) / ln
            # in that plane's own axis: built as a stack of short posts stepping in (each a box: they read as a leg)
            n = 6
            for k_ in range(n):
                t0, t1 = k_ / n, (k_ + 1) / n
                px = fx + (cx - fx) * (t0 + t1) / 2
                py = fy + (cy - fy) * (t0 + t1) / 2
                out.append(prism("z", ngon(px, py, w, 4, math.pi / 4), z + (top - z) * t0, z + (top - z) * t1 + 2, "trim", 1, "drill leg"))
        out.append(prism("z", ngon(cx, cy, half * 0.6, 6), top, top + 12, "trim", 1, "drill crown"))
    else:   # gantry: two posts and a beam across
        for sx in (-1, 1):
            out.append(prism("z", [(cx + sx * half * 1.4 - w, cy - w), (cx + sx * half * 1.4 + w, cy - w),
                                   (cx + sx * half * 1.4 + w, cy + w), (cx + sx * half * 1.4 - w, cy + w)], z, top + 12, "trim", 1, "drill leg"))
        out.append(prism("z", [(cx - half * 1.4 - w, cy - 10), (cx + half * 1.4 + w, cy - 10), (cx + half * 1.4 + w, cy + 10),
                               (cx - half * 1.4 - w, cy + 10)], top, top + 12, "trim", 1, "drill crown"))
    return out


# ------------------------------------------------------------------------------------------------- cogs («шестерни»)
def cog(axis: str, ca: float, cb: float, r: float, teeth: int, lo: float, hi: float, note: str = "cog") -> list:
    """A cog wheel across `axis` centred (ca, cb): its rim polygon and its teeth, each a prism from lo to hi. The rim a
    `nice_oct`, its eight teeth on the axes (boxes) and the diagonals (squares turned 45 degrees): every face's normal
    small and whole."""
    if not OLD_NEAR_FACES:
        # no part inside another: the rim a `flat_oct`, each tooth standing on one of its sides (its foot that side's
        # middle), the hub two caps on the rim's faces - parts that overlap were drawn otherwise by the engine's round
        # trip (the test map mg_new_368_mach5: a cog's teeth and hub through its rim, «walls covered differently»)
        rim = flat_oct(ca, cb, r)
        a, b = int(round(ca)), int(round(cb))
        R = rim[1][0] - a
        s = rim[1][1] - b
        tl = 12                                   # a tooth's length
        half = max(3, min(s - 2, R // 5))
        h = max(2, min((R - s) // 2 - 1, int(round(half / 1.41))))
        parts = [prism(axis, rim, lo, hi, "drum", 1, note)]
        for dx, dy in NICE_DIRS:
            if dx == 0 or dy == 0:
                if dx:
                    pts = [(a + dx * R, b - half), (a + dx * (R + tl), b - half), (a + dx * (R + tl), b + half), (a + dx * R, b + half)]
                else:
                    pts = [(a - half, b + dy * R), (a + half, b + dy * R), (a + half, b + dy * (R + tl)), (a - half, b + dy * (R + tl))]
            else:
                m = (R + s) // 2                          # the diagonal side's middle: (m, m) turned to (dx, dy)
                c0, c1 = m, m + 8                         # along the diagonal from the side, eight each way
                px, py = -dy * h, dx * h                  # across it
                pts = [(a + dx * c0 + px, b + dy * c0 + py), (a + dx * c1 + px, b + dy * c1 + py),
                       (a + dx * c1 - px, b + dy * c1 - py), (a + dx * c0 - px, b + dy * c0 - py)]
            parts.append(prism(axis, pts, lo, hi, "drum", 1, note))
        hub = flat_oct(ca, cb, max(6, r * 0.25))
        parts.append(prism(axis, hub, lo - 4, lo, "trim", 1, note + " hub"))
        parts.append(prism(axis, hub, hi, hi + 4, "trim", 1, note + " hub"))
        return parts
    n = max(8, teeth)
    parts = [prism(axis, ngon(ca, cb, r, n, math.pi / n), lo, hi, "drum", 1, note)]
    # the teeth's feet well inside the rim: their edge apart from the rim's own (two faces nearly one otherwise)
    fr = 0.95 if OLD_NEAR_FACES else 0.8
    for i in range(teeth):
        a = 2 * math.pi * i / teeth
        da = math.pi / teeth * 0.55
        parts.append(prism(axis, [(ca + r * fr * math.cos(a - da), cb + r * fr * math.sin(a - da)),
                                  (ca + (r + 12) * math.cos(a - da * 0.6), cb + (r + 12) * math.sin(a - da * 0.6)),
                                  (ca + (r + 12) * math.cos(a + da * 0.6), cb + (r + 12) * math.sin(a + da * 0.6)),
                                  (ca + r * fr * math.cos(a + da), cb + r * fr * math.sin(a + da))],
                           lo + 1, hi - 1, "drum", 1, note))
    parts.append(prism(axis, ngon(ca, cb, max(6, r * 0.25), 6), lo - 4, hi + 4, "trim", 1, note + " hub"))
    return parts
