#!/usr/bin/env python3
"""MAPGEN-1 M3 - Training aggregation into a snapshot's chunks.

Contract sections 7 (what Training learns) and 8 (canonical order, per-source
contributions, the duplicate rule and the low-diversity warning).

Five halves:

  * STATIC - the duplicate decision is NOT made on arrival, the counts are
    derived rather than incremented, and the canonical order is
    (SHA-256, provider, qpath) as the contract states;

  * ORDER - the same maps offered forwards and backwards must produce one
    byte-identical payload. This is the case that found the defect: whichever
    of two identical maps arrived first used to become the accepted one;

  * CORPUS - all 132 shipped maps train in one pass, and the five byte-identical
    pairs are resolved to the same five accepted names every time;

  * WARNINGS - a one-map snapshot is legal and carries a visible low-diversity
    warning; a snapshot with nothing accepted is refused outright;

  * CHUNKS - the payloads are parsed back and their own invariants checked, by
    a reader that knows only the contract's rules and nothing of the C.

Run: python tools/check_mapgen_training_contract.py
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
sys.path.insert(0, str(REPO / "tools"))

import mapgen_snapshot_oracle as snapshot  # noqa: E402

# The one rule for what belongs to the fixed corpus; see mapgen_corpus.py.
from mapgen_corpus import is_generated  # noqa: E402

HEADER = REPO / "inc" / "common" / "mapgen_training.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_training.c"
DRIVER = REPO / "tools" / "mapgen_training_test_driver.c"
PARTS = [
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

# The five byte-identical pairs in the shipped corpus, found independently by
# the BspDocument guard. The canonically FIRST qpath of each pair is the one
# that must be accepted, whatever order the maps arrive in.
KNOWN_DUPLICATE_PAIRS = {
    "aerowalk.bsp": "q2duel1.bsp",
    "ikdm3.bsp": "q2duel6.bsp",
    "q2duel3.bsp": "q2rdm5.bsp",
    "q2duel8.bsp": "ztn2dm3.bsp",
    "ztn2dm1.bsp": "ztn2dm1_c.bsp",
}

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
    head("static: nothing decided on arrival, nothing counted on arrival")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))

    statics = [
        m.group(0).strip()
        for m in re.finditer(r"^static\s+[^;(){}]*;", src, re.MULTILINE)
        if "const" not in m.group(0)
    ]
    check("no mutable file-scope state", not statics, f"{statics[:3]}")
    check(
        "no per-thread scratch either",
        "_Thread_local" not in src,
        "an accessor that returns a pointer into per-thread scratch is a "
        "surprise the caller has to know about",
    )

    add = src[src.find("mapgen_training_result_t MapGenTraining_AddSource"):]
    add = add[:add.find("\nmapgen_training_result_t MapGenTraining_RejectSource")]
    check(
        "AddSource decides nothing about duplicates",
        "MAPGEN_SOURCE_DUPLICATE" not in add,
        "deciding it on arrival makes the answer depend on which worker "
        "finished first, which contract 8 forbids",
    )
    check(
        "the duplicate decision is made in canonical order",
        "static source_t *sorted_sources" in src
        and "MAPGEN_SOURCE_DUPLICATE" in src[src.find("static source_t *sorted_sources"):],
        "",
    )
    check(
        "the canonical order is (SHA-256, provider, qpath)",
        bool(re.search(
            r"compare_sources.*?memcmp\(x->identity\.sha256.*?"
            r"strcmp\(x->identity\.provider.*?strcmp\(x->identity\.qpath",
            src, re.DOTALL)),
        "contract 8 names that order exactly",
    )
    check(
        "the counts are derived, not incremented on arrival",
        "static void tally(" in src and "t->accepted++" not in src
        and "t->duplicates++" not in src,
        "a counter incremented on arrival is an arrival-order answer wearing "
        "a different hat",
    )
    check(
        "a rejected source is never reclassified as a duplicate",
        "if (copy[i].identity.status == MAPGEN_SOURCE_REJECTED)\n            continue;" in src,
        "several unreadable maps would otherwise share a zero hash and all but "
        "one would read as duplicates of each other",
    )
    check(
        "a qpath is sanitized once, where it enters",
        "((unsigned char)src[i] < 0x20 || src[i] == '\\n') ? '?' : src[i]" in src,
        "it comes from a file listing and reaches a report and a UI",
    )
    check(
        "an empty corpus is refused",
        "MAPGEN_TRAINING_ERR_NO_SOURCES" in src,
        "a snapshot that learned from nothing is not a snapshot",
    )
    # The rule protects the PO's binary, not the generator: a module the
    # packaged helper runs has to be linked somewhere, and mapgen_src is the
    # somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_training.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


# The engine's own files. Movement evidence is read under the shared pmove, so
# they have to be linked - and they carry warnings this project did not write.
# They are compiled separately so -Werror keeps meaning something where it is
# pointed: at the mapgen sources this file is about.
# The engine's own files, which carry warnings this project did not write. They
# are compiled separately so -Werror keeps meaning something where it is
# pointed: at the mapgen sources this file is about.
ENGINE = [
    Path("src") / "shared" / "shared.c",
    Path("tools") / "mapgen_host_stubs.c",
]


def build_engine(cc: str, out: Path) -> list[str] | None:
    objects = []
    for source in ENGINE:
        obj = out / (source.stem + ".o")
        run = subprocess.run(
            [cc, "-std=c17", "-O2", "-w", "-I", str(REPO / "inc"),
             "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
             "-DUSE_NEW_GAME_API=0", "-c", str(REPO / source), "-o", str(obj)],
            capture_output=True, text=True)
        if run.returncode != 0:
            print((run.stdout + run.stderr)[-1500:])
            return None
        objects.append(str(obj))
    return objects


def build(cc: str, out: Path) -> Path | None:
    engine = build_engine(cc, out)
    if engine is None:
        return None
    exe = out / ("training.exe" if os.name == "nt" else "training")
    p = subprocess.run(
        # The engine's headers want to be told what machine they are on.
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0",
         str(DRIVER), str(SOURCE), *[str(x) for x in PARTS], *engine,
         "-o", str(exe), "-lz", "-lm"],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def run(exe: Path, *args: str) -> str:
    p = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=1800)
    return p.stdout


def corpus() -> list[Path]:
    """Every map that SHIPPED, which is not the same as every map present.

    MAPGEN publishes its own output into this directory under the `q2mg_`
    basename contract 22 reserves for it, and those are excluded here. They are
    perfectly legal training input - a user may well want to train on one - but
    they are not part of the fixed corpus this guard counts, and letting them
    in would make its numbers drift every time a map is generated.
    """
    return [p for root in MAP_ROOTS if root.is_dir()
            for p in sorted(root.glob("*.bsp"))
            if not is_generated(p.name)]


def find_map(name: str) -> Path | None:
    for root in MAP_ROOTS:
        if (root / name).exists():
            return root / name
    return None


def test_order(exe: Path) -> None:
    head("order: the same maps, offered backwards")
    pairs = [("aerowalk.bsp", "q2duel1.bsp"), ("ikdm3.bsp", "q2duel6.bsp")]
    picks = [find_map(n) for pair in pairs for n in pair]
    picks += [find_map("2box4.bsp"), find_map("redyard.bsp")]
    picks = [p for p in picks if p]
    if not check("the order maps are available", len(picks) >= 5, f"{len(picks)}"):
        return

    out = run(exe, "shuffle", *[str(p) for p in picks]).strip()
    check(
        "a set containing duplicate pairs trains identically in either order",
        out.startswith("IDENTICAL"),
        out[:160],
    )

    everything = corpus()
    out = run(exe, "shuffle", *[str(p) for p in everything]).strip()
    check(
        "the whole corpus trains identically in either order",
        out.startswith("IDENTICAL"),
        out[:160],
    )


def parse_summary(line: str) -> dict[str, int]:
    parts = line.split()
    out: dict[str, int] = {}
    for i in range(2, len(parts) - 1):
        if parts[i].isalpha() and parts[i + 1].lstrip("-").isdigit():
            out[parts[i]] = int(parts[i + 1])
    return out


def test_corpus(exe: Path, work: Path) -> Path | None:
    head("corpus: every shipped map, in one pass")
    maps = corpus()
    if not check("real maps are available", len(maps) >= 100, f"found {len(maps)}"):
        return None

    path = work / "corpus.q2mgdb"
    line = run(exe, "train", str(path), *[str(p) for p in maps]).strip().splitlines()
    line = line[0] if line else ""
    if not check("the corpus trained", line.startswith("OK "), line[:160]):
        return None
    summary = parse_summary(line)

    check(f"all {len(maps)} maps were offered",
          summary.get("sources") == len(maps), str(summary))
    check(
        "exactly the five byte-identical pairs were deduplicated",
        summary.get("duplicates") == len(KNOWN_DUPLICATE_PAIRS),
        f"{summary.get('duplicates')}; the pairs were found independently by "
        "the BspDocument guard",
    )
    check("the rest were accepted",
          summary.get("accepted") == len(maps) - len(KNOWN_DUPLICATE_PAIRS),
          str(summary))
    check("nothing failed to analyse", summary.get("rejected") == 0, str(summary))
    check("the material allowlist is not empty",
          summary.get("materials", 0) > 1000, str(summary))
    check("a 127-source snapshot is not low diversity",
          summary.get("lowdiv") == 0, str(summary))

    # Which name wins is part of the contract, not an accident.
    order = [ln.split() for ln in run(exe, "order", *[str(p) for p in maps]).splitlines() if ln]
    status = {row[2]: row[3] for row in order}
    wrong = []
    for keep, drop in KNOWN_DUPLICATE_PAIRS.items():
        if status.get(keep) != "accepted":
            wrong.append(f"{keep} is {status.get(keep)}")
        if status.get(drop) != "duplicate":
            wrong.append(f"{drop} is {status.get(drop)}")
    check("each duplicate pair resolves to its canonically first name",
          not wrong, "; ".join(wrong[:4]))

    hashes = [row[0] for row in order]
    check("sources are serialized in SHA-256 order",
          hashes == sorted(hashes), "")
    return path


def test_warnings(exe: Path, work: Path) -> None:
    head("warnings: a snapshot that knows how little it knows")
    one = find_map("2box4.bsp")
    if not check("a map is available", one is not None, ""):
        return
    assert one is not None

    line = run(exe, "train", str(work / "one.q2mgdb"), str(one)).strip().splitlines()[0]
    summary = parse_summary(line)
    check("a one-map snapshot is legal", line.startswith("OK "), line[:120])
    check("and carries the low-diversity warning", summary.get("lowdiv") == 1,
          str(summary))

    text = run(exe, "chunks", str(one))
    check("the warning is in the QUALITY chunk, not only in a counter",
          "warning=few_sources_low_confidence" in text, "")
    check("the QUALITY chunk states what it is a warning about",
          "accepted=1" in text and "low_diversity=1" in text, "")

    empty = run(exe, "train", str(work / "empty.q2mgdb")).strip().splitlines()
    check(
        "a corpus with nothing in it is refused, not written",
        bool(empty) and empty[0] == "ERR_NO_SOURCES",
        empty[0] if empty else "<nothing>",
    )

    six = [find_map(n) for n in ("2box4.bsp", "redyard.bsp", "rcdm17.bsp",
                                 "lbrdm1.bsp", "aerowalk.bsp")]
    six = [p for p in six if p]
    if len(six) >= 5:
        line = run(exe, "train", str(work / "five.q2mgdb"),
                   *[str(p) for p in six]).strip().splitlines()[0]
        check("five sources is no longer low diversity",
              parse_summary(line).get("lowdiv") == 0, line[:120])


def test_chunks(exe: Path, path: Path) -> None:
    head("chunks: the payloads, read back by the rules alone")
    try:
        snap = snapshot.parse(path.read_bytes())
    except snapshot.SnapshotError as exc:
        check("the trained snapshot opens", False, exc.code)
        return
    check("the trained snapshot opens", True, f"{len(snap.chunks)} chunks")

    def text(kind: int) -> str:
        data = snap.chunk(kind)
        return data.decode("ascii", "replace") if data else ""

    sources = text(snapshot.CHUNK_SOURCES).splitlines()
    rows = [ln[2:].split(",") for ln in sources if ln.startswith("s=")]
    check("every source is recorded, duplicates included",
          len(rows) == 132, f"{len(rows)}")
    check("each row carries a full SHA-256",
          all(len(r[0]) == 64 for r in rows), "")
    check("the rows are in SHA-256 order",
          [r[0] for r in rows] == sorted(r[0] for r in rows), "")
    check("every row has a status the contract names",
          all(r[4] in ("accepted", "duplicate", "rejected") for r in rows),
          str({r[4] for r in rows}))

    groups: dict[str, list[str]] = {}
    for r in rows:
        groups.setdefault(r[0], []).append(r[4])
    bad = [h for h, statuses in groups.items() if statuses.count("accepted") > 1]
    check("no two sources with one hash are both accepted", not bad, str(bad[:3]))

    materials = text(snapshot.CHUNK_MATERIALS).splitlines()
    mrows = [ln[2:].split(",") for ln in materials if ln.startswith("m=")]
    check("the material allowlist is exact and sorted",
          [r[0] for r in mrows] == sorted(r[0] for r in mrows) and len(mrows) > 1000,
          f"{len(mrows)} materials")

    stats = text(snapshot.CHUNK_STATS).splitlines()
    frows = [ln[2:].split(",") for ln in stats if ln.startswith("f=")]
    check("every statistic is min <= median <= max",
          all(int(r[1]) <= int(r[2]) <= int(r[3]) for r in frows),
          str([r for r in frows if not int(r[1]) <= int(r[2]) <= int(r[3])][:2]))
    check("every statistic is an integer",
          all(all(part.lstrip("-").isdigit() for part in r[1:]) for r in frows), "")
    check("the mean lies inside the range",
          all(int(r[1]) <= int(r[4]) <= int(r[3]) for r in frows),
          str([r for r in frows if not int(r[1]) <= int(r[4]) <= int(r[3])][:2]))

    # The six features that also appear per-source in REGIONS can be
    # recomputed from those rows, which turns STATS from a plausible set
    # of numbers into a checkable one. Without this, a mean over the
    # wrong population - duplicates included, say - reads as fine.
    # The per-source rows moved from REGIONS to STATS when schema 2 gave
    # REGIONS the architecture: a row of counts and shares describes nothing
    # about where anything is, and the guard kept reading the old address.
    region_rows = [ln[2:].split(",") for ln in
                   text(snapshot.CHUNK_STATS).splitlines() if ln.startswith("r=")]
    text_sources = text(snapshot.CHUNK_SOURCES)
    # Field 0 is the source's own hash, so the statistic and the map it came
    # from travel together and mixing can dedupe by identity rather than by
    # row position.
    per_source = {
        "nodes": [int(r[1]) for r in region_rows],
        "regions": [int(r[2]) for r in region_rows],
        "largest_region_permille": [int(r[3]) for r in region_rows],
        "height_bands": [int(r[4]) for r in region_rows],
        "vertical_span": [int(r[5]) for r in region_rows],
        "open_permille": [int(r[6]) for r in region_rows],
    }
    # One hash plus one field per statistic. Taken from the enum rather than
    # written here, because the mix reads exactly MAPGEN_MIX_STAT_COUNT fields
    # out of this row: a writer that emits a different number does not fail,
    # it silently shifts every statistic by one.
    mix_header = (REPO / "inc" / "common" / "mapgen_mix.h").read_text(
        encoding="utf-8")
    stats = [m for m in re.findall(r"MAPGEN_MIX_STAT_[A-Z_0-9]+", mix_header)
             if not m.endswith("_COUNT")]
    expected = 1 + len(dict.fromkeys(stats))
    check(
        "every per-source row names the source it came from",
        all(len(r) == expected and len(r[0]) == 64
            and all(c in "0123456789abcdef" for c in r[0]) for r in region_rows),
        f"expected {expected} fields; "
        + str([len(r) for r in region_rows if len(r) != expected][:2]),
    )
    source_hashes = {ln[2:].split(",")[0] for ln in
                     text_sources.splitlines() if ln.startswith("s=")}
    check(
        "and that source is one the snapshot actually accepted",
        all(r[0] in source_hashes for r in region_rows),
        "a statistic attributed to a map the snapshot never learned from "
        "would be worse than no statistic",
    )
    stated = {r[0]: [int(x) for x in r[1:]] for r in frows}
    wrong_stats = []
    for name, values in per_source.items():
        if name not in stated or not values:
            wrong_stats.append(f"{name}: absent")
            continue
        ordered = sorted(values)
        want = [ordered[0], ordered[len(ordered) // 2], ordered[-1],
                sum(values) // len(values)]
        if stated[name] != want:
            wrong_stats.append(f"{name}: {stated[name]} vs {want}")
    check(
        "each statistic is exactly what the per-source rows say it is",
        not wrong_stats,
        "; ".join(wrong_stats[:3]),
    )
    check(
        "the statistics are computed over the accepted sources alone",
        len(region_rows) == 127,
        f"{len(region_rows)} per-source rows; 127 maps were accepted, and a\n        duplicate contributing again would teach the same map twice",
    )

    quality = text(snapshot.CHUNK_QUALITY)
    check("QUALITY accounts for every source",
          re.search(r"^sources=(\d+)$", quality, re.M)
          and int(re.search(r"^sources=(\d+)$", quality, re.M).group(1))
          == int(re.search(r"^accepted=(\d+)$", quality, re.M).group(1))
          + int(re.search(r"^duplicates=(\d+)$", quality, re.M).group(1))
          + int(re.search(r"^rejected=(\d+)$", quality, re.M).group(1)),
          quality[:160])
    check("the snapshot carries no BSP bytes",
          b"IBSP" not in (snap.chunk(snapshot.CHUNK_MATERIALS) or b"")
          and b"IBSP" not in (snap.chunk(snapshot.CHUNK_REGIONS) or b""),
          "contract 8: descriptors and provenance, never map bytes",
    )


def main() -> int:
    print("=== MAPGEN-1 M3 Training aggregation contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_training_") as td:
        work = Path(td)
        head("building")
        exe = build(cc, work)
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_order(exe)
        path = test_corpus(exe, work)
        test_warnings(exe, work)
        if path:
            test_chunks(exe, path)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
