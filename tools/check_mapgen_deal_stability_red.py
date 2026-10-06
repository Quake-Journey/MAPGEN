"""Controlled RED for the deal-stability gate.

Each mutation is a real way the deal stops being scale-free or stops being
seeded. The gate is required to FAIL on each of them.

R1: every mutation happens in a disposable copy under the task's own temp root.
The shared worktree is never opened for writing. The first version of this
matrix mutated the real tree in place and restored it in a `finally:` - which
is exactly the practice R1 exists to forbid, and it was written the day after
reading the directive that forbids it. The suite runs guards in parallel, so an
in-place mutation is not merely unsafe on a kill: it is visible to every other
guard compiling at that moment.

A gate that cannot be made to fail is not a gate. This one was written after a
measured defect - one added graft moved 61 of 292 edits - so each mutation is
that defect or its neighbours, not a syntactic poke.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapgen_red_sandbox import Sandbox  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SANDBOX = Sandbox(REPO, Path(__file__).stem)

GUARD = SANDBOX.path('tools/check_mapgen_deal_stability.py')
EDIT = SANDBOX.path('src/mapgen/mapgen_geometry_edit.c')
EDIT_REL = 'src/mapgen/mapgen_geometry_edit.c'

MUTATIONS = [
    # The defect this gate was written for, restored exactly: a position
    # computed from plan->num_edits and a collision resolved by walking to the
    # next free slot. One added graft then moves a fifth of the schedule.
    #
    # An earlier attempt at this mutation - breaking the tie on `index` instead
    # of on (kind, within) - did NOT turn the gate red, and it was right not
    # to: indices are grouped by kind and ascending within it, so ordering by
    # index IS ordering by (kind, within). That mutation was an equivalent
    # rewrite, not a defect. It is recorded here rather than dropped quietly,
    # because a mutation that fails to fire is a claim about the gate that has
    # to be checked before it is believed.
    (
        'the deal goes back to being a function of the total edit count',
        """            qsort(deal, plan->num_edits, sizeof(*deal), deal_order);
            for (uint32_t i = 0; i < plan->num_edits; i++)
                dealt[i] = plan->edits[deal[i].index];""",
        """            uint8_t *taken = calloc(plan->num_edits ? plan->num_edits : 1, 1);
            at = 0;
            for (uint32_t k = 0; k < MAPGEN_EDIT_KINDS; k++) {
                const uint32_t n2 = plan->counts[k];
                for (uint32_t i = 0; i < n2; i++) {
                    uint32_t slot = (uint32_t)(((uint64_t)(2 * i + 1)
                                                * plan->num_edits)
                                               / (2ull * n2));
                    if (slot >= plan->num_edits)
                        slot = plan->num_edits - 1;
                    while (taken[slot]) {
                        slot++;
                        if (slot >= plan->num_edits)
                            slot = 0;
                    }
                    taken[slot] = 1;
                    dealt[slot] = plan->edits[at + i];
                }
                at += n2;
            }
            free(taken);""",
        'a donor adds a graft without moving anything else',
    ),
    (
        'the deal ignores the fraction and keeps the grouped order',
        """    if (x->pos != y->pos)
        return x->pos < y->pos ? -1 : 1;""",
        """    if (0)
        return x->pos < y->pos ? -1 : 1;""",
        'kinds interleave along the run instead of clustering',
    ),
    (
        'the per-kind shuffle stops depending on the seed',
        """            uint64_t kind_stream =
                substream(seed, MapGenGeometryEdit_KindName(""",
        """            uint64_t kind_stream =
                substream(0, MapGenGeometryEdit_KindName(""",
        'different seeds deal differently',
    ),
]


def run_guard() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(GUARD)], capture_output=True,
                       text=True)
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    rc, out = run_guard()
    if rc != 0:
        print(out[-2500:])
        print('the gate is not GREEN in the sandbox; nothing can be proved RED')
        return 1
    print('the gate is GREEN in the sandbox before any mutation\n')

    failures = 0
    for name, old, new in ((m[0], m[1], m[2]) for m in MUTATIONS):
        holds = next(m[3] for m in MUTATIONS if m[0] == name)
        text = EDIT.read_bytes().decode('utf-8')
        # These sources are CRLF in the worktree, and the sandbox is a byte
        # copy. An anchor written with bare newlines matches nothing there, and
        # the first version of this matrix reported three BROKEN anchors for
        # exactly that reason - which is the harness working: a mutation that
        # cannot be APPLIED is never silently counted as one that failed to
        # fire.
        o, n = old, new
        if text.find(chr(13) + chr(10)) >= 0:
            o = o.replace(chr(10), chr(13) + chr(10))
            n = n.replace(chr(10), chr(13) + chr(10))
        if text.count(o) != 1:
            print(f'  BROKEN  {name}  -- {text.count(o)} anchors, expected 1')
            failures += 1
            continue
        try:
            EDIT.write_bytes(text.replace(o, n, 1).encode('utf-8'))
            rc, _ = run_guard()
        finally:
            SANDBOX.restore(EDIT_REL)
        if rc == 0:
            print(f'  FAIL    {name}')
            print(f'          the gate passed anyway, so it does not hold: {holds}')
            failures += 1
        else:
            print(f'  RED     {name}')
            print(f'          holds: {holds}')

    rc, _ = run_guard()
    if rc != 0:
        print('the gate is not GREEN again after restoration')
        return 1
    print('\nthe gate is GREEN again in the sandbox')

    print(f'\n=== {len(MUTATIONS)} mutations, {failures} failures')
    if failures:
        print('RESULT: FAIL')
        return 1
    SANDBOX.dispose()
    print('RESULT: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
