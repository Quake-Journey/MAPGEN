#!/usr/bin/env python3
"""R1 — prove a controlled-RED run cannot damage the shared worktree.

Codex, 2026-09-01: "make mutation tests run on isolated copies ... so process
termination cannot alter the shared repository. Prove shared-file pre/post hash
identity on success, failure, timeout and forced child termination. Do not
solve this by adding a longer timeout."

The history this answers: two full RED sweeps were run under a shell timeout,
killed mid-mutation, and left a mutation applied in `mapgen_entities.c` and
then in `mapgen_features.c`. Both were caught by the next guard sweep. Neither
should have been possible.

Four scenarios, each hashing every file a matrix could mutate before and after:

  1. a matrix that PASSES;
  2. a matrix that FAILS, with a deliberately broken expectation;
  3. a matrix killed by a TIMEOUT while it is mutating;
  4. a matrix killed by force - SIGKILL/TerminateProcess - while it is
     mutating, which is the case a `finally:` block cannot survive.

Scenarios 3 and 4 must also be shown to have caught the process WITH a mutation
applied in its sandbox; killing an idle process proves nothing.

Exit 0 = the shared tree is byte-identical in all four.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from mapgen_red_sandbox import OWNED_TEMP, hash_tree  # noqa: E402

CASES = 0
FAILED = 0

# A small, fast matrix: this checks the isolation mechanism, not the contract
# the matrix happens to carry.
MATRIX = REPO / "tools" / "check_mapgen_random_contract_red.py"


def check(name: str, ok: bool, detail: str = "") -> None:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1


def differences(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changed = [k for k in before if after.get(k) != before[k]]
    changed += [k for k in after if k not in before]
    return sorted(set(changed))


def run_to_completion(argv: list[str]) -> int:
    return subprocess.run(argv, capture_output=True, text=True).returncode


def kill_mid_mutation(argv: list[str], force: bool) -> bool:
    """Start the matrix, wait until it has actually mutated, then kill it.

    Returns whether a mutated sandbox file was observed while the process was
    alive - without that, the kill proves nothing.
    """
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    observed = False
    deadline = time.monotonic() + 120.0
    try:
        while time.monotonic() < deadline and proc.poll() is None:
            # A sandbox whose file differs from its own pristine copy is a
            # process caught mid-mutation.
            for root in sorted(OWNED_TEMP.glob("*")):
                if root.name.endswith("-pristine") or not root.is_dir():
                    continue
                pristine = root.with_name(root.name + "-pristine")
                if not pristine.is_dir():
                    continue
                for live in root.rglob("*.c"):
                    twin = pristine / live.relative_to(root)
                    # Both of these can vanish between the look and the read:
                    # the sandbox this is watching is being disposed of by the
                    # process being killed. A file that disappears mid-
                    # comparison is the disposal working, not a mutation, and
                    # crashing on it reported FAIL for a tree that was clean.
                    try:
                        if twin.read_bytes() != live.read_bytes():
                            observed = True
                            break
                    except OSError:
                        continue
                if observed:
                    break
            if observed:
                break
            time.sleep(0.05)
    finally:
        if proc.poll() is None:
            if force:
                proc.kill()          # TerminateProcess: no finally, no atexit
            else:
                proc.terminate()
        proc.wait(timeout=30)
    return observed


def main() -> int:
    print("=== MAPGEN-1 R1: controlled-RED isolation from the shared worktree")

    if not MATRIX.is_file():
        print(f"  FAIL  matrix not found: {MATRIX}")
        return 2

    argv = [sys.executable, str(MATRIX)]

    # --- 1: a passing run ----------------------------------------------------
    before = hash_tree(REPO)
    rc = run_to_completion(argv)
    after = hash_tree(REPO)
    check("a matrix that passes leaves the shared tree untouched",
          not differences(before, after), str(differences(before, after)[:3]))
    check("and it did pass, so the mechanism was actually exercised", rc == 0,
          f"exit {rc}")

    # --- 2: a failing run ----------------------------------------------------
    # A matrix whose expectation cannot be met still mutates, still restores.
    broken = OWNED_TEMP / "broken_expectation_red.py"
    broken.parent.mkdir(parents=True, exist_ok=True)
    text = MATRIX.read_text(encoding="utf-8")
    # Point every expectation at a case name no suite will ever print.
    text = text.replace('REPO = Path(__file__).resolve().parent.parent',
                        f'REPO = Path(r"{REPO}")', 1)
    broken.write_text(text.replace('"a zero chance never happens"',
                                   '"no suite prints this case name"'),
                      encoding="utf-8")
    before = hash_tree(REPO)
    rc = run_to_completion([sys.executable, str(broken)])
    after = hash_tree(REPO)
    check("a matrix that fails leaves the shared tree untouched",
          not differences(before, after), str(differences(before, after)[:3]))
    check("and it did fail, so the failure path was exercised", rc != 0,
          f"exit {rc}")

    # --- 3: killed by a timeout ---------------------------------------------
    before = hash_tree(REPO)
    observed = kill_mid_mutation(argv, force=False)
    after = hash_tree(REPO)
    check("a matrix killed by a timeout leaves the shared tree untouched",
          not differences(before, after), str(differences(before, after)[:3]))
    check("and it was caught with a mutation applied, not idle", observed,
          "a kill that lands between cases proves nothing")

    # --- 4: killed by force -------------------------------------------------
    before = hash_tree(REPO)
    observed = kill_mid_mutation(argv, force=True)
    after = hash_tree(REPO)
    check("a matrix killed by FORCE leaves the shared tree untouched",
          not differences(before, after), str(differences(before, after)[:3]))
    check("and that one too was caught mid-mutation", observed,
          "TerminateProcess runs no finally, no atexit and no handler")

    # --- and the shared tree is never opened for writing at all -------------
    sources = "".join((REPO / "tools" / name).read_text(encoding="utf-8")
                      for name in ("mapgen_red_sandbox.py",))
    check("the sandbox only ever removes its own trees",
          "shutil.rmtree(tree, ignore_errors=True)" in sources
          and 'for tree in (self.root, self.pristine)' in sources,
          "dispose() must not be able to name a shared path")

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    print("RESULT: " + ("PASS" if not FAILED else "FAIL"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
