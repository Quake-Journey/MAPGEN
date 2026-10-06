r"""Destruction (Fable's brief 11 D2, ledger row 412l) - the ladder, the start rule, the cracked copies, the seal.

The PO, 06.10: «разрушаемость» 0..100, default 0; at 100 «почти весь уровень»; spawns always available; and
«универсальны, а не только для q2dm1». So on two donors as they are - q2dm1 and q3t2 (a finished map is any map) -
the destroy driver at D = 0, 25, 60 and 100 (seed 42), no compile:
* D 0 destroys nothing and needs nothing - the map as today;
* the ladder: the kinds appear at their steps (craters from 20, breaches and gouges from 35, broken edges from 50,
  collapses from 65, ruin from 80) and the whole grows with D;
* the start rule: nothing built or carved within 96 of any start at any D (the driver's own measure);
* every cracked copy is drawn from its original in the game (none missing).
Then once, q2dm1 at 100, the destroy tool whole - pack, driver, bsp, vis, the light pass under q2dm1's calibration:
it compiles sealed (no leak) and lit, and the delivery gates' «starts» and «finished» pass on it.
RED: the same driver with the start keep-out taken out (`DESTROY_STARTS_KEEP` 0, a sandbox copy): at 100 something
stands within 96 of a start - the case above goes red.

    python tools/check_mapgen_destruction.py [--work DIR] [--no-compile] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_destroy as md  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

REPO = TOOLS.parent
DONORS = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\MapgenStudio\engine\donors")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\destruction")
CASES = ["q2dm1", "q3t2"]
LEVELS = [0, 25, 60, 100]
KINDS = ["cracks", "rubble", "craters", "breaches", "gouges", "broken", "collapses", "ruins"]
FAILED = TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED, TOTAL
    TOTAL += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def drive(exe: Path, donor: str, d: int, work: Path, pack: Path) -> dict:
    into = work / "into"
    (into / "textures" / "mgd").mkdir(parents=True, exist_ok=True)
    plist = work / "pack.txt"
    if not plist.is_file():
        md.pack_list(pack, plist)
        md.install(into, pack)          # as the destroy tool does: a crater is drawn into a texture of the pack
    out = work / f"{donor}_{d}.map"
    needs = work / f"{donor}_{d}.needs.txt"
    r = subprocess.run([str(exe), str(DONORS / f"{donor}.bsp"), str(out), "--destruction", str(d), "--seed", "42",
                        "--pack", str(plist), "--needs", str(needs), "--game", str(md.GAME),
                        "--masks", str(pack / "textures" / "mapgen" / "masks"), "--into", str(into)],
                       capture_output=True, text=True, errors="replace", timeout=3600)
    m = md.DESTROYED.search(r.stdout)
    words = m.group(1).split(" wanted ")[0].split() if m else []
    got = {k: float(v) for k, v in zip(words[0::2], words[1::2])}
    dr = md.DRAWN.search(r.stdout)
    got["drawn"] = int(dr.group(1)) if dr else 0
    got["missing"] = int(dr.group(2)) if dr else -1
    got["rc"] = r.returncode
    return got


def said(c: dict) -> str:
    return ", ".join(f"{k} {int(c.get(k, 0))}" for k in KINDS if c.get(k)) or "nothing"


def ladder(exe: Path, work: Path, pack: Path, tag: str) -> dict:
    res = {}
    for donor in CASES:
        for d in LEVELS:
            res[(donor, d)] = drive(exe, donor, d, work / tag, pack)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-compile", action="store_true")
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    if a.work.exists():
        shutil.rmtree(a.work)
    (a.work / "green").mkdir(parents=True)
    pack = md.pack_dir(None)
    exe = md.driver(a.work / "green")
    res = ladder(exe, a.work, pack, "green")
    for donor in CASES:
        z = res[(donor, 0)]
        check(f"{donor} at 0: nothing destroyed, nothing needed", z["rc"] == 0 and not any(z.get(k) for k in KINDS)
              and not z.get("needs"), said(z))
        totals = [sum(res[(donor, d)].get(k, 0) for k in KINDS) for d in LEVELS]
        check(f"{donor}: the ruin grows with D (0/25/60/100)", totals == sorted(totals) and totals[-1] > totals[1] > 0,
              " / ".join(str(int(t)) for t in totals))
        r25, r60, r100 = res[(donor, 25)], res[(donor, 60)], res[(donor, 100)]
        steps_ok = (not r25.get("breaches") and not r25.get("gouges") and not r25.get("broken")
                    and not r25.get("collapses") and not r60.get("collapses") and not r60.get("ruins"))
        check(f"{donor}: each kind from its step of the ladder", steps_ok,
              f"25: {said(r25)}; 60: {said(r60)}; 100: {said(r100)}")
        check(f"{donor} at 100: the carving kinds are there", (r100.get("craters", 0) + r100.get("breaches", 0)
                                                              + r100.get("gouges", 0) + r100.get("collapses", 0)) > 0,
              said(r100))
        near = min(res[(donor, d)].get("nearest", 1e9) for d in LEVELS[1:])
        check(f"{donor}: nothing within 96 of a start at any D", near >= 96.0, f"nearest {near:.0f}")
        miss = [res[(donor, d)]["missing"] for d in LEVELS[1:]]
        check(f"{donor}: every cracked copy drawn from its original", all(m == 0 for m in miss),
              f"drawn {[int(res[(donor, d)]['drawn']) for d in LEVELS[1:]]}, missing {miss}")
    if not a.no_compile:
        bsp = a.work / "q2dm1_100.bsp"
        shutil.copy2(DONORS / "q2dm1.bsp", bsp)
        into = a.work / "compile_into"
        r = subprocess.run([sys.executable, str(TOOLS / "mapgen_destroy.py"), str(bsp), "--donor",
                            str(DONORS / "q2dm1.bsp"), "--destruction", "100", "--seed", "42", "--into", str(into),
                            "--work", str(a.work / "compile")], capture_output=True, text=True, errors="replace",
                           timeout=7200)
        ok = "DESTRUCTION OK" in r.stdout and "left out" not in r.stdout
        check("q2dm1 at 100, the destroy tool whole: compiled sealed with every kind, lit", ok,
              (re.findall(r"^destroyed: .*$", r.stdout, re.M) or [r.stdout[-300:]])[-1][:220])
        if ok:
            g = subprocess.run([sys.executable, str(TOOLS / "check_mapgen_delivery.py"), "--finished", str(bsp)],
                               capture_output=True, text=True, errors="replace", timeout=3600)
            check("q2dm1 at 100: lit, with visibility data", g.returncode == 0 and "0 failures" in g.stdout,
                  g.stdout.strip().splitlines()[-1] if g.stdout.strip() else g.stderr[-200:])
            from mapgen_delivery_gates import ask_starts
            ok2, why = ask_starts(bsp)
            check("q2dm1 at 100: every start stands in air on a floor and can step off", ok2, why)
    if not a.no_red:
        before = hash_tree(REPO)
        box = Sandbox(REPO, "destruction")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            line = b"#define DESTROY_STARTS_KEEP 112.0f"
            if check("RED: the start keep-out is where the mutation says", data.count(line) == 1):
                target.write_bytes(data.replace(line, b"#define DESTROY_STARTS_KEEP 0.0f", 1))
                (a.work / "red").mkdir(parents=True, exist_ok=True)
                saved = md.REPO
                md.REPO = box.root
                try:
                    rexe = md.driver(a.work / "red")
                finally:
                    md.REPO = saved
                near = min(drive(rexe, donor, 100, a.work / "red", pack).get("nearest", 1e9) for donor in CASES)
                check("RED: without the keep-out the ruin comes within 96 of a start - the case above goes red",
                      near < 96.0, f"nearest {near:.0f}")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    print(f"{TOTAL - FAILED}/{TOTAL} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
