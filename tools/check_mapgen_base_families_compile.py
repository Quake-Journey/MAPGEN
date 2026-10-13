"""Brief 15: the base's own architecture changed - does the map still build, and how much of the arena moved?

    python tools/check_mapgen_base_families_compile.py [--donor q2dm1] [--seeds 6675 1 42] [--ambition 95]

For each seed, at the PO's options (the Studio's words of mg_10_6669), every edit of the four families that change
the base itself - remodel (walls moved, turned, terraces), block, floor-shift (daises, channels), stair-reshape - is
applied in schedule order to the donor's geometry by the recut driver (`--apply-base`), ALL of them at once, with no
transaction to refuse any: stricter than a generation, which keeps only those its gates accept. Then ONE compile, the
BSP stage only (no vis, no light), single-thread at the pin's policy, through the load guard:

    the baseline (the donor rebuilt by the same compiler) compiles sealed      no "leaked"
    the candidate with every base edit compiles sealed                         no "leaked", a .bsp
    the divergence module (the compiled-map measure the brief names), counted over the arena's box only:
        15 % or more of its cells changed by the base's own edits (brief 15 D7)

No pipeline.exe and no generation: two compiles of one map per seed, a few seconds each. The PO's rules: nothing heavy,
nothing on the disk but the two maps and the cell lists in the work folder (removed at the end unless --keep).
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
import mapgen_load_guard as guard  # noqa: E402
from check_mapgen_recut import build_driver, compile_map  # noqa: E402
from check_mapgen_divergence_oracle import GATE_SRC  # noqa: E402

WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\b15_compile")
DONORS = Path(r"O:\Claude2\MapgenStudio\engine\donors")
PO_OPTIONS = ["--digs", "8", "--annexes", "6", "768", "768", "320", "--storeys", "8", "--spans", "8", "--halls", "6",
              "--decor", "100", "--stairways", "10", "--new-water", "15", "--new-slime", "30", "--new-lava", "100"]
FAILS = 0


def check(what: str, ok: bool, detail: str = "") -> bool:
    global FAILS
    FAILS += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def build_gate(out: Path) -> Path:
    exe = out / "divergence_gate.exe"
    run = guard.run(["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"), "-I" + str(REPO / "src" / "mapgen"),
                     "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                    + [str(REPO / s) for s in GATE_SRC] + ["-o", str(exe), "-lm"], capture_output=True, text=True)
    if run.returncode != 0 or not exe.is_file():
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the divergence gate")
    return exe


def compiled(map_path: Path) -> tuple[bool, str]:
    out = compile_map(map_path)
    bsp = map_path.with_suffix(".bsp")
    return bsp.is_file() and "leaked" not in out.lower(), out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--donor", default="q2dm1")
    ap.add_argument("--seeds", nargs="+", default=["6675"])
    ap.add_argument("--ambition", default="95")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    donor = DONORS / f"{a.donor}.bsp"
    driver = build_driver(REPO, WORK)
    gate = build_gate(WORK)
    print(f"{a.donor}: the baseline", flush=True)
    base_map = WORK / f"{a.donor}_base.map"
    guard.run([str(driver), str(donor), "--out", str(base_map)], capture_output=True, text=True, timeout=1200)
    ok, out = compiled(base_map)
    if not check("the baseline compiles sealed", ok, out.strip().splitlines()[-1][:160] if out.strip() else "no output"):
        return 1
    for seed in a.seeds:
        print(f"{a.donor} seed {seed}, ambition {a.ambition}, the PO's options", flush=True)
        cand = WORK / f"{a.donor}_{seed}_base_edits.map"
        run = guard.run([str(driver), str(donor), "--seed", seed, "--ambition", a.ambition, "--apply-base",
                         "--arena-change", "--out", str(cand)] + PO_OPTIONS, capture_output=True, text=True,
                        timeout=1800)
        text = run.stdout + run.stderr
        applied = re.findall(r"^apply \d+ \((\S+)\): \S+, changed (yes|no)", text, re.M)
        declined = re.findall(r"^declined: (.*)$", text, re.M)
        kinds = {}
        for k, ch in applied:
            kinds.setdefault(k, [0, 0])[0 if ch == "yes" else 1] += 1
        check("the base edits apply", any(ch == "yes" for _, ch in applied),
              ", ".join(f"{k} {v[0]} applied {v[1]} declined" for k, v in sorted(kinds.items()))
              + (f"; declined: {'; '.join(sorted(set(d[:70] for d in declined)))}" if declined else ""))
        gauge = re.search(r"arena change \(the base's own architecture\): room (-?\d+) (-?\d+) (-?\d+) \.\. (-?\d+) "
                          r"(-?\d+) (-?\d+);.*?(\d+) of (\d+) boundary cells changed = ([\d.]+) %", text)
        ok, out = compiled(cand)
        check("every base edit at once compiles sealed", ok,
              ("leaked" if "leaked" in out.lower() else "built") + f", {cand.with_suffix('.bsp').stat().st_size // 1024 if cand.with_suffix('.bsp').is_file() else 0} KB")
        if not ok:
            continue
        g = subprocess.run([str(gate), str(base_map.with_suffix(".bsp")), str(cand.with_suffix(".bsp")), "5"],
                           capture_output=True, text=True, timeout=1800,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        agg = re.search(r"together\s+(\d+) permille\s+\((\d+) of (\d+)", g.stdout)
        print("    module:", " ".join(l.strip() for l in g.stdout.splitlines() if "permille" in l)[:400], flush=True)
        if gauge:
            # the arena: on q2dm1 the brief's own box (room 0, 816 176 .. 1808 1680, the room's heights); elsewhere the
            # largest reachable room the generator calls the arena
            room = [gauge.group(i) for i in range(1, 7)]
            box = ["816", "176", room[2], "1808", "1680", room[5]] if a.donor == "q2dm1" else room

            def measured(b: list[str]):
                ga = subprocess.run([str(gate), str(base_map.with_suffix(".bsp")), str(cand.with_suffix(".bsp")), "5",
                                     "--box"] + b, capture_output=True, text=True, timeout=1800,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return re.search(r"together\s+(\d+) permille\s+\((\d+) of (\d+)", ga.stdout)
            arena = measured(box)
            whole_room = measured(room)
            check("the arena's skeleton changed by 15 % or more - the module's own count over its box (brief 15 D7)",
                  bool(arena) and int(arena.group(1)) >= 150,
                  (f"module {int(arena.group(1)) / 10:.1f} % ({arena.group(2)} of {arena.group(3)} cells) over "
                   f"{' '.join(box)}" if arena else "no measure")
                  + (f"; over the room's whole box {int(whole_room.group(1)) / 10:.1f} %" if whole_room else "")
                  + f"; the geometry gauge {gauge.group(9)} %"
                  + (f"; whole map {int(agg.group(1)) / 10:.1f} %" if agg else ""))
    if not a.keep:
        shutil.rmtree(WORK, ignore_errors=True)
    print(f"{'PASS' if not FAILS else 'FAIL'} {FAILS} failed", flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
