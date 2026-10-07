"""Every gate a generated map passes before it is installed for the PO, asked of the file itself.

Rounds 34 to 36 ran these from the session's scratch folder, and on 2026-09-15 that folder was wiped while round 36's
pipeline ran: two gates never ran and the chain's console was lost (ledger row 312). The PO, 2026-09-13: «если есть
служебные скрипты то их нужно хранить там где ничего не чистится». They live here now.

    python tools/mapgen_delivery_gates.py CANDIDATE.bsp --job JOB [--donor q2dm1.bsp] [--work DIR] [--only a,b]
    python tools/mapgen_delivery_gates.py --selftest [--work DIR]

One PASS or FAIL line per gate; exit 1 on any failure:

  pickups   a weapon_chaingun in the entity lump (the PO missed it on mg_20e); the transaction's lost-pickup oracle
            finds no pickup lost at spawn and no spawn blocked by a mover (rows 302, 307)
  glass     the mix the PO asked for: a moving pane (a func_door whose brush model has a translucent face) that opens
            when SHOT (it carries health), one ON A PLATE (a func_button targets it), and more fixed translucent world
            faces than the donor has (rows 294, 297)
  hall      the halls the plan dealt are built (rows 310, 313): the recut driver built from this tree lists the plan
            on the job's own baseline at the job's seed and ambition; for every hall on a dig the job accepted, along
            each level axis the hall spans 176 units or more, the line through its centre holds a run of points 4
            apart that are air in the map and rock in the donor, at least that span less 16. At least one such hall.
            A square of new air proves nothing: a passage's own segments side by side make one (row 313).
  annex     the annex rooms the plan dealt are built (row 315): every annex on a dig the job accepted - a dig with its
            place as one end and a box holding its room, its own or the wing it was joined into (row 324) - is new
            air across its middle on both level axes, and a
            pickup stands where the plan moved one to, inside it in the file - of whatever class, since a later
            swap-item may trade it (row 320) - worth the walk: 5 or more by the generator's own table (row 379,
            `PICKUP_WORTH`; the PO: «у игроков должна быть цель заходить в неё»). At least two.
  clips     no player-clip brush stands beside space the generator opened - rock in the donor, air in the map, 12 out
            from one of its faces (row 337: q2dm1's beams left in a doorway the PO could pass only along a jamb)
  light     the map is lit like its donor (rows 405, 408; Fable's briefs 5 L4 and 6): the faces both maps draw - the
            same texture, the same box - keep their light per orientation (within 0.8..1.25 of the donor's), and every
            accepted dig's new faces are lit like the donor round its doors (512): level 0.8..1.25, tint (G/R, B/R)
            within 0.15, the light's unevenness not under 0.8 of the door's, the ceiling not over 1.15 of the floor
  digwalls  every accepted dig is dug (row 343): inside its box no new space open sideways to the old map more than 176
            over the donor's floor, and nothing it built standing in the old air more than 64 over that floor - other
            edits' boxes aside (a window, a flood); the old map is the job's rebuilt baseline, the map the digs were
            dug into (row 405)
  sky       nothing new is seen through the sky (row 351): no point of new space in an accepted dig's box that a
            point under a sky face sees - its cluster in that point's PVS - along a line that first leaves the air
            inside a sky brush
  storeys   the rooms of two storeys the plan dealt are built (row 327): every storey on a dig the job accepted - a
            dig whose two ends are its place below and its place above - is new air across its middle on both level
            axes; its terrace is solid 8 under its top and half way down to the room's floor, with air 32 over it;
            the middle tread of its flight is solid 8 under its top, with no rock over it from 32 up to 32 under the
            room's ceiling; and a pickup stands where the plan moved one, inside the room. At least one.
  eye       the PO's eye at 920 65 718 (row 297): the visgate oracle, from exactly that eye, loses no pair the donor
            showed round the stair under corridor 12
  stair     the same box from the oracle's own lattice of eyes: no pair lost
  finished  lit, with visibility data
  water     no vertical liquid face
  reach     the reach gate PASS
  axes      every drawn face wears its texture
  static    panes, lifts, sounds and every accepted dig's mouths (`check_mapgen_static.py --digs`)

Every binary is built from this tree into the work folder.

--selftest asks the questions this tool brought of inputs that must FAIL them: round 36's plan and job against round
35's map (the two long tunnels, dealt without halls); the annexes today's plan deals on round 36's baseline against
round 36's map, which has none; the storeys today's plan deals on round 38's baseline against mg_20k, which has none;
the glass of q2dm1 itself; and the eye of mg_20d, which carried the hole. A gate that passes those is not a gate.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as guard  # noqa: E402
from check_mapgen_static import Bsp, SURF_TRANS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
from mapgen_load_guard import game_dir  # noqa: E402  (brief 13 W1: the game folder of this run)
MAPS = Path(game_dir()) / "maps"
ROUND35 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round35\s3")
ROUND36 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round36\s3")
ROUND40_S7 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round40\s3_7")
ROUND41_1020 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round41\s3_1020\job")
ROUND42_42 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round42\s3_42\job")
ROUND47_42 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round47\s3_42")
STOREY_RED = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round39\storeys_red_dryrun")
STOREY_GREEN = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round39\storeys_dryrun")
ROUND38 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round38\s3")
GATES = ["pickups", "glass", "hall", "annex", "storeys", "stairways", "clips", "digwalls", "sky", "eye", "stair",
         "finished", "light", "water", "reach", "axes", "static", "starts"]
LIGHT_BAND = (0.8, 1.25)        # row 405 (L4): a shared face's light per orientation, against the donor's
EYE = ["920", "65", "718"]
STAIR_BOX = ["700", "-60", "630", "1120", "300", "900"]
GROW = "256"
SURF_WARP = 0x8
HALL_SPAN = 176.0
ANNEX_MIN = 2
# Row 377's table, the generator's `pickup_worth` (src/mapgen/mapgen_geometry_edit.c) - the dig guard's case 7 holds
# the two equal. An annex is dealt only for a pickup of ANNEX_WORTH_MIN or more, and a swap does not trade it away.
PICKUP_WORTH = {
    "item_quad": 10, "item_invulnerability": 10, "weapon_bfg": 10,
    "weapon_railgun": 9, "item_armor_body": 9,
    "weapon_rocketlauncher": 8, "item_armor_combat": 8, "item_health_mega": 8,
    "weapon_hyperblaster": 7, "item_power_shield": 7,
    "weapon_grenadelauncher": 6, "weapon_chaingun": 6, "item_armor_jacket": 6,
    "weapon_supershotgun": 5, "item_power_screen": 5, "item_adrenaline": 5,
    "item_pack": 5, "weapon_machinegun": 4, "item_bandolier": 4,
    "weapon_shotgun": 3,
}
ANNEX_WORTH_MIN = 5
STOREYS_MIN = 1
NUM = r"(-?\d+)"
DIG = re.compile(r"^\s*\d+\s+dig\s+ACCEPTED\s+\d+\s+(-?\d+) (-?\d+) (-?\d+)\s+(-?\d+) (-?\d+) (-?\d+)"
                 r"\s+from (-?\d+) (-?\d+) (-?\d+) to (-?\d+) (-?\d+) (-?\d+)(?: shape (\S+))?( air)?", re.M)
HEAD = re.compile(r"^# \S+ fidelity (\d+) seed (\d+)", re.M)
PLAN_OPTIONS = re.compile(r"^# plan-options (.+)$", re.M)    # brief 11: the run's options that change the plan
OFFERED = re.compile(r"^  dig offered: (-?\d+) (-?\d+) (-?\d+) \(.*?\) -> (-?\d+) (-?\d+) (-?\d+) \(")
HALL_LINE = re.compile(r"^  dig hall: segment \d+ (-?\d+) (-?\d+) (-?\d+) \.\. (-?\d+) (-?\d+) (-?\d+)$")
ANNEX_LINE = re.compile(r"^  dig annex: room " + " ".join([NUM] * 3) + r" \.\. " + " ".join([NUM] * 3)
                        + " off " + " ".join([NUM] * 3) + r" through (\d+) of wall(, built in air)?$", re.M)
ANNEX_MOVE = re.compile(r"^  dig annex moves: (\S+) from " + " ".join([NUM] * 3) + " to "
                        + " ".join([NUM] * 3) + "$", re.M)
T3 = " ".join([NUM] * 3)
STOREY_LINE = re.compile(r"^  dig storeys: room " + T3 + r" \.\. " + T3 + " from " + T3 + " below, " + T3 + " above$",
                         re.M)
STOREY_PARTS = re.compile(r"^  dig storeys terrace: " + T3 + r" \.\. " + T3 + "; flight " + T3 + r" \.\. " + T3
                          + r", (\d+) treads$", re.M)
STOREY_MOVE = re.compile(r"^  dig storeys moves: (\S+) from " + T3 + " to " + T3 + "$", re.M)
LOST = re.compile(r"(\d+) eyes, (\d+) pairs LOST")
# brief 11 step 1: where a carried room came from - «base» (a room-copy of the donor) or «second»
COPY_SOURCE = re.compile(r"^  dig room-of source: (base|second) off " + T3 + " from " + T3 + r" \.\. " + T3 + "$", re.M)


def copy_sources(text: str) -> list:
    """Each carried room's door (the dig's `from`), the map it came from and its box there."""
    return [{"which": m.group(1), "host": [float(v) for v in m.groups()[1:4]],
             "src": [float(v) for v in m.groups()[4:10]]} for m in COPY_SOURCE.finditer(text)]


def job_sources(job: Path | None, text: str) -> list:
    """The copies' sources of the re-dealt plan and of every round the run wrote (job/sources.txt)."""
    more = (job / "sources.txt").read_text(encoding="utf-8", errors="replace") if job and (job / "sources.txt").is_file() \
        else ""
    return copy_sources(text + "\n" + more)


def judged_source(d: dict, sources: list, donor: Path):
    """
    Brief 13 W2: the original a carried room is judged against, and a note of how much of it is under the sky.
    Measured on q2dm1 20/42 (b12's job, the post steps alone): judged by their DOORS, the three copies of sky-lit
    originals that passed against them (96 %, 100 % and 16 % of their plan under the sky) failed - on tint, on a
    ceiling over the floor - while the one copy that fails (1504 1312 768, flat: contrast 1.41 against 1.87) came from
    a LAMP-lit room (0 % under the sky). The door rule fixed nothing and broke three: the judgement stays with the
    original, the sky is said; the deal tries sky-lit rooms last (`room_sky_lit`).
    """
    src = source_of(d, sources, donor)
    if not src:
        return None, ""
    from mapgen_light_profile import SKY_LIT_SHARE, sky_share
    share = sky_share(src[0], src[1])
    return src, (f"; original {share:.0%} under the sky" if share >= SKY_LIT_SHARE else "")


def source_of(d: dict, sources: list, donor: Path):
    """A carried dig's original: (the map, its box) - None for any other dig."""
    if d.get("shape") not in ("room-copy", "room-of"):
        return None
    for s in sources:
        if all(abs(s["host"][i] - d["from"][i]) <= 1.0 for i in range(3)):
            src_map = donor if s["which"] == "base" else SECOND
            return (src_map, s["src"]) if src_map else None
    return None


# brief 11 D1: the stairways the plan dealt (`deal_stairways`), and the ledger's accepted ones by their box
STAIRWAY_LINE = re.compile(r"^  stairway (\d+): foot " + T3 + " top " + T3 + r", (\d+) steps (\d+) wide, "
                           r"(meets a ledge|holds a pickup)$", re.M)
STAIRWAY_LANDING = re.compile(r"^  stairway (\d+) landing: " + T3 + r" \.\. " + T3 + "$", re.M)
STAIRWAY_MOVE = re.compile(r"^  stairway (\d+) moves: (\S+) from " + T3 + " to " + T3 + "$", re.M)
STAIRWAY_ACCEPTED = re.compile(r"^\s*\d+\s+stairway\s+ACCEPTED\s+\d+\s+" + T3 + r"\s+" + T3, re.M)

SECOND: Path | None = None      # brief 9: the run's second map, for the plan re-dealt here
CASES = 0
FAILED = 0
_LISTINGS: dict = {}


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    # brief 11 D2: the checks asked again of a map put in ruins are named apart (MAPGEN_GATE_PREFIX)
    print(f"  {'PASS' if ok else 'FAIL'}  {os.environ.get('MAPGEN_GATE_PREFIX', '')}{name}"
          + (f"  -- {detail}" if detail else ""), flush=True)
    if not ok:
        FAILED += 1
    return ok


def run(argv: list, timeout: int = 3600) -> tuple[int, str]:
    r = guard.run([str(a) for a in argv], capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def tail(text: str, n: int = 220) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1].strip()[:n] if lines else "no output"


def accepted_others(job: Path) -> list[list]:
    """Row 343: the boxes of every accepted edit that is not a dig."""
    text = (job / "ledger.txt").read_text(encoding="utf-8", errors="replace")
    return [[float(m.group(i)) for i in range(2, 8)] for m in re.finditer(
        r"^\s*\d+\s+(\S+)\s+ACCEPTED\s+\d+\s+(-?\d+) (-?\d+) (-?\d+)\s+(-?\d+) (-?\d+) (-?\d+)", text, re.M)
        if m.group(1) != "dig"]


def walls_reference(job: Path, donor: Path) -> Path:
    """Row 405 (brief 5 W4.1): the map a dig was dug INTO - the job's rebuilt baseline, compiled by the same compiler
    as the candidate - not the donor. mg_q3t2's four «open high» points at -184 1720 440..488 lie exactly on the corner
    edge of a pier (x -184, y 1720): q3t2.bsp counts the edge as rock, the rebuilt baseline - before any dig - as air.
    No carve of the dig reaches them (probed on the replay). The rebuild's own residue is the faithful and sealing
    gates' to judge."""
    base = sorted((job / "baseline").glob("*.bsp"))
    return base[0] if base else donor


def ask_digwalls(bsp: Path, job: Path, donor: Path) -> tuple[bool, str]:
    from check_mapgen_dig_walls import open_high, solid_in_air, said as walls_said
    digs, others = accepted_digs(job), accepted_others(job)
    donor = walls_reference(job, donor)
    # row 405: an annex BUILT in air stands in the old air by design - its shell is the building; its room is still
    # asked whether it opens high to the old map
    built = [d for d in digs if d.get("air")]
    high = open_high(bsp, digs, donor, others)
    standing = solid_in_air(bsp, [d for d in digs if not d.get("air")], donor, others + [d["box"] for d in built])
    return (not high and not standing,
            f"{len(digs)} digs: {len(high)} points open high" + (f" ({walls_said(high)})" if high else "")
            + f"; {len(standing)} points standing in the old air" + (f" ({walls_said(standing)})" if standing else ""))


def ask_light(bsp: Path, job: Path | None, donor: Path, work: Path | None = None) -> tuple[bool, str]:
    """Row 405 (Fable's brief 5 L4): «нет вообще лайтмапов или почти нет» - the PO on mg_q3t2, whose new rooms were
    lit 3 to 10 against the donor's 44. Read face by face (`mapgen_light_ratio.faces`): the mean of the lump hides a
    black room under a bright courtyard."""
    from mapgen_light_ratio import shared_ratios
    bad, said = [], []
    for kind, r in shared_ratios(bsp, donor).items():
        said.append(f"{kind} {r:.2f}")
        if not LIGHT_BAND[0] <= r <= LIGHT_BAND[1]:
            bad.append(f"{kind} {r:.2f}")
    # row 408 (Fable's brief 6 decision 4): every dug room against the light round its doors - its level as a whole,
    # its tint, the unevenness of its light, its ceiling not clearly over its floor (`room_against_door`); the old
    # «60 % of the donor's mean» let white rooms twice the door's level through
    from mapgen_light_profile import room_against_door, room_against_source
    digs = static_digs(job, work) if job and work else (accepted_digs(job) if job else [])
    text, err = plan_listing(job, work) if job and work else ("", "")
    sources = job_sources(job, text if not err else "")
    # brief 12 L2: rooms the room-light step found lit by their doors (their own lights at nothing still over the band)
    lit_by_door = []
    if job and (job / "lit" / "door_lit.txt").is_file():
        for line in (job / "lit" / "door_lit.txt").read_text(encoding="utf-8").splitlines():
            m = re.match(r"door-lit ((?:-?\d+ ){6})with (\S+) without (\S+)", line)
            if m:
                lit_by_door.append(([float(v) for v in m.group(1).split()], m.group(3)))
    rooms = []
    for d in digs:
        doors = [d["from"]] if d.get("own_room_end") == "to" else [d["from"], d["to"]]
        # brief 11 step 1: a room carried whole is lit like its original, not like the corridor at its door
        src, sky = judged_source(d, sources, donor)
        lit, how = room_against_source(bsp, src[0], d["box"], src[1]) if src else \
            room_against_door(bsp, donor, d["box"], doors)
        how += sky
        door = next((alone for box, alone in lit_by_door if all(abs(box[i] - d["box"][i]) <= 1.0 for i in range(6))),
                    None)
        level = re.search(r"all (\d+)/(\d+)", how)
        over = bool(level) and int(level.group(1)) / max(1, int(level.group(2))) > 1.25
        if not lit and door and over:
            how += f"; lit by its door - with none of its own lights {door}, over the band by the door's light alone"
            lit = True
        # brief 12 L1, the decision: a carried room is judged by its level and contrast against its original; its
        # tint is said, never failed on - q2dm1's courtyard copied underground stayed B/R 0.77..0.82 for 0.12 with its
        # panels in the original's colour and its lights recoloured (rows 412m, 412n)
        if not lit and src and " - " in how:
            faults = how.split(" - ", 1)[1].split(" | ")[0]
            if all(f.strip().startswith("tint") for f in faults.split(";") if f.strip()):
                how += " (tint said, not judged: a carried room)"
                lit = True
        rooms.append(f"{d.get('shape') or 'dig'} at {coords(d['box'][:3])}: {how}")
        if not lit:
            bad.append(rooms[-1])
    return (not bad, f"shared faces {', '.join(said)} (0.8..1.25); {len(rooms)} dug rooms against their doors"
                     + (f": {'; '.join(rooms)}" if rooms else ""))   # brief 14 F4: every room, not the first 8


def ask_sky(bsp: Path, job: Path, donor: Path) -> tuple[bool, str]:
    from check_mapgen_sky_portal import seen_through_sky, said as sky_said
    digs = accepted_digs(job)
    found, nv, nt = seen_through_sky(bsp, digs, donor)
    return (not found, f"{len(digs)} digs, {nv} viewers under the sky, {nt} points of new space, {len(found)} seen"
                       f" through it" + (f": {sky_said(found)}" if found else ""))


def accepted_digs(job: Path) -> list[dict]:
    text = (job / "ledger.txt").read_text(encoding="utf-8", errors="replace")
    return [{"box": [float(m.group(i)) for i in range(1, 7)],
             "from": [float(m.group(i)) for i in (7, 8, 9)],
             "to": [float(m.group(i)) for i in (10, 11, 12)],
             "shape": m.group(13) or "", "air": bool(m.group(14))} for m in DIG.finditer(text)]


def coords(v: list) -> str:
    return " ".join(f"{x:.0f}" for x in v)


def annex_on(accepted: list, a: dict) -> bool:
    """Row 324: an annex is on an accepted dig that has its place as one end and a box holding its room - its own
    dig, or the wing it was joined into."""
    host, room = a["ends"][:3], a["room"]
    return any(any(all(abs(end[i] - host[i]) <= 1.0 for i in range(3)) for end in (d["from"], d["to"]))
               and all(d["box"][i] - 1.0 <= room[i] and room[3 + i] <= d["box"][3 + i] + 1.0 for i in range(3))
               for d in accepted)


def dealt_on(accepted: list, ends: list) -> bool:
    return any(all(abs(d["from"][a] - ends[a]) <= 1.0 and abs(d["to"][a] - ends[3 + a]) <= 1.0
                   for a in range(3)) for d in accepted)


# ---- pickups -------------------------------------------------------------------------------------------------------
def prebuilt(name: str) -> Path | None:
    """Brief 10 (D2): a helper the released Studio ships built (engine/helpers, named by MAPGEN_HELPERS) - a user has
    no C compiler; on the authors' machine the helper is built from this tree as before."""
    folder = os.environ.get("MAPGEN_HELPERS", "")
    exe = Path(folder) / name if folder else None
    return exe if exe and exe.is_file() else None


def gate_pickups(bsp: Path, work: Path, donor: Path | None = None) -> None:
    chain = [e.get("origin") for e in Bsp(bsp).ents if e.get("classname") == "weapon_chaingun"]
    check("pickups: the chaingun is in the map", bool(chain), f"at {chain}" if chain else "none")
    from check_mapgen_lost_pickup import build, ask
    exe = prebuilt("lost_pickup_oracle.exe") or work / "lost_pickup_oracle.exe"
    err = ""
    if not prebuilt("lost_pickup_oracle.exe"):
        exe.unlink(missing_ok=True)
        err = build(REPO, exe)
    if err:
        check("pickups: the lost-pickup oracle builds", False, err[:220])
        return
    n_lost, lost, n_blocked, blocked, _ = ask(exe, bsp)
    # row 404: a pickup the donor itself loses - the same class at the same place - is the donor's, not the
    # generator's: cor's own ammo_grenades at (435, -1843, 232) and ammo_rockets at (307, -1715, 386) start inside
    # the floor and never appear in the game. Said on the line; one the donor does not lose still fails.
    inherited = {}
    if donor and donor.is_file() and (lost or blocked):
        _, d_lost, _, d_blocked, _ = ask(exe, donor)
        inherited = {k: v for k, v in list(lost.items()) + list(blocked.items()) if k in d_lost or k in d_blocked}
    own_lost = {k: v for k, v in lost.items() if k not in inherited}
    own_blocked = {k: v for k, v in blocked.items() if k not in inherited}
    said = "; ".join(f"{c} at {o} {i}" for (c, o), i in list(own_lost.items())[:3] + list(own_blocked.items())[:2])
    if inherited:
        said = (said + "; " if said else "") + "the donor's own, lost there too: " + "; ".join(
            f"{c} at {o}" for (c, o) in list(inherited)[:4])
    # the oracle's own counts, less what the donor loses too - an oracle that did not answer (-1) fails
    n_own_lost = n_lost - (len(lost) - len(own_lost))
    n_own_blocked = n_blocked - (len(blocked) - len(own_blocked))
    check("pickups: none lost at spawn, no spawn in a mover's column",
          n_lost >= 0 and n_blocked >= 0 and n_own_lost == 0 and n_own_blocked == 0,
          f"{n_own_lost} lost, {n_own_blocked} blocked" + (f": {said}" if said else ""))


# ---- glass ---------------------------------------------------------------------------------------------------------
def glass_mix(bsp: Path) -> dict:
    b = Bsp(bsp)
    targeted = {e["target"] for e in b.ents if e.get("classname") == "func_button" and e.get("target")}
    mix = {"shot": 0, "plate": 0, "other": 0,
           "buttons": sum(1 for e in b.ents if e.get("classname") == "func_button")}
    for e in b.ents:
        model = e.get("model", "")
        if e.get("classname") != "func_door" or not model.startswith("*") or not model[1:].isdigit():
            continue
        mi = int(model[1:])
        if mi >= len(b.models) or not any(b.face_flags(f) & SURF_TRANS for f in b.model_faces(mi)):
            continue
        try:
            health = float(e.get("health", "0") or "0")
        except ValueError:
            health = 0.0
        if health > 0.0:
            mix["shot"] += 1
        elif e.get("targetname") in targeted:
            mix["plate"] += 1
        else:
            mix["other"] += 1
    mix["fixed"] = sum(1 for f in b.model_faces(0)
                       if b.face_flags(f) & SURF_TRANS and not b.face_flags(f) & SURF_WARP)
    return mix


def ask_glass(bsp: Path, donor: Path, job: Path | None = None) -> tuple[bool, str]:
    m, d = glass_mix(bsp), glass_mix(donor)
    # brief 9 section 5: the panes are asked of a map whose edits put windows in - a map whose plan dealt none (or
    # none of them was accepted) has nothing to be asked, and a FAIL there said a check, not the map, was wrong
    if job is not None and (job / "ledger.txt").is_file():
        ledger = (job / "ledger.txt").read_text(encoding="utf-8", errors="replace")
        windows = len(re.findall(r"^\s*\d+ window\s+ACCEPTED", ledger, re.M))
        if windows == 0:
            return True, (f"no window edit accepted in this map, nothing to ask; {m['fixed']} fixed glass faces in the"
                          f" world, the donor {d['fixed']}")
    return (m["shot"] > 0 and m["plate"] > 0 and m["fixed"] > d["fixed"],
            f"{m['shot']} shot, {m['plate']} on a plate ({m['buttons']} func_button), {m['other']} other moving"
            f" panes; {m['fixed']} fixed glass faces in the world, the donor {d['fixed']}")


# ---- the plan: halls and annexes -----------------------------------------------------------------------------------
def plan_listing(job: Path, work: Path, tree: Path = REPO) -> tuple[str, str]:
    """The plan the pipeline dealt from, as the recut driver built from this tree lists it on the job's own baseline
    at the job's seed and ambition 100 - fidelity - once per job and work folder. Called directly: the recut guard's
    `drive` adds `--recuts`, which the product does not deal. `tree` is the working tree unless a selftest asks a
    sandbox's (row 346), each tree's driver and listing kept apart."""
    key = (str(job), str(work), str(tree))
    if key in _LISTINGS:
        return _LISTINGS[key]
    ledger = (job / "ledger.txt").read_text(encoding="utf-8", errors="replace")
    head = HEAD.search(ledger)
    opts = PLAN_OPTIONS.search(ledger)
    base = sorted((job / "baseline").glob("*.bsp"))
    if not head or not base:
        return "", f"no fidelity and seed in {job / 'ledger.txt'}, or no map in {job / 'baseline'}"
    from check_mapgen_recut import build_driver
    if tree != REPO:
        work = work / tree.name
        work.mkdir(parents=True, exist_ok=True)
    try:
        exe = (prebuilt("recut_driver.exe") if tree == REPO else None) or build_driver(tree, work)
    except SystemExit as e:
        return "", str(e)
    rc, out = run([exe, base[0], "--seed", head.group(2), "--ambition", str(100 - int(head.group(1))), "--list"]
                  + (["--second", str(SECOND)] if SECOND else []) + (opts.group(1).split() if opts else []))
    (work / "plan_list.txt").write_text(out, encoding="utf-8")
    _LISTINGS[key] = (out, "" if rc == 0 else f"the recut driver exited {rc}: {tail(out)}")
    return _LISTINGS[key]


def plan_halls(text: str) -> list:
    """Each `dig hall` line with the two ends of the `dig offered` before it."""
    halls, ends = [], None
    for line in text.splitlines():
        m = OFFERED.match(line)
        if m:
            ends = [float(v) for v in m.groups()]
            continue
        h = HALL_LINE.match(line)
        if h and ends:
            halls.append((ends, [float(v) for v in h.groups()]))
    return halls


def plan_annexes(text: str) -> list:
    """Each annex: its room, the place it opens off, its two ends as the dig report prints them, and its move."""
    # row 405: «, built in air» closes the line of an annex the generator built in the map's free air
    found = [m for m in ANNEX_LINE.finditer(text)]
    rooms = [[float(v) for v in m.groups()[:-1]] for m in found]
    moves = [(m.group(1), [float(v) for v in m.groups()[1:]]) for m in ANNEX_MOVE.finditer(text)]
    if len(rooms) != len(moves):
        return []
    out = []
    for r, m, (cls, mv) in zip(rooms, found, moves):
        room, host = r[:6], r[6:9]
        mid = [0.5 * (room[0] + room[3]), 0.5 * (room[1] + room[4]), host[2]]
        out.append({"room": room, "ends": host + mid, "cls": cls, "from": mv[:3], "to": mv[3:],
                    "air": bool(m.group(m.re.groups))})
    return out


def building_built(cand: Bsp, donor: Bsp, box: list, host: list) -> tuple[bool, str]:
    """Row 405 (brief 5 W2): an annex BUILT in the map's free air is no new air - the donor had air there too - but a
    building: along the line through its middle on its long axis, air in the map at every 16; over it a roof, solid
    in the map 8 over its ceiling where the donor had air; and its back wall - the face away from the place it opens
    off - solid 8 out at its middle."""
    lo, hi = box[:3], box[3:]
    mid = [(lo[a] + hi[a]) / 2.0 for a in range(3)]
    long_ax = 0 if hi[0] - lo[0] >= hi[1] - lo[1] else 1
    inside = roof = 0
    asked = 0
    t = lo[long_ax] + 16.0
    while t < hi[long_ax] - 8.0:
        p = list(mid)
        p[long_ax] = t
        p[2] = lo[2] + 48.0
        inside += 0 if cand.solid(p) else 1
        r = list(p)
        r[2] = hi[2] + 8.0
        roof += 1 if cand.solid(r) and not donor.solid(r) else 0
        asked += 1
        t += 16.0
    back_ax = 1 - long_ax
    out = hi[back_ax] + 8.0 if abs(host[back_ax] - lo[back_ax]) < abs(host[back_ax] - hi[back_ax]) else lo[back_ax] - 8.0
    b = list(mid)
    b[back_ax] = out
    back = cand.solid(b)
    ok = asked > 0 and inside == asked and roof == asked and back
    return ok, f"built in air: {inside}/{asked} air inside, {roof}/{asked} roof, back wall {'solid' if back else 'OPEN'}"


def plan_storeys(text: str) -> list:
    """Each storey (row 327): its room, its two places, its terrace, its flight and its treads, and its move."""
    rooms = [[float(v) for v in m.groups()] for m in STOREY_LINE.finditer(text)]
    parts = [[float(v) for v in m.groups()] for m in STOREY_PARTS.finditer(text)]
    moves = [(m.group(1), [float(v) for v in m.groups()[1:]]) for m in STOREY_MOVE.finditer(text)]
    if not (len(rooms) == len(parts) == len(moves)):
        return []
    return [{"room": r[:6], "ends": r[6:12], "terrace": p[:6], "flight": p[6:12], "treads": int(p[12]),
             "cls": mv[0], "from": mv[1][:3], "to": mv[1][3:]} for r, p, mv in zip(rooms, parts, moves)]


def hall_built(cand: Bsp, donor: Bsp, box: list) -> tuple[bool, str]:
    """Along each level axis the box spans HALL_SPAN or more, the longest run of new air - air in the map, rock in
    the donor - on the line through its centre, 4 units at a time."""
    lo, hi = box[:3], box[3:]
    mid = [(lo[a] + hi[a]) / 2.0 for a in range(3)]
    spans = []
    for a in (0, 1):
        span = hi[a] - lo[a]
        if span < HALL_SPAN:
            continue
        # row 412 (brief 9 D3): a drawn room may hold columns on the line through its middle - the longest run of
        # new air on that line or on one beside it, 64 and 128 off, is the room's
        best = 0.0
        other = 1 - a
        for shift in (0.0, -64.0, 64.0, -128.0, 128.0):
            if not lo[other] + 8.0 < mid[other] + shift < hi[other] - 8.0:
                continue
            length = 0.0
            t = lo[a] + 2.0
            while t < hi[a]:
                p = list(mid)
                p[a] = t
                p[other] = mid[other] + shift
                if not cand.solid(p) and donor.solid(p):
                    length += 4.0
                    best = max(best, length)
                else:
                    length = 0.0
                t += 4.0
        spans.append(("xy"[a], span, best))
    ok = bool(spans) and all(best >= span - 16.0 for _, span, best in spans)
    return ok, ", ".join(f"{best:.0f} of {span:.0f} new across {ax}" for ax, span, best in spans) or \
        f"no level axis spans {HALL_SPAN:.0f}"


def ask_hall(bsp: Path, job: Path, donor: Path, work: Path, tree: Path = REPO) -> tuple[bool, str]:
    text, err = plan_listing(job, work, tree)
    if err:
        return False, err
    halls = plan_halls(text)
    accepted = accepted_digs(job)
    mine = [(ends, box) for ends, box in halls if dealt_on(accepted, ends)]
    cand, don = Bsp(bsp), Bsp(donor)
    built, said = 0, []
    for ends, box in mine:
        ok, how = hall_built(cand, don, box)
        built += 1 if ok else 0
        said.append(f"{coords(box[:3])} .. {coords(box[3:])} on {coords(ends[:3])} -> {coords(ends[3:])}"
                    f" {'built' if ok else 'NOT BUILT'} ({how})")
    # row 335: a plan that dealt no hall on an accepted dig is not refused for it
    return (built == len(mine),
            f"{len(halls)} halls in the plan, {len(mine)} on accepted digs, {built} built"
            + (": " + "; ".join(said[:6]) if said else " - no hall dealt, nothing to build"))


def ask_annex(bsp: Path, job: Path, donor: Path, work: Path, accepted_only: bool = True,
              listing: str | None = None) -> tuple[bool, str]:
    """`listing`: a plan listing to ask instead of the one this tree's driver deals on the job (the selftest asks
    mg_20r with its own)."""
    text, err = (listing, "") if listing is not None else plan_listing(job, work)
    if err:
        return False, err
    annexes = plan_annexes(text)
    accepted = accepted_digs(job)
    mine = [a for a in annexes if not accepted_only or annex_on(accepted, a)]
    cand, don = Bsp(bsp), Bsp(donor)
    built, worthy, said = 0, 0, []
    for a in mine:
        air, how = (building_built(cand, don, a["room"], a["ends"][:3]) if a.get("air")
                    else hall_built(cand, don, a["room"]))
        room = a["room"]
        # row 320: a pickup at the place the plan moved one to, whatever class a swap has since given it
        held = [e.get("classname") for e in cand.ents
                if e.get("classname", "").startswith(("weapon_", "item_", "ammo_"))
                and len(e.get("origin", "").split()) == 3
                and all(abs(float(e["origin"].split()[i]) - a["to"][i]) <= 1.0 for i in range(3))
                and all(room[i] <= a["to"][i] <= room[3 + i] for i in range(3))]
        ok = air and bool(held)
        built += 1 if ok else 0
        # row 379: what it holds is worth the walk
        worth = max((PICKUP_WORTH.get(c, 0) for c in held), default=0)
        worthy += 1 if worth >= ANNEX_WORTH_MIN else 0
        said.append(f"{coords(room[:3])} .. {coords(room[3:])} {'built' if ok else 'NOT BUILT'} ({how};"
                    f" moved {a['cls']}, holds {held[0] if held else 'NO pickup at its place'}, worth {worth})")
    # row 412: the generator deals its own box rooms only when asked (the PO, 05.10: «скучно, в оригинальных картах
    # такого нет») - a plan with none has nothing to be asked here; its new rooms are real rooms (room-of)
    if not annexes:
        return True, "no box annex in the plan: the new rooms are real rooms of the maps"
    return (len(mine) >= ANNEX_MIN and built == len(mine) and worthy == len(mine),
            f"{len(annexes)} annexes in the plan, {len(mine)} {'on accepted digs' if accepted_only else 'asked'},"
            f" {built} built, {worthy} worth the walk: " + "; ".join(said[:6]))


def storey_built(cand: Bsp, s: dict, others: list | None = None) -> tuple[bool, str]:
    """The terrace, at five places along its length (row 335): solid 8 under its top and air 32 over it at every
    one, solid half way down at every one no OTHER accepted dig's box contains - a later passage may run under it -
    and at least one such; the flight's middle tread solid 8 under its top and no rock over it from 32 up to 32
    under the ceiling. The flight touches the terrace on one level axis, and that face is its high end."""
    room, ter, fl, n = s["room"], s["terrace"], s["flight"], max(1, s["treads"])
    z0, zt, ceil = room[2], ter[2], room[5]
    long_ax = 0 if ter[3] - ter[0] >= ter[4] - ter[1] else 1
    probes, foot_asked, terrace = [], 0, True
    for f in (0.1, 0.3, 0.5, 0.7, 0.9):
        q = [(ter[0] + ter[3]) / 2.0, (ter[1] + ter[4]) / 2.0]
        q[long_ax] = ter[long_ax] + f * (ter[3 + long_ax] - ter[long_ax])
        foot = [q[0], q[1], (z0 + zt) / 2.0]
        walk = cand.solid([q[0], q[1], zt - 8.0]) and not cand.solid([q[0], q[1], zt + 32.0])
        covered = any(all(o[i] <= foot[i] <= o[3 + i] for i in range(3)) for o in (others or []))
        solid_foot = covered or cand.solid(foot)
        foot_asked += 0 if covered else 1
        terrace = terrace and walk and solid_foot
        probes.append(f"{q[0]:.0f} {q[1]:.0f} {'top' if walk else 'NO TOP'}"
                      f" {'foot under a passage' if covered else ('foot' if solid_foot else 'NO FOOT')}")
    terrace = terrace and foot_asked > 0
    tx, ty = (ter[0] + ter[3]) / 2.0, (ter[1] + ter[4]) / 2.0
    bax = next((a for a in (0, 1) if abs(fl[a] - ter[3 + a]) < 1.0 or abs(fl[3 + a] - ter[a]) < 1.0), None)
    if bax is None:
        return False, "the flight does not touch the terrace"
    high, step = (fl[bax], 1.0) if abs(fl[bax] - ter[3 + bax]) < 1.0 else (fl[3 + bax], -1.0)
    t = n // 2
    p = [(fl[0] + fl[3]) / 2.0, (fl[1] + fl[4]) / 2.0, 0.0]
    p[bax] = high + step * (t + 0.5) * (fl[3 + bax] - fl[bax]) / n
    top = zt - (t + 1) * (zt - z0) / n
    under = cand.solid([p[0], p[1], top - 8.0])
    rock = [z for z in range(int(top + 32.0), int(ceil - 32.0) + 1, 16) if cand.solid([p[0], p[1], float(z)])]
    ok = terrace and under and not rock
    return ok, (f"terrace {'solid' if terrace else 'NOT SOLID'} at {tx:.0f} {ty:.0f} ({'; '.join(probes)});"
                f" tread {t} of {n} at"
                f" {p[0]:.0f} {p[1]:.0f} top {top:.0f} {'solid' if under else 'NOT SOLID'} under,"
                f" rock over it at {rock[:4] or 'none'}")


def ask_storeys(bsp: Path, job: Path, donor: Path, work: Path, accepted_only: bool = True) -> tuple[bool, str]:
    text, err = plan_listing(job, work)
    if err:
        return False, err
    storeys = plan_storeys(text)
    accepted = accepted_digs(job)
    mine = [s for s in storeys if not accepted_only or dealt_on(accepted, s["ends"])]
    cand, don = Bsp(bsp), Bsp(donor)
    built, said = 0, []
    for s in mine:
        air, how = hall_built(cand, don, s["room"])
        own = [d["box"] for d in accepted if all(abs(d["from"][i] - s["ends"][i]) <= 1.0
                                                 and abs(d["to"][i] - s["ends"][3 + i]) <= 1.0 for i in range(3))]
        others = [d["box"] for d in accepted if d["box"] not in own]
        parts, where = storey_built(cand, s, others)
        room = s["room"]
        held = [e.get("classname") for e in cand.ents
                if e.get("classname", "").startswith(("weapon_", "item_", "ammo_"))
                and len(e.get("origin", "").split()) == 3
                and all(abs(float(e["origin"].split()[i]) - s["to"][i]) <= 1.0 for i in range(3))
                and all(room[i] <= s["to"][i] <= room[3 + i] for i in range(3))]
        ok = air and parts and bool(held)
        built += 1 if ok else 0
        said.append(f"{coords(room[:3])} .. {coords(room[3:])} from {coords(s['ends'][:3])} below and"
                    f" {coords(s['ends'][3:])} above {'built' if ok else 'NOT BUILT'} ({how}; {where};"
                    f" moved {s['cls']}, holds {held[0] if held else 'NO pickup at its place'})")
    if not storeys:                    # row 412: dealt only when asked
        return True, "no generated two-storey hall in the plan: the new rooms are real rooms of the maps"
    return (len(mine) >= STOREYS_MIN and built == len(mine),
            f"{len(storeys)} storeys in the plan, {len(mine)} {'on accepted digs' if accepted_only else 'asked'},"
            f" {built} built: " + "; ".join(said[:4]))


def plan_stairways(text: str) -> list:
    """Each stairway the plan dealt: its foot, its top, its steps, its landing box and its pickup's move."""
    out = {}
    for m in STAIRWAY_LINE.finditer(text):
        v = [float(x) for x in m.groups()[1:7]]
        out[m.group(1)] = {"foot": v[:3], "top": v[3:], "steps": int(m.group(8)), "wide": float(m.group(9)),
                           "ledge": m.group(10) == "meets a ledge"}
    for m in STAIRWAY_LANDING.finditer(text):
        if m.group(1) in out:
            out[m.group(1)]["landing"] = [float(x) for x in m.groups()[1:]]
    for m in STAIRWAY_MOVE.finditer(text):
        if m.group(1) in out:
            v = [float(x) for x in m.groups()[2:]]
            out[m.group(1)]["move"] = (m.group(2), v[:3], v[3:])
    return [s for s in out.values() if "landing" in s]


def stairway_built(cand: Bsp, don: Bsp, s: dict) -> tuple[bool, str]:
    """Built, and nothing of it floats: the landing solid from its top to the floor at its middle and its four inner
    corners (rock in the map where the donor had air), the flight solid under its middle line, STAIR_HEAD of air over
    the landing's middle, and the foot standing air."""
    lo, hi = s["landing"][:3], s["landing"][3:]
    floor = s["foot"][2]
    pts = [[(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2]] + [[x, y] for x in (lo[0] + 6, hi[0] - 6)
                                                            for y in (lo[1] + 6, hi[1] - 6)]
    for x, y in pts:
        for z in range(int(floor) + 4, int(hi[2]) - 2, 12):
            if not cand.solid([x, y, z]):
                return False, f"the landing is not solid down to the floor at {x:.0f} {y:.0f} {z} - it floats"
    if not any(not don.solid([x, y, (floor + hi[2]) / 2]) for x, y in pts):
        return False, "the donor had rock where the landing stands - nothing new was built"
    top = s["top"]
    for h in (8, 40, 64):
        if cand.solid([top[0], top[1], top[2] + h]):
            return False, f"no headroom over the landing at {h}"
    if cand.solid([s["foot"][0], s["foot"][1], floor + 32]):
        return False, "its foot is buried"
    # the flight: under the line from the foot to the landing, solid from the floor to each tread
    fx, fy = s["foot"][0], s["foot"][1]
    tx, ty = top[0], top[1]
    n = s["steps"]
    run = max(1.0, ((tx - fx) ** 2 + (ty - fy) ** 2) ** 0.5)
    for i in range(n):
        f = (24.0 + 32.0 * (i + 0.5)) / run          # the flight starts 24 past the foot, a tread is 32
        x, y = fx + (tx - fx) * f, fy + (ty - fy) * f
        if not cand.solid([x, y, floor + 6]):
            return False, f"step {i + 1} missing at {x:.0f} {y:.0f}"
    return True, "built, solid to the floor"


def ask_stairways(bsp: Path, job: Path, donor: Path, work: Path) -> tuple[bool, str]:
    """Brief 11 D1: every stairway the plan dealt and the ledger accepted is built, stands on the floor, and holds the
    pickup it was dealt for at its place (or meets its ledge); none dealt - nothing to build."""
    text, err = plan_listing(job, work)
    if err:
        return False, err
    planned = plan_stairways(text)
    if not planned:
        return True, "no stairway in the plan"
    ledger = (job / "ledger.txt").read_text(encoding="utf-8", errors="replace")
    boxes = [[float(v) for v in m.groups()] for m in STAIRWAY_ACCEPTED.finditer(ledger)]

    def accepted(s: dict) -> bool:
        L = s["landing"]
        return any(b[0] - 1 <= L[0] and L[3] <= b[3] + 1 and b[1] - 1 <= L[1] and L[4] <= b[4] + 1 for b in boxes)

    mine = [s for s in planned if accepted(s)]
    cand, don = Bsp(bsp), Bsp(donor)
    built, said = 0, []
    for s in mine:
        ok, how = stairway_built(cand, don, s)
        held = "a ledge"
        if not s["ledge"]:
            cls, _, to = s.get("move", ("?", None, s["top"]))
            # the pickup dealt, or the one a later swap of the plan put in its place - what stands on the landing
            got = [e.get("classname") for e in cand.ents
                   if e.get("classname", "").startswith(("weapon_", "item_", "ammo_"))
                   and len(e.get("origin", "").split()) == 3
                   and all(abs(float(e["origin"].split()[i]) - to[i]) <= 1.0 for i in range(3))]
            held = got[0] if got else f"NO {cls} at its place"
            ok = ok and bool(got)
        built += 1 if ok else 0
        said.append(f"{coords(s['foot'])} up to {coords(s['top'])}, {s['steps']} steps: "
                    f"{'built' if ok else 'NOT BUILT'} ({how}; {held})")
    return (built == len(mine), f"{len(planned)} stairways in the plan, {len(mine)} accepted, {built} built"
            + (": " + "; ".join(said[:4]) if said else ""))


def ask_starts(bsp: Path) -> tuple[bool, str]:
    """Brief 11 D2 (kept at every destruction): every start stands - its body in air (a player's box, 32 x 32 x 56,
    sampled), floor within 32 under its feet - and can move: a free step 32 off it at least one way."""
    cand = Bsp(bsp)
    starts = [e for e in cand.ents if e.get("classname") == "info_player_deathmatch"
              and len(e.get("origin", "").split()) == 3]
    bad = []
    for e in starts:
        o = [float(v) for v in e["origin"].split()]
        # the game puts a player 9 over the start's origin (PutClientInServer), its box -24..32 round that: q3t2's
        # starts stand 15 over the floor and read «buried» when the box was taken from the origin itself
        o[2] += 9.0
        body = [[o[0] + dx, o[1] + dy, o[2] + dz] for dx in (-14, 0, 14) for dy in (-14, 0, 14) for dz in (-20, 0, 28)]
        if any(cand.solid(p) for p in body):
            bad.append(f"{coords(o)} buried")
            continue
        if not any(cand.solid([o[0], o[1], o[2] - 24 - dz]) for dz in range(2, 34, 4)):
            bad.append(f"{coords(o)} over no floor")
            continue
        free = any(all(not cand.solid([o[0] + sx * 32 + dx, o[1] + sy * 32 + dy, o[2] + dz])
                       for dx in (-15, 15) for dy in (-15, 15) for dz in (-6, 28))
                   for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        if not free:
            bad.append(f"{coords(o)} cannot move")
    return (bool(starts) and not bad, f"{len(starts)} starts, {len(bad)} not standing free"
            + (": " + "; ".join(bad[:4]) if bad else ""))


# ---- visibility ----------------------------------------------------------------------------------------------------
def visgate_oracle(work: Path) -> tuple[Path, str]:
    from check_mapgen_visgate import build
    if prebuilt("visgate_oracle.exe"):
        return prebuilt("visgate_oracle.exe"), ""
    exe = work / "visgate_oracle.exe"
    exe.unlink(missing_ok=True)
    return exe, build(REPO, exe)


def ask_sight(exe: Path, bsp: Path, donor: Path, eye: list | None) -> tuple[bool, str]:
    rc, out = run([exe, donor, bsp, *STAIR_BOX, GROW] + (["--eye", *eye] if eye else []), timeout=3600)
    m = LOST.search(out)
    return (bool(m) and int(m.group(1)) > 0 and m.group(2) == "0"), tail(out)


# ---- the rest ------------------------------------------------------------------------------------------------------
def gate_finished(bsp: Path) -> None:
    rc, out = run([sys.executable, TOOLS / "check_mapgen_delivery.py", "--finished", bsp])
    check("finished: lit, with visibility data", rc == 0 and "0 failures" in out, tail(out))


# Row 405 (Fable's brief 5 W7): a finding the donor has itself, at the same place, is the donor's own - named on the
# line and not counted, as the pickups gate does. q3t2's killsky warp faces and its own func_wall panes in rock failed
# water and static on mg_q3t2 exactly as they fail on q3t2. The numbers the compiler owns (a face's index, a model's
# "*N") are taken out before the comparison; the texture, the class, the place and the finding stay.
_FACE_INDEX = re.compile(r"^face\s+\d+\s+")
_MODEL_INDEX = re.compile(r"^\*\d+\s+")


def _place_of(finding: str) -> str:
    return _MODEL_INDEX.sub("", _FACE_INDEX.sub("face ", finding.strip()))


_AT = re.compile(r"at \[(-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\]")


def _same_finding(mine: str, theirs: set) -> bool:
    """The donor has this finding: the same text, or - for a face, which the two compilers split differently (q3t2's
    window at x 7 y 1201: a face's middle at z 38 here, 43 there) - the same words at a place within 24 units."""
    m = _place_of(mine)
    if m in theirs:
        return True
    at = _AT.search(m)
    if not at or not m.startswith("face "):
        return False
    words = m[at.end():]
    here = [float(v) for v in at.groups()]
    for other in theirs:
        o = _AT.search(other)
        if not (o and other.startswith("face ") and other[o.end():] == words):
            continue
        there = [float(v) for v in o.groups()]
        near = all(abs(there[i] - here[i]) <= 24.0 for i in range(3))
        # or one strip split elsewhere: q3t2's at x 126 z -1008 is one face at y -241 there, two at -51 and -290 here
        same_line = sum(abs(there[i] - here[i]) <= 2.0 for i in range(3)) >= 2
        if near or same_line:
            return True
    return False


def gate_water(bsp: Path, work: Path, donor: Path | None = None) -> None:
    from check_mapgen_standing_water import build, PROBE_SRC
    work.mkdir(parents=True, exist_ok=True)      # its folder made here: a guard's fresh work tree has none
    try:
        exe = prebuilt("water_probe.exe") or build(REPO, work, "water_probe", PROBE_SRC)
    except SystemExit as e:
        check("water: the probe builds", False, str(e))
        return
    rc, out = run([exe, bsp])
    first = out.strip().splitlines()[0] if out.strip() else "no output"
    faces = [ln for ln in out.splitlines() if ln.startswith("face")]
    # the two compilers split one liquid wall into faces differently (q3t2's killsky at y -830: 64..126 and 0..64
    # here, 64..126 and 56..64 in the donor), so a face is the donor's when the donor draws the same texture on the
    # same plane over the face's whole extent
    def parsed(line: str):
        f = line.split()
        try:
            return f[2], [float(v) for v in f[3:6] + f[7:10]]
        except (ValueError, IndexError):
            return None

    donor_faces = []
    if faces and donor and donor.is_file():
        _, dout = run([exe, donor])
        donor_faces = [x for x in (parsed(ln) for ln in dout.splitlines() if ln.startswith("face")) if x]

    def inherited(line: str) -> bool:
        me = parsed(line)
        if not me:
            return False
        tex, b = me
        same = [d for t2, d in donor_faces if t2 == tex
                and any(abs(b[a] - b[a + 3]) < 0.5 and abs(d[a] - d[a + 3]) < 0.5 and abs(b[a] - d[a]) <= 1.0
                        for a in range(3))]
        if not same:
            return False
        return all(min(d[a] for d in same) - 1.0 <= b[a] and b[a + 3] <= max(d[a + 3] for d in same) + 1.0
                   for a in range(3))

    mine = [ln for ln in faces if not inherited(ln)]
    n_own = len(faces) - len(mine)
    said = mine[0].strip() if mine else (f"{len(faces)} vertical liquid faces" if faces else first)
    if n_own:
        said += f"; the donor's own, there too: {n_own} ({' '.join(faces[0].split()[2:3])})"
    check("water: no vertical liquid face", first.startswith("vertical liquid faces 0 ") or bool(faces and not mine),
          said[:300])


def gate_reach(bsp: Path, work: Path, donor: Path | None = None) -> None:
    from check_mapgen_reach_gate import build_gate
    exe = prebuilt("reach_gate.exe") or build_gate(work)
    # row 404: held to the donor where the donor itself fails (the generator's own rule since row 400), and the
    # teleporters and pads a player crosses named on the line
    argv = [exe, bsp, "40000"] + (["--donor", donor] if donor and donor.is_file() else [])
    rc, out = run(argv, timeout=7200)
    lines = [ln.strip() for ln in out.strip().splitlines()]
    said = lines[1:3] + [ln for ln in lines if ln.startswith(("HELD TO THE DONOR", "the donor", "new traps"))
                         or "teleporter" in ln]
    check("reach: every start, pickup and landmark reachable", rc == 0 and ("PASS" in out or "HELD TO THE DONOR" in out),
          " / ".join(dict.fromkeys(said)))


def gate_axes(bsp: Path, work: Path) -> None:
    rc, out = run([sys.executable, TOOLS / "check_mapgen_texture_axes.py", "--map", bsp, "--work", work / "axes"])
    check("axes: every drawn face wears its texture", rc == 0 and "0 failures" in out, tail(out))


# row 405 (brief 5 W6c): a storey with one door - its upper end is the middle of its own terrace, as an annex's is
ONE_DOOR = re.compile(r"^  dig storeys: room .* from " + T3 + " below, " + T3 + r" above\n"
                      r"  dig storeys doorway: .*, the one door$", re.M)


def static_digs(job: Path, work: Path) -> list:
    """The accepted digs, each annex's and each one-door storey's marked: its far end is the middle of its own room
    (rows 334, 405)."""
    text, err = plan_listing(job, work)
    ends = [[float(v) for v in m.groups()] for m in ONE_DOOR.finditer(text)] if not err else []
    one_door = [{"ends": e} for e in ends]
    return mark_own_rooms(accepted_digs(job), (plan_annexes(text) if not err else []) + one_door)


def mark_own_rooms(digs: list, annexes: list) -> list:
    """An annex - named so by the ledger's shape, or matching a planned annex's (or one-door storey's) two ends -
    ends in its own room."""
    for d in digs:
        if d.get("shape") == "annex" or any(all(abs(d["to"][i] - a["ends"][3 + i]) <= 1.0 for i in range(3))
                                            for a in annexes):
            d["own_room_end"] = "to"
    return digs


_MODEL_OF = re.compile(r"^\*(\d+) ")


def _model_shape(b, mi: int) -> tuple:
    """A brush model's shape as a copy keeps it, wherever it stands and however it is turned: its size, sorted, and
    its textures."""
    lo, hi = b.model_box(mi)
    return (tuple(sorted(round(hi[a] - lo[a]) for a in range(3))),
            tuple(sorted({b.texinfo[b.faces[f][4]][1] for f in b.model_faces(mi)})))


def _donor_copies(bsp: Path, donor: Path, donor_bad: dict) -> dict:
    """Row 412: {model of `bsp`: the questions the donor's model of the same shape is found out by too}."""
    from check_mapgen_static import Bsp
    mine, theirs = Bsp(bsp), Bsp(donor)
    said = defaultdict(set)
    for q, fs in donor_bad.items():
        for f in fs:
            m = _MODEL_OF.match(f)
            if m and int(m.group(1)) < len(theirs.models):
                said[_model_shape(theirs, int(m.group(1)))].add(q)
    return {mi: said[_model_shape(mine, mi)] for mi in range(1, len(mine.models)) if _model_shape(mine, mi) in said}


def gate_static(bsp: Path, job: Path, work: Path, donor: Path | None = None) -> None:
    digs = work / "digs.json"
    listed = static_digs(job, work)
    digs.write_text(json.dumps({bsp.name: listed}, indent=1), encoding="utf-8")
    rc, out = run([sys.executable, TOOLS / "check_mapgen_static.py", "--digs", digs, bsp])
    if rc == 0 and "0 failures" in out:
        check("static: panes, lifts, sounds and the digs' mouths", True, tail(out))
        return
    # row 405: the findings, each asked of the donor too
    from check_mapgen_static import judge
    found = judge(bsp, listed)["bad"]
    own = {}
    if donor and donor.is_file():
        own = {q: {_place_of(f) for f in fs} for q, fs in judge(donor)["bad"].items()}
    mine = {q: [f for f in fs if not _same_finding(f, own.get(q, set()))] for q, fs in found.items()}
    # row 412: and a model that is a COPY of one of the donor's - its wall lamp hung on a dig's wall (q3t2's flames are
    # translucent func_walls, asked as panes) - with the finding the donor's model has too, is the donor's own kind
    copies = _donor_copies(bsp, donor, judge(donor)["bad"]) if donor and donor.is_file() else {}
    before_copies = sum(len(fs) for fs in mine.values())
    mine = {q: [f for f in fs if (_MODEL_OF.match(f) is None or q not in copies.get(int(_MODEL_OF.match(f).group(1)),
                                                                                       set()))]
            for q, fs in mine.items()}
    mine = {q: fs for q, fs in mine.items() if fs}
    copied = before_copies - sum(len(fs) for fs in mine.values())
    inherited = sum(len(fs) for fs in found.values()) - sum(len(fs) for fs in mine.values())
    said = "; ".join(f"{q}: {fs[0]}" for q, fs in list(mine.items())[:2]) or tail(out)
    if inherited:
        said += f"; the donor's own, there too: {inherited - copied}"
    if copied:
        said += f"; on copies of the donor's own models (its wall pieces), as the donor's are: {copied}"
    check("static: panes, lifts, sounds and the digs' mouths", not mine, said[:300])


def selftest(work: Path) -> None:
    print("selftest: the new questions, of inputs that must fail them", flush=True)
    r35 = ROUND35 / "deliver" / "candidate.bsp"
    if check("selftest: round 35's map and round 36's job are there",
             r35.is_file() and (ROUND36 / "job" / "ledger.txt").is_file(), str(r35)):
        # row 346: round 36's plan as dealt then - the dug rule (row 343) now refuses the passages it grew its
        # halls on; the question is the gate's, so it is asked of a driver with that rule taken out
        from mapgen_red_sandbox import Sandbox, hash_tree
        rules = (b"if (have_vox && dig_air_beyond_mouths(&vox, &d, walled_at)) {",
                 b"if (dig_air_beyond_mouths(&vox, &d, walled_at)) {")
        before = hash_tree(REPO)
        box = Sandbox(REPO, "gateshalldugoff")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            if check("selftest: the dug rule is where the dug-off driver takes it out",
                     all(data.count(r) == 1 for r in rules), ", ".join(str(data.count(r)) for r in rules)):
                for r in rules:
                    data = data.replace(r, r.replace(b"if (", b"if (false && ", 1), 1)
                target.write_bytes(data)
                ok, said = ask_hall(r35, ROUND36 / "job", DONOR, work, box.root)
                check("selftest: the hall gate refuses round 35's map - the halls round 36's plan dealt are not in"
                      " it", not ok and "0 on accepted digs" not in said, said)
        finally:
            box.dispose()
            check("selftest: the shared worktree was never opened for writing", hash_tree(REPO) == before)
    r36 = ROUND36 / "deliver" / "candidate.bsp"
    if check("selftest: round 36's map is there", r36.is_file(), str(r36)):
        ok, said = ask_annex(r36, ROUND36 / "job", DONOR, work, accepted_only=False)
        check("selftest: the annex gate refuses round 36's map - the annexes today's plan deals on its baseline are"
              " not in it", not ok and "annexes in the plan, 0" not in said, said)
    # row 379: the annex gate refuses mg_20r - its four rooms built, each holding an ammo box or a shard (the PO's
    # quake163/164), asked with mg_20r's own plan
    mg20r = MAPS / "mg_20r.bsp"
    r47_list = ROUND47_42 / "deliver" / "gates" / "plan_list.txt"
    if check("selftest: mg_20r, its job and its plan's listing are there",
             mg20r.is_file() and (ROUND47_42 / "job" / "ledger.txt").is_file() and r47_list.is_file(), str(mg20r)):
        ok, said = ask_annex(mg20r, ROUND47_42 / "job", DONOR, work,
                             listing=r47_list.read_text(encoding="utf-8", errors="replace"))
        check("selftest: the annex gate refuses mg_20r - its rooms are built and hold nothing worth the walk",
              not ok and ", 4 built, 0 worth the walk" in said, said[:400])
    # row 352: the sky gate refuses mg_20q - its annex past the courtyard's sky, the PO's quake162
    mg20q = MAPS / "mg_20q.bsp"
    if check("selftest: mg_20q and its job are there", mg20q.is_file() and (ROUND42_42 / "ledger.txt").is_file(),
             str(mg20q)):
        ok, said = ask_sky(mg20q, ROUND42_42, DONOR)
        check("selftest: the sky gate refuses mg_20q", not ok, said[:260])
    # row 343: the digwalls gate refuses mg_20o - its courtyard stair and the shaft open to a room
    mg20o = MAPS / "mg_20o.bsp"
    if check("selftest: mg_20o and its job are there", mg20o.is_file() and (ROUND41_1020 / "ledger.txt").is_file(),
             str(mg20o)):
        ok, said = ask_digwalls(mg20o, ROUND41_1020, DONOR)
        check("selftest: the digwalls gate refuses mg_20o", not ok, said[:260])
    # row 337: the clips gate refuses the mg_20m delivered with two clip beams in its north doorway
    from check_mapgen_clips import EVIDENCE as CLIP_EVIDENCE, exposed
    if check("selftest: the mg_20m kept with its clip beams is there", CLIP_EVIDENCE.is_file(), str(CLIP_EVIDENCE)):
        bad = exposed(CLIP_EVIDENCE, DONOR)
        check("selftest: the clips gate refuses it", bool(bad), f"{len(bad)} found")
        check("selftest: and passes q2dm1 itself", not exposed(DONOR, DONOR))
    # row 335: the storey gate refuses row 328's FILL RED - its terrace a slab - and passes its green storey
    red_bsp = STOREY_RED / "fill_storey_1.bsp"
    if check("selftest: row 328's FILL RED storey and its listing are there",
             red_bsp.is_file() and (STOREY_RED / "fill_1.txt").is_file(), str(red_bsp)):
        st = plan_storeys((STOREY_RED / "fill_1.txt").read_text(encoding="utf-8", errors="replace"))
        ok, said = storey_built(Bsp(red_bsp), st[0], []) if st else (True, "no storey in the listing")
        check("selftest: the storey gate refuses a storey whose terrace is a slab", not ok, said[:220])
    green_bsp = STOREY_GREEN / "storey_1020.bsp"
    if check("selftest: row 328's green storey and its listing are there",
             green_bsp.is_file() and (STOREY_GREEN / "green_1020.txt").is_file(), str(green_bsp)):
        st = plan_storeys((STOREY_GREEN / "green_1020.txt").read_text(encoding="utf-8", errors="replace"))
        ok, said = storey_built(Bsp(green_bsp), st[0], []) if st else (False, "no storey in the listing")
        check("selftest: and passes the storey built as declared", ok, said[:220])
    mg20k = MAPS / "mg_20k.bsp"
    if check("selftest: mg_20k and round 38's job are there",
             mg20k.is_file() and (ROUND38 / "job" / "ledger.txt").is_file(), str(mg20k)):
        ok, said = ask_storeys(mg20k, ROUND38 / "job", DONOR, work, accepted_only=False)
        check("selftest: the storeys gate refuses mg_20k - the storeys today's plan deals on round 38's baseline are"
              " not in it", not ok and "storeys in the plan, 0" not in said, said)
    ok, said = ask_glass(DONOR, DONOR)
    check("selftest: the glass gate refuses q2dm1 itself", not ok, said)
    # row 334: round 40's seed-7 map - a hall of 768 whose middle is 432 from its doorway
    r7 = ROUND40_S7 / "deliver" / "candidate.bsp"
    if check("selftest: round 40's seed-7 map and job are there",
             r7.is_file() and (ROUND40_S7 / "job" / "ledger.txt").is_file(), str(r7)):
        # the ledger's shape, as today's pipeline prints it - round 40's seed 7 ran before it did
        line = ("  171 dig              ACCEPTED                  482  2496 944 1024  3312 1712 1344  from 1872 1328"
                " 1024 to 2928 1328 1024 shape annex  ms 1")
        m = DIG.search(line)
        check("selftest: a ledger dig line with its shape is read with the shape",
              bool(m) and m.group(13) == "annex", m.group(0)[-60:] if m else "not read")
        digs = accepted_digs(ROUND40_S7 / "job")
        for d in digs:
            if [round(v) for v in d["to"]] == [2928, 1328, 1024]:
                d["shape"] = "annex"
        marked = mark_own_rooms(digs, [])
        bare = [{k: v for k, v in d.items() if k != "own_room_end"} for d in marked]
        def closed(out: str) -> bool:
            return any("FAIL" in ln and "dig closed at an end" in ln for ln in out.splitlines())

        outs = {}
        for tag, digs in (("marked", marked), ("bare", bare)):
            f = work / f"digs_{tag}.json"
            f.write_text(json.dumps({r7.name: digs}, indent=1), encoding="utf-8")
            outs[tag] = run([sys.executable, TOOLS / "check_mapgen_static.py", "--digs", f, r7])[1]
        check("selftest: the static gate finds an annex of 768 closed at its middle when the dig is not marked as"
              " its own room's - and not when it is", closed(outs["bare"])
              and not closed(outs["marked"])
              and sum(1 for d in marked if d.get("own_room_end")) >= 1,
              f"{sum(1 for d in marked if d.get('own_room_end'))} marked; bare: {tail(outs['bare'], 160)}")
    exe, err = visgate_oracle(work)
    mg20d = MAPS / "mg_20d.bsp"
    if check("selftest: the oracle builds and mg_20d is there", not err and mg20d.is_file(), err[:200] or str(mg20d)):
        ok, said = ask_sight(exe, mg20d, DONOR, EYE)
        check("selftest: the eye gate refuses mg_20d, which carried the hole", not ok, said)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidate", nargs="?", type=Path)
    ap.add_argument("--job", type=Path, help="the pipeline's job folder: its ledger.txt and its baseline map")
    ap.add_argument("--donor", type=Path, default=DONOR)
    ap.add_argument("--second", type=Path, help="brief 9: the second map the run was given - the plan is dealt with it")
    ap.add_argument("--work", type=Path, help="where binaries and reports go (default: gates/ beside the candidate)")
    ap.add_argument("--only", help="the gates to ask, comma-separated, of: " + ", ".join(GATES))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        work = a.work or (REPO.parent / "_agent_temp" / "claude" / "delivery_gates_selftest")
        work.mkdir(parents=True, exist_ok=True)
        selftest(work)
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures", flush=True)
        return 1 if FAILED else 0
    if not a.candidate or not a.candidate.is_file() or not a.job or not (a.job / "ledger.txt").is_file():
        ap.error("a candidate .bsp and --job with its ledger.txt are needed")
    want = set(a.only.split(",")) if a.only else set(GATES)
    if want - set(GATES):
        ap.error(f"no gate called {', '.join(sorted(want - set(GATES)))}")
    global SECOND
    SECOND = a.second
    work = a.work or (a.candidate.parent / "gates")
    work.mkdir(parents=True, exist_ok=True)
    bsp, donor = a.candidate, a.donor
    print(f"gates for {bsp} (job {a.job}, donor {donor.name}): {', '.join(g for g in GATES if g in want)}",
          flush=True)
    if "pickups" in want:
        gate_pickups(bsp, work, donor)
    if "glass" in want:
        check("glass: shot panes, panes on a plate, fixed glass beyond the donor's", *ask_glass(bsp, donor, a.job))
    if "hall" in want:
        check("hall: every hall the plan dealt on an accepted dig is built", *ask_hall(bsp, a.job, donor, work))
    if "annex" in want:
        check(f"annex: every annex the plan dealt on an accepted dig is built and holds a pickup worth the walk,"
              f" at least {ANNEX_MIN}", *ask_annex(bsp, a.job, donor, work))
    if "stairways" in want:
        check("stairways: every stairway the plan dealt and the ledger accepted is built, stands on the floor and"
              " holds its pickup", *ask_stairways(bsp, a.job, donor, work))
    if "sky" in want:
        check("sky: nothing new is seen through the sky", *ask_sky(bsp, a.job, donor))
    if "digwalls" in want:
        check("digwalls: every accepted dig is dug - no new space open high to the old map, nothing standing in its"
              " air", *ask_digwalls(bsp, a.job, donor))
    if "clips" in want:
        from check_mapgen_clips import exposed, said as clips_said
        bad = exposed(bsp, donor)
        check("clips: no player-clip brush beside space the generator opened", not bad,
              f"{len(bad)} found" + (f": {clips_said(bad)}" if bad else ""))
    if "storeys" in want:
        check(f"storeys: every storey the plan dealt on an accepted dig is built - its hall, its terrace, its flight"
              f" - and holds its pickup, at least {STOREYS_MIN}", *ask_storeys(bsp, a.job, donor, work))
    if want & {"eye", "stair"}:
        exe, err = visgate_oracle(work)
        if check("visibility: the oracle builds", not err, err[:200]):
            if "eye" in want:
                check("eye: from the PO's eye 920 65 718 no pair the donor showed is lost",
                      *ask_sight(exe, bsp, donor, EYE))
            if "stair" in want:
                check("stair: from the oracle's own eyes round the stair no pair is lost",
                      *ask_sight(exe, bsp, donor, None))
    if "finished" in want:
        gate_finished(bsp)
    if "light" in want:
        check("light: the map is lit like its donor - shared faces per orientation, every dug room lit",
              *ask_light(bsp, a.job, donor, work))
    if "water" in want:
        gate_water(bsp, work, donor)
    if "reach" in want:
        gate_reach(bsp, work, donor)
    if "axes" in want:
        gate_axes(bsp, work)
    if "static" in want:
        gate_static(bsp, a.job, work, donor)
    if "starts" in want:
        check("starts: every start stands in air on a floor and can step off", *ask_starts(bsp))
    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures", flush=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
