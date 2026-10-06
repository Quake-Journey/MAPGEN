"""One compiler thread policy, in one place, everywhere it is asked for.

Codex, 2026-09-06 section 4: "Reconcile the pin's thread policy 1 with
transaction requests 4 and crease guard requests 8. Use the declared qualified
policy, or provide the required qualification for a deliberate change; do not
silently call all three one pinned configuration."

The pin's value is 1 and it says why: the semantic digest does not depend on
the count (MEASURED at 1, 2 and 16), but q2tools' RunThreadsOn waits a fixed
second per parallel batch, so one thread is 0.3s where sixteen is 12.8s on the
same fixture. So the answer is not to qualify 4 and 8 - it is to stop asking
for them, and to make the next literal impossible to add quietly.

    python tools/check_mapgen_thread_policy.py [--red]

Cases: the C constant equals the pin; no production or driver site assigns a
thread count that is not that constant; the two guards that shell out to the
compiler read the pin rather than carrying a copy of the number.

--red mutates each of those three in a scratch copy and requires the case that
covers it to fail, so a green run is a statement about the check and not only
about today's tree.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIN = REPO / "tools" / "mapgen_compiler_pin.json"
HEADER = REPO / "src" / "mapgen" / "mapgen_compiler.h"
MACRO = "MAPCOMPILE_PINNED_THREADS"

# Every place that fills in a compile request's thread count. Named, not
# globbed: a new one should have to be added here deliberately.
ASSIGN_SITES = [
    "src/mapgen/mapgen_pipeline.c",
    "src/mapgen/mapgen_transaction.c",
    "tools/mapgen_compile_driver.c",
    "tools/mapgen_pipeline_driver.c",
]
# The guards that run the compiler themselves, over a command line rather than
# a request struct. They must read the pin; a literal here is the same defect.
PIN_READER_SITES = [
    "tools/check_mapgen_crease.py",
    "tools/check_mapgen_visible_holes.py",
    "tools/mapgen_make_demo_maps.py",
]

# `x.threads = <something>;` - the assignment, whatever the something is.
ASSIGN = re.compile(r"\.threads\s*=\s*([^;]+);")
# The only two spellings that are not a number of our own: the macro, and a
# caller-supplied count that falls back to the macro.
OK_ASSIGN = re.compile(r"^(request->threads\s*\?\s*request->threads\s*:?\s*)?"
                       + MACRO + r"$")
# Row 404: the final light compile's rule - every P-core thread of the machine - and only in the pipeline, once.
LIGHT = "MAPCOMPILE_LIGHT_THREADS(request->light_threads)"
LIGHT_SITE = "src/mapgen/mapgen_pipeline.c"


def pin_value() -> int:
    return int(json.loads(PIN.read_text(encoding="utf-8"))
               ["thread_policy"]["value"])


def macro_value(header_text: str) -> int | None:
    m = re.search(r"#define\s+" + MACRO + r"\s+(\d+)", header_text)
    return int(m.group(1)) if m else None


def check(tree: Path, log: bool) -> list[str]:
    """Every case, against a tree - the repo, or a mutated copy of it."""
    bad: list[str] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        if log:
            print(f"  {'PASS' if ok else 'FAIL'}  {name}"
                  + (f"  -- {detail}" if detail and not ok else ""))
        if not ok:
            bad.append(name)

    header = (tree / "src/mapgen/mapgen_compiler.h").read_text(encoding="utf-8")
    declared = macro_value(header)
    want = pin_value()
    case("the C constant is declared", declared is not None)
    case("the C constant equals the pin",
         declared == want, f"{MACRO}={declared} pin={want}")

    for rel in ASSIGN_SITES:
        text = (tree / rel).read_text(encoding="utf-8")
        # a struct field assignment may wrap; join continuation lines first
        flat = re.sub(r"\s+", " ", text)
        found = [m.group(1).strip() for m in ASSIGN.finditer(flat)]
        light = [f for f in found if f == LIGHT]
        offenders = [f for f in found if not OK_ASSIGN.match(f) and f != LIGHT]
        case(f"{rel} asks for the pinned count",
             found and not offenders,
             "no .threads assignment at all" if not found
             else "asks for " + ", ".join(offenders))
        if rel == LIGHT_SITE:
            case(f"{rel}: the final light compile asks for the machine's P-core threads, once",
                 len(light) == 1, f"{len(light)} light assignments")
        elif light:
            case(f"{rel}: only the pipeline's final light compile may ask for the P-core threads", False,
                 f"{len(light)} here")

    for rel in PIN_READER_SITES:
        text = (tree / rel).read_text(encoding="utf-8")
        # the pin read directly, or through `mapgen_pinned_compiler.pinned_compiler()`, which returns its thread
        # policy beside the binary (mapgen_make_demo_maps.py since 2026-09-12)
        reads_pin = 'thread_policy' in text or 'pinned_compiler()' in text
        literal = re.search(r'"-threads",\s*"\d+"', text)
        case(f"{rel} reads the pin for -threads",
             reads_pin and not literal,
             "literal " + literal.group(0) if literal else "no pin read")

    return bad


# --- the controlled REDs ---------------------------------------------------
#
# Each one puts back exactly the defect its case exists for.
REDS = [
    ("the constant drifts from the pin",
     "src/mapgen/mapgen_compiler.h",
     f"#define {MACRO}   1", f"#define {MACRO}   4",
     "the C constant equals the pin"),
    ("a transaction asks for four again",
     "src/mapgen/mapgen_transaction.c",
     f"request.threads = {MACRO};", "request.threads = 4;",
     "src/mapgen/mapgen_transaction.c asks for the pinned count"),
    ("the final light compile asks for a number of its own",
     "src/mapgen/mapgen_pipeline.c",
     "creq.threads = MAPCOMPILE_LIGHT_THREADS(request->light_threads);", "creq.threads = 8;",
     "src/mapgen/mapgen_pipeline.c asks for the pinned count"),
    ("a guard carries its own -threads",
     "tools/check_mapgen_crease.py",
     '"-threads", pinned_threads()', '"-threads", "8"',
     "tools/check_mapgen_crease.py reads the pin for -threads"),
]


def red(work: Path) -> int:
    import shutil
    failures = 0
    for name, rel, old, new, expect in REDS:
        tree = work / re.sub(r"\W+", "_", name)
        if tree.exists():
            shutil.rmtree(tree)
        for d in ("src/mapgen", "tools"):
            (tree / d).mkdir(parents=True, exist_ok=True)
        for f in ["src/mapgen/mapgen_compiler.h"] + ASSIGN_SITES + PIN_READER_SITES:
            shutil.copy2(REPO / f, tree / f)
        p = tree / rel
        t = p.read_text(encoding="utf-8")
        if t.count(old) < 1:
            print(f"  FAIL  RED {name}: cannot mutate, {old!r} not present")
            failures += 1
            continue
        p.write_text(t.replace(old, new, 1), encoding="utf-8")
        broke = check(tree, log=False)
        ok = expect in broke
        print(f"  {'PASS' if ok else 'FAIL'}  RED {name}"
              + ("" if ok else f"  -- {expect!r} still passed; broke {broke}"))
        failures += 0 if ok else 1
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--red", action="store_true",
                    help="also run the controlled REDs")
    ap.add_argument("--work", type=Path,
                    default=Path(r"O:\Claude2\_agent_temp\claude"
                                 r"\mapgen1-20260906\threadpolicy"))
    a = ap.parse_args()

    print("thread policy")
    bad = check(REPO, log=True)
    cases = 2 + len(ASSIGN_SITES) + len(PIN_READER_SITES) + 1
    failures = len(bad)

    if a.red:
        a.work.mkdir(parents=True, exist_ok=True)
        print("controlled RED")
        failures += red(a.work)
        cases += len(REDS)

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
