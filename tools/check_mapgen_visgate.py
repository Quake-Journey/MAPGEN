"""Does the transaction refuse an edit whose compiled map HIDES a surface a player can see - and only that?

The PO recorded a hole out of the level on the curved stair under corridor 12,
on mg_20b, mg_20c and mg_20d (2026-09-14, viewpos 920 65 718). The geometry was
sealed and every face drawn; the compiler's own visibility no longer joined the
stair to the step the player stood over, so the renderer skipped it. The flood of
corridor 12 made it, in the very draft that added the flood (ledger row 297).

Round 33 (row 299) then showed the other half: the gate refused five edits that
were no holes at all - a sightline under the flood's slime or q2dm1's own opaque
water, where the compiler's visibility rightly stops and so does the eye, and one
that grazed an edge. The sightline now stops at every content the compiler's
visibility can stop at, in a box a unit each way.

This asks `MapGenTransaction_HiddenInSight` - the question REJECTED_HIDDEN is
decided by - through `tools/mapgen_visgate_oracle.c`, on copies of drafts kept
beside the corpus, each checked against the digest its row declared:

    the flood of corridor 12, round 32's try_0111 -> try_0123: pairs are lost,
        from the lattice and from the PO's own eye;
    try_0111 against itself, and dig 111 (try_0103 -> try_0111): none;
    round 33's flood under slime (try_0011 -> try_0014), the window whose eye is
        under water (try_0025 -> try_0034), flood 96 from the eye that grazed an
        edge (try_0094 -> try_0096) and the accepted stairs-to-lift
        (try_0008 -> try_0011): none.

Then three controlled REDs, each in a disposable sandbox (the shared tree is
hashed before and after): the question stops consulting the candidate's PVS (the
flood loses nothing), the sightline stops only at SOLID again (the slime flood
loses pairs), and the box shrinks to nothing again (the grazing eye loses its
pair). Each is a case above going red, and this guard must say so.

    python tools/check_mapgen_visgate.py [--work DIR] [--skip-red]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as guard  # noqa: E402
from check_mapgen_transaction import SOURCES as TXN_SOURCES  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DRAFTS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\visgate")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\visgate_guard")
DRAFT_SHA256 = {
    # row 297: round 32
    "try_0103.bsp": "aa4dc9ea8d85a65e",
    "try_0111.bsp": "225bc7fd9ced6f0c",
    "try_0123.bsp": "8a18099046ad8939",
    # row 299: round 33
    "r33_try_0008.bsp": "7c28ca1566c73ab6",
    "r33_try_0011.bsp": "824f2aa65d6a43c7",
    "r33_try_0014.bsp": "3fe0eba6649dcafb",
    "r33_try_0025.bsp": "c5c8c22df4cb731f",
    "r33_try_0034.bsp": "d4580e9f56396fd6",
    "r33_try_0094.bsp": "5f350c09cf511342",
    "r33_try_0096.bsp": "ed5779493db1edf0",
}

# The oracle links everything the transaction does, with its own main.
SOURCES = [s for s in TXN_SOURCES if s != "tools/mapgen_transaction_driver.c"] \
    + ["tools/mapgen_visgate_oracle.c"]

FLOOD = ["1008", "-112", "878", "1904", "80", "896"]
DIG111 = ["40", "552", "432", "168", "680", "720"]
SLIME = ["976", "1424", "678", "1392", "1680", "768"]
WINDOW = ["192", "-328", "576", "288", "-312", "768"]
FLOOD96 = ["1520", "16", "422", "1904", "496", "512"]
LIFT = ["448", "504", "568", "544", "672", "624"]
PO_EYE = ["--eye", "920", "65", "718"]
GRAZING_EYE = ["--eye", "1896", "-22", "670"]
LOST = re.compile(r"(\d+) eyes, (\d+) pairs LOST")

TXN = b"src/mapgen/mapgen_transaction.c"
REDS = [
    ("the question stops consulting the candidate's PVS",
     b"MapGenBsp_ClusterSees(candidate, em->cluster, sm->mine)", b"true",
     ("try_0111.bsp", "try_0123.bsp", FLOOD, []), "the flood of corridor 12 loses nothing",
     lambda eyes, lost: eyes > 0 and lost == 0),
    ("the sightline stops only at SOLID again",
     b"MAPGEN_TXN_HIDDEN_STOPS, &tr);", b"MAPGEN_CONTENTS_SOLID, &tr);",
     ("r33_try_0011.bsp", "r33_try_0014.bsp", SLIME, []), "the flood under slime loses pairs",
     lambda eyes, lost: eyes > 0 and lost > 0),
    ("the box the sightline sweeps shrinks to nothing again",
     b"#define MAPGEN_TXN_HIDDEN_HALF  1.0f", b"#define MAPGEN_TXN_HIDDEN_HALF  0.0f",
     ("r33_try_0094.bsp", "r33_try_0096.bsp", FLOOD96, GRAZING_EYE),
     "the eye that grazed an edge loses its pair",
     lambda eyes, lost: eyes == 1 and lost > 0),
]

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


def build(root: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in SOURCES] + ["-o", str(out), "-lm"],
        capture_output=True, text=True)
    if run.returncode == 0 and out.is_file():
        return ""
    errs = [ln for ln in run.stderr.splitlines() if "error" in ln.lower()]
    return "\n".join(errs) if errs else run.stderr[-1500:]


def ask(exe: Path, parent: str, candidate: str, box: list[str],
        extra: list[str]) -> tuple[int, int, str]:
    began = time.time()
    run = guard.run([str(exe), str(DRAFTS / parent), str(DRAFTS / candidate)] + box + ["256"]
                    + extra, capture_output=True, text=True, timeout=1800)
    text = ((run.stdout or "") + (run.stderr or "")).strip()
    text = f"{text} [{time.time() - began:.1f} s]"
    m = LOST.search(text)
    return (int(m.group(1)), int(m.group(2)), text) if m else (-1, -1, text[-300:])


def red() -> None:
    before = hash_tree(REPO)
    box = Sandbox(REPO, "visgate")
    try:
        target = box.root / TXN.decode()
        for what, anchor, broken, (parent, cand, bx, extra), then, holds in REDS:
            print(f"=== controlled RED: {what}")
            box.restore(TXN.decode())
            data = target.read_bytes()
            if not check("the line to break is where the mutation says",
                         data.count(anchor) == 1, f"{data.count(anchor)} occurrences"):
                continue
            target.write_bytes(data.replace(anchor, broken, 1))
            red_exe = box.root / "visgate_red.exe"
            err = build(box.root, red_exe)
            if not check("the mutated tree still compiles", not err, err):
                continue
            eyes, lost, text = ask(red_exe, parent, cand, bx, extra)
            check(f"RED: {then} - a case above goes red", holds(eyes, lost), text)
    finally:
        box.dispose()
        check("the shared worktree was never opened for writing", hash_tree(REPO) == before)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    print("=== the drafts the gate is asked about")
    for name, prefix in DRAFT_SHA256.items():
        path = DRAFTS / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"
        check(f"{name} is the copy its row declared", digest.startswith(prefix),
              f"{path} {digest[:16]}")
    if FAILED:
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1

    exe = a.work / "visgate_oracle.exe"
    err = build(REPO, exe)
    if not check("the oracle builds with the transaction's own sources", not err, err):
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1

    print("=== a hole the compiler made (row 297)")
    eyes, lost, text = ask(exe, "try_0111.bsp", "try_0123.bsp", FLOOD, [])
    check("the flood of corridor 12 loses pairs a player sees", eyes > 0 and lost > 0, text)
    eyes, lost, text = ask(exe, "try_0111.bsp", "try_0123.bsp", FLOOD, PO_EYE)
    check("... and from the PO's own eye", eyes == 1 and lost > 0, text)
    eyes, lost, text = ask(exe, "try_0111.bsp", "try_0111.bsp", FLOOD, [])
    check("the same map against itself loses none", eyes > 0 and lost == 0, text)
    eyes, lost, text = ask(exe, "try_0103.bsp", "try_0111.bsp", DIG111, [])
    check("dig 111, far from the stair, loses none", eyes > 0 and lost == 0, text)

    print("=== and no hole where the eye itself stops (row 299)")
    eyes, lost, text = ask(exe, "r33_try_0011.bsp", "r33_try_0014.bsp", SLIME, [])
    check("the flood whose floor lies under opaque slime loses none", eyes > 0 and lost == 0, text)
    eyes, lost, text = ask(exe, "r33_try_0025.bsp", "r33_try_0034.bsp", WINDOW, [])
    check("the window seen from under q2dm1's opaque water loses none",
          eyes > 0 and lost == 0, text)
    eyes, lost, text = ask(exe, "r33_try_0094.bsp", "r33_try_0096.bsp", FLOOD96, GRAZING_EYE)
    check("flood 96 from the eye whose line grazed an edge loses none",
          eyes == 1 and lost == 0, text)
    eyes, lost, text = ask(exe, "r33_try_0008.bsp", "r33_try_0011.bsp", LIFT, [])
    check("the accepted stairs-to-lift loses none", eyes > 0 and lost == 0, text)

    if not a.skip_red:
        red()

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
