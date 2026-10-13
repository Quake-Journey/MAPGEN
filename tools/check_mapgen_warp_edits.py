"""The edits on a stretched base guard (brief 16, the base's frame; src/mapgen/mapgen_geometry_edit.c, mapgen_geometry.c,
mapgen_reach.c).

The PO, 10.10.2026: «хочется именно менять донора и уже к нему пристраивать». On q2dm3 at his options and the Studio's
default frame (150 %, spread 50, seed 6695) a generation of 20 minutes reached 12.5 % where the plan said 49.6 %: of
its edits, eight were thrown away by the compiler («leaked») and about one in four by the walk («3 landmarks out of
reach against the donor's 2»). Four causes, each in the edits and not in the frame, each found on that base:

  1 an annex's sky skin skipped a voxel that lay partly in a wall the stretch had laid off the 8 (a face at -204.46)
    and partly in the void outside it: the gap band ran past the enclosure to the outside;
  2 a doorway cut to the foot of a wall that stood on nothing (two lava pools' floors meeting under it) opened the map
    downwards;
  3 a reshape grew the ceiling slab over a wall pushed back, and the slab's bevel at the old corner stopped it short;
  4 a room holding a pickup no player gets on the donor either was a landmark in reach while a place of the walk fell
    in its cells and out of reach after an edit across the map changed how the rooms fell;
  5 the plan's largest edit, a tunnel of three halls worth 48 % of its word, was refused «standing water»: it cut a
    piece of the void round the map off from the outside, the compiler left that piece empty, and a pool's side 400
    away counted as water standing in the air;
  6 a reshape pushed back a wall that stood on the void at a room's corner: the strip it gave up opened the room
    onto the void under the wall (and at its end).

This builds the warped base once (the pipeline, its first attempt only), and on it, with the recut driver and the reach
gate:
  A the annex (976 -496 192 .. 1232 -192 416), the doorway (443 462 -128 .. 487 619 128) and the reshapes (driver
    edits 18, 37 and 41) each applied alone compile sealed;
  B five edits the run accepted in a row (two annex/tunnel digs, the stairway, a window, a block at -440 72 -56)
    applied together walk no worse than the base: no landmark lost;
  C the run's first attempt, that tunnel, is accepted (two attempts are run; the second is brief 17's storey, D1).

Brief 17 (Fable, 11.10; the PO: «чтобы работало все - и двухэтажная комната и окна всех видов»), D on both stretched
bases - q2dm3 above and q2dm1 6675 at his options (plan only, the base kept):
  D1 the storey the plan deals on q2dm3 (-624 720 208, its doorway lowered under the courtyard's sky) is dealt and
     compiles sealed;
  D2 the reshape whose wall stood over a floor piece ending short of it (q2dm3, target 7) compiles sealed;
  D3 every large dig of q2dm3's plan applied in a row: each built, the map sealed;
  D4 q2dm1: the annex at 1968 304 896 and the storey at 1392 1936 768 (under the sky lift whose near box spans walls
     with the void beyond) each compile sealed; the storey's map walked whole, every pickup in reach - its terrace's
     too (the storey dealt before at 688 -240 1056 had its doorway's host on a wall top under q2dm1's player clip, and
     its terrace's pickup was out of reach in both runs); no storey's host stands in player clip; every large dig of
     its plan applied in a row: each built (none refused for changing an earlier dig's skin), the map sealed; two
     storeys and six annexes dealt;
  D5 windows: the plans offer a fixed pane, a pane shot down and a pane on a plate on both maps; all windows of a plan
     applied show two outlines or more and two glass tints or more.

RED: `--red` builds the pipeline, the driver and the gate with the rules taken out - every case of A, B, C fails;
`--red17` with brief 17's rules taken out (the doorway lowered under the sky, the storeys filled to two, the void past
a near box filled, a lift piece that does not close, the thin neighbour carried over a strip, the windows' variety, a
doorway's host clear of player clip) - every case of D fails.

    python tools/check_mapgen_warp_edits.py [--work DIR] [--red] [--keep]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from check_mapgen_equivalence import PIPELINE_SOURCES, build  # noqa: E402
from check_mapgen_recut import SOURCES as DRIVER_SOURCES  # noqa: E402
from check_mapgen_reach_gate import SOURCES as GATE_SOURCES  # noqa: E402

ENGINE = Path(r"O:\Claude2\MapgenStudio\engine")
MODDIR = Path(r"O:\Claude2\q2pro-release\baseq2")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen_warp_edits_guard")
NO_WINDOW = 0x08000000
FAILED = 0

# the four rules, each taken out for RED: (file, the rule as it stands, without it)
MUTATIONS = [
    ("src/mapgen/mapgen_geometry_edit.c",
     # brief 17: the rule now probes 27 points of the voxel (a 1.4 sliver at 814.64 slipped between the old 8)
     b"                if (flush)\n                    for (int k = 0; k < 27 && air; k++) {",
     b"                if (false)\n                    for (int k = 0; k < 27 && air; k++) {"),
    ("src/mapgen/mapgen_geometry_edit.c",
     b"    if (!stands && add_box(g, &pattern, sill[0], sill[1]) != MAPGEN_GEOMETRY_OK)",
     b"    if (false && add_box(g, &pattern, sill[0], sill[1]) != MAPGEN_GEOMETRY_OK)"),
    ("src/mapgen/mapgen_geometry.c",
     b"    if (delta > 0.0f)\n        for (uint32_t b = 0; b < g->num_brushes; b++) {",
     b"    if (false)\n        for (uint32_t b = 0; b < g->num_brushes; b++) {"),
    ("src/mapgen/mapgen_reach.c",
     b"                    for (uint32_t i = 0; item_got && i < num_items; i++) {\n                        if (!item_got[i])",
     b"                    for (uint32_t i = 0; false && i < num_items; i++) {\n                        if (!item_got[i])"),
    ("src/mapgen/mapgen_reach.c",
     b"                    for (uint32_t i = 0; item_got && i < num_rooms; i++)",
     b"                    for (uint32_t i = 0; false && i < num_rooms; i++)"),
    ("src/mapgen/mapgen_transaction.c",
     b"        water_now = MapGenBsp_StandingWaterNear(built, txn->baseline_bsp, water_lo, water_hi, NULL);",
     b"        water_now = MapGenBsp_StandingWater(built, NULL);"),
    ("src/mapgen/mapgen_geometry_edit.c",
     b"        for (uint32_t s = 0; s < was_n[k]; s++) {\n            if (!open[s])\n                continue;",
     b"        for (uint32_t s = 0; s < was_n[k]; s++) {\n            if (1)\n                continue;"),
]

# brief 17's rules, taken out by `--red17`: they move the plan itself (a storey not dealt, two storeys not filled), so
# the run's own edits of A-C are not found by their boxes - this RED asks D only
MUTATIONS17 = [
    ("src/mapgen/mapgen_transaction.c",
     b"static const bool g_txn_seam_moved_spared = true;",
     b"static const bool g_txn_seam_moved_spared = false;"),
    ("src/mapgen/mapgen_geometry_edit.c",
     b"    if (lowered && dig_dry_build(plan, donor, ground, &low)) {",
     b"    if (false && lowered && dig_dry_build(plan, donor, ground, &low)) {"),
    ("src/mapgen/mapgen_geometry_edit.c",
     b"static const bool g_reshape_grows_neighbours = true;",
     b"static const bool g_reshape_grows_neighbours = false;"),
    ("src/mapgen/mapgen_geometry_edit.c",
     b"static const bool g_lift_void_filled = true;",
     b"static const bool g_lift_void_filled = false;"),
    ("src/mapgen/mapgen_geometry_edit.c",
     b"static const bool g_lift_shape_closed = true;",
     b"static const bool g_lift_shape_closed = false;"),
    ("src/mapgen/mapgen_geometry_edit.c",
     b"static const bool g_window_variety = true;",
     b"static const bool g_window_variety = false;"),
    ("src/mapgen/mapgen_geometry_edit.c",
     b"        const uint32_t fill = want_storeys < STOREY_FILL ? want_storeys : STOREY_FILL;",
     b"        const uint32_t fill = 0u;"),
    ("src/mapgen/mapgen_geometry_edit.c",
     b"static const bool g_annex_host_clear_of_clip = true;",
     b"static const bool g_annex_host_clear_of_clip = false;"),
]


def check(what: str, ok: bool, detail: str = "") -> bool:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def gcc(sources: list[str], exe: Path, red: dict[str, Path]) -> bool:
    run = subprocess.run(["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"), "-I" + str(REPO / "src" / "mapgen"),
                          "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                         + [str(red.get(s, REPO / s)) for s in sources] + ["-o", str(exe), "-lm"],
                         capture_output=True, text=True, creationflags=NO_WINDOW)
    if run.returncode != 0:
        print(run.stderr[-2000:])
    return run.returncode == 0 and exe.exists()


def compile_map(path: Path) -> str:
    run = subprocess.run([str(ENGINE / "q2tool.exe"), "-bsp", str(path)], capture_output=True, text=True,
                         creationflags=NO_WINDOW, timeout=1800, cwd=str(path.parent))
    return run.stdout + run.stderr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--red", action="store_true")
    ap.add_argument("--red17", action="store_true")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    red: dict[str, Path] = {}
    if a.red17:
        a.red = True
    if a.red:
        texts: dict[str, bytes] = {}
        for rel, rule, without in (MUTATIONS17 if a.red17 else MUTATIONS):
            text = texts.get(rel, (REPO / rel).read_bytes())
            if text.count(rule) != 1:
                check(f"RED: the rule is where it says in {rel}", False, rule[:70].decode())
                return 1
            texts[rel] = text.replace(rule, without)
        for rel, text in texts.items():
            red[rel] = a.work / ("red_" + Path(rel).name)
            red[rel].write_bytes(text)
    driver = a.work / ("driver_red.exe" if a.red else "driver.exe")
    gate = a.work / ("gate_red.exe" if a.red else "gate.exe")
    if not (check("the recut driver builds", gcc(DRIVER_SOURCES, driver, red))
            and check("the reach gate builds", gcc(GATE_SOURCES, gate, red))):
        return 1

    # the warped base: the pipeline's first attempt only, at the PO's options (his run mg_10_6695) on the default frame
    exe = build(a.work, "pipeline_red.exe" if a.red else "pipeline.exe",
                [str(red[s]) if s in red else s for s in PIPELINE_SOURCES], strict=False)
    launch = [l for l in (Path(__file__).resolve().parent / "fixtures" / "mapgen_runs" / "mg_10_6695_q2dm3" / "launches.txt")
              .read_text(encoding="utf-8").splitlines() if "pipeline.exe" in l]
    options = launch[-1].split(" --digs ", 1)[1].split(" --memory ")[0].split() if launch else []
    job = a.work / "job"
    shutil.rmtree(job, ignore_errors=True)
    job.mkdir(parents=True)
    print("warping q2dm3 at the PO's options to 150 %, spread 50 (the first attempt only)", flush=True)
    subprocess.run([str(exe), str(ENGINE / "q2tool.exe"), str(ENGINE / "donors" / "q2dm3.bsp"), str(job), "q2mg",
                    "10", "6695", "--moddir", str(MODDIR), "--memory", "4000", "--checkpoints", "0",
                    "--max-attempts", "2", "--time-budget", "0", "--hold-to-donor",
                    "--digs"] + options + ["--warp-size", "150", "--warp-shape", "50"],
                   capture_output=True, text=True, creationflags=NO_WINDOW, timeout=3600)
    base = job / "warped_base.bsp"
    ledger = (job / "ledger.txt").read_text(encoding="utf-8", errors="replace") if (job / "ledger.txt").exists() else ""
    plan_options = re.search(r"^# plan-options (.*)$", ledger, re.M)
    if not check("the warped base is kept and its plan's options written", base.is_file() and bool(plan_options)):
        return 1
    plan_args = plan_options.group(1).split()
    if a.red17:
        brief17(a, exe, driver, base, plan_args, ledger)
        if not a.keep:
            shutil.rmtree(job, ignore_errors=True)
        print("FAIL" if FAILED else "PASS")
        return 1 if FAILED else 0

    listing = subprocess.run([str(driver), str(base), "--seed", "6695", "--list"] + plan_args, capture_output=True,
                             text=True, creationflags=NO_WINDOW, timeout=1800).stdout
    boxes = {tuple(int(round(float(v))) for v in m.group(3).split()): (int(m.group(1)), m.group(2))
             for m in re.finditer(r"^  editbox (\d+) (\S+) ([-\d. ]+)$", listing, re.M)}

    def edit_at(box: tuple[int, ...]) -> int:
        return boxes.get(box, (-1, ""))[0]

    annex = edit_at((976, -496, 192, 1232, -192, 416))
    doorway = next((i for (b, (i, kind)) in boxes.items() if kind == "open-connector"
                    and b == (443, 462, -128, 487, 619, 128)), -1)
    reshape = 18 if re.search(r"^  edit 18  reshape-room  target 6 ", listing, re.M) else -1
    corners = [e for e in (37, 41) if re.search(rf"^  edit {e}  reshape-room  target ", listing, re.M)]
    chain = [edit_at((80, 800, -40, 400, 1168, 184)), edit_at((985, 446, 0, 1113, 574, 272)),
             edit_at((-1050, 272, -40, -858, 784, 120)), edit_at((-568, -176, -48, -524, -80, 128)),
             edit_at((-440, 72, -56, -360, 152, 384))]
    if not check("the plan is the one the run dealt: the annex, the doorway, the reshape and the five edits found",
                 min([annex, doorway, reshape] + chain) >= 0 and len(corners) == 2,
                 f"annex {annex}, doorway {doorway}, reshape {reshape}, chain {chain}"):
        return 1

    def build_edits(name: str, edits: list[int]) -> tuple[Path, str]:
        d = a.work / name
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        applies = [x for e in edits for x in ("--apply", str(e))]
        subprocess.run([str(driver), str(base), "--seed", "6695"] + applies + ["--out", str(d / "q2mg.map")]
                       + plan_args, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=1800)
        return d / "q2mg.bsp", compile_map(d / "q2mg.map")

    print("A: each edit alone, compiled", flush=True)
    for label, edit in (("the annex by the wall laid off the 8", annex),
                        ("the doorway over the two pools", doorway),
                        ("the reshape whose ceiling grows past its bevel", reshape),
                        ("a reshape at a corner whose wall stood on the void", 37),
                        ("a reshape whose wall stood on the void at its foot and its end", 41)):
        bsp, said = build_edits(f"edit_{edit}", [edit])
        check(f"{label} (edit {edit}) compiles sealed", bsp.is_file() and "leaked" not in said,
              "leaked" if "leaked" in said else "")

    print("B: five edits the run accepted in a row, walked against the base", flush=True)
    bsp, said = build_edits("chain", chain)
    if check("they compile sealed", bsp.is_file() and "leaked" not in said):
        run = subprocess.run([str(gate), str(bsp), "--donor", str(base)], capture_output=True, text=True,
                             creationflags=NO_WINDOW, timeout=3600)
        out = run.stdout + run.stderr
        lost = re.search(r"\d+ landmarks out of reach against the donor's \d+", out)
        check("and lose no landmark: the room of a pickup out of reach on the base too is no landmark lost",
              lost is None, lost.group(0) if lost else "")

    print("C: the run's first attempt", flush=True)
    first = re.search(r"^ +(\d+) (\S+) +(\S+) +\d+ +(-?\d+ -?\d+ -?\d+ +-?\d+ -?\d+ -?\d+)", ledger, re.M)
    check("the plan's largest edit, the tunnel of three halls, is tried first and accepted - no pocket of the void is "
          "water standing in the air",
          bool(first) and first.group(2) == "dig" and first.group(3) == "ACCEPTED"
          and first.group(4).split() == "-122 -1157 -48 710 -581 464".split(),
          " ".join(first.groups()) if first else "no attempt on the ledger")

    brief17(a, exe, driver, base, plan_args, ledger)

    if not a.keep:
        shutil.rmtree(job, ignore_errors=True)
    print("FAIL" if FAILED else "PASS")
    return 1 if FAILED else 0


WINDOW_LOOKS = re.compile(r"^window looks: box (\d+), ellipse (\d+), arch (\d+), vent (\d+); glass:(.*)$", re.M)


def window_kinds(listing: str) -> set[str]:
    """The kinds of pane the plan offers: fixed, shot, plate."""
    kinds = set()
    for m in re.finditer(r"^  window offered(?: FIRST)?: .*?(window fixed|shot (?:down|up)|plate down|as a plate)",
                         listing, re.M):
        kinds.add({"window fixed": "fixed", "plate down": "plate", "as a plate": "plate"}.get(m.group(1), "shot"))
    return kinds


def large_digs(listing: str) -> list[int]:
    return [int(m.group(1)) for m in re.finditer(r"^  edit (\d+)  dig  ", listing, re.M)]


def build_on(a, driver: Path, base: Path, seed: str, args: list[str], name: str, edits: list[int]) -> tuple[Path, str]:
    """Edits applied in a row by the driver at the PO's fidelity (ambition 90), what it said kept, compiled."""
    d = a.work / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    applies = [x for e in edits for x in ("--apply", str(e))]
    run = subprocess.run([str(driver), str(base), "--seed", seed, "--ambition", "90"] + applies
                         + ["--out", str(d / "q2mg.map")] + args, capture_output=True, text=True,
                         creationflags=NO_WINDOW, timeout=3600)
    (d / "applied.txt").write_text(run.stdout + run.stderr, encoding="utf-8")
    return d / "q2mg.bsp", compile_map(d / "q2mg.map")


def brief17(a, exe: Path, driver: Path, base: Path, plan_args: list[str], ledger: str) -> None:
    print("D (brief 17): q2dm3", flush=True)
    # the run's second attempt: the storey after the tunnel, judged - a vertex the compile failed to weld 600 units
    # away in a wall it never touched refused it on Studio 3.20 («a new crack in the world at -218 183 -16»)
    judged = re.search(r"^ +\d+ dig +(\S+) +\d+ +-1008 800 208 +-240 1616 688 .*shape storeys(.*)$", ledger, re.M)
    check("D1 the run's second attempt, the storey, is judged and accepted - a crack far from it is the compile's",
          bool(judged) and judged.group(1) == "ACCEPTED",
          (judged.group(1) + judged.group(2)[:160]) if judged else "no storey row on the ledger")
    listing = subprocess.run([str(driver), str(base), "--seed", "6695", "--ambition", "90", "--list"] + plan_args,
                             capture_output=True, text=True, creationflags=NO_WINDOW, timeout=1800).stdout

    def build_edits(name: str, edits: list[int]) -> tuple[Path, str]:
        return build_on(a, driver, base, "6695", plan_args, name, edits)

    storey = re.search(r"^  edit (\d+)  dig  \d+  -624 720 208 -> -624 1552 368  storeys", listing, re.M)
    if check("D1 the storey at -624 720 208 is dealt", storey is not None):
        bsp, said = build_edits(f"storey_{storey.group(1)}", [int(storey.group(1))])
        check("D1 and compiles sealed", bsp.is_file() and "leaked" not in said, "leaked" if "leaked" in said else "")
    seven = re.search(r"^  edit (\d+)  reshape-room  target 7 ", listing, re.M)
    if check("D2 the reshape of target 7 is dealt", seven is not None):
        bsp, said = build_edits(f"reshape_{seven.group(1)}", [int(seven.group(1))])
        check("D2 and compiles sealed (the floor piece short of the wall carried over the strip)",
              bsp.is_file() and "leaked" not in said, "leaked" if "leaked" in said else "")
    digs = large_digs(listing)
    bsp, said = build_edits("digs_q2dm3", digs)
    applied = (a.work / "digs_q2dm3" / "applied.txt")
    built = len(re.findall(r"^apply \d+ \(dig\): OK, changed yes", applied.read_text() if applied.exists() else "",
                           re.M))
    check(f"D3 every large dig of q2dm3's plan in a row ({len(digs)}) is built and the map sealed",
          bool(digs) and built == len(digs) and bsp.is_file() and "leaked" not in said,
          f"{built} of {len(digs)} built" + (", leaked" if "leaked" in said else ""))
    kinds3 = window_kinds(listing)
    check("D5 q2dm3's plan offers a fixed pane, a shot pane and a plate", kinds3 >= {"fixed", "shot", "plate"},
          ", ".join(sorted(kinds3)))
    windows = [int(m.group(1)) for m in re.finditer(r"^  edit (\d+)  window  ", listing, re.M)]
    bsp, said = build_edits("windows_q2dm3", windows)
    said_w = a.work / "windows_q2dm3" / "applied.txt"
    looks = WINDOW_LOOKS.search(said_w.read_text(encoding="utf-8") if said_w.exists() else "")
    outlines = sum(1 for k in range(1, 5) if looks and int(looks.group(k)) > 0)
    tints = len([n for n in re.findall(r" (\d+)", looks.group(5)) if int(n) > 0]) if looks else 0
    check("D5 q2dm3's windows, all applied, sealed, in two outlines or more and two tints or more",
          bsp.is_file() and "leaked" not in said and outlines >= 2 and tints >= 2,
          looks.group(0) if looks else "no window looks said")

    print("D (brief 17): q2dm1 6675 at his options", flush=True)
    launch = [l for l in (Path(r"O:\Claude2\MapgenStudio\data\runs\mg_b16d_q2dm1") / "launches.txt")
              .read_text(encoding="utf-8").splitlines() if "pipeline.exe" in l]
    options = launch[-1].split(" --digs ", 1)[1].split(" --memory ")[0].split() if launch else []
    options = [o for o in options if o not in ("--warp-size", "--warp-shape", "150", "50")]
    job1 = a.work / "job_q2dm1"
    shutil.rmtree(job1, ignore_errors=True)
    job1.mkdir(parents=True)
    subprocess.run([str(exe), str(ENGINE / "q2tool.exe"), str(ENGINE / "donors" / "q2dm1.bsp"), str(job1), "q2mg",
                    "10", "6675", "--moddir", str(MODDIR), "--memory", "4000", "--checkpoints", "0",
                    "--plan-only", "--time-budget", "0", "--hold-to-donor",
                    "--digs"] + options + ["--warp-size", "150", "--warp-shape", "50"],
                   capture_output=True, text=True, creationflags=NO_WINDOW, timeout=3600)
    base1 = job1 / "warped_base.bsp"
    ledger1 = (job1 / "ledger.txt").read_text(encoding="utf-8", errors="replace") if (job1 / "ledger.txt").exists() \
        else ""
    po1 = re.search(r"^# plan-options (.*)$", ledger1, re.M)
    if not check("D4 the warped q2dm1 base is kept and its plan's options written", base1.is_file() and bool(po1)):
        return
    args1 = po1.group(1).split()
    list1 = subprocess.run([str(driver), str(base1), "--seed", "6675", "--ambition", "90", "--list"] + args1,
                           capture_output=True, text=True, creationflags=NO_WINDOW, timeout=1800).stdout

    def build1(name: str, edits: list[int]) -> tuple[Path, str]:
        return build_on(a, driver, base1, "6675", args1, name, edits)

    storeys1 = re.search(r"^  dig storeys dealt: (\d+) of", list1, re.M)
    annexes1 = re.search(r"^  dig annexes: (\d+) dealt of", list1, re.M)
    check("D4 q2dm1's plan deals two storeys and six annexes",
          bool(storeys1 and annexes1) and int(storeys1.group(1)) >= 2 and int(annexes1.group(1)) >= 6,
          f"storeys {storeys1.group(1) if storeys1 else '?'}, annexes {annexes1.group(1) if annexes1 else '?'}")
    gate = a.work / ("gate_red.exe" if a.red else "gate.exe")
    for label, pattern in (("the annex at 1968 304 896", r"1968 304 896 -> \S+ \S+ \S+  annex"),
                           ("the storey at 1392 1936 768", r"1392 1936 768 -> \S+ \S+ \S+  storeys")):
        m = re.search(r"^  edit (\d+)  dig  \d+  " + pattern, list1, re.M)
        if check(f"D4 {label} is dealt", m is not None):
            bsp, said = build1(f"q2dm1_{m.group(1)}", [int(m.group(1))])
            if check(f"D4 {label} compiles sealed (the void beyond the near box's walls filled)",
                     bsp.is_file() and "leaked" not in said, "leaked" if "leaked" in said else "") and "storey" in label:
                walked = subprocess.run([str(gate), str(bsp)], capture_output=True, text=True, creationflags=NO_WINDOW,
                                        timeout=3600)
                out = walked.stdout + walked.stderr
                lost = re.search(r"(\d+) pickups, (\d+) of them out of a player's reach", out)
                check(f"D4 {label}: walked whole, every pickup in reach - its terrace's too",
                      lost is not None and lost.group(2) == "0", lost.group(0) if lost else out[-300:])
    # brief 17: a doorway's host on a wall top under player clip (688 -240 1056 on q2dm1) is no host
    check("D4 no storey of q2dm1's plan has its doorway's host where q2dm1 keeps players out with clip",
          re.search(r"^  edit \d+  dig  \d+  688 -240 1056 -> \S+ \S+ \S+  storeys", list1, re.M) is None)
    digs1 = large_digs(list1)
    bsp, said = build1("digs_q2dm1", digs1)
    out = (a.work / "digs_q2dm1" / "applied.txt").read_text(encoding="utf-8")
    built1 = len(re.findall(r"^apply \d+ \(dig\): OK, changed yes", out, re.M))
    refused = re.search(r"^declined: (.*)$", out, re.M)
    check(f"D4 every large dig of q2dm1's plan in a row ({len(digs1)}) is built and the map sealed",
          bool(digs1) and built1 == len(digs1) and bsp.is_file() and "leaked" not in said,
          f"{built1} of {len(digs1)} built" + (f", {refused.group(1)}" if refused else "")
          + (", leaked" if "leaked" in said else ""))
    kinds1 = window_kinds(list1)
    check("D5 q2dm1's plan offers a fixed pane, a shot pane and a plate", kinds1 >= {"fixed", "shot", "plate"},
          ", ".join(sorted(kinds1)))
    if not a.keep:
        shutil.rmtree(job1, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
