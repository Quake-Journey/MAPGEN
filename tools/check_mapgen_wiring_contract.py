#!/usr/bin/env python3
"""MAPGEN-1 M2 - MapGenWiring, the target/targetname graph.

Contract sections 5.4 ("target/targetname, mover, key, door, trigger, train
and progression graphs") and 18.4.

Five halves:

  * STATIC - the exact classname table decides before any prefix does, links
    that resolve to nothing are kept rather than dropped, and the module holds
    no global state;

  * CLASSIFICATION - every classname in the corpus classifies to something, and
    the ones that matter classify to what they are. Tested through the compiled
    C, including names no shipped map contains;

  * CRAFTED - dangling links, a name shared by several entities, a self-target,
    a three-entity cycle, teams and malformed `model` values, on synthesized
    maps. Real maps cannot be made to contain a `model` of "*12a";

  * REFERENCE - the C and an independent Python build must produce identical
    canonical text on all 132 shipped maps;

  * CORPUS - the measured facts, asserted so they cannot drift in silence.

Run: python tools/check_mapgen_wiring_contract.py
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

import mapgen_bsp_oracle as oracle  # noqa: E402
import mapgen_bsp_synth as synth  # noqa: E402
import mapgen_wiring_oracle as wiring  # noqa: E402

# The one rule for what belongs to the fixed corpus; see mapgen_corpus.py.
from mapgen_corpus import is_generated  # noqa: E402

HEADER = REPO / "inc" / "common" / "mapgen_wiring.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_wiring.c"
DRIVER = REPO / "tools" / "mapgen_wiring_test_driver.c"
GENOME = REPO / "src" / "mapgen" / "mapgen_genome.c"
BSPDOC = REPO / "src" / "mapgen" / "mapgen_bsp.c"

MAP_ROOTS = [
    Path(r"O:\Claude2\q2pro-release\baseq2\maps"),
    Path(r"O:\Claude2\q2pro-release\action\maps"),
]

# Measured over the corpus on 2026-08-31. Asserted, not printed: if any of
# these move, something about the graph moved with them.
CORPUS_LINKS = 1205
CORPUS_DANGLING = 47
CORPUS_EDITOR_LEFTOVERS = 770
CORPUS_WORLDSPAWNS = 132

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
    head("static: how a classname may be read")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))

    file_statics = [
        m.group(0).strip()
        for m in re.finditer(r"^static\s+[^;(){}]*;", src, re.MULTILINE)
        if "const" not in m.group(0)
    ]
    check("no mutable file-scope state", not file_statics, f"{file_statics[:3]}")
    local_statics = [
        m.group(0).strip()
        for m in re.finditer(r"^[ \t]+static\s+(?!const\b)[^;{]*;", src, re.MULTILINE)
    ]
    check("no function-local mutable state", not local_statics, f"{local_statics[:3]}")

    # A classname is the format's own semantic label, so matching it is
    # legitimate - but only from the START, and never as a substring. A
    # `strstr` here would be contract 7.7's defect wearing a different hat.
    check(
        "a classname is never matched as a substring",
        "strstr(" not in src,
        "'monster' inside a name does not make an entity a monster",
    )
    fn = src[src.find("uint32_t MapGenWiring_RolesForClassname"):]
    fn = fn[:fn.find("\n}")]
    check(
        "the exact table is consulted before any prefix",
        fn.find("EXACT_ROLES") < fn.find("PREFIX_ROLES"),
        "otherwise `item_health_mega` would classify as a plain item",
    )
    check(
        "the prefix match is anchored at the start",
        "strncmp(PREFIX_ROLES[i].name, classname, n)" in fn,
        "",
    )

    check(
        "a link that resolves to nothing is recorded, not dropped",
        "push_dangling" in src and "if (!matched" in src,
        "46 targets in the corpus name nothing; discarding them hides the fact",
    )
    check(
        "one name may be fired by one target",
        "for (uint32_t j = 0; j < count; j++)" in src
        and "matched++" in src,
        "77 targetnames in the corpus are shared by more than one entity",
    )
    check(
        "a submodel index is validated against the document",
        "(uint32_t)e->submodel >= models" in src and "num_bad_submodels++" in src,
        "the value comes out of a file we did not write",
    )
    check(
        "cycles are counted as strongly connected components",
        "close_component" in src and "lowlink" in src,
        "unwinding the DFS stack on a back edge answers a different question",
    )
    check(
        "the cycle walk is iterative",
        "frame_node" in src and "while (frames)" in src,
        "a deep chain out of a file must not become a stack overflow",
    )
    # The rule protects the PO's binary, not the generator: a module the
    # packaged helper runs has to be linked somewhere, and mapgen_src is the
    # somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_wiring.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("wiring.exe" if os.name == "nt" else "wiring")
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), str(GENOME), str(BSPDOC), "-o", str(exe)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def run(exe: Path, *args: str) -> str:
    p = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=600)
    return p.stdout


def corpus() -> list[Path]:
    return [p for root in MAP_ROOTS if root.is_dir() for p in sorted(root.glob("*.bsp"))
            # The generator publishes into this directory under contract 22's
            # reserved `q2mg_` basename. Those are legal training input but they are
            # not part of the fixed corpus these checks count, and a count that moves
            # every time somebody generates a map is not a count.
            if not is_generated(p.name)]


EXPECTED_ROLES = {
    "func_door": {"door", "mover"},
    "func_door_rotating": {"door", "mover", "rotating"},
    "func_plat": {"plat", "mover"},
    "func_train": {"train", "mover"},
    "func_group": {"editor_leftover"},
    "func_wall": {"decor"},
    "misc_teleporter": {"teleporter"},
    "misc_teleporter_dest": {"teleport_dest"},
    "trigger_push": {"push", "trigger"},
    "trigger_hurt": {"hazard", "trigger"},
    "info_player_deathmatch": {"spawn_dm"},
    "info_player_start": {"spawn_sp"},
    "path_corner": {"path"},
    "worldspawn": {"worldspawn"},
    "item_health_mega": {"health", "powerup", "item"},
    "item_armor_shard": {"armor", "item"},
    # None of these appear in any shipped map; the prefix rules exist for them.
    "monster_soldier_light": {"monster"},
    "monster_tank_commander": {"monster"},
    "weapon_bfg": {"weapon", "item"},
    "ammo_bullets": {"ammo", "item"},
    "key_blue_key": {"item"},
    "light_torch_small_walltorch": {"light"},
    "trigger_elevator": {"trigger"},
    # And a name that is nothing at all.
    "there_is_no_such_entity": set(),
}


def test_classification(exe: Path) -> None:
    head("classification: what a classname means")
    names = sorted(EXPECTED_ROLES)
    out = run(exe, "classify", *names)
    got: dict[str, set[str]] = {}
    for line in out.splitlines():
        parts = line.split()
        if parts:
            got[parts[0]] = set(parts[2:])

    wrong = [f"{n}: got {sorted(got.get(n, set()))} want {sorted(EXPECTED_ROLES[n])}"
             for n in names if got.get(n, set()) != EXPECTED_ROLES[n]]
    check(
        f"{len(names)} classnames classify to exactly the right roles",
        not wrong,
        "; ".join(wrong[:4]),
    )
    check(
        "a name that means nothing classifies as nothing",
        got.get("there_is_no_such_entity") == set(),
        str(got.get("there_is_no_such_entity")),
    )
    check(
        "the exact table beats the prefix that also matches",
        got.get("item_health_mega") == {"health", "powerup", "item"}
        and got.get("func_group") == {"editor_leftover"},
        "`item_` and `func_` would swallow both",
    )

    # Every classname the corpus actually contains must mean something.
    seen: set[str] = set()
    for path in corpus():
        for ent in oracle.load(path).entities():
            seen.add(ent.get("classname", ""))
    seen.discard("")
    unknown = sorted(n for n in seen if not wiring.roles_for_classname(n))
    check(
        f"all {len(seen)} classnames in the corpus classify to something",
        not unknown,
        f"{len(unknown)} unclassified: {unknown[:8]}",
    )


# --------------------------------------------------------------------------


def synth_map(entities: list[dict[str, str]], out: Path, name: str) -> Path:
    path = out / f"{name}.bsp"
    path.write_bytes(synth.synth_solid_cube(entities=entities))
    return path


def field_of(text: str, prefix: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    return None


def test_crafted(exe: Path, out: Path) -> None:
    head("crafted: what no shipped map contains")

    base = {"classname": "worldspawn"}

    cases: list[tuple[str, list[dict[str, str]], str, str]] = [
        (
            "a target naming nothing is kept as a dangling link",
            [base, {"classname": "trigger_once", "target": "nobody_here"}],
            "dangling=", "1",
        ),
        (
            "a target naming two entities fires both",
            [base,
             {"classname": "trigger_once", "target": "both"},
             {"classname": "func_door", "targetname": "both"},
             {"classname": "func_door", "targetname": "both"}],
            "links=", "2",
        ),
        (
            "a name shared by two entities is counted once",
            [base,
             {"classname": "func_door", "targetname": "both"},
             {"classname": "func_door", "targetname": "both"}],
            "shared_names=", "1",
        ),
        (
            "an entity that targets itself is on a cycle",
            [base, {"classname": "trigger_relay", "targetname": "me", "target": "me"}],
            "on_cycle=", "1",
        ),
        (
            "a three-entity ring is a cycle",
            [base,
             {"classname": "path_corner", "targetname": "a", "target": "b"},
             {"classname": "path_corner", "targetname": "b", "target": "c"},
             {"classname": "path_corner", "targetname": "c", "target": "a"}],
            "on_cycle=", "3",
        ),
        (
            "a chain that does not close is not a cycle",
            [base,
             {"classname": "path_corner", "targetname": "a", "target": "b"},
             {"classname": "path_corner", "targetname": "b", "target": "c"},
             {"classname": "path_corner", "targetname": "c"}],
            "on_cycle=", "0",
        ),
        (
            "two entities sharing a team form one group",
            [base,
             {"classname": "func_door", "team": "gates"},
             {"classname": "func_door", "team": "gates"},
             {"classname": "func_door", "team": "other"}],
            "teams=", "2",
        ),
        (
            "a submodel index past the end of the document is refused",
            [base, {"classname": "func_door", "model": "*999"}],
            "bad_submodels=", "1",
        ),
        (
            "submodel zero is the world and is accepted",
            [base, {"classname": "func_door", "model": "*0"}],
            "bad_submodels=", "0",
        ),
        (
            "killtarget and pathtarget are links too",
            [base,
             {"classname": "trigger_once", "killtarget": "gone", "pathtarget": "walk"},
             {"classname": "func_door", "targetname": "gone"},
             {"classname": "path_corner", "targetname": "walk"}],
            "links=", "2",
        ),
    ]

    for i, (name, entities, prefix, want) in enumerate(cases):
        path = synth_map(entities, out, f"crafted{i}")
        text = run(exe, "text", str(path))
        check(name, field_of(text, prefix) == want,
              f"{prefix}{field_of(text, prefix)}, wanted {want}")

    # Malformed `model` values, which a real map cannot be made to contain.
    # "*0a" earns its place: a loose parser reads it as 0, which is IN range,
    # so the submodel validation cannot rescue it the way it does for "*12a".
    for value, expect in (("*12a", -1), ("*0a", -1), ("*", -1), ("12", -1),
                          ("", -1), ("*1", -1), ("*0", 0)):
        entities = [base, {"classname": "func_door", "model": value}]
        path = synth_map(entities, out, "model_" + (value or "empty").replace("*", "s"))
        text = run(exe, "text", str(path))
        rows = [ln for ln in text.splitlines() if ln.startswith("w=")]
        got = int(rows[1].split(",")[1]) if len(rows) > 1 else None
        check(
            f"a model of {value!r} yields submodel {expect}",
            got == expect,
            f"got {got}",
        )

    # The Python build must agree on every crafted case too, since these are
    # exactly the shapes the corpus never exercises.
    disagreements: list[str] = []
    for i, (_name, entities, _p, _w) in enumerate(cases):
        path = out / f"crafted{i}.bsp"
        py = wiring.canonical_text(wiring.from_map(path))
        if run(exe, "text", str(path)) != py:
            disagreements.append(f"crafted{i}")
    check("the reference agrees on every crafted case", not disagreements,
          str(disagreements))


# --------------------------------------------------------------------------


def test_reference(exe: Path) -> None:
    head("reference: two independent builds, every shipped map")
    maps = corpus()
    if not check("real maps are available", len(maps) >= 100, f"found {len(maps)}"):
        return

    differing: list[str] = []
    for path in maps:
        py = wiring.canonical_text(wiring.from_map(path))
        if run(exe, "text", str(path)) != py:
            differing.append(path.name)
    check(
        f"all {len(maps)} maps wire identically in C and in the reference",
        not differing,
        f"{len(differing)}: {differing[:4]}",
    )


def test_corpus(exe: Path) -> None:
    head("corpus: the measured facts")
    maps = corpus()
    if not maps:
        return

    totals = {"links": 0, "dangling": 0, "leftovers": 0, "badmodel": 0}
    worldspawns = 0
    failures: list[str] = []
    for path in maps:
        line = run(exe, "summary", str(path)).strip()
        if not line.startswith("OK "):
            failures.append(f"{path.name}: {line[:60]}")
            continue
        parts = line.split()
        for k in totals:
            for i in range(2, len(parts) - 1, 2):
                if parts[i] == k:
                    totals[k] += int(parts[i + 1])
        text = run(exe, "text", str(path))
        for ln in text.splitlines():
            if ln.startswith("role=worldspawn,"):
                worldspawns += int(ln.split(",")[1])

    check("every map wired", not failures, "; ".join(failures[:4]))
    check(
        f"the corpus has {CORPUS_LINKS} resolved links",
        totals["links"] == CORPUS_LINKS,
        f"got {totals['links']}",
    )
    check(
        f"the corpus has {CORPUS_DANGLING} links that go nowhere",
        totals["dangling"] == CORPUS_DANGLING,
        f"got {totals['dangling']}; these are real and must stay visible",
    )
    check(
        f"the corpus carries {CORPUS_EDITOR_LEFTOVERS} func_group leftovers",
        totals["leftovers"] == CORPUS_EDITOR_LEFTOVERS,
        f"got {totals['leftovers']}; an editor construct that survived compilation",
    )
    check(
        "no shipped map names a submodel that does not exist",
        totals["badmodel"] == 0,
        f"got {totals['badmodel']}",
    )
    check(
        f"every one of the {CORPUS_WORLDSPAWNS} maps has exactly one worldspawn",
        worldspawns == CORPUS_WORLDSPAWNS,
        f"got {worldspawns}",
    )


def main() -> int:
    print("=== MAPGEN-1 M2 MapGenWiring contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_wiring_") as td:
        work = Path(td)
        head("building")
        exe = build(cc, work)
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_classification(exe)
        test_crafted(exe, work)
        test_reference(exe)
        test_corpus(exe)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
