r"""
Brief 14 F5: the checks judge the plan the run made.

The PO's mg_1_6662 (Studio 2.6: digs 8, annexes 6 of 768, storeys 8, spans 8, halls 6, decor, stairways 10, new
water/slime/lava) carried only `--stairways 10 --new-water 15 --new-slime 30 --new-lava 100` in its ledger's
`# plan-options` line, so the gates re-dealt ANOTHER plan («9 stairways in the plan» where the run dealt 8, 4 of its
boxes matched). And the recut driver read `--halls N W H`: the Studio's `--halls 6` swallowed the next option whole.

Read from a generation the PO ran in the Studio (its kept records, `data/runs/<map>`: `launches.txt` - the engine's
words as the Studio gave them -, `ledger.txt`, `progress.txt`). It runs NO generation of its own: the PO, 07.10 - a
guard's pipeline run wrote its files to the disk and hung his editor, «можешь меня попросить чтобы я запустил студию
сам», and the generator's work goes to memory, never to the SSD. Only plan listings (the recut driver, no compile).
  * the ledger's head holds every plan option the Studio passed the engine;
  * the run's first line says whether it resumed;
  * the recut driver, given that line as the gates give it, deals the run's own count of stairways;
RED, in a sandbox: the recut driver's `--halls` back to three numbers - the re-deal differs.

    python tools/check_mapgen_plan_options.py [--run DIR] [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from check_mapgen_recut import build_driver  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

STUDIO = Path(r"O:\Claude2\MapgenStudio")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\plan_options")
# the plan's options and how many words follow each, as the Studio passes them (Options.Args())
PLAN_FLAGS = {"--digs": 1, "--annexes": 4, "--storeys": 1, "--spans": 1, "--halls": 1, "--liquids": 1, "--decor": 1,
              "--stairways": 1, "--new-water": 1, "--new-slime": 1, "--new-lava": 1}
FAILS = 0


def check(what: str, ok: bool, detail: str = "") -> bool:
    global FAILS
    FAILS += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def newest_run() -> Path | None:
    runs = [p for p in (STUDIO / "data" / "runs").glob("*") if (p / "launches.txt").is_file()]
    return max(runs, key=lambda p: (p / "launches.txt").stat().st_mtime) if runs else None


def studio_options(launch: str) -> list[str]:
    words = launch.split()
    return [" ".join(words[i:i + 1 + PLAN_FLAGS[w]]) for i, w in enumerate(words) if w in PLAN_FLAGS]


def listed_stairways(exe: Path, bsp: Path, seed: str, ambition: str, options: str) -> int:
    run = guard.run([str(exe), str(bsp), "--seed", seed, "--ambition", ambition, "--list"] + options.split(),
                    capture_output=True, text=True, timeout=3600)
    m = re.search(r"^\s*stairways: (\d+) dealt of", run.stdout + run.stderr, re.M)
    return int(m.group(1)) if m else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, help="a run's kept records (default: the Studio's newest with launches.txt)")
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    guard.pin_self()
    a.work.mkdir(parents=True, exist_ok=True)
    before = hash_tree(REPO)
    run_dir = a.run or newest_run()
    if not check("a generation of Studio 2.7 or later to read (its launches.txt)", run_dir is not None,
                 "none yet - a map generated in the Studio"):
        return 1
    launch = (run_dir / "launches.txt").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1]
    ledger = (run_dir / "ledger.txt").read_text(encoding="utf-8", errors="replace")
    progress = (run_dir / "progress.txt").read_text(encoding="utf-8", errors="replace")
    head = re.search(r"^# q2mg fidelity (\d+) seed (\d+)$", ledger, re.M)
    m = re.search(r"^# plan-options (.+)$", ledger, re.M)
    line = m.group(1) if m else ""
    want = studio_options(launch)
    missing = [w for w in want if w not in line]
    check(f"{run_dir.name}: the ledger's plan-options line holds every plan option the Studio passed",
          bool(want) and not missing, f"missing {missing}; line: {line}")
    first = progress.splitlines()[0] if progress else ""
    check(f"{run_dir.name}: the run's first line says whether it resumed", " resume=" in first, first)
    pm = re.search(r"stage=plan .*?\bstairways=(\d+)", progress)
    planned = int(pm.group(1)) if pm else -1
    donor = re.search(r"(\S+\.bsp)", launch)
    bsp = STUDIO / "engine" / "donors" / Path(donor.group(1)).name if donor else None
    exe = build_driver(REPO, a.work)
    ambition = str(100 - int(head.group(1))) if head else "0"
    got = listed_stairways(exe, bsp, head.group(2), ambition, line) if head and bsp else -1
    check(f"{run_dir.name}: the checks' re-deal from that line deals the run's own stairways", got == planned,
          f"the run's plan {planned}, the re-deal {got}")
    if not a.no_red and head and bsp and "--halls" in line and planned > 0:
        box = Sandbox(REPO, "planoptions")
        try:
            target = box.root / "tools" / "mapgen_recut_driver.c"
            data = target.read_bytes()
            old = b"if (a + 2 < argc && argv[a + 1][0] != '-' && argv[a + 2][0] != '-') {"
            if check("RED: the halls' optional size is where the mutation says", data.count(old) == 1):
                target.write_bytes(data.replace(old, b"if (a + 2 < argc) {", 1))
                (a.work / "red_bin").mkdir(exist_ok=True)
                red = listed_stairways(build_driver(box.root, a.work / "red_bin"), bsp, head.group(2), ambition, line)
                check("RED: `--halls` swallowing the next option - the re-deal differs, the case goes red",
                      red != planned, f"the run's plan {planned}, the red re-deal {red}")
        finally:
            box.dispose()
    check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    print(f"\n{'PASS' if FAILS == 0 else 'FAIL'}: {FAILS} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
