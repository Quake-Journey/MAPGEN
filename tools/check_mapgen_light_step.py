"""
Brief 13 W5: the room light's learnt step (tools/mapgen_room_light.py, learn_power and step_floor).

A room whose level rose while its factor was under 1 (a neighbour's light spilling in) gave a NEGATIVE answer; it was
taken as power 0.2, and the next step for a room twice too bright was 0.5 ** 5 = 0.03, held at the floor 0.15 - the
room overshot dark. Now: a negative answer keeps the power the room had, and a step under 0.3 is only for a room whose
own last answer was under 1.

Cases, then RED: the same cases asked of the old rules (0.2 for any answer under 0.05, the floor 0.15 for every room)
must fail - the check tells the two apart.

    python tools/check_mapgen_light_step.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapgen_room_light import learn_power, step_floor  # noqa: E402

FAILS = 0


def check(what: str, ok: bool, detail: str = "") -> bool:
    global FAILS
    FAILS += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"  -- {detail}" if detail else ""))
    return ok


def step(power: float, answer: float | None, want: float, floor) -> float:
    return max(floor(answer), min(3.0, want ** (1.0 / power)))


def cases(learn, floor) -> list[tuple[str, bool, str]]:
    out = []
    # a room at power 1.2 whose level rose under a factor 0.8 (answer -0.4), still twice too bright
    p = learn(1.2, -0.4)
    k = step(p, None, 0.5, floor)
    out.append(("a negative answer keeps the room's power", abs(p - 1.2) < 1e-9, f"power {p:.2f}"))
    out.append(("... and its next step is not the hardest", k >= 0.3, f"step {k:.2f}"))
    # a real answer is learnt, clamped
    out.append(("a real answer is learnt", abs(learn(2.0, 0.7) - 0.7) < 1e-9, f"{learn(2.0, 0.7):.2f}"))
    out.append(("... held to 0.2 .. 2.0", learn(1.0, 0.1) == 0.2 and learn(1.0, 5.0) == 2.0,
                f"{learn(1.0, 0.1):.2f}, {learn(1.0, 5.0):.2f}"))
    # a room that moves less than its lights (its last answer 0.4) may take the hard step
    k2 = step(0.4, 0.4, 0.5, floor)
    out.append(("a room whose own answer was under 1 may step under 0.3", k2 < 0.3, f"step {k2:.2f}"))
    # one that never answered, or answered over 1, never under 0.3
    out.append(("a room with no answer, or one over 1, never steps under 0.3",
                step(0.2, None, 0.1, floor) >= 0.3 and step(0.2, 1.4, 0.1, floor) >= 0.3,
                f"{step(0.2, None, 0.1, floor):.2f}, {step(0.2, 1.4, 0.1, floor):.2f}"))
    return out


def main() -> int:
    for what, ok, detail in cases(learn_power, step_floor):
        check(what, ok, detail)
    old = cases(lambda prev, answer: max(0.2, min(2.0, answer)) if answer > 0.05 else 0.2, lambda answer: 0.15)
    wrong = [what for what, ok, _ in old if not ok]
    check("RED: the old rules fail these cases", len(wrong) >= 2, "; ".join(wrong))
    print(f"\n{'PASS' if FAILS == 0 else 'FAIL'}: {FAILS} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
