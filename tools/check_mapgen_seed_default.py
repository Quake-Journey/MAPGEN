"""Two builds of the same thing must not be the same map.

The PO's words on 2026-09-07: "не должно быть повторяемости создания карт".
Codex had already ruled it on 2026-09-03, section 10, item 6: "Different seeds
producing the same compiled architecture is an acceptance blocker."

Before this, `mapgen_seed` was 1 and CVAR_ARCHIVE, and every path in the client
read it straight - `mapgen_start` (the menu button), `mapgen_generate` with no
third argument, and the map name itself. So every generation a player ever
started from the menu ran seed 1 and built the same map, by construction. That
is not a degenerate selection policy; it is no policy at all, and it hid the
selection problem underneath it.

    python tools/check_mapgen_seed_default.py

This is the static half - what the client does with the seed - because the
compiled half is a sixteen-seed sweep that takes an hour per anchor and lives
in tools/mapgen_seed_sweep.py.

Cases: the default draws; a seed asked for by name is used unchanged; the drawn
seed is never written back into the cvar, or the next build would repeat this
one; the map is named after the seed that ran, not after the cvar; replay reads
the Recipe. And the menu offers the choice as a choice rather than as a number
a player has to know to change.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLIENT = REPO / "src" / "client" / "mapgen_client.c"
MENU = REPO / "src" / "client" / "ui" / "q2pro-x.menu2"

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail
                                                     and not ok else ""))
    if not ok:
        FAILED += 1
    return ok


def body_of(source: str, name: str) -> str:
    at = source.find("\n" + name)
    if at < 0:
        return ""
    start = source.find("{", at)
    depth, i = 0, start
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1
    return ""


def main() -> int:
    c = CLIENT.read_text(encoding="utf-8", errors="replace")
    m = MENU.read_text(encoding="utf-8", errors="replace")

    print("the seed a build runs with")
    check("there is one place that decides it",
          c.count("static uint32_t mapgen_seed_for_this_run(void)") == 1)
    draw = body_of(c, "static uint32_t mapgen_seed_for_this_run")
    check("it draws one unless a seed was asked for",
          "Q_rand()" in draw and "mapgen_seed_mode->integer" in draw
          and "mapgen_seed->integer" in draw, draw[:200])
    check("and never draws zero, which is the word for 'draw one'",
          "while (!drawn)" in draw or "if (!drawn)" in draw, draw[-200:])
    check("the drawn seed is not written back into the cvar",
          "Cvar_Set" not in draw and "cvar_set" not in draw.lower(), draw)

    print("and every path uses it")
    for fn, why in (("mapgen_start_now", "the menu button"),
                    ("mapgen_generate_f", "the console command")):
        b = body_of(c, f"static void {fn}") or body_of(c, fn)
        if not b:
            # the start path is whichever function fills the request
            b = ""
        check(f"{why} does not read the cvar straight",
              "mapgen_seed->integer" not in b, b[:200])
    # Every reader of the cvar has to be inside the one function that decides,
    # or some other path can quietly go back to building the same map.
    check("no path outside the decision reads the cvar",
          c.count("mapgen_seed->integer")
          == draw.count("mapgen_seed->integer"),
          f"{c.count('mapgen_seed->integer')} readers in the file,"
          f" {draw.count('mapgen_seed->integer')} of them in the decision")
    check("the map is named after the seed that ran",
          re.search(r'"q2mg_%08x",\s*seed\)', c) is not None)
    check("replaying a map takes the seed from its Recipe",
          "MapGenRecipe_Seed(recipe)" in c)

    print("and the menu asks it as a question")
    check("the choice is a preset widget, not a bare number",
          "pairs" in m and "mapgen_seed_mode" in m)
    check("the number is still there for building one map again",
          "field --numeric" in m and "mapgen_seed" in m)
    seed_lines = [l for l in m.splitlines() if "mapgen_seed" in l]
    check("nothing tells the player the same seed gives the same map as if"
          " that were the default",
          not any("Один и тот же seed" in l for l in seed_lines),
          "\n".join(seed_lines)[:300])

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
