"""A window: a hole cut through a wall with glass in it - and the glass is one
of four things, every one of them built out of what the STOCK game keeps.

The PO asked for glass by name on 2026-09-10, of the one thing he liked in the
93-permille map - «есть даже дырка в стенке - что топ... а можно и разные
варианты пробовать - чтобы в дырке стекло было». Three deliveries later he shot
at three maps and said «не вижу никаких стёкол нигде»: the pane was a
`func_explosive`, and `SP_func_explosive` frees itself at spawn when
`deathmatch` is set (`src/game/g_misc.c:740`), which q2dm1 is played as. So he
answered it himself - «если нельзя разбиваемое, то точно можно просто обычное
прозрачное. А открывать его тогда как дверью: подошёл к двери, на полу кнопка,
наступил на неё - открылось» - and a pane is now one of:

    WINDOW  a WORLD brush wearing base1's glass and carrying no entity at all,
            so there is nothing there for any game to delete;
    DOOR    a `func_door` with neither `health` nor `targetname`, which is the
            one case where the game spawns an approach trigger;
    PLATE   a `func_door` with a `targetname` and a visible `func_button`
            lying on the floor in front of it, one each side;
    SHOT    a `func_door` with `health 10`, `wait -1` and `sounds 1`, firing a
            `target_speaker` that carries base1's own `world/brkglas.wav`.

    python tools/check_mapgen_window.py [--work DIR]

The fixture is one hall with a single-box wall across the middle of it, and it
answers both halves of the contract at once:

    the interior wall    is offered, and the operator cuts it: the run of rock
                         between the two halves is emptied over the opening's
                         rectangle and a pane fills the hole;
    the shell walls      are refused, because the only thing on the far side
                         of them is the void - a window into nothing is not a
                         window, and this is the RED that proves the trace is
                         what is deciding.

A second fixture - the same hall with the middle wall standing on nothing, its
foot 96 units off the floor - is what proves the DIRECTION is measured rather
than assumed: a pane with no rock under it has to slide up instead of down.

What the built maps are then held to, per shape:

    the pane is there    a brush wearing a translucent skin, which the pinned
                         compiler turns into CONTENTS_WINDOW by itself
                         (q2tools-220 src/map.c: "if any side is translucent,
                         mark the contents and change solid to window") - so
                         the player cannot walk through it and the renderer
                         draws what is behind it;
    it is base1's        the texture and the flag are the ones base1 gives its
                         own glass, because base1 is what the PO named. The
                         first version used `e2u3/window1`, a near-black
                         texture nothing shows through; he said «никаких
                         зеркал тут я не вижу» and he was describing exactly
                         that;
    the machinery is
    exactly the stock
    game's              every key of every entity, and nothing else: a door
                         with a `targetname` has no approach trigger, a door
                         with `health` has none either, `wait -1` never
                         returns, and a negative lip lengthens the travel so
                         no strip of glass is left across the opening;
    it really hides      the swept volume of every moving pane is SOLID in the
                         compiled map, sampled - a pane that slides into air
                         is a pane the player watches hang beside the hole;
    the speaker is
    audible             its origin is in AIR, because `Use_Target_Speaker`
                         plays a positioned sound and a sound in a solid leaf
                         reaches nobody;
    a ROW breaks one at
    a time               a wall with room for it gets up to three panes, one
                         shape for the whole row: three doors with three
                         triggers, or three doors sharing one plate, or three
                         doors with three speakers. He asked for «длинные окна
                         со стёклами и (или) много окон со стёклами стоящими
                         рядом... игроки стреляют, стёкла разлетаются и дают
                         проход»;
    nothing to see       surface faults do not rise: the hollow's cut faces
                         and the pane's own faces meet on the same planes;
    it is still sealed   the compiler writes no pointfile;
    it is not a route    the sill is 96 units above the wall's base, higher
                         than a player can step or jump onto, so the opening
                         adds a view and not a way through.

And the retired pane is still built: `--breakable` on the driver reaches the
`func_explosive` the game deletes, which is what lets
`check_mapgen_glass_alive.py` regenerate the map its red case needs.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIN = REPO / "tools" / "mapgen_compiler_pin.json"
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260913\window_gate")

sys.path.insert(0, str(REPO / "tools"))
from check_mapgen_recut import build_driver          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as load_guard          # noqa: E402

AXES = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 0 0"
SKY_AXES = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 4 0"
WALL = "e2u3/blum12_1"
FLOOR = "e2u3/floor1_6"
SKY = "e2u3/sky1"
T = 32

# The hall, and the wall across the middle of it. The wall is ONE box, which
# is what makes it a candidate: q2dm1's walls are several boxes side by side
# and the family finds none there - measured, 1080 faces considered, 0 offered,
# every one of the 37 that had room for an opening with rock behind its own
# face rather than a space.
HALL = (0, 0, 0, 1600, 768, 512)
WALL_X = (768, 800)
# How far off the floor the second fixture's wall stands. A pane whose foot is
# the wall's own foot has AIR under it and must slide the other way.
PANEL_UP = 96

FAULTS = re.compile(r"^surface faults (\d+)$", re.M)
# «  edit 6  window  opening 1  amount 64» - the opening index is the only
# identity that survives the deal: the schedule is dealt round-robin by kind
# and shuffled within each kind, so the k-th window edit is NOT the k-th offer.
OFFER = re.compile(r"^  edit (\d+)  window  opening (\d+)", re.M)
TALLY = re.compile(r"^  windows: (\d+) room faces considered, (\d+) offered;(.*)$",
                   re.M)
APPLY = re.compile(r"^apply (\d+): (\S+), changed (\S+), (\d+) brushes$", re.M)
# «window offered FIRST: opening 0, the doorway at 768 -0 0, glazed as a door»
DOORWAY = re.compile(r"^  window offered (?:FIRST|second): opening (\d+), the"
                     r" doorway at \S+ \S+ \S+, glazed as a (\w+)", re.M)
# «window offered: opening 1, room 0 +x, run 768..800, open 352..416, sill 96,
#  3 panes: plate down, 2 plates at 256/256»
SILL = re.compile(r"^  window offered: opening (\d+), room \d+ [-+][xy],"
                  r" run \S+\.\.\S+,"
                  r" open \S+\.\.\S+, sill (\S+), (\d+) panes?: (\w+) (\w+),"
                  r" (\d+) plates? at (\S+)/(\S+)", re.M)

# The pane's own skin, and the frame's.
#
# `e1u1/wndow0_3` - base1's, which this guard used to insist on - is 128x128 with
# the Strogg emblem filling it, and the PO asked the obvious question on
# 2026-09-11: «у левого стекла зачем-то кусок текстуры какого-то логотипа
# наклеен, да ещё и обрезано - зачем так? И при чём тут base1, когда мы говорим
# про q2dm1-форк?». `e2u3/window5_1` is the brightest PLAIN glass in PAK0 (mean
# luminance 71 of 255, spread 5.5 over all 24 window WALs) and lives in the unit
# sixty of q2dm1's own sixty-five texture names belong to.
GLASS_TEXTURE = "e2u3/window5_1"
PLATE_TEXTURE = "e2u3/metal5_1"
FRAME_TEXTURE = "e2u3/metal5_1"
# The construction's own numbers, which the module defines and this asserts.
PANE_THICK = 8.0
# how far a MOVING pane is sunk into its frame on every edge (WINDOW_PANE_BURY)
PANE_BURY = 4.0
FRAME_WIDE = 16.0
FRAME_PROUD = 8.0
RAIL = 8.0
MULLION = 16.0
PLATE_TALL = 16.0
PLATE_BEVEL = 4.0
SHOT_WAIT_MIN = 2
SHOT_WAIT_MAX = 30
GLASS_HEALTH = "10"
GLASS_MASS = "800"
BRKGLAS = "world/brkglas.wav"

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


def box(x0, y0, z0, x1, y1, z1, tex, axes=AXES) -> str:
    faces = [
        [(x0, 0, 0), (x0, 1, 0), (x0, 0, 1)],
        [(x1, 0, 0), (x1, 0, 1), (x1, 1, 0)],
        [(0, y0, 0), (0, y0, 1), (1, y0, 0)],
        [(0, y1, 0), (1, y1, 0), (0, y1, 1)],
        [(0, 0, z0), (1, 0, z0), (0, 1, z0)],
        [(0, 0, z1), (0, 1, z1), (1, 0, z1)],
    ]
    out = ["{"]
    for f in faces:
        out.append(" ".join(f"( {p[0]} {p[1]} {p[2]} )" for p in f)
                   + f" {tex} {axes}")
    out.append("}")
    return "\n".join(out)


# where the buttressed hall's wall becomes 48 units thicker, along the row
BUTTRESS_Y = 440


def write_fixture(path: Path, panel: bool = False,
                  buttress: bool = False) -> None:
    """The hall.

    `panel` stands the middle wall 96 units off the floor, which takes the
    rock out from under any pane cut in it - that is how the SLIDE direction
    gets measured rather than assumed.

    `buttress` puts 48 more units of rock against the wall over the second and
    third panes of a row and NOT over the first. That is q2dm1's own shape -
    a wall of several boxes, thicker where the row's later panes are - and it
    is what the row's speakers and plates have to survive: the plan proves air
    outside the FIRST pane only.
    """
    x0, y0, z0, x1, y1, z1 = HALL
    brushes = [
        box(x0, y0, z0 - T, x1, y1, z0, FLOOR),
        box(x0 - T, y0, z0, x0, y1, z1, WALL),
        box(x1, y0, z0, x1 + T, y1, z1, WALL),
        box(x0 - T, y0 - T, z0, x1 + T, y0, z1, WALL),
        box(x0 - T, y1, z0, x1 + T, y1 + T, z1, WALL),
        box(x0 - T, y0 - T, z1, x1 + T, y1 + T, z1 + T, SKY, SKY_AXES),
        # the wall across the middle: ONE box, floor to lid
        box(WALL_X[0], y0, z0 + (PANEL_UP if panel else 0), WALL_X[1], y1, z1,
            WALL),
    ]
    if buttress:
        brushes.append(box(WALL_X[0] - 48, BUTTRESS_Y, z0, WALL_X[0], y1, z1,
                           WALL))
    text = ["// Game: Quake 2", "// Format: Valve",
            "{", '"classname" "worldspawn"', '"mapversion" "220"',
            "\n".join(brushes), "}",
            "{", '"classname" "info_player_start"',
            '"origin" "128 384 32"', "}",
            "{", '"classname" "info_player_deathmatch"',
            '"origin" "1400 384 32"', "}",
            "{", '"classname" "light"', '"origin" "384 384 400"',
            '"light" "500"', "}",
            "{", '"classname" "light"', '"origin" "1200 384 400"',
            '"light" "500"', "}"]
    path.write_text("\n".join(text) + "\n", encoding="ascii")


def pinned() -> tuple[Path, str]:
    """The pinned compiler, or another binary the pin's own list says a
    complete M0Q passed (`tools/mapgen_pinned_compiler.py`)."""
    from mapgen_pinned_compiler import pinned_compiler
    return pinned_compiler()


def compile_map(path: Path) -> str:
    exe, threads = pinned()
    run = load_guard.run(
        [str(exe), "-bsp", "-threads", threads, "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(path)],
        capture_output=True, text=True, timeout=3600)
    return run.stdout + run.stderr


def drive(exe: Path, bsp: Path, *args: str) -> str:
    run = load_guard.run([str(exe), str(bsp), *args],
                         capture_output=True, text=True, timeout=3600)
    return run.stdout + run.stderr


# ---- reading the compiled map ----------------------------------------------

CONTENTS_SOLID = 0x1
CONTENTS_WINDOW = 0x2


def lump(data: bytes, i: int) -> bytes:
    ofs, ln = struct.unpack_from("<ii", data, 8 + 8 * i)
    return data[ofs:ofs + ln]


class Bsp:
    """Just enough of a Quake II BSP to ask where things are and what is
    solid: the entity string, the brush contents, the submodel boxes, the
    translucent texture names, and the world tree."""

    def __init__(self, path: Path):
        d = path.read_bytes()
        self.d = d
        self.ents = lump(d, 0).decode("latin1")
        raw = lump(d, 1)
        self.planes = [struct.unpack_from("<ffffi", raw, 20 * i)
                       for i in range(len(raw) // 20)]
        raw = lump(d, 4)
        self.nodes = [struct.unpack_from("<iii6hHH", raw, 28 * i)
                      for i in range(len(raw) // 28)]
        raw = lump(d, 8)
        self.leafs = [struct.unpack_from("<ihh6hHHHH", raw, 28 * i)
                      for i in range(len(raw) // 28)]
        raw = lump(d, 13)
        self.models = [struct.unpack_from("<9f3i", raw, 48 * i)
                       for i in range(len(raw) // 48)]
        raw = lump(d, 14)
        self.brushes = [struct.unpack_from("<iii", raw, 12 * i)
                        for i in range(len(raw) // 12)]
        raw = lump(d, 15)
        # The brush SIDES, so a pane's own box can be read off its six planes:
        # the construction assertions need the box, not the count.
        self.brushsides = [struct.unpack_from("<Hh", raw, 4 * i)
                           for i in range(len(raw) // 4)]
        raw = lump(d, 5)
        self.texinfo = [struct.unpack_from("<8fii32si", raw, 76 * i)
                        for i in range(len(raw) // 76)]

    def contents(self, p) -> int:
        node = self.models[0][9]
        while node >= 0:
            pl = self.nodes[node][0]
            n = self.planes[pl][0:3]
            dist = self.planes[pl][3]
            d = n[0] * p[0] + n[1] * p[1] + n[2] * p[2] - dist
            node = self.nodes[node][1] if d >= 0 else self.nodes[node][2]
        return self.leafs[-1 - node][0]

    def solid(self, p) -> bool:
        return bool(self.contents(p) & CONTENTS_SOLID)

    def window_brushes(self) -> int:
        return sum(1 for b in self.brushes if b[2] & CONTENTS_WINDOW)

    def pane_textures(self) -> set:
        out = set()
        for rec in self.texinfo:
            if rec[8] & 0x10:
                out.add(rec[10].split(b"\0")[0].decode("latin1"))
        return out

    def entities(self, classname: str) -> list:
        out = []
        for block in re.findall(r"\{[^}]*\}", self.ents):
            keys = dict(re.findall(r'"([^"]*)"\s+"([^"]*)"', block))
            if keys.get("classname") == classname:
                out.append(keys)
        return out

    def model_box(self, spec: str):
        """The box of `*N`, as the compiler wrote it."""
        if not spec.startswith("*"):
            return None
        n = int(spec[1:])
        if n >= len(self.models):
            return None
        m = self.models[n]
        return (list(m[0:3]), list(m[3:6]))


def glass_lines(map_text: str) -> int:
    """A pane face: the glass skin with the translucent flag.

    It used to require the literal axes string « 1 16 0» as well, which was the
    world-anchored mapping the PO saw a cropped emblem through. Every face is now
    anchored to the pane's own corner, so its offsets differ by design and the
    flag is what identifies the face.
    """
    return sum(1 for line in map_text.splitlines()
               if GLASS_TEXTURE in line and line.rstrip().endswith(" 16 0"))


def plate_lines(map_text: str) -> int:
    """A plate face: the metal skin, and NOT translucent."""
    return sum(1 for line in map_text.splitlines()
               if PLATE_TEXTURE in line and " 1 0 0" in line)


# ---- the offers, and which edit is which -----------------------------------

def offers(listing: str) -> list:
    """Every window offer in plan order, paired with its edit index.

    The refusal log and the `edit N window` lines are both written in plan
    order, so the k-th offer is the k-th window edit. Nothing else ties them
    together, and a mismatch in count is reported rather than guessed at.
    """
    found = []
    for m in re.finditer(r"^  window offered.*$", listing, re.M):
        line = m.group(0)
        d = DOORWAY.match(line)
        s = SILL.match(line)
        if d:
            found.append({"where": "doorway", "opening": int(d.group(1)),
                          "shape": d.group(2),
                          "panes": 1, "sill": 0.0, "slide": None,
                          "plates": 0, "out": (0.0, 0.0),
                          "line": line.strip()})
        elif s:
            found.append({"where": "sill", "opening": int(s.group(1)),
                          "shape": s.group(4),
                          "panes": int(s.group(3)),
                          "sill": float(s.group(2)),
                          "slide": s.group(5),
                          "plates": int(s.group(6)),
                          "out": (float(s.group(7)), float(s.group(8))),
                          "line": line.strip()})
    by_opening = {int(op): edit for edit, op in OFFER.findall(listing)}
    for o in found:
        o["edit"] = by_opening.get(o["opening"])
    return [o for o in found if o["edit"] is not None]


# ---- what each shape has to be --------------------------------------------

def travel_of(box_lo, box_hi) -> float:
    """A door's travel: its own size along the move direction, less the lip,
    and the lip is -4."""
    return (box_hi[2] - box_lo[2]) + 4.0


def swept_is_rock(bsp: Bsp, box_lo, box_hi, up: bool) -> tuple:
    """Is the volume a pane moves through SOLID in the compiled map?"""
    travel = travel_of(box_lo, box_hi)
    bad = 0
    total = 0
    z0 = box_hi[2] + 4.0 if up else box_lo[2] - travel + 4.0
    z1 = box_hi[2] + travel if up else box_lo[2]
    z = z0
    while z < z1 - 1.0:
        y = box_lo[1] + 4.0
        while y < box_hi[1] - 1.0:
            x = box_lo[0] + 4.0
            while x < box_hi[0] - 1.0:
                total += 1
                if not bsp.solid((x, y, z)):
                    bad += 1
                x += 8.0
            y += 8.0
        z += 8.0
    return bad, total


def machinery_ok(bsp: Bsp, shape: str, panes: int, plates: int) -> tuple:
    """Every entity the shape is supposed to have, every key it is supposed to
    carry, and nothing else."""
    doors = bsp.entities("func_door")
    buttons = bsp.entities("func_button")
    speakers = bsp.entities("target_speaker")
    booms = bsp.entities("func_explosive")
    say = []

    if booms:
        say.append(f"{len(booms)} func_explosive - the game deletes those")

    if shape == "window":
        if doors or buttons or speakers:
            say.append(f"{len(doors)} doors, {len(buttons)} buttons,"
                       f" {len(speakers)} speakers on a pane that is a WORLD"
                       f" brush")
        return (not say), "; ".join(say) or "no entity at all, as it should be"

    if len(doors) != panes:
        say.append(f"{len(doors)} func_door for {panes} pane(s)")
    keys_want = {
        "door": {"classname", "model", "angle", "lip", "speed", "wait"},
        "plate": {"classname", "model", "angle", "lip", "speed", "wait",
                  "targetname"},
        "shot": {"classname", "model", "angle", "lip", "speed", "wait",
                 "sounds", "health", "target"},
    }[shape]
    for d in doors:
        extra = set(d) - keys_want
        missing = keys_want - set(d)
        if extra or missing:
            say.append(f"door keys {sorted(set(d))}"
                       f" want {sorted(keys_want)}")
            break
        if d["angle"] not in ("-1", "-2"):
            say.append(f"angle {d['angle']} is neither up nor down")
        if d["lip"] != "-4":
            say.append(f"lip {d['lip']} leaves a strip of glass")
    if shape == "door":
        if len(buttons) or len(speakers):
            say.append("a door that opens by itself needs no machinery")
    if shape == "plate":
        names = {d.get("targetname") for d in doors}
        if len(names) != 1:
            say.append(f"a row has to share one name, got {sorted(names)}")
        if not buttons:
            say.append("no plate to step on")
        if len(buttons) > 2:
            say.append(f"{len(buttons)} plates for one pane")
        for b in buttons:
            if set(b) != {"classname", "model", "angle", "lip", "wait",
                          "target"}:
                say.append(f"plate keys {sorted(set(b))}")
                break
            if b.get("target") not in names:
                say.append(f"a plate wired to {b.get('target')}"
                           f" and not to {sorted(names)}")
            if b["angle"] != "-2" or b["lip"] != "4" or b["wait"] != "1":
                say.append(f"plate moves {b['angle']}/{b['lip']}/{b['wait']}")
        if speakers:
            say.append("a plate makes no glass noise")
    if shape == "shot":
        if len(speakers) != panes:
            say.append(f"{len(speakers)} speakers for {panes} pane(s)")
        wanted = {d.get("target") for d in doors}
        named = {s.get("targetname") for s in speakers}
        if wanted != named:
            say.append(f"doors fire {sorted(wanted)},"
                       f" speakers answer to {sorted(named)}")
        for d in doors:
            if d.get("health") != GLASS_HEALTH:
                say.append(f"health {d.get('health')}")
            w = d.get("wait")
            #
            # It COMES BACK, and that is the point.
            #
            # This used to demand `wait -1` - shot out and gone for the match -
            # which is exactly what the PO asked to be rid of on 2026-09-11:
            # «Выстрел опускает стекло, а как его обратно поднять - непонятно.
            # Нужно, чтобы оно само поднималось, и не ровно через 10 секунд, а
            # варьировалось от карты к карте - от 2 до 30».
            #
            if not (w and w.isdigit()
                    and SHOT_WAIT_MIN <= int(w) <= SHOT_WAIT_MAX):
                say.append(f"wait {w} is not {SHOT_WAIT_MIN}..{SHOT_WAIT_MAX}"
                           f" seconds - it never comes back")
            if d.get("sounds") != "1":
                say.append("a door noise over the glass")
        for s in speakers:
            if s.get("noise") != BRKGLAS:
                say.append(f"noise {s.get('noise')}")
            if s.get("attenuation") != "1":
                say.append(f"attenuation {s.get('attenuation')}")
            org = [float(v) for v in s.get("origin", "0 0 0").split()]
            if bsp.solid(org):
                say.append(f"the speaker at {s.get('origin')} is in rock -"
                           f" a positioned sound nobody hears")
        if buttons:
            say.append("a shot pane needs no plate")
    return (not say), "; ".join(say) or (
        f"{len(doors)} door(s), {len(buttons)} plate(s),"
        f" {len(speakers)} speaker(s), every key the stock game reads")


def pane_boxes(b) -> list:
    """One box per CONTENTS_WINDOW brush, off its own six planes."""
    out = []
    for first, count, contents in b.brushes:
        if not contents & 0x2:
            continue
        lo = [-1e9] * 3
        hi = [1e9] * 3
        for s in range(first, first + count):
            pl = b.planes[b.brushsides[s][0]]
            for a in range(3):
                if pl[a] > 0.99:
                    hi[a] = min(hi[a], pl[3])
                elif pl[a] < -0.99:
                    lo[a] = max(lo[a], -pl[3])
        if all(hi[a] > lo[a] for a in range(3)):
            out.append((lo, hi))
    return out


def construction_ok(b, map_text: str, name: str, shape: str,
                    panes: int) -> None:
    """«стекло - это часть физической поверхности... и у него должна быть рама».

    Six things, each one of them something the PO asked for in words, and each one
    read out of the COMPILED file or the .map the operator wrote - never out of
    the plan.
    """
    boxes = sorted(pane_boxes(b), key=lambda p: (p[0][0], p[0][1], p[0][2]))
    if not check(f"{name}: the panes are boxes the file can be read from",
                 len(boxes) == panes, f"{len(boxes)} for {panes}"):
        return

    # 1 EIGHT thick, which is base1's own number and the cure for the shimmer
    thicks = []
    thins = []
    for lo, hi in boxes:
        size = [hi[a] - lo[a] for a in range(3)]
        axis = size.index(min(size))
        thins.append(axis)
        thicks.append(round(size[axis]))
    check(f"{name}: every pane is {PANE_THICK:.0f} thick - base1's own number,"
          f" not the 16 and 32 that shimmered",
          all(v == PANE_THICK for v in thicks), f"thicknesses {thicks}")

    # 2 the FRAME, proud of the wall on both faces, wearing the donor's metal
    frame_faces = sum(1 for line in map_text.splitlines()
                      if FRAME_TEXTURE in line)
    check(f"{name}: there is a FRAME, and it wears the donor's own metal",
          frame_faces >= 6 * 4,
          f"{frame_faces} {FRAME_TEXTURE} sides in the map the operator wrote")

    thin = thins[0]
    #
    # A MOVING pane is sunk PANE_BURY into the jambs, the sill and the head
    # (`WINDOW_PANE_BURY`), so none of its edge faces lies on the reveal - the
    # coplanar faces the PO saw as «рассыпаются на пиксели». Its compiled box is
    # therefore the opening plus four on every edge, and the questions below that
    # are about the OPENING - the mullion between two, the rail beside one - are
    # asked of the box less that.
    #
    if shape in ("door", "plate", "shot"):
        across_axis = 1 if thin == 0 else 0
        shrunk = []
        for lo, hi in boxes:
            lo = list(lo)
            hi = list(hi)
            lo[across_axis] += PANE_BURY
            hi[across_axis] -= PANE_BURY
            lo[2] += PANE_BURY
            hi[2] -= PANE_BURY
            shrunk.append((lo, hi))
        boxes = shrunk
    run_lo = min(lo[thin] for lo, _ in boxes)
    run_hi = max(hi[thin] for _, hi in boxes)
    mid = 0.5 * (run_lo + run_hi)
    # the frame's own extent along the thin axis, from the .map's metal brushes
    proud = frame_extent(map_text, thin)
    check(f"{name}: the frame stands {FRAME_PROUD:.0f} proud of the wall on"
          f" BOTH faces - a frame flush with the wall is paint",
          proud is not None and proud[0] <= mid - PANE_THICK / 2 - FRAME_PROUD
          and proud[1] >= mid + PANE_THICK / 2 + FRAME_PROUD,
          f"metal spans {proud} on axis {thin}, pane centred at {mid:.0f}")

    # 3 a ROW is one window: 16-unit mullions, not 32 of bare wall
    if panes > 1:
        across = 0 if thin else 1
        if thin == 0:
            across = 1
        gaps = []
        ordered = sorted(boxes, key=lambda p: p[0][across])
        for a, c in zip(ordered, ordered[1:]):
            gaps.append(round(c[0][across] - a[1][across]))
        check(f"{name}: a row is ONE window - {MULLION:.0f}-unit mullions, not"
              f" 32 of bare wall between three holes",
              all(g == MULLION for g in gaps), f"gaps {gaps}")

    # 4 the RAIL: the frame's plate stops short of the glass on each jamb
    check(f"{name}: each jamb leaves an {RAIL:.0f}-wide recessed RAIL beside the"
          f" glass - «по салазкам»", rails_ok(map_text, boxes, thin),
          "the frame's jamb plate stops short of the pane on both sides")

    # 5 the HOUSING: a moving pane slides into a visible box
    if shape in ("door", "plate", "shot"):
        up = any(d.get("angle") == "-1" for d in b.entities("func_door"))
        ok, why = housing_ok(map_text, boxes, thin, up)
        check(f"{name}: the pane slides into a visible HOUSING, not into bare"
              f" rock", ok, why)

    # 6 the plate is 16 tall with a bevel
    if shape == "plate":
        tall = []
        bevelled = 0
        for btn in b.entities("func_button"):
            mb = b.model_box(btn.get("model", ""))
            if not mb:
                continue
            tall.append(round(mb[1][2] - mb[0][2]))
            if (mb[1][0] - mb[0][0]) > 0:
                bevelled += 1
        check(f"{name}: the plate is {PLATE_TALL:.0f} tall with a"
              f" {PLATE_BEVEL:.0f}-unit bevel - nobody noticed an 8-unit flat"
              f" one", bool(tall) and all(v == PLATE_TALL for v in tall),
              f"heights {tall}")

    # and the shot pane COMES BACK
    if shape == "shot":
        waits = {d.get("wait") for d in b.entities("func_door")}
        ok = all(w is not None and w.isdigit()
                 and SHOT_WAIT_MIN <= int(w) <= SHOT_WAIT_MAX for w in waits)
        check(f"{name}: a shot pane comes back after this map's own"
              f" {SHOT_WAIT_MIN}..{SHOT_WAIT_MAX} seconds, and it is ONE number"
              f" for the map", ok and len(waits) == 1, f"waits {sorted(waits)}")


def map_brush_boxes(map_text: str, texture: str) -> list:
    """Every brush wearing `texture`, as a box, off its own plane equations.

    NOT off the three points each plane is written with: for an axis-aligned face
    two of the three coordinates of those points are the plane's own basis rather
    than the brush's extent, so a min/max over them answers about the world and
    not about the brush - MEASURED, `0 -512 -512` for a brush that begins at 1240.
    """
    import re as _re
    out = []
    for blk in _re.findall(r"\{[^{}]*\}", map_text):
        if texture not in blk:
            continue
        lo = [-1e9] * 3
        hi = [1e9] * 3
        planes = 0
        for m in _re.finditer(
                r"\(\s*(-?[\d.e+-]+)\s+(-?[\d.e+-]+)\s+(-?[\d.e+-]+)\s*\)"
                r"\s*\(\s*(-?[\d.e+-]+)\s+(-?[\d.e+-]+)\s+(-?[\d.e+-]+)\s*\)"
                r"\s*\(\s*(-?[\d.e+-]+)\s+(-?[\d.e+-]+)\s+(-?[\d.e+-]+)\s*\)",
                blk):
            v = [float(x) for x in m.groups()]
            p0, p1, p2 = v[0:3], v[3:6], v[6:9]
            a = [p1[k] - p0[k] for k in range(3)]
            b = [p2[k] - p0[k] for k in range(3)]
            n = [a[1] * b[2] - a[2] * b[1],
                 a[2] * b[0] - a[0] * b[2],
                 a[0] * b[1] - a[1] * b[0]]
            ln = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5
            if ln < 1e-6:
                continue
            #
            # NEGATED, because a Quake .map states a face's three points
            # clockwise as seen from OUTSIDE the solid, so the cross product
            # points INWARD. MEASURED on the frame's own head band: taken as
            # written it gives z from 112 down to 96, a box with negative
            # height, and `map_brush_boxes` then returned nothing at all.
            #
            n = [-x / ln for x in n]
            d = sum(n[k] * p0[k] for k in range(3))
            planes += 1
            for k in range(3):
                if n[k] > 0.99:
                    hi[k] = min(hi[k], d)
                elif n[k] < -0.99:
                    lo[k] = max(lo[k], -d)
        if planes >= 6 and all(hi[k] > lo[k] for k in range(3)) \
                and all(abs(v) < 1e8 for v in lo + hi):
            out.append((lo, hi))
    return out


def frame_extent(map_text: str, thin: int):
    """How far the metal brushwork reaches along the pane's thin axis."""
    boxes = map_brush_boxes(map_text, FRAME_TEXTURE)
    if not boxes:
        return None
    return (min(b[0][thin] for b in boxes), max(b[1][thin] for b in boxes))


def metal_spans(map_text: str, axis: int) -> list:
    """Every metal brush's extent along one axis."""
    return [(b[0][axis], b[1][axis])
            for b in map_brush_boxes(map_text, FRAME_TEXTURE)]


def rails_ok(map_text: str, boxes, thin: int) -> bool:
    """Are the two JAMB PLATES there, each stopping RAIL short of the glass?

    Constructive rather than an absence test, and that is a correction: the first
    version asked whether any metal brush reaches the pane's own edge, and the
    HOUSING does - it spans the frame's full width by design - so it failed on
    every shape that has one.

    The left jamb plate spans exactly [pane_lo - FRAME_WIDE, pane_lo - RAIL] and
    the right one [pane_hi + RAIL, pane_hi + FRAME_WIDE]. The 8 units between a
    plate and the glass is the recessed strip the pane runs in.
    """
    across = 1 if thin == 0 else 0
    pane_lo = min(lo[across] for lo, _ in boxes)
    pane_hi = max(hi[across] for _, hi in boxes)
    want = ((pane_lo - FRAME_WIDE, pane_lo - RAIL),
            (pane_hi + RAIL, pane_hi + FRAME_WIDE))
    spans = metal_spans(map_text, across)
    for a, b in want:
        if not any(abs(s[0] - a) < 0.5 and abs(s[1] - b) < 0.5 for s in spans):
            return False
    return True


def housing_ok(map_text: str, boxes, thin: int, up: bool) -> tuple:
    """Is there a metal box over the volume the pane sweeps THROUGH?

    Identified by WHERE it is, not by how deep it is. Depth cannot identify it -
    it is 24 deep where the donor has room and falls back to the frame's own 8
    where it does not - and two versions of this test compared depths and were
    tautologies: the frame alone stands further from the PANE's faces than
    `pane/2 + 8`, because the pane is 8 thick in a wall that is 16.

    The pane travels its own height plus four (`lip -4`), downward unless `angle
    -1`. Somewhere in the volume it ends up in there has to be metal, spanning the
    panes' own width: that is the box the player watches it go into.
    """
    across = 1 if thin == 0 else 0
    pane_lo = min(lo[across] for lo, _ in boxes)
    pane_hi = max(hi[across] for _, hi in boxes)
    foot = min(lo[2] for lo, _ in boxes)
    head = max(hi[2] for _, hi in boxes)
    travel = (head - foot) + 4.0
    want_z = (head + travel * 0.5) if up else (foot - travel * 0.5)
    want_c = 0.5 * (pane_lo + pane_hi)
    for lo, hi in map_brush_boxes(map_text, FRAME_TEXTURE):
        if not (lo[2] - 0.5 <= want_z <= hi[2] + 0.5):
            continue
        if not (lo[across] - 0.5 <= want_c <= hi[across] + 0.5):
            continue
        if hi[across] - lo[across] < (pane_hi - pane_lo):
            continue
        return True, (f"a metal box {[round(v) for v in lo]}"
                      f"..{[round(v) for v in hi]} over the volume the pane"
                      f" sweeps {'up' if up else 'down'} into")
    return False, (f"no metal anywhere near {want_c:.0f} at z {want_z:.0f},"
                   f" where a pane sliding {'up' if up else 'down'}"
                   f" {travel:.0f} ends up")


# ---- the cases -------------------------------------------------------------

# One case per shape, and a row case per shape. The seed is what draws the
# shape and the guard ASSERTS what it drew before it looks at the map, so a
# change to the deal shows up as a failure here rather than as a case that
# quietly tests something else.
#
# A door ROW cannot exist and that is a measurement, not an omission: a door
# opens by an approach trigger, `Think_SpawnDoorTrigger` grows the door's box
# by sixty units in x and y and NOT in z (`g_func.c:983`), so a pane 96 units
# up has its trigger 96 units up and a standing player never touches it. A
# door is therefore only dealt where the pane reaches the floor - the glazed
# doorway - and that family cuts exactly one pane.
SHAPE_CASES = [
    ("a plain window in a doorway", 1, 80, "doorway", "window", 1),
    ("a door in a doorway", 2, 80, "doorway", "door", 1),
    ("a plate in a doorway", 9, 80, "doorway", "plate", 1),
    ("a shot pane in a doorway", 5, 80, "doorway", "shot", 1),
    # Seed 4, not 3: at seed 3 the row draws a door, which on a sill is a
    # moving pane now; seed 4 draws plain glass itself (ledger rows 292, 297).
    ("a row of plain windows", 4, 80, "sill", "window", 3),
    ("a row on one plate", 11, 80, "sill", "plate", 3),
    ("a row of shot panes", 1, 80, "sill", "shot", 3),
]


def one_shape(exe: Path, bsp: Path, work: Path, name: str, seed: int,
              ambition: int, where: str, shape: str, panes: int,
              base_faults: int) -> None:
    listing = drive(exe, bsp, "--seed", str(seed), "--ambition",
                    str(ambition), "--list")
    want = [o for o in offers(listing)
            if o["where"] == where and o["shape"] == shape
            and o["panes"] == panes]
    if not check(f"{name}: the plan offers it at seed {seed}", bool(want),
                 want[0]["line"] if want else
                 "; ".join(o["line"] for o in offers(listing))[:200]):
        return
    o = want[0]
    out = work / f"cut_{shape}_{panes}_{seed}.map"
    got = drive(exe, bsp, "--seed", str(seed), "--ambition", str(ambition),
                "--apply", o["edit"], "--out", str(out))
    m = APPLY.search(got)
    if not check(f"{name}: the operator cuts it",
                 bool(m) and m.group(2) == "OK" and m.group(3) == "yes",
                 m.group(0) if m else got[-200:]):
        return
    #
    # The SOURCE fault count is recorded, not asserted.
    #
    # The frame, the rails and the housing are new brushwork, so it rises by
    # construction - MEASURED, 14 to 27 against a fixture's own 0 - and the
    # transaction stopped gating on it in September because the compiler's own
    # FixTjuncs pass stitches the world before anybody sees the map. What the gate
    # reads is the compiled world-against-world T-junction count, and that is
    # asserted below, on the compiled file.
    #
    after = FAULTS.search(got)
    now = int(after.group(1)) if after else -1
    print(f"        {name}: {now} source faults against the fixture's own"
          f" {base_faults} - recorded, not a gate")

    text = out.read_text(encoding="latin1") if out.is_file() else ""
    check(f"{name}: the panes are in the map file",
          glass_lines(text) >= 6 * panes,
          f"{glass_lines(text)} translucent sides for {panes} pane(s)")
    if shape == "plate":
        check(f"{name}: the plate wears metal rather than glass",
              plate_lines(text) >= 6,
              f"{plate_lines(text)} opaque {PLATE_TEXTURE} sides")

    log = compile_map(out)
    cut = out.with_suffix(".bsp")
    if not check(f"{name}: the cut map compiles", cut.is_file(),
                 log.strip().splitlines()[-1][:80] if log.strip() else ""):
        return
    check(f"{name}: and it is still sealed",
          not out.with_suffix(".pts").is_file(), "no pointfile")

    b = Bsp(cut)
    check(f"{name}: the compiler made the panes windows rather than walls",
          b.window_brushes() == panes,
          f"{b.window_brushes()} brushes with CONTENTS_WINDOW"
          f" for {panes} pane(s)")
    check(f"{name}: the panes wear the DONOR's own plain glass, not base1's"
          f" emblem",
          b.pane_textures() == {GLASS_TEXTURE},
          f"translucent textures: {sorted(b.pane_textures())}")
    construction_ok(b, text, name, shape, panes)
    ok, why = machinery_ok(b, shape, panes, o["plates"])
    check(f"{name}: the machinery is exactly what deathmatch keeps", ok, why)

    if shape != "window":
        bad = total = 0
        for d in b.entities("func_door"):
            mb = b.model_box(d.get("model", ""))
            if not mb:
                continue
            n, t = swept_is_rock(b, mb[0], mb[1], d.get("angle") == "-1")
            bad += n
            total += t
        check(f"{name}: every pane is inside rock for its whole travel",
              total > 0 and bad == 0,
              f"{bad} of {total} samples of the swept volume are air"
              f" ({'up' if o['slide'] == 'up' else 'down'})")
    if shape == "plate":
        stands = True
        detail = []
        for btn in b.entities("func_button"):
            mb = b.model_box(btn.get("model", ""))
            if not mb:
                stands = False
                continue
            under = ((mb[0][0] + mb[1][0]) / 2, (mb[0][1] + mb[1][1]) / 2,
                     mb[0][2] - 4.0)
            over = ((mb[0][0] + mb[1][0]) / 2, (mb[0][1] + mb[1][1]) / 2,
                    mb[1][2] + 16.0)
            if not b.solid(under) or b.solid(over):
                stands = False
            detail.append(f"{mb[0][2]:.0f}..{mb[1][2]:.0f}")
        check(f"{name}: the plate lies on the floor with room to stand on it",
              stands, ", ".join(detail) or "no plate at all")


def glass_shapes_static() -> None:
    """The glass a map keeps: fixed, shot, plate - asked of the source.

    The PO, 2026-09-14: «стекла реагировали на выстрелы и на триггеры нажатия ...
    это было топ» (row 290), and on the map row 294 made, where every plain draw
    was a shot pane: «все - только по триггеру ... а вчера часть стекол от
    выстрела открывалось, часть по триггеру + еще было не реагирующее постоянное
    стекло» (row 297). Two rules, each with a controlled RED in memory.
    """
    print("=== the glass a map keeps")
    text = (REPO / "src" / "mapgen" / "mapgen_geometry_edit.c").read_text(
        encoding="utf-8")
    head = ("static void deal_glass_shape(const mapgen_geometry_edit_plan_t *plan,\n"
            "                             uint64_t *stream, const mapgen_bsp_t *donor,\n"
            "                             opening_t *o, const char **why)\n{")

    def body_of(src: str) -> str:
        at = src.find(head)
        return src[at:src.find("\n}\n", at)] if at >= 0 else ""

    plain = ("    if (want == GLASS_WINDOW)\n"
             "        return;\n")
    shot_all = ("    const bool drew_window = want == GLASS_WINDOW;\n"
                "    if (drew_window) {\n"
                "        if (pool < 3u)\n"
                "            return;\n"
                "        want = GLASS_SHOT;\n"
                "    }\n")

    def plain_stays(src: str) -> bool:
        body = body_of(src)
        return plain in body and "drew_window" not in body

    check("a plain-glass draw stays fixed glass", plain_stays(text))
    if check("the plain-glass return to take out is where it says",
             text.count(plain) == 1, f"{text.count(plain)} occurrences"):
        check("RED: every plain draw turned into a shot pane is caught",
              not plain_stays(text.replace(plain, shot_all, 1)))

    moving = ("    const bool drew_door_on_sill = want == GLASS_DOOR && o->sill > 0.0f;\n"
              "    if (drew_door_on_sill)\n"
              "        want = glass_fewer_of_shot_and_plate(plan);\n")
    fixed = ("    if (want == GLASS_DOOR && o->sill > 0.0f) {\n"
             "        *why = \"a door needs a pane at floor level - a window instead\";\n"
             "        return;\n"
             "    }\n")

    def door_moves(src: str) -> bool:
        body = body_of(src)
        return (moving in body
                and "return plate < shot ? (uint32_t)GLASS_PLATE : (uint32_t)GLASS_SHOT;" in src
                and "a door needs a pane at floor level - a window instead" not in body)

    check("a sill window that draws a door takes the fewer of a shot pane and"
          " a plate", door_moves(text))
    if check("the door-on-a-sill branch to take out is where it says",
             text.count(moving) == 1, f"{text.count(moving)} occurrences"):
        check("RED: a sill window's door sent back to fixed glass is caught",
              not door_moves(text.replace(moving, fixed, 1)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    glass_shapes_static()

    src = a.work / "window_hall.map"
    bsp = src.with_suffix(".bsp")
    write_fixture(src)
    out = compile_map(src)
    if not check("the hall with a wall across it compiles", bsp.is_file(),
                 out.strip().splitlines()[-1][:80] if out.strip() else ""):
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1
    check("and it is sealed", not (a.work / "window_hall.pts").is_file(),
          "no pointfile")

    exe = build_driver(REPO, a.work)
    listing = drive(exe, bsp, "--seed", "1", "--ambition", "10", "--list")

    tally = TALLY.search(listing)
    check("the family says what it considered and what it refused",
          tally is not None, tally.group(0).strip() if tally else listing[-300:])

    edits = OFFER.findall(listing)
    check("the wall across the middle is offered", bool(edits),
          f"{len(edits)} offered"
          + (f"; {tally.group(3).strip()}" if tally else ""))

    # The RED: the hall's outer walls are the same shape and the same size as
    # the one across its middle, and the only thing beyond them is the void.
    # A window into nothing is not a window, and this is what says the trace
    # is deciding rather than the geometry happening to fit.
    if tally:
        refused = re.search(r"(\d+) a space on one side only", tally.group(3))
        beyond = re.search(r"(\d+) no room beyond", tally.group(3))
        void = (refused and int(refused.group(1)) > 0) \
            or (beyond and int(beyond.group(1)) > 0)
        check("a wall with nothing but void behind it is refused - the RED",
              bool(void), tally.group(3).strip())

    before = FAULTS.search(drive(exe, bsp, "--seed", "1", "--ambition", "10"))
    base_faults = int(before.group(1)) if before else -1

    if not edits:
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1

    for name, seed, amb, where, shape, panes in SHAPE_CASES:
        one_shape(exe, bsp, a.work, name, seed, amb, where, shape, panes,
                  base_faults)

    # ---- the direction is MEASURED: the same hall, the wall off the floor --
    panel_src = a.work / "window_panel.map"
    write_fixture(panel_src, panel=True)
    panel_log = compile_map(panel_src)
    panel_bsp = panel_src.with_suffix(".bsp")
    if check("the hall whose wall stands on nothing compiles",
             panel_bsp.is_file(),
             panel_log.strip().splitlines()[-1][:80]):
        listing = drive(exe, panel_bsp, "--seed", "1", "--ambition", "80",
                        "--list")
        moving = [o for o in offers(listing) if o["shape"] != "window"]
        if check("a pane with nothing under it is still dealt as a machine",
                 bool(moving),
                 "; ".join(o["line"] for o in offers(listing))[:200]):
            o = moving[0]
            check("and it slides UP, because the rock is over it and not"
                  " under it", o["slide"] == "up", o["line"])
            cut = a.work / "cut_panel.map"
            got = drive(exe, panel_bsp, "--seed", "1", "--ambition", "80",
                        "--apply", o["edit"], "--out", str(cut))
            m = APPLY.search(got)
            if check("the operator cuts the panel wall",
                     bool(m) and m.group(2) == "OK", m.group(0) if m else ""):
                compile_map(cut)
                if cut.with_suffix(".bsp").is_file():
                    b = Bsp(cut.with_suffix(".bsp"))
                    bad = total = 0
                    for d in b.entities("func_door"):
                        mb = b.model_box(d.get("model", ""))
                        if mb:
                            n, t = swept_is_rock(b, mb[0], mb[1],
                                                 d.get("angle") == "-1")
                            bad += n
                            total += t
                    check("and the pane it hung there is inside rock all the"
                          " same", total > 0 and bad == 0,
                          f"{bad} of {total} samples air")

    # ---- the wall that is thicker where the row's later panes are ---------
    #
    # The one the delivered maps caught and this fixture could not: a
    # speaker looked for 32 units on ONE side of the run lands inside a
    # buttress, and a positioned sound in a solid leaf reaches nobody.
    butt_src = a.work / "window_buttress.map"
    write_fixture(butt_src, buttress=True)
    butt_log = compile_map(butt_src)
    butt_bsp = butt_src.with_suffix(".bsp")
    if check("the hall with a buttress against its wall compiles",
             butt_bsp.is_file(), butt_log.strip().splitlines()[-1][:80]):
        #
        # The ROW does not grow over the buttress.
        #
        # It used to: the row extension proved the run solid at every pane and
        # never proved AIR outside the later ones, so the second and third panes
        # were cut in front of the buttress and looked into rock - MEASURED in
        # the delivered mg_glass (2026-09-11), whose middle pane sat in solid on
        # both faces. Now every extra pane has to have air 4 units outside both
        # faces, as the first one has. Asserted over every offer of 24 seeds,
        # and CONTRASTED with the same hall without the buttress, which still
        # grows a row - so the buttress, and nothing else, is what stops it.
        #
        over = []
        shot = None
        for seed in range(1, 25):
            listing = drive(exe, butt_bsp, "--seed", str(seed), "--ambition",
                            "80", "--list")
            for o in offers(listing):
                m = re.search(r"open (-?\d+)\.\.(-?\d+)", o["line"])
                if m and o["panes"] > 1:
                    lo, hi = float(m.group(1)), float(m.group(2))
                    last_hi = hi + (o["panes"] - 1) * ((hi - lo) + MULLION)
                    if last_hi > BUTTRESS_Y + 0.5:
                        over.append(f"seed {seed}: {o['line']}")
                if shot is None and o["shape"] == "shot":
                    shot = (seed, o)
        check("no row grows over the buttress, where rock would stand behind"
              " a pane", not over,
              "; ".join(over[:2]) if over
              else f"24 seeds, every pane of every row short of y {BUTTRESS_Y}")
        plain_rows = []
        for seed in range(1, 9):
            listing = drive(exe, bsp, "--seed", str(seed), "--ambition", "80",
                            "--list")
            plain_rows += [o for o in offers(listing) if o["panes"] > 1]
        check("and the same hall WITHOUT the buttress still grows a row - the"
              " buttress is what stops it", bool(plain_rows),
              plain_rows[0]["line"] if plain_rows else "no row in 8 seeds")
        if check("a shot pane is still offered on the buttressed wall",
                 shot is not None,
                 f"seed {shot[0]}: {shot[1]['line']}" if shot
                 else "no shot pane in 24 seeds"):
            seed, o = shot
            cut = a.work / "cut_buttress.map"
            got = drive(exe, butt_bsp, "--seed", str(seed), "--ambition",
                        "80", "--apply", o["edit"], "--out", str(cut))
            m = APPLY.search(got)
            if check("the operator cuts the buttressed wall",
                     bool(m) and m.group(2) == "OK" and m.group(3) == "yes",
                     m.group(0) if m else got[-200:]):
                compile_map(cut)
                if cut.with_suffix(".bsp").is_file():
                    b = Bsp(cut.with_suffix(".bsp"))
                    ok, why = machinery_ok(b, "shot", o["panes"], 0)
                    check("every pane's shatter is in AIR even where the wall"
                          " is thicker than the run", ok, why)

    # ---- the retired pane is still built when the seam asks ---------------
    listing = drive(exe, bsp, "--seed", "1", "--ambition", "80", "--list",
                    "--breakable")
    broke = [o for o in offers(listing) if o["shape"] == "breakable"]
    if check("the seam still reaches base1's breakable pane", bool(broke),
             "; ".join(o["line"] for o in offers(listing))[:200]):
        cut = a.work / "cut_breakable.map"
        drive(exe, bsp, "--seed", "1", "--ambition", "80", "--apply",
              broke[0]["edit"], "--out", str(cut), "--breakable")
        compile_map(cut)
        if cut.with_suffix(".bsp").is_file():
            b = Bsp(cut.with_suffix(".bsp"))
            booms = b.entities("func_explosive")
            check("and it is base1's to the value - which is why the game"
                  " deletes it in deathmatch",
                  bool(booms)
                  and all(x.get("health") == GLASS_HEALTH for x in booms)
                  and all(x.get("mass") == GLASS_MASS for x in booms),
                  f"{len(booms)} func_explosive: "
                  + "; ".join(f"health {x.get('health')} mass {x.get('mass')}"
                              for x in booms[:3]))

    # ---- what the FIDELITY moves ------------------------------------------
    seen = {}
    for amb in (10, 25, 40, 80):
        listing = drive(exe, bsp, "--seed", "11", "--ambition", str(amb),
                        "--list")
        plates = [o for o in offers(listing)
                  if o["where"] == "sill" and o["shape"] == "plate"]
        seen[amb] = plates[0]["out"] if plates else None
    check("how far the plate lies from the pane reads the fidelity",
          seen.get(25) is not None and seen.get(80) is not None
          and max(seen[80]) > max(seen[25]),
          "; ".join(f"F{100 - k}: {v}" for k, v in seen.items()))

    # ---- and two rules that are never broken over a sweep -----------------
    doors_off_floor = []
    machines_nowhere = []
    for seed in range(1, 25):
        for amb in (10, 40, 80):
            for o in offers(drive(exe, bsp, "--seed", str(seed), "--ambition",
                                  str(amb), "--list")):
                if o["shape"] == "door" and o["sill"] > 0.0:
                    doors_off_floor.append((seed, amb, o["line"]))
                if o["shape"] not in ("window", "breakable") \
                        and o["slide"] not in (None, "up", "down"):
                    machines_nowhere.append((seed, amb, o["line"]))
    check("no door is ever dealt where the pane is off the floor",
          not doors_off_floor,
          f"{len(doors_off_floor)} of 72 listings"
          + (f": {doors_off_floor[0][2]}" if doors_off_floor else ""))
    check("no pane is ever dealt as a machine with nowhere to go",
          not machines_nowhere,
          f"{len(machines_nowhere)} of 72 listings")

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
