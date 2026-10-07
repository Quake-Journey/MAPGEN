"""Are the panes ALIVE after the map spawns, in DEATHMATCH? Asked of a
HEADLESS dedicated server - no window, no video, no sound.

The guard that would have caught the defect of 2026-09-10. `mg_glass`, `mg_90`
and `mg_20` each carried a correct pane in the BSP - the entity string, the
`CONTENTS_WINDOW` brush, base1's own texture and health - and the PO loaded
them and said «не вижу никаких стёкол нигде». Every check in this tree read
the lump; none of them asked the running game. `SP_func_explosive` frees
itself at spawn when `deathmatch` is set (`src/game/g_misc.c:740`, id's own
code), q2dm1 is played as a deathmatch map, and the pane was gone before his
first frame.

    python tools/check_mapgen_glass_alive.py mg_90 mg_75 ...
    python tools/check_mapgen_glass_alive.py mg_glass --expect-none

NO WINDOW EVER APPEARS, and that is the second lesson of the same day: the
first version of this guard started the CLIENT, and the PO was at his machine
while it ran - «не нужно мне экраны эти открывать». The client cannot be
hidden (`src/windows/client.c:215` shows its window unconditionally), so this
runs a DEDICATED server instead, created with `STARTF_USESHOWWINDOW` and
`SW_HIDE` plus its own console, and the guard ENUMERATES that process's
top-level windows every 100 ms and fails the case if one of them is ever
visible.

The proof is the SERVER's own, not the file's:

    `emit_gamestate` (`src/server/mvd.c:612`) walks every edict from 1 to
    `ge->num_edicts` and writes each one's packed state into the MVD stream,
    with `MSG_ES_REMOVE` for the ones that are not in use. `G_FreeEdict`
    memsets the edict (`g_utils.c:380`), so a pane the game deleted is a
    REMOVE record with no model, and a live `func_door` carries its
    modelindex. The same gamestate carries the configstrings, which is how
    that index becomes the `*N` string the BSP knows - `modelindex` is a
    configstring SLOT resolved by name (`PF_ModelIndex`,
    `src/server/game.c:354`) and not the N of `*N`.

    `mvdrecord` needs `sv_mvd_enable 1` (latched, so it goes on the command
    line) and writes the gamestate as soon as the stream is active;
    `sv_mvd_suspend_time 0` is what makes it active on a server with no
    players (`check_players_activity`, `mvd.c:891`).

    `dumpents` is NOT used and must not be: it prints the entity STRING out
    of the BSP (`src/server/commands.c:466`), which is exactly the evidence
    that lied last time.

The client-demo parser is kept beside the MVD one because the two are
independent readings of the same fact, and the demos recorded before the
guard went headless are what proved the MVD parser right: 4 of 4 panes alive
in the new mg_glass and 0 of 1 in the old one, both ways.

Every run carries the standing agent flags - `q2prox_config_readonly 1` so it
cannot touch the PO's config and `net_clientport -1` so it cannot take the
client port from under his own game - and the guard hashes his four config
files immediately before the launch and asserts them unchanged after it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as load_guard          # noqa: E402

from mapgen_load_guard import game_dir  # noqa: E402  (brief 13 W1: the game folder of this run)
RELEASE = Path(game_dir()).parent
EXE = RELEASE / "Q2PRO-X.exe"
MAPS = RELEASE / "baseq2" / "maps"
DEMOS = RELEASE / "baseq2" / "demos"
DUMPS = RELEASE / "baseq2" / "condumps"

# The PO's own settings. `q2prox_config_readonly 1` on the command line is the
# barrier; these are hashed immediately BEFORE each launch and asserted
# unchanged after it, because the barrier is code and a hash is evidence. Per
# Hard Rule #9 the hash is taken fresh every run - he edits these between
# runs, so a session-start snapshot is stale and "restoring" it would destroy
# what he just set.
PO_CONFIGS = (
    RELEASE / "baseq2" / "q2pro-x" / "q2pro-x.local.cfg",
    RELEASE / "baseq2" / "q2pro-x" / "q2pro-x.cfg",
    RELEASE / "baseq2" / "q2pro-x" / "q2pro-x.bindings.cfg",
    RELEASE / "baseq2" / "q2config.cfg",
)


def config_hashes() -> dict:
    out = {}
    for f in PO_CONFIGS:
        try:
            out[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
        except OSError:
            out[f.name] = "absent"
    return out

GLASS_TEXTURE = "e1u1/wndow0_3"
PANE_CLASSES = ("func_door", "func_explosive")
# A dig's lift, asked the same question as the glass.
LIFT_CLASSES = ("func_plat",)

# protocol 34, the classic table (inc/common/protocol.h)
SVC_STUFFTEXT = 11
SVC_SERVERDATA = 12
SVC_CONFIGSTRING = 13
SVC_SPAWNBASELINE = 14
LOGNAME = "mgalive"            # our own log, never his console.log

U_ORIGIN1, U_ORIGIN2, U_ANGLE2, U_ANGLE3 = 1 << 0, 1 << 1, 1 << 2, 1 << 3
U_FRAME8, U_EVENT, U_REMOVE, U_MOREBITS1 = 1 << 4, 1 << 5, 1 << 6, 1 << 7
U_NUMBER16, U_ORIGIN3, U_ANGLE1, U_MODEL = 1 << 8, 1 << 9, 1 << 10, 1 << 11
U_RENDERFX8, U_ANGLE16, U_EFFECTS8, U_MOREBITS2 = (1 << 12, 1 << 13,
                                                   1 << 14, 1 << 15)
U_SKIN8, U_FRAME16, U_RENDERFX16, U_EFFECTS16 = (1 << 16, 1 << 17,
                                                 1 << 18, 1 << 19)
U_MODEL2, U_MODEL3, U_MODEL4, U_MOREBITS3 = (1 << 20, 1 << 21,
                                             1 << 22, 1 << 23)
U_OLDORIGIN, U_SKIN16, U_SOUND, U_SOLID = (1 << 24, 1 << 25,
                                           1 << 26, 1 << 27)
U_MODEL16, U_MOREFX8, U_ALPHA = 1 << 28, 1 << 29, 1 << 30
U_SCALE, U_MOREFX16 = 1 << 32, 1 << 33
U_MOREFX32 = U_MOREFX8 | U_MOREFX16
U_SKIN32 = U_SKIN8 | U_SKIN16
U_EFFECTS32 = U_EFFECTS8 | U_EFFECTS16
U_RENDERFX32 = U_RENDERFX8 | U_RENDERFX16

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


# ---- what the map SAYS it has ----------------------------------------------

def lump(data: bytes, i: int) -> bytes:
    ofs, ln = struct.unpack_from("<ii", data, 8 + 8 * i)
    return data[ofs:ofs + ln]


class Tree:
    """The world model's BSP tree, for one question: is this point solid?"""

    def __init__(self, d: bytes):
        raw = lump(d, 1)
        self.planes = [struct.unpack_from("<4fi", raw, 20 * i)
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

    def solid(self, p) -> bool:
        node = self.models[0][9]
        while node >= 0:
            pl = self.planes[self.nodes[node][0]]
            d = (pl[0] * p[0] + pl[1] * p[1] + pl[2] * p[2]) - pl[3]
            node = self.nodes[node][1] if d >= 0 else self.nodes[node][2]
        return bool(self.leafs[-1 - node][0] & 0x1)


def speakers_of(bsp: Path) -> list:
    """Every glass speaker in the file, with whether its origin is audible."""
    d = bsp.read_bytes()
    tree = Tree(d)
    out = []
    for block in re.findall(r"\{[^}]*\}", lump(d, 0).decode("latin1")):
        keys = dict(re.findall(r'"([^"]*)"\s+"([^"]*)"', block))
        if keys.get("classname") != "target_speaker":
            continue
        if "brkglas" not in keys.get("noise", ""):
            continue
        org = [float(v) for v in keys.get("origin", "0 0 0").split()]
        out.append({"origin": org, "in_rock": tree.solid(org),
                    "targetname": keys.get("targetname", "")})
    return out


def panes_of(bsp: Path, classes=PANE_CLASSES, glass_only=True) -> tuple:
    """Every pane in the file: the submodels whose faces wear base1's glass,
    split into the ones an entity owns and the ones the world does."""
    d = bsp.read_bytes()
    ents = lump(d, 0).decode("latin1")

    raw = lump(d, 5)
    texinfo = [struct.unpack_from("<8fii32si", raw, 76 * i)
               for i in range(len(raw) // 76)]
    #
    # Glass is what the compiler draws TRANSLUCENT, not one texture's name.
    #
    # This asked for base1's `e1u1/wndow0_3` by name, and when the panes moved to
    # the donor's own plain glass on 2026-09-11 it found «0 panes» in every map it
    # was given - and reported every map GREEN, because nothing it could see was
    # dead. A guard keyed on a name the product no longer uses is Hard Rule #46
    # word for word. SURF_TRANS33 | SURF_TRANS66, whatever the skin.
    #
    glassy = {i for i, t in enumerate(texinfo) if t[8] & 0x30}

    # dface_t: planenum(u16) side(i16) firstedge(i32) numedges(i16)
    #          texinfo(i16) styles[4] lightofs(i32) = 20 bytes. The texinfo is
    #          field FOUR; reading field three finds `numedges` and matches
    #          nothing, which is how the first run of this guard reported that
    #          a map with a pane in it had none.
    raw = lump(d, 6)
    faces = [struct.unpack_from("<Hhi2h4Bi", raw, 20 * i)
             for i in range(len(raw) // 20)]
    raw = lump(d, 13)
    models = [struct.unpack_from("<9f3i", raw, 48 * i)
              for i in range(len(raw) // 48)]
    raw = lump(d, 1)
    planes = [struct.unpack_from("<4fi", raw, 20 * i)
              for i in range(len(raw) // 20)]
    raw = lump(d, 14)
    brushes = [struct.unpack_from("<iii", raw, 12 * i)
               for i in range(len(raw) // 12)]
    raw = lump(d, 15)
    brushsides = [struct.unpack_from("<Hh", raw, 4 * i)
                  for i in range(len(raw) // 4)]

    def glass_faces(model: int) -> int:
        if model >= len(models):
            return 0
        first, count = models[model][10], models[model][11]
        return sum(1 for f in faces[first:first + count]
                   if f[4] in glassy)

    def window_boxes() -> list:
        """One box per CONTENTS_WINDOW brush, off its own six planes: one
        brush is one pane, whoever owns it."""
        out = []
        for first, count, contents in brushes:
            if not contents & 0x2:
                continue
            lo = [-1e9] * 3
            hi = [1e9] * 3
            for s in range(first, first + count):
                pl = planes[brushsides[s][0]]
                for a in range(3):
                    if pl[a] > 0.99:
                        hi[a] = min(hi[a], pl[3])
                    elif pl[a] < -0.99:
                        lo[a] = max(lo[a], -pl[3])
            if all(hi[a] > lo[a] for a in range(3)):
                out.append((lo, hi))
        return out

    owned = []
    for block in re.findall(r"\{[^}]*\}", ents):
        keys = dict(re.findall(r'"([^"]*)"\s+"([^"]*)"', block))
        spec = keys.get("model", "")
        if keys.get("classname") not in classes or not spec.startswith("*"):
            continue
        n = int(spec[1:])
        #
        # A PANE has to wear glass; a LIFT does not wear anything in particular.
        #
        # `glass_only` is what separates the two, and it is why the first attempt
        # at counting lifts found «0 of 0 in the file» on a map whose entity lump
        # plainly holds three `func_plat`: the filter asked whether the submodel
        # had a translucent face, which no deck has.
        #
        if not glass_only or glass_faces(n) > 0:
            owned.append({"model": spec, "classname": keys["classname"],
                          "keys": keys})
    # The world's panes: every window brush whose middle is not inside some
    # submodel's own box.
    submodels = []
    for o in owned:
        m = models[int(o["model"][1:])]
        submodels.append((list(m[0:3]), list(m[3:6])))
    world = 0
    for lo, hi in window_boxes():
        mid = [(lo[a] + hi[a]) / 2 for a in range(3)]
        if any(all(s[0][a] - 1 <= mid[a] <= s[1][a] + 1 for a in range(3))
               for s in submodels):
            continue
        world += 1
    return owned, world


# ---- what the running server SENT ------------------------------------------

class Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.at = 0

    def byte(self) -> int:
        v = self.d[self.at]
        self.at += 1
        return v

    def short(self) -> int:
        v = struct.unpack_from("<h", self.d, self.at)[0]
        self.at += 2
        return v

    def word(self) -> int:
        v = struct.unpack_from("<H", self.d, self.at)[0]
        self.at += 2
        return v

    def long(self) -> int:
        v = struct.unpack_from("<i", self.d, self.at)[0]
        self.at += 4
        return v

    def string(self) -> str:
        end = self.d.index(b"\0", self.at)
        v = self.d[self.at:end].decode("latin1")
        self.at = end + 1
        return v

    def left(self) -> int:
        return len(self.d) - self.at


def parse_baseline(r: Reader, extended: bool = False) -> dict:
    """MSG_ParseEntityBits + MSG_ParseDeltaEntity.

    The classic table, which is what a client demo of protocol 34 carries and
    what an MVD stream carries unless the server's own configstring space is
    the extended one. `MSG_ES_UMASK` and `MSG_ES_BEAMORIGIN` - the two flags
    an MVD stream always sets - change only WHICH bits the writer chooses,
    never a field's size (`src/common/msg.c:599`, `681`).
    """
    bits = r.byte()
    if bits & U_MOREBITS1:
        bits |= r.byte() << 8
    if bits & U_MOREBITS2:
        bits |= r.byte() << 16
    if bits & U_MOREBITS3:
        bits |= r.byte() << 24
    number = r.word() if bits & U_NUMBER16 else r.byte()

    ent = {"number": number, "modelindex": 0, "origin": [0.0, 0.0, 0.0],
           "solid": 0, "bits": bits}
    wide = extended and bits & U_MODEL16
    read = r.word if wide else r.byte
    if bits & U_MODEL:
        ent["modelindex"] = read()
    if bits & U_MODEL2:
        read()
    if bits & U_MODEL3:
        read()
    if bits & U_MODEL4:
        read()
    if bits & U_FRAME8:
        r.byte()
    if bits & U_FRAME16:
        r.word()
    if (bits & U_SKIN32) == U_SKIN32:
        r.long()
    elif bits & U_SKIN8:
        r.byte()
    elif bits & U_SKIN16:
        r.word()
    if (bits & U_EFFECTS32) == U_EFFECTS32:
        r.long()
    elif bits & U_EFFECTS8:
        r.byte()
    elif bits & U_EFFECTS16:
        r.word()
    if (bits & U_RENDERFX32) == U_RENDERFX32:
        r.long()
    elif bits & U_RENDERFX8:
        r.byte()
    elif bits & U_RENDERFX16:
        r.word()
    for a in range(3):
        if bits & (U_ORIGIN1, U_ORIGIN2, U_ORIGIN3)[a]:
            ent["origin"][a] = r.short() * 0.125
    for a in range(3):
        if bits & (U_ANGLE1, U_ANGLE2, U_ANGLE3)[a]:
            r.short() if (extended and bits & U_ANGLE16) else r.byte()
    if bits & U_OLDORIGIN:
        for _ in range(3):
            r.short()
    if bits & U_SOUND:
        r.word() if extended else r.byte()
    if bits & U_EVENT:
        r.byte()
    if bits & U_SOLID:
        ent["solid"] = r.long() if extended else r.word()
    if extended:
        if bits & U_MOREFX32 == U_MOREFX32:
            r.long()
        elif bits & U_MOREFX8:
            r.byte()
        elif bits & U_MOREFX16:
            r.word()
        if bits & U_ALPHA:
            r.byte()
        if bits & U_SCALE:
            r.byte()
    return ent


def read_gamestate(demo: Path) -> tuple:
    """The configstrings and the baselines the server really sent."""
    data = demo.read_bytes()
    at = 0
    strings = {}
    baselines = []
    protocol = 0
    while at + 4 <= len(data):
        (length,) = struct.unpack_from("<i", data, at)
        at += 4
        if length == -1 or length <= 0 or at + length > len(data):
            break
        block = data[at:at + length]
        at += length
        r = Reader(block)
        while r.left() > 0:
            op = r.byte()
            if op == SVC_SERVERDATA:
                protocol = r.long()
                r.long()            # servercount
                r.byte()            # attract loop
                r.string()          # gamedir
                r.short()           # clientnum
                r.string()          # level name
            elif op == SVC_CONFIGSTRING:
                index = r.word()
                strings[index] = r.string()
            elif op == SVC_SPAWNBASELINE:
                baselines.append(parse_baseline(r))
            elif op == SVC_STUFFTEXT:
                # `precache`, which is the last thing CL_Record_f writes: the
                # gamestate is complete.
                r.string()
                return protocol, strings, baselines, ""
            else:
                # Anything else means the gamestate is over (or the encoding
                # is not the one this parser mirrors): stop rather than
                # guess, and let the caller judge what was collected.
                return protocol, strings, baselines, f"stopped at svc {op}"
        # ... and NOT `if baselines: return`. The gamestate is written in as
        # many blocks as the write buffer needs - MEASURED on mg_glass: four
        # blocks of configstrings, then 79 baselines, then 34 more. Stopping
        # at the first block that carried one reported 0 of 4 panes alive on a
        # map where all four were.
    return protocol, strings, baselines, (
        "" if baselines else "no baselines in the demo")


# ---- the MVD gamestate, which is the server's own record of its edicts ------

MVD_MAGIC = b"MVD2"
MVD_SERVERDATA = 4
SVCMD_BITS = 5
SVCMD_MASK = (1 << SVCMD_BITS) - 1
PROTOCOL_VERSION_MVD = 37
MVD_VERSION_EXTENDED_LIMITS = 2011
MVD_VERSION_EXTENDED_LIMITS_2 = 2012
MVD_VERSION_PLAYERFOG = 2013
MVF_EXTLIMITS = 1 << 1
MVF_EXTLIMITS_2 = 1 << 2
CLIENTNUM_NONE = 255

# The two configstring layouts (`inc/shared/shared.h`): which one a stream
# uses is the EXTLIMITS flag's business, and reading the wrong one turns
# «*4» into an empty string.
CS_MODELS_OLD = 32
CS_END_OLD = 2080
CS_MODELS_EXT = 62
CS_END_EXT = 13630

PPS_M_TYPE, PPS_M_ORIGIN, PPS_M_ORIGIN2 = 1 << 0, 1 << 1, 1 << 2
PPS_VIEWOFFSET, PPS_VIEWANGLES, PPS_VIEWANGLE2 = 1 << 3, 1 << 4, 1 << 5
PPS_KICKANGLES, PPS_BLEND, PPS_FOV = 1 << 6, 1 << 7, 1 << 8
PPS_WEAPONINDEX, PPS_WEAPONFRAME = 1 << 9, 1 << 10
PPS_GUNOFFSET, PPS_GUNANGLES = 1 << 11, 1 << 12
PPS_RDFLAGS, PPS_STATS, PPS_MOREBITS = 1 << 13, 1 << 14, 1 << 15
PPS_FOG = 1 << 17


def skip_playerstate(r: Reader, ext2: bool) -> None:
    """One player record of an MVD gamestate, by its own bit table
    (`MSG_WriteDeltaPlayerstate_Packet`, `src/common/msg.c:1463`). Nothing in
    it is wanted - the point is to reach the ENTITIES behind it."""
    pflags = r.word()
    if ext2 and pflags & PPS_MOREBITS:
        pflags |= r.byte() << 16
    if pflags & PPS_M_TYPE:
        r.byte()
    if pflags & PPS_M_ORIGIN:
        r.short(), r.short()
    if pflags & PPS_M_ORIGIN2:
        r.short()
    if pflags & PPS_VIEWOFFSET:
        r.at += 3
    if pflags & PPS_VIEWANGLES:
        r.short(), r.short()
    if pflags & PPS_VIEWANGLE2:
        r.short()
    if pflags & PPS_KICKANGLES:
        r.at += 3
    if pflags & PPS_WEAPONINDEX:
        r.byte()
    if pflags & PPS_WEAPONFRAME:
        r.byte()
    if pflags & PPS_GUNOFFSET:
        r.at += 3
    if pflags & PPS_GUNANGLES:
        r.at += 3
    if pflags & PPS_BLEND:
        r.at += 4
    if pflags & PPS_FOG:
        raise ValueError("a playerstate with fog: this stream is newer than"
                         " the guard's reader")
    if pflags & PPS_FOV:
        r.byte()
    if pflags & PPS_RDFLAGS:
        r.byte()
    if pflags & PPS_STATS:
        statbits = struct.unpack_from("<I", r.d, r.at)[0]
        r.at += 4
        for i in range(32):
            if statbits & (1 << i):
                r.short()


def read_mvd_gamestate(path: Path) -> tuple:
    """The configstrings and the entity states the SERVER wrote."""
    data = path.read_bytes()
    if data[:4] != MVD_MAGIC:
        return 0, {}, [], f"not an MVD file: {data[:4]!r}"
    at = 4
    (length,) = struct.unpack_from("<H", data, at)
    at += 2
    if not length or at + length > len(data):
        return 0, {}, [], "the MVD has no gamestate block"
    r = Reader(data[at:at + length])

    head = r.byte()
    if head & SVCMD_MASK != MVD_SERVERDATA:
        return 0, {}, [], f"the first MVD message is {head & SVCMD_MASK}"
    flags = head >> SVCMD_BITS
    protocol = r.long()
    version = r.word()
    if version >= MVD_VERSION_EXTENDED_LIMITS:
        flags = r.word()
    extended = bool(flags & MVF_EXTLIMITS)
    ext2 = bool(flags & MVF_EXTLIMITS_2)
    r.long()                      # spawncount
    r.string()                    # gamedir
    r.short()                     # the dummy client's number, or -1

    cs_models = CS_MODELS_EXT if extended else CS_MODELS_OLD
    cs_end = CS_END_EXT if extended else CS_END_OLD
    strings = {}
    while True:
        index = r.word()
        if index >= cs_end:
            break
        strings[index] = r.string()

    # The portal bits, and the count byte is NOT free: `r.at += r.byte()`
    # reads `r.at` BEFORE the call that advances it, so the count byte itself
    # is read twice - which put this parser one byte behind and sent it
    # walking through the player section as if the terminator were a player.
    portalbytes = r.byte()
    r.at += portalbytes

    while True:
        number = r.byte()
        if number == CLIENTNUM_NONE:
            break
        skip_playerstate(r, ext2)

    baselines = []
    while r.left() > 0:
        ent = parse_baseline(r, extended)
        if not ent["number"]:
            break
        if ent["bits"] & U_REMOVE:
            continue              # an edict that is not in use
        baselines.append(ent)
    return protocol, strings, baselines, ("" if baselines
                                          else "no live edicts in the MVD")


# ---- one watched launch, and it opens nothing --------------------------------

def free_port() -> int:
    """A UDP port nothing is using, from the OS."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def visible_windows(pid: int) -> list:
    """Every VISIBLE top-level window of this process, by enumeration.

    Not a promise that the flags worked - a measurement of it. The PO's screen
    is the contract.
    """
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            found.append(f"{cls.value}:{title.value}")
        return True

    user32.EnumWindows(each, 0)
    return found


def launch(name: str, seconds: int) -> tuple:
    """One headless dedicated server, watched for windows, and the MVD it
    wrote."""
    mvd = DEMOS / f"alive_{name}.mvd2"
    log = RELEASE / "baseq2" / "logs" / f"{LOGNAME}.log"
    for f in (mvd, log):
        if f.exists():
            f.unlink()
    argv = [
        str(EXE),
        "+set", "dedicated", "1",
        "+set", "q2prox_config_readonly", "1",
        "+set", "net_clientport", "-1",
        # A port of our own, asked of the OS: the PO's own game holds 27910,
        # and a dedicated server that cannot bind its port is a FATAL error -
        # which is how the first run of this guard put a dialog on his
        # screen.
        "+set", "net_port", str(free_port()),
        # ... and if anything else goes fatal, exit instead of opening a
        # MessageBox or sleeping on a console prompt forever
        # (`src/windows/system.c:818`).
        "+set", "sys_exitonerror", "1",
        "+set", "deathmatch", "1",
        "+set", "sv_mvd_enable", "1",
        "+set", "sv_mvd_suspend_time", "0",
        "+set", "logfile_name", LOGNAME,
        "+set", "logfile", "2",
        "+map", name,
        "+mvdrecord", f"alive_{name}",
        "+wait", "20",
        "+mvdstop",
        "+quit",
    ]

    # No window, and then PROVE no window: hidden show-state plus a console of
    # its own, so the AllocConsole in Sys_ConsoleInit finds one already there
    # and returns.
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0                      # SW_HIDE
    flags = subprocess.CREATE_NEW_CONSOLE

    before = config_hashes()
    began = time.time()
    seen = []
    proc = load_guard.popen(argv, cwd=str(RELEASE), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL,
                            startupinfo=startup, creationflags=flags)
    while proc.poll() is None:
        if time.time() - began > seconds:
            proc.kill()
            return (None, f"the server did not exit within {seconds}s",
                    before, config_hashes(), seen)
        now = visible_windows(proc.pid)
        for w in now:
            if w not in seen:
                seen.append(w)
        if now:
            # Nothing of ours may sit on his screen. Not a report - a kill.
            proc.kill()
            break
        time.sleep(0.1)
    took = time.time() - began
    after = config_hashes()
    if not mvd.is_file():
        return (None, f"no MVD after {took:.0f}s - it never recorded",
                before, after, seen)
    return mvd, f"{took:.0f}s", before, after, seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("maps", nargs="*")
    ap.add_argument("--bsp", type=Path, action="append", default=[])
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--keep-demo-parser", action="store_true",
                    help="unused; the client-demo reader stays for reference")
    ap.add_argument("--lifts", type=int, default=None,
                    help="also assert that at least N func_plat edicts are"
                         " alive after spawn - a dig's lift")
    ap.add_argument("--expect-none", action="store_true",
                    help="the RED case: prove a map's panes are all DELETED")
    ap.add_argument("--expect-lost", action="store_true",
                    help="the RED case: prove the game frees a pickup of the"
                         " map at spawn")
    ap.add_argument("--json", type=Path,
                    help="write the per-map counts here, for the README")
    a = ap.parse_args()

    if not EXE.is_file():
        print(f"no client at {EXE}")
        return 2
    DEMOS.mkdir(parents=True, exist_ok=True)
    DUMPS.mkdir(parents=True, exist_ok=True)

    jobs = [(m, MAPS / f"{m}.bsp") for m in a.maps]
    jobs += [(p.stem, p) for p in a.bsp]
    counted = {}

    for name, bsp in jobs:
        if not check(f"{name}: the map is where the game looks for it",
                     bsp.is_file(), str(bsp)):
            continue
        owned, world = panes_of(bsp)
        print(f"        {name}: {len(owned)} pane entities"
              f" ({', '.join(sorted({o['classname'] for o in owned})) or '-'}),"
              f" {world} panes in the world")

        heard = speakers_of(bsp)
        if heard:
            check(f"{name}: every glass speaker stands in air, where a"
                  f" positioned sound is heard",
                  not any(s["in_rock"] for s in heard),
                  "; ".join(f"{s['targetname']} at"
                            f" {[round(v) for v in s['origin']]}"
                            f"{' IN ROCK' if s['in_rock'] else ''}"
                            for s in heard[:4]))

        demo, why, before, after, windows = launch(name, a.seconds)
        check(f"{name}: the run put NOTHING on the screen",
              not windows,
              "; ".join(windows) if windows
              else "no visible window of that process, polled every 100 ms")
        touched = [k for k in before if before[k] != after[k]]
        check(f"{name}: the run left the PO's own settings alone",
              not touched,
              ", ".join(touched) if touched
              else f"{len(before)} config files, hash for hash")
        # Row 302: the pickups the game FREES at spawn. `droptofloor`
        # (g_items.c:890) says so on the server's console, and mg_20e's said
        # it six times - the chaingun, the jacket armour, a box of bullets
        # and three shards inside the resting decks of two lifts - while
        # every lump in the file was right. The PO: «Не нашел где теперь
        # лежит chaingun».
        server_log = RELEASE / "baseq2" / "logs" / f"{LOGNAME}.log"
        freed = (re.findall(r"droptofloor: (\S+) startsolid at \(([^)]*)\)",
                            server_log.read_text(encoding="utf-8",
                                                 errors="replace"))
                 if server_log.is_file() else None)
        said = ("no server log" if freed is None
                else "; ".join(f"{c} at ({o})" for c, o in freed[:6])
                or "no droptofloor line in the server's log")
        if a.expect_lost:
            check(f"{name}: the game FREES a pickup of it at spawn - the RED",
                  bool(freed), said)
        else:
            check(f"{name}: no pickup the file has is freed at spawn",
                  freed is not None and not freed, said)
        if not check(f"{name}: the dedicated server loaded it in deathmatch"
                     f" and recorded its gamestate", demo is not None, why):
            continue
        protocol, strings, baselines, trouble = read_mvd_gamestate(demo)
        check(f"{name}: the stream is the MVD protocol this parser reads",
              protocol == PROTOCOL_VERSION_MVD, f"protocol {protocol}")
        if not check(f"{name}: the gamestate carries baselines",
                     bool(baselines), trouble or f"{len(baselines)} baselines"):
            continue

        base = CS_MODELS_EXT if max(strings, default=0) >= CS_END_OLD \
            else CS_MODELS_OLD
        models = {i - base: s for i, s in strings.items()
                  if base <= i and s.startswith("*")}
        want = {o["model"] for o in owned}
        alive = {}
        for b in baselines:
            spec = models.get(b["modelindex"], "")
            if spec in want:
                alive.setdefault(spec, []).append(b)
        counted[name] = (len(alive), len(owned), world)

        #
        # The LIFTS, when the caller asked for them.
        #
        # `SP_func_plat` has no deathmatch branch - read, not assumed - but so
        # had `func_door`, and the round before this one shipped three maps whose
        # panes the stock game deleted while every lump in them was perfect. The
        # only answer that counts is the one the running game gives.
        #
        if a.lifts is not None:
            plats, _ = panes_of(bsp, LIFT_CLASSES, glass_only=False)
            plat_want = {o["model"] for o in plats}
            plat_alive = {}
            for b in baselines:
                spec = models.get(b["modelindex"], "")
                if spec in plat_want:
                    plat_alive.setdefault(spec, []).append(b)
            check(f"{name}: at least {a.lifts} func_plat edict(s) are ALIVE"
                  f" after spawn in deathmatch",
                  len(plat_alive) >= a.lifts,
                  f"{len(plat_alive)} of {len(plats)} in the file;"
                  + "; ".join(f" {k} solid {x[0]['solid']}"
                              for k, x in sorted(plat_alive.items())[:4]))
            check(f"{name}: and every live lift is a solid the player rides",
                  bool(plat_alive) and all(x[0]["solid"] != 0
                                           for x in plat_alive.values()),
                  "; ".join(f"{k} solid {x[0]['solid']}"
                            for k, x in sorted(plat_alive.items())[:4]))

        detail = (f"{len(alive)} of {len(owned)} alive; "
                  + "; ".join(f"{k} at "
                              f"{tuple(round(v, 0) for v in x[0]['origin'])}"
                              f" solid {x[0]['solid']}"
                              for k, x in sorted(alive.items())[:4]))
        if a.expect_none:
            check(f"{name}: the game DELETED every pane - the RED",
                  len(owned) > 0 and not alive,
                  detail + f" (models known: {len(models)})")
        elif not owned and a.lifts is not None:
            # A map whose subject is the DIG has no glass in it, and that is not
            # a failure of anything: the lift assertions above are its subject.
            print(f"        {name}: no glass in this map - the lifts above are"
                  f" what it was launched for")
        elif not owned:
            # Every pane is a WORLD brush - the `window` shape - so there is
            # no edict for any game to delete. The safest state there is, and
            # it is a PASS as long as the map really has glass in it.
            check(f"{name}: every pane is part of the WORLD, so there is"
                  f" nothing here for any game to delete", world > 0,
                  f"{world} window brushes in the world model")
        else:
            check(f"{name}: every pane the file has is ALIVE after spawn in"
                  f" deathmatch",
                  len(alive) == len(owned), detail)
            check(f"{name}: and every live pane is a solid the player runs"
                  f" into", bool(alive) and all(x[0]["solid"] != 0
                                                for x in alive.values()),
                  "; ".join(f"{k} solid {x[0]['solid']}"
                            for k, x in sorted(alive.items())[:4]))

    print()
    for name, (alive, owned, world) in counted.items():
        print(f"  {name}: {alive} of {owned} pane edicts alive,"
              f" {world} panes in the world")
    if a.json:
        a.json.write_text(json.dumps(
            {name: {"alive": alive, "panes": owned, "world_faces": world}
             for name, (alive, owned, world) in counted.items()}, indent=1),
            encoding="utf-8")
        print(f"  counts written to {a.json}")
    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
