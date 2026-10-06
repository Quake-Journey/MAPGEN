"""Controlled RED for the client-integration gate.

Each mutation is the real defect the assertion is about, applied to a COPY of
the tree; the originals are restored from bytes held in memory, and the run
reports the tree's hash before and after so an interrupted RED cannot leave a
mutation behind.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r'O:\Claude2\q2pro')
GUARD = REPO / 'tools' / 'check_mapgen_client_integration.py'
CLIENT = REPO / 'src' / 'client' / 'mapgen_client.c'
MENU = REPO / 'src' / 'client' / 'ui' / 'q2pro-x.menu2'
OWNERSHIP = REPO / 'src' / 'common' / 'q2prox_config_ownership.c'


def hash_tree() -> str:
    h = hashlib.sha256()
    for p in sorted((REPO / 'src').rglob('*')):
        if p.is_file():
            h.update(p.relative_to(REPO).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def run() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(GUARD)], capture_output=True,
                       text=True)
    return p.returncode, p.stdout + p.stderr


MENU_C = REPO / 'src' / 'client' / 'ui' / 'menu.c'

NOTICE = REPO / 'src' / 'client' / 'ui' / 'mapgen_notice.c'

MUTATIONS = [
    (
        "the panel is composed once and never refreshed",
        NOTICE,
        "    s_live(scratch, size, MGN_Ru());",
        "    (void)s_live;",
        "the panel is live, not a sentence that was true once",
    ),
    (
        "the end never announces itself",
        CLIENT,
        "        if (!mapgen_announced) {",
        "        if (false) {",
        "the end announces itself, once, naming the map",
    ),
    (
        "a button acts on the value the field had before",
        MENU_C,
        "    if (item->type == MTYPE_ACTION)\n        Menu_CommitEditedFields(s, item);",
        "    if (false)\n        Menu_CommitEditedFields(s, item);",
        "a button acts on what the page shows",
    ),
    (
        "the donor box stops taking a list",
        CLIENT,
        "        while (*end && *end != ';')",
        "        while (*end)",
        "the donor box takes a list",
    ),
    (
        "a job is submitted before the names are checked",
        CLIENT,
        "    if (!donors_are_installed(names, count))\n        return;",
        "    (void)donors_are_installed;",
        "every named map is checked before a job is submitted",
    ),
    (
        "the donor loses its working default",
        CLIENT,
        'Cvar_Get("mapgen_donor", "q2dm1"',
        'Cvar_Get("mapgen_donor", ""',
        "the donor has a default that works",
    ),
    (
        "a command shares a name with a cvar",
        CLIENT,
        'Cmd_AddCommand("mapgen_list", mapgen_maps_f);',
        'Cmd_AddCommand("mapgen_maps", mapgen_maps_f);',
        "no command shares a name with a cvar",
    ),
    (
        "the page invokes a command nobody registered",
        MENU,
        '"Play the newest" mapgen_play',
        '"Play the newest" mapgen_play_the_newest_one',
        "every command the page invokes is registered",
    ),
    (
        "the page edits a cvar nobody registered",
        MENU,
        '"Seed" mapgen_seed',
        '"Seed" mapgen_seed_value',
        "every cvar the page edits is registered",
    ),
    (
        "an archived setting has no ownership rule",
        OWNERSHIP,
        '"mapgen_"',
        '"mapgen_disabled_"',
        "config ownership claims the mapgen prefix",
    ),
    (
        "a row loses its Russian name",
        MENU,
        '--name-ru "Играть последнюю" "Play the newest"',
        '"Play the newest"',
        "every named row has a Russian name",
    ),
    (
        "a row loses its Russian hint",
        MENU,
        '--status-ru "Играть последнюю построенную." --name-ru "Играть последнюю"',
        '--name-ru "Играть последнюю"',
        "every row with a hint has a Russian hint",
    ),
    (
        "the page admits it is unfinished",
        MENU,
        '"Play the newest" mapgen_play',
        '"Play the newest (TODO)" mapgen_play',
        "no unfinished vocabulary on the page",
    ),
]


def main() -> int:
    before = hash_tree()
    print(f"tree before: {before}")

    rc, out = run()
    if rc != 0:
        print("the gate is not GREEN to begin with:")
        print(out[-1500:])
        return 1
    print("GREEN before any mutation")

    failures = 0
    originals = {p: p.read_bytes() for p in (CLIENT, MENU, OWNERSHIP, MENU_C, NOTICE)}
    try:
        for name, path, old, new, expect in MUTATIONS:
            text = path.read_text(encoding='utf-8')
            if old not in text:
                print(f"  FAIL  {name}: the site was not found")
                failures += 1
                continue
            path.write_text(text.replace(old, new, 1), encoding='utf-8')
            rc, out = run()
            path.write_bytes(originals[path])

            fired = rc != 0 and f"FAIL  {expect}" in out
            print(f"  {'RED ' if fired else 'FAIL'}  {name}"
                  f"{'' if fired else '  -- the gate stayed green'}")
            if not fired:
                failures += 1
    finally:
        for p, data in originals.items():
            p.write_bytes(data)

    rc, out = run()
    if rc != 0:
        print("the gate did not come back GREEN:")
        print(out[-1500:])
        failures += 1
    else:
        print("GREEN again after every mutation was restored")

    after = hash_tree()
    print(f"tree after:  {after}")
    if after != before:
        print("FAIL: the worktree did not come back to what it was")
        failures += 1

    print(f"\n=== {len(MUTATIONS)} mutations, {failures} failures")
    print("RESULT: FAIL" if failures else "RESULT: PASS")
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
