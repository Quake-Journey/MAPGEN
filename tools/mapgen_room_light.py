r"""Each dug room's lights brought to the light round its door, in the finished map (row 408, Fable's brief 6 P2).

    python tools/mapgen_room_light.py MAP.bsp --job JOB --donor DONOR.bsp [--work DIR] [--flags "..."] [--rounds N]

The generator values a room's lights from the DONOR's light round its door (`dig_light_reference`), but the map is lit
by its own light pass, calibrated on the faces both maps share - and round one door it may read otherwise: mg_cor's
annex opens onto a roof our pass lights at 112 where cor.bsp reads 74. So, in the finished map: every accepted dig's
room is measured against the light round its doors as THIS map lights them (`mapgen_light_profile.room_against_door`);
a room whose level is out of the band has the `light` values of its own lights - the ones inside its box the donor
does not have - scaled, and the map is relit by the light pass alone (the donor's sun, the donor's calibrated flags,
`-maxdata`, the P-cores of the hour), up to N rounds. The map is rewritten in place with the values it was lit with.
Colour is not corrected here: measured, a lamp's colour barely moves a closed room's tint (cor: 0.25 -> 0.31 from warm
to blue-white); the room's walls and the sky through its door carry it. Prints one line per room per round.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from mapgen_light_calibrate import donor_light, entity_text, with_entities, with_keys, with_sun  # noqa: E402
import mapgen_light_profile as profile  # noqa: E402
from mapgen_light_profile import LEVEL_BAND, TINT_BAND, room_against_door  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
from mapgen_memfile import compile_bsp_in_memory  # noqa: E402

GAME = r"O:\Claude2\q2pro-release\baseq2"
LIGHT = re.compile(r'\{[^{}]*"classname" "light"[^{}]*\}')
ORIGIN = re.compile(r'"origin" "(\S+) (\S+) (\S+)"')
VALUE = re.compile(r'"light" "(\d+(?:\.\d+)?)"')
VALUED = re.compile(r'"_mapgen_scale" "([\d.]+)(?: ([\d.]+))?"')


def flags_scale(flags: str) -> float:
    """The light pass's multiplier on a point light, as the generator reads it (`MapGenGeometryEdit_SetLightFlags`):
    `-scale` times `-entity`."""
    s = 1.0
    for word in ("-scale", "-entity"):
        m = re.search(rf"(?:^|\s){word}\s+([\d.]+)", flags or "")
        if m and 0.05 < float(m.group(1)) < 20.0:
            s *= float(m.group(1))
    return s


def revalue(text: str, flags: str) -> tuple[str, int]:
    """Row 412h (brief 11 step 1): the lights the generator valued for one light pass (`_mapgen_scale`, its fill and
    stairs' lights) brought to the pass that lights the map now - a donor fitted for the first time AFTER its first map
    was generated (q2dm1's fit, -scale 2.289, relit lights valued at 1.0: tunnels x2.0..x2.6 their doors)."""
    now = flags_scale(flags)
    changed = 0

    def one(m):
        nonlocal changed
        e = m.group(0)
        v = VALUED.search(e)
        if not v or abs(float(v.group(1)) - now) < 1e-3:
            return e
        k = float(v.group(1)) / now
        reach = float(v.group(2) or 0)      # the part of the value that is distance, not level: not scaled
        changed += 1
        e = VALUE.sub(lambda x: f'"light" "{max(1, round((float(x.group(1)) - reach) * k + reach))}"', e)
        return VALUED.sub(f'"_mapgen_scale" "{now:.4f} {reach:.0f}"', e)

    return LIGHT.sub(one, text), changed


def donor_lights(donor: Path) -> set:
    return {m.group(0) for m in ORIGIN.finditer(" ".join(LIGHT.findall(entity_text(donor.read_bytes()))))}


def rooms_of(job: Path, work: Path) -> list:
    import mapgen_delivery_gates as gates
    return gates.static_digs(job, work)


def measure(bsp: Path, donor: Path, digs: list, sources: list | None = None) -> list:
    import mapgen_delivery_gates as gates
    from mapgen_light_profile import room_against_source
    out = []
    for d in digs:
        doors = [d["from"]] if d.get("own_room_end") == "to" else [d["from"], d["to"]]
        # brief 11 step 1: a carried room is brought to its original's light, not its door's
        src = gates.source_of(d, sources or [], donor)
        ok, said = room_against_source(bsp, src[0], d["box"], src[1]) if src else \
            room_against_door(bsp, donor, d["box"], doors)
        m = re.search(r"all (\d+)/(\d+)", said)
        ref, room = profile.LAST.get("ref"), profile.LAST.get("room")
        tint_off = bool(ref and room and (abs(room["gr"] - ref["gr"]) > TINT_BAND or abs(room["br"] - ref["br"]) > TINT_BAND))
        colour = None
        if ref:
            top = max(ref["rgb"][3]) or 1.0
            colour = " ".join(f"{c / top:.3f}" for c in ref["rgb"][3])
        out.append((d, ok, said, (int(m.group(1)), int(m.group(2))) if m else None, tint_off, colour))
    return out


def scale_panels(bsp: Path, boxes: list, factors: list) -> int:
    """Brief 11 step 1: the glowing faces (SURF_LIGHT) a room's own panels are - their light value scaled by the room's
    factor, through a copy of their texture record so the same texture elsewhere keeps its value. Measured on q2dm1's
    first map: a tunnel lit by its lamp panels stood at x1.8 its door after three rounds that could only scale lamp
    entities. Returns how many faces took a new value. The light pass that follows reads the values from the file."""
    import struct
    d = bytearray(bsp.read_bytes())

    def lump(i):
        return struct.unpack_from("<ii", d, 8 + 8 * i)

    tio, til = lump(5)
    fo, fl = lump(6)
    vo, _ = lump(2)
    eo, _ = lump(11)
    so, _ = lump(12)
    texinfo = [bytes(d[tio + 76 * i: tio + 76 * (i + 1)]) for i in range(til // 76)]
    added: dict = {}
    changed = 0
    for f in range(fl // 20):
        at = fo + 20 * f
        _, _, firstedge, numedges, ti = struct.unpack_from("<HHiHH", d, at)
        flags, value = struct.unpack_from("<ii", texinfo[ti], 32) if ti < len(texinfo) else (0, 0)
        if not (flags & 1) or value <= 0 or numedges <= 0:
            continue
        c = [0.0, 0.0, 0.0]
        for k in range(numedges):
            se = struct.unpack_from("<i", d, so + 4 * (firstedge + k))[0]
            v0, v1 = struct.unpack_from("<HH", d, eo + 4 * abs(se))
            v = v1 if se < 0 else v0
            x = struct.unpack_from("<fff", d, vo + 12 * v)
            for a in range(3):
                c[a] += x[a] / numedges
        for box, k in zip(boxes, factors):
            if all(box[a] - 1 <= c[a] <= box[a + 3] + 1 for a in range(3)):
                key = (ti, round(k, 3))
                if key not in added:
                    rec = bytearray(texinfo[ti])
                    struct.pack_into("<i", rec, 36, max(1, int(round(value * k))))
                    struct.pack_into("<i", rec, 72, -1)          # no animation chain for the copy
                    added[key] = len(texinfo)
                    texinfo.append(bytes(rec))
                struct.pack_into("<H", d, at + 10, added[key])
                changed += 1
                break
    if added:
        # the texture records grown: the lump moved to the file's end, the header pointed at it
        new = b"".join(texinfo)
        while len(d) % 4:
            d.append(0)
        struct.pack_into("<ii", d, 8 + 8 * 5, len(d), len(new))
        d += new
        bsp.write_bytes(bytes(d))
    return changed


def relight(bsp: Path, text: str, flags: str, work: Path, keys: dict | None = None, moddir: Path | None = None,
            basedir: Path | None = None) -> None:
    raw = bsp.read_bytes()
    lit = work / "relight"
    if lit.exists():
        shutil.rmtree(lit)
    lit.mkdir(parents=True)
    lit_text = with_keys(text, keys)     # row 410: the donor's sun as the tool must be told it
    sunny = with_sun(lit_text)
    threads = str(bin(guard.affinity_mask()).count("1"))
    # brief 11 D2: a destroyed map's own textures may lie in another folder than the game's (a guard's scratch)
    words = ["-rad", "-maxdata", "8388608", "-threads", threads, *flags.split(),
             "-moddir", str(moddir or GAME), "-basedir", str(basedir or GAME), "-gamedir", str(basedir or GAME)]
    # row 411 (Fable's brief 8 D): the light pass in memory - the map relit is written once, over itself
    runs, out = compile_bsp_in_memory(pinned_compiler()[0], [words], with_entities(raw, sunny or lit_text),
                                      label="relight")
    if runs is None:
        (lit / "q2mg.bsp").write_bytes(with_entities(raw, sunny or lit_text))
        r = guard.run([str(pinned_compiler()[0]), *words, str(lit / "q2mg.map")],
                      capture_output=True, text=True, errors="replace", timeout=7200)
        out = (lit / "q2mg.bsp").read_bytes() if not r.returncode else None
    else:
        r = runs[-1]
    (lit / "rad.log").write_text(r.stdout, encoding="utf-8")
    if r.returncode or not out:
        raise SystemExit(f"the light pass failed ({r.returncode}): {r.stdout[-400:]}")
    bsp.write_bytes(with_entities(out, text))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=Path)
    ap.add_argument("--job", type=Path)
    ap.add_argument("--digs", type=Path, help="the accepted digs as JSON (the light lab's), instead of a job")
    ap.add_argument("--donor", type=Path, required=True)
    ap.add_argument("--second", type=Path, help="brief 9: the second map the run was given (the plan is dealt with it)")
    ap.add_argument("--work", type=Path)
    ap.add_argument("--flags")
    ap.add_argument("--rounds", type=int, default=8)       # brief 11: a lamp-panel tunnel converges by ~6 % a round
    ap.add_argument("--relight-first", action="store_true",
                    help="row 410: relight the map under its donor's current calibration before measuring - a map "
                         "already built, lit by an older one, brought up to date without generating it again")
    a = ap.parse_args()
    guard.pin_self()
    if a.second:
        import mapgen_delivery_gates as gates
        gates.SECOND = a.second
    work = a.work or (a.map.parent / "room_light")
    work.mkdir(parents=True, exist_ok=True)
    own_flags, keys = donor_light(a.donor)
    flags = a.flags if a.flags is not None else own_flags
    if a.digs:
        digs = json.loads(a.digs.read_text(encoding="utf-8"))
        for d in digs:
            if d.get("shape") == "annex":
                d["own_room_end"] = "to"
    else:
        digs = rooms_of(a.job, work)
    theirs = donor_lights(a.donor)
    recoloured = 0
    sources = []
    if a.job:
        import mapgen_delivery_gates as gates
        text, err = gates.plan_listing(a.job, work)
        sources = gates.job_sources(a.job, text if not err else "")
    tinted: set = set()
    if a.relight_first:
        text, moved = revalue(entity_text(a.map.read_bytes()), flags)
        print(f"relighting under the donor's calibration: flags '{flags}', keys {keys}; {moved} lights the generator"
              f" valued for another pass revalued", flush=True)
        relight(a.map, text, flags, work, keys)
    for rnd in range(a.rounds + 1):
        found = measure(a.map, a.donor, digs, sources)
        for d, ok, said, *_ in found:
            print(f"round {rnd} {'PASS' if ok else 'FAIL'} {d.get('shape')} {[round(v) for v in d['box'][:3]]}: {said}",
                  flush=True)
        # a room out of the band, or off its door's tint: its own lights take the door's colour as THIS map lit it
        # (measured on mg_cor: our pass lights cor's courtyard B/R 0.12 where cor.bsp reads 0.82 - lights coloured by
        # the donor's 0.76, brought up to level, drew the room to 0.38)
        off = [(d, lv, colour) for d, ok, said, lv, tint_off, colour in found
               if lv and (tint_off or not LEVEL_BAND[0] <= lv[0] / max(1, lv[1]) <= LEVEL_BAND[1])]
        if not off or rnd == a.rounds:
            break
        text = entity_text(a.map.read_bytes())
        changed = 0

        def scale(m):
            nonlocal changed
            e = m.group(0)
            o = ORIGIN.search(e)
            if not o or o.group(0) in theirs:
                return e
            p = [float(v) for v in o.groups()]
            for d, (room, ref), colour in off:
                b = d["box"]
                if all(b[i] - 1 <= p[i] <= b[i + 3] + 1 for i in range(3)):
                    if colour and f'"_color" "{colour}"' not in e:
                        e = re.sub(r'"_color" "[^"]*"', f'"_color" "{colour}"', e)
                        nonlocal recoloured
                        recoloured += 1
                    target = ref * (LEVEL_BAND[0] + LEVEL_BAND[1]) / 2.0
                    # measured: a room's level goes about as the square of its lights' values (q2dm1's annex: 17 at
                    # half, 68 at full - q2tools' light is (value - distance), and most of a room is far)
                    k = max(0.3, min(3.0, (target / max(1, room)) ** 0.5))
                    changed += 1
                    return VALUE.sub(lambda v: f'"light" "{round(float(v.group(1)) * k)}"', e)
            return e

        text = LIGHT.sub(scale, text)
        # a carried room whose colour stays off its original's (an original lit by its sky - orange q3t2, q2dm1's
        # courtyard rooms - copied underground under white lamps): one light of the original's colour in its middle,
        # its own panels dimmed, once (brief 11 step 1)
        extra = []
        for d, (room, ref), colour in off:
            key = tuple(round(v) for v in d["box"])
            src = gates.source_of(d, sources, a.donor) if sources else None
            if not src or not colour or key in tinted or not profile.LAST:
                continue
            b = d["box"]
            mid = [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, b[2] + (b[5] - b[2]) * 0.6]
            extra.append('{\n"classname" "light"\n"origin" "%.0f %.0f %.0f"\n"light" "%d"\n"_color" "%s"\n}\n'
                         % (mid[0], mid[1], mid[2], max(150, round(ref * 2.5)), colour))
            tinted.add(key)
        if extra:
            text = text + "".join(extra)
            scale_panels(a.map, [d["box"] for d, _, _ in off if tuple(round(v) for v in d["box"]) in tinted],
                         [0.6] * len(extra))
        # and the rooms' own glowing panels, by the level's own ratio (a panel's light goes about as its value)
        panels = scale_panels(a.map, [d["box"] for d, _, _ in off],
                              [max(0.3, min(3.0, ref * (LEVEL_BAND[0] + LEVEL_BAND[1]) / 2.0 / max(1, room)))
                               for _, (room, ref), _ in off])
        print(f"round {rnd}: {changed} lights and {panels} panel faces rescaled in {len(off)} rooms; relighting",
              flush=True)
        if not changed and not panels:
            break
        relight(a.map, text, flags, work, keys)
    # row 410 (brief 7 decision 3): recolouring now means the light pass drifted from the donor - said, not hidden
    if recoloured:
        print(f"RECOLOURED: {recoloured} lights took their door's colour as this map lit it - the light pass does not"
              f" light the donor's faces in the donor's colour", flush=True)
    record(a.map, a.job, theirs)
    return 0


def record(bsp: Path, job: Path | None, theirs: set) -> None:
    """Row 410 (brief 7 decision 5): what is delivered is what is recorded - the file's sha256 and every light the
    donor does not have, with its final value and colour, into job/lit/delivered.txt (the job's own artifact, its
    hash and its saved map describe the file before this step)."""
    if not job:
        return
    out = job / "lit"
    out.mkdir(parents=True, exist_ok=True)
    text = entity_text(bsp.read_bytes())
    lines = [f"delivered {bsp.name} sha256 {hashlib.sha256(bsp.read_bytes()).hexdigest()}"]
    for e in LIGHT.findall(text):
        o = ORIGIN.search(e)
        if not o or o.group(0) in theirs:
            continue
        v = VALUE.search(e)
        c = re.search(r'"_color" "([^"]*)"', e)
        lines.append(f"light {' '.join(o.groups())} value {v.group(1) if v else '-'} colour {c.group(1) if c else '-'}")
    (out / "delivered.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"recorded {len(lines) - 1} lights and the delivered sha256 in {out / 'delivered.txt'}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
