"""The seeded deal must be scale-free: offering a donor ADDS, it does not re-deal.

Why this gate exists, in one measurement: F75 reached 290 of 250 with no second
donor and 79 of 250 with one, same seed and same worker. That was recorded as
the cost of grafting. It was not. The deal placed edit i of n in its kind at

    slot = (2i + 1) * plan->num_edits / (2n)

- a function of the TOTAL number of edits - and resolved collisions by walking
to the next free slot. So adding a single edit of any kind moved every other
kind, and a second donor adds exactly one graft. Offering a donor was
arithmetically obliged to re-order a schedule the seed had already chosen, and
the transaction spends its budget in schedule order.

Measured on the defect: one added graft moved 61 of 292 edits, first difference
at position three.

The properties asserted here are the ones that make the deal worth having AND
the one it was violating:

  additive      every edit that exists in both plans keeps its relative place
                when a donor is offered; only grafts appear
  proportional  kinds interleave along the run rather than clustering, which is
                what the deal exists for and what a naive sort destroyed
  seeded        different seeds deal differently - the tie-break must never
                fall back to properties of the map
  deterministic the same inputs deal the same way twice
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(r'O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus')

# Keyed on which tree this copy of the gate belongs to. The RED matrix runs the
# SANDBOX copy of this file while the suite may be running the worktree's copy,
# and two builds writing one deal.exe would be a race that reports itself as a
# contract failure somewhere else entirely.
WORK = (Path(r'O:\Claude2\_agent_temp\claude\mapgen1-20260904')
        / ('deal_gate-' + hashlib.sha256(str(REPO).encode()).hexdigest()[:12]))

SOURCES = [
    'tools/mapgen_deal_dump.c',
    'src/mapgen/mapgen_geometry_edit.c',
    'src/mapgen/mapgen_graft.c',
    'src/mapgen/mapgen_geometry.c',
    'src/mapgen/mapgen_bundle.c',
    'src/mapgen/mapgen_closure.c',
    'src/mapgen/mapgen_rooms.c',
    'src/mapgen/mapgen_trace.c',
    'src/mapgen/mapgen_bsp.c',
    'src/shared/shared.c',
    'tools/mapgen_host_stubs.c',
]

CASES = 0
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = '') -> bool:
    global CASES
    CASES += 1
    if ok:
        print(f'  PASS  {name}')
    else:
        print(f'  FAIL  {name}' + (f'  -- {detail}' if detail else ''))
        FAILURES.append(name)
    return ok


def build() -> Path | None:
    WORK.mkdir(parents=True, exist_ok=True)
    exe = WORK / 'deal.exe'
    run = subprocess.run(
        ['gcc', '-std=c17', '-O2', '-Wall', '-Wextra',
         '-I' + str(REPO / 'inc'), '-I' + str(REPO / 'src' / 'mapgen'),
         '-DUSE_LITTLE_ENDIAN=1', '-DUSE_CLIENT=1', '-DUSE_SERVER=0',
         '-DUSE_NEW_GAME_API=1', '-DUSE_MVD_CLIENT=1']
        + [str(REPO / s) for s in SOURCES] + ['-o', str(exe), '-lm'],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-3000:])
        return None
    return exe


def deal(exe: Path, seed: int, others: list[str]) -> list[tuple[str, int]]:
    """The schedule, in order, as (kind, target)."""
    cmd = [str(exe), str(CORPUS / 'q2dm1.bsp'), str(seed)] + \
          [str(CORPUS / o) for o in others]
    run = subprocess.run(cmd, capture_output=True, text=True)
    if run.returncode != 0:
        return []
    out = []
    for line in run.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 3:
            out.append((parts[1], int(parts[2])))
    return out


def main() -> int:
    if not (CORPUS / 'q2dm1.bsp').is_file() or not (CORPUS / 'q2dm2.bsp').is_file():
        print(f'the corpus is not at {CORPUS}')
        return 2

    exe = build()
    if not exe:
        print('RESULT: FAIL (the dump did not build)')
        return 1

    print('=== a donor is additive, not a re-deal')
    for seed in (1, 2, 3):
        alone = deal(exe, seed, [])
        withd = deal(exe, seed, ['q2dm2.bsp'])
        if not check(f'seed {seed}: both plans were produced',
                     bool(alone) and bool(withd)):
            continue

        a = [e for e in alone if e[0] != 'graft-bundle']
        b = [e for e in withd if e[0] != 'graft-bundle']
        moved = sum(1 for x, y in zip(a, b) if x != y) if len(a) == len(b) else -1
        check(f'seed {seed}: offering a donor moved no other edit',
              a == b,
              f'{moved} of {len(a)} edits sit elsewhere' if moved >= 0
              else f'{len(a)} edits alone against {len(b)} with a donor')
        check(f'seed {seed}: the donor added at least one graft',
              len(withd) > len(a),
              'a second donor was offered and the schedule did not grow')

    print('\n=== the deal still does what it is for')
    base = deal(exe, 1, [])
    check('the schedule is not empty', len(base) > 50, f'{len(base)} edits')

    # Proportional: no kind may sit in one contiguous block. A kind that
    # clusters is a kind a fidelity either spends entirely or not at all, which
    # is the failure the deal was written to prevent.
    counts = Counter(k for k, _ in base)
    biggest = counts.most_common(1)[0][0] if counts else None
    if biggest:
        at = [i for i, (k, _) in enumerate(base) if k == biggest]
        contiguous = all(at[i] + 1 == at[i + 1] for i in range(len(at) - 1))
        check(f'the largest kind ({biggest}, {len(at)}) is spread, not clustered',
              not contiguous,
              'it occupies one contiguous block')

    # Seeded: the tie-break must not fall back to properties of the map, which
    # would give every seed the same schedule and every seed the same map.
    s1, s2, s3 = deal(exe, 1, []), deal(exe, 2, []), deal(exe, 3, [])
    check('seeds 1 and 2 deal differently', s1 != s2)
    check('seeds 1 and 3 deal differently', s1 != s3)
    check('seeds 2 and 3 deal differently', s2 != s3)

    check('the same seed deals the same way twice', deal(exe, 1, []) == s1)

    print(f'\n=== {CASES} cases asserted, {len(FAILURES)} failures')
    if FAILURES:
        print('RESULT: FAIL')
        return 1
    print('RESULT: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
