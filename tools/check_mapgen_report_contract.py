#!/usr/bin/env python3
"""MAPGEN-1 M3 - the Training result report.

Contract section 21's Training result page and section 19's reporting rule:
"The UI/report must not claim 'balanced' or 'good' as a theorem. It reports
measured structural evidence."

Three halves:

  * HONESTY - a list of judgement words must appear nowhere in a rendered
    report, and the closing sentence must hand the question of whether a map
    plays well back to playing it. Section 19's rule made checkable rather than
    remembered;

  * WHAT WAS NOT LEARNED - a snapshot trained on deathmatch maps must SAY it
    learned nothing about monsters or single-player progression. A report that
    lists only what it knows invites the reader to assume the rest, and this is
    the mitigation recorded against U12;

  * ACCOUNTING - every number in the report is the number in the snapshot's own
    QUALITY chunk, and the warnings follow from those numbers.

Run: python tools/check_mapgen_report_contract.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_build_target as build_target  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

HEADER = REPO / "inc" / "common" / "mapgen_report.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_report.c"
DRIVER = REPO / "tools" / "mapgen_report_test_driver.c"
PARTS = [
    REPO / "src" / "mapgen" / "mapgen_lineage.c",
    REPO / "src" / "mapgen" / "mapgen_training.c",
    REPO / "src" / "mapgen" / "mapgen_snapshot.c",
    REPO / "src" / "mapgen" / "mapgen_digest.c",
    REPO / "src" / "mapgen" / "mapgen_features.c",
    REPO / "src" / "mapgen" / "mapgen_wiring.c",
    REPO / "src" / "mapgen" / "mapgen_space.c",
    REPO / "src" / "mapgen" / "mapgen_trace.c",
    REPO / "src" / "mapgen" / "mapgen_genome.c",
    REPO / "src" / "mapgen" / "mapgen_bsp.c",
    REPO / "src" / "mapgen" / "mapgen_geometry.c",
    REPO / "src" / "mapgen" / "mapgen_blueprint.c",
]

MAP_ROOTS = [
    Path(r"O:\Claude2\q2pro-release\baseq2\maps"),
    Path(r"O:\Claude2\q2pro-release\action\maps"),
]

# A verdict the report is not entitled to reach. Contract 19 names the first
# two explicitly; the rest are the same claim in other clothes.
JUDGEMENT_WORDS = [
    "balanced", "good", "excellent", "great", "poor", "bad ", "badly",
    "high quality", "well-designed", "well designed", "optimal", "ideal",
    "perfect", "fun", "beautiful", "playable", "solid design",
]

CASES = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    if condition:
        print(f"  PASS  {name}")
        return True
    print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    FAILED += 1
    return False


def head(text: str) -> None:
    print(f"\n=== {text}")


def strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


# --------------------------------------------------------------------------


def test_static() -> None:
    head("static: the report has no vocabulary for a verdict")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))

    literals = " ".join(re.findall(r'"((?:[^"\\]|\\.)*)"', src)).lower()
    offenders = [w for w in JUDGEMENT_WORDS if w in literals]
    check(
        "no judgement word appears in any string the report can emit",
        not offenders,
        f"{offenders}; contract 19 forbids claiming a verdict as a theorem",
    )
    check(
        "the report hands the question back to playing the map",
        "decided by playing it" in src,
        "contract 19: final fun, pacing and visual quality require PO playtesting",
    )
    check(
        "capabilities are derived from the snapshot, not supplied",
        "MapGenReport_Capabilities(const mapgen_snapshot_t *snap" in src
        and "role_total(snap" in src,
        "a caller who was optimistic could otherwise report whatever it liked",
    )
    check(
        "liquid is read from the material contents, not inferred from hazards",
        "0x8 | 0x10 | 0x20" in src and "MAPGEN_CHUNK_MATERIALS" in src,
        "water is liquid and harmless; lava is both, and they are not the same "
        "question",
    )
    check(
        "single-player progression needs somewhere to progress to",
        "out->sp_progression = out->monsters && role_total(snap, \"changelevel\") > 0;" in src,
        "",
    )

    statics = [
        m.group(0).strip()
        for m in re.finditer(r"^static\s+[^;(){}]*;", src, re.MULTILINE)
        if "const" not in m.group(0)
    ]
    check("no mutable file-scope state", not statics, f"{statics[:3]}")
    # The rule protects the PO's binary, not the generator: a module the
    # packaged helper runs has to be linked somewhere, and mapgen_src is the
    # somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_report.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("report.exe" if os.name == "nt" else "report")
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), *[str(x) for x in PARTS], "-o", str(exe), "-lz"],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def find_map(name: str) -> Path | None:
    for root in MAP_ROOTS:
        if (root / name).exists():
            return root / name
    return None


def render(exe: Path, names: list[str]) -> str:
    paths = [find_map(n) for n in names]
    paths = [p for p in paths if p]
    if len(paths) != len(names):
        return ""
    p = subprocess.run([str(exe), "render", *[str(x) for x in paths]],
                       capture_output=True, text=True, timeout=1800)
    return p.stdout


def section(text: str, title: str) -> str:
    start = text.find(title)
    if start < 0:
        return ""
    rest = text[start + len(title):]
    end = rest.find("\n\n")
    return rest[:end if end > 0 else len(rest)]


def test_honesty(exe: Path) -> None:
    head("honesty: what the report refuses to say")
    text = render(exe, ["aerowalk.bsp", "redyard.bsp", "q2duel1.bsp"])
    if not check("a report was rendered", bool(text) and "Training result" in text,
                 text[:200]):
        return

    lowered = text.lower()
    offenders = [w for w in JUDGEMENT_WORDS if w in lowered]
    check(
        "the rendered report contains no judgement word",
        not offenders,
        f"{offenders}",
    )
    check(
        "it ends by handing the question back to playing the map",
        "decided by playing it" in text,
        "",
    )
    check(
        "it reports numbers with the population they were measured over",
        "Sources measured:" in text, "")


def test_unlearned(exe: Path) -> None:
    head("what was NOT learned, said out loud")
    text = render(exe, ["aerowalk.bsp", "redyard.bsp", "q2duel1.bsp"])
    if not text:
        return

    missing = section(text, "NOT present in these sources, and therefore not learned")
    check("the report has a section for what it did not learn", bool(missing), "")
    check(
        "a deathmatch corpus reports monsters as unlearned",
        "- monsters" in missing,
        missing,
    )
    check(
        "and single-player progression as unlearned",
        "- single-player progression" in missing,
        missing,
    )

    learned = section(text, "Learned from these sources")
    check("and reports what it did learn", "- player spawns" in learned, learned)
    check("including items and weapons",
          "- items" in learned and "- weapons" in learned, learned)
    check(
        "the two lists do not overlap",
        not (set(re.findall(r"- (.+)", learned)) & set(re.findall(r"- (.+)", missing))),
        "",
    )
    check(
        "redyard's water is reported as learned",
        "- liquids" in learned,
        "it is the smallest map in the corpus with liquid, and it is in this set",
    )


def test_accounting(exe: Path) -> None:
    head("accounting: the numbers are the snapshot's own")
    text = render(exe, ["aerowalk.bsp", "redyard.bsp", "q2duel1.bsp"])
    if not text:
        return

    def value(label: str) -> int | None:
        m = re.search(rf"^{re.escape(label)}: (\d+)$", text, re.M)
        return int(m.group(1)) if m else None

    offered, accepted = value("Offered"), value("Accepted")
    duplicates, rejected = value("Duplicates skipped"), value("Rejected")
    check("every source count is present",
          None not in (offered, accepted, duplicates, rejected), text[:400])
    if None in (offered, accepted, duplicates, rejected):
        return
    check("the counts account for every offered source",
          accepted + duplicates + rejected == offered,
          f"{accepted} + {duplicates} + {rejected} != {offered}")
    check(
        "the known duplicate pair is reported as one skipped source",
        duplicates == 1 and accepted == 2,
        f"accepted {accepted}, duplicates {duplicates}; aerowalk and q2duel1 "
        "are byte-identical",
    )

    warnings = section(text, "Warnings")
    check("a duplicate produces a warning",
          "byte-identical" in warnings, warnings)
    check("so does a small corpus",
          "Few distinct sources" in warnings, warnings)
    check(
        "the small-corpus warning says what it is about",
        "not about\n  the maps" in text,
        "a warning about the sample must not read as a warning about the maps",
    )


def main() -> int:
    print("=== MAPGEN-1 M3 Training report contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_report_") as td:
        head("building")
        exe = build(cc, Path(td))
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_honesty(exe)
        test_unlearned(exe)
        test_accounting(exe)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
