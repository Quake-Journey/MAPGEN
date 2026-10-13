r"""Brief 18 (mg_b18_q2dm3, 12.10): the delivery gates ask the digs of EVERY round the run dealt.

The gates re-dealt the first round alone: two of that run's three accepted annexes were a later round's and were never
asked (annex: «1 on accepted digs», at least 2 asked), and its first-round stairway (top 127, refused) was matched to
the later one accepted beside it (top 63) by plan alone and read «NOT BUILT». The pipeline writes every round's dealt
digs into job/plan_rounds.txt; the gates read the later rounds from it, each round numbering its own stairways, the
same dig dealt twice counted once, a stairway accepted only by a ledger box holding its landing in height too.

  PASS: a listing of round 0 and a plan_rounds.txt of rounds 0 and 2 give both rounds' stairways (each its own
        stairway 1), both rounds' annexes, the round-0 annex dealt again in round 2 once; the stairway of top 127 is
        not taken for the accepted box of top 63
  and the digwalls gate skips an accepted flood's footprint (job/plan_rounds.txt «flood footprint:»), not its box
  RED (--red): the rounds read as one listing - round 2's stairway 1 takes round 0's place

    python tools/check_mapgen_gate_rounds.py [--red]
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_delivery_gates as g  # noqa: E402

CASES = FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    if not ok:
        FAILED += 1
    return ok


ROUND0 = """refused 3 (showing 3):
  dig annex: room 240 848 -97 .. 560 1168 127 off 400 720 -97 through 32 of wall
  dig annex moves: item_armor_jacket from 100 100 -97 to 400 1008 -97
  stairway 1: foot -770 336 -97 top -1010 592 127, 18 steps 64 wide, holds a pickup
  stairway 1 landing: -1050 560 -97 .. -970 624 127
  stairway 1 moves: ammo_shells from 0 0 0 to -1010 592 127
"""
ROUNDS = """# round 0
  dig annex: room 240 848 -97 .. 560 1168 127 off 400 720 -97 through 32 of wall
  dig annex moves: item_armor_jacket from 100 100 -97 to 400 1008 -97
# round 2
  dig annex: room 240 848 -97 .. 560 1168 127 off 400 720 -97 through 32 of wall
  dig annex moves: item_armor_jacket from 100 100 -97 to 400 1008 -97
  dig annex: room 976 -624 187 .. 1232 -192 411 off 1104 -112 187 through 32 of wall
  dig annex moves: item_quad from 5 5 5 to 1104 -432 187
  stairway 1: foot -800 300 -97 top -1000 560 63, 10 steps 64 wide, holds a pickup
  stairway 1 landing: -1050 528 -97 .. -950 592 63
  stairway 1 moves: ammo_shells from 0 0 0 to -1000 560 63
"""


def main() -> int:
    red = "--red" in sys.argv[1:]
    if red:
        g.rounds_of = lambda text: [text]
    work = Path(tempfile.mkdtemp(prefix="gate_rounds_"))
    try:
        (work / "plan_rounds.txt").write_text(ROUNDS, encoding="utf-8")
        text = ROUND0 + g.later_rounds(work)
        check("round 0 of plan_rounds.txt is left to the re-deal", text.count("# round ") == 1, text[-200:])
        st = g.plan_stairways(text)
        tops = sorted(s["top"][2] for s in st)
        check("both rounds' stairways, each its own «stairway 1»", tops == [63.0, 127.0], f"tops {tops}")
        an = g.plan_annexes(text)
        check("both rounds' annexes, round 0's dealt again in round 2 counted once", len(an) == 2,
              f"{len(an)} annexes: {[a['room'][:3] for a in an]}")
        # the accepted box of the later stairway (the ledger's) - the first-round one, top 127, is not inside it
        box = [-1050.0, 272.0, -97.0, -858.0, 784.0, 63.0]
        inside = [s["top"][2] for s in st
                  if box[0] - 1 <= s["landing"][0] and s["landing"][3] <= box[3] + 1 and box[1] - 1 <= s["landing"][1]
                  and s["landing"][4] <= box[4] + 1 and box[2] - 1 <= s["landing"][2] and s["landing"][5] <= box[5] + 1]
        check("the ledger's stairway box (top 63) holds the later stairway alone", inside == [63.0], f"{inside}")
        # mg_b18_q3t2: a flood's shore stood 96 past its box over the pit - the digwalls gate skips its footprint
        (work / "ledger.txt").write_text(
            "   27 flood            ACCEPTED                   23  -240 2704 431  816 3664 524  ms 1\n", encoding="utf-8")
        with open(work / "plan_rounds.txt", "a", encoding="utf-8") as f:
            f.write("  flood footprint: -240 2704 431 816 3664 524 -> -336 2672 415 912 3696 524\n")
        others = g.accepted_others(work)
        check("the digwalls gate skips a flood's footprint, its shore with it, not its box",
              others == [[-336.0, 2672.0, 415.0, 912.0, 3696.0, 524.0]], f"{others}")
        src = (TOOLS / "mapgen_delivery_gates.py").read_text(encoding="utf-8")
        check("ask_stairways asks the box in height", "and b[2] - 1 <= L[2] and L[5] <= b[5] + 1" in src)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{CASES} cases asserted, {FAILED} failures")
    print("FAIL" if FAILED else "PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
