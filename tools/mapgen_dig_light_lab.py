r"""A dig's room lit as the finished map lights it, and measured against the light round its door (row 408, Fable's
brief 6 P2/P3).

    python tools/mapgen_dig_light_lab.py DONOR.bsp WORK_DIR [--tree DIR] [--attempts N] [--skip LIST]

Builds the transaction driver from the tree, attempts the donor's digs (`--only dig`, seed 42, ambition 80), takes
the last accepted try's map, gives it the donor's sun the way the pipeline's light compile does and runs the light
pass alone with the donor's calibrated flags (`tools/mapgen_donor_light.json`), then asks every accepted dig's room
what the light gate asks (`mapgen_light_profile.room_against_door`). Heavy launches go through the load guard; one
light pass at a time.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from check_mapgen_pipeline import SOURCES  # noqa: E402
from mapgen_light_calibrate import donor_light, entity_text, with_entities, with_keys, with_sun  # noqa: E402
from mapgen_light_profile import room_against_door  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

GAME = r"O:\Claude2\q2pro-release\baseq2"
LOG = re.compile(r"attempt=(\d+) edit=(\d+) family=dig verdict=ACCEPTED .*?box=(\S+) (\S+) (\S+)\.\.(\S+) (\S+) (\S+)"
                 r".*? dig_from=(\S+) dig_to=(\S+) dig_shape=(\S+)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("donor", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--tree", type=Path, default=TOOLS.parent)
    ap.add_argument("--attempts", default="1")
    ap.add_argument("--skip", default="-1")
    a = ap.parse_args()
    guard.pin_self()
    a.work.mkdir(parents=True, exist_ok=True)
    src = [s if s != "tools/mapgen_pipeline_driver.c" else "tools/mapgen_transaction_driver.c" for s in SOURCES]
    exe = a.work / "txn.exe"
    r = subprocess.run(["gcc", "-std=c17", "-O2", "-I" + str(a.tree / "inc"), "-I" + str(a.tree / "src" / "mapgen"),
                        "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                       + [str(a.tree / s) for s in src] + ["-o", str(exe), "-lm", "-lz"], capture_output=True,
                       text=True)
    if r.returncode:
        print(r.stderr[-1500:])
        return 1
    job = a.work / "job"
    if job.exists():
        shutil.rmtree(job)
    job.mkdir()
    compiler = str(pinned_compiler()[0])
    flags, _ = donor_light(a.donor)
    guard.run([str(exe), compiler, str(a.donor), str(job), "q2mg", GAME, "42", a.attempts, "--only", "dig",
               "--skip", a.skip, "--ambition", "80", "--light-flags", flags], capture_output=True, text=True,
              timeout=7200)
    log = (job / "attempts.log").read_text(encoding="utf-8", errors="replace") if (job / "attempts.log").is_file() \
        else ""
    digs = []
    for m in LOG.finditer(log):
        digs.append({"try": int(m.group(1)) - 1, "box": [float(v) for v in m.groups()[2:8]],
                     "from": [float(v) for v in m.group(9).split(",")], "to": [float(v) for v in m.group(10).split(",")],
                     "shape": m.group(11)})
    if not digs:
        print("no dig accepted")
        return 1
    last = job / f"try_{digs[-1]['try']:04d}" / "q2mg.bsp"
    (a.work / "digs.json").write_text(json.dumps(digs), encoding="utf-8")
    lit = a.work / "lit"
    if lit.exists():
        shutil.rmtree(lit)
    lit.mkdir()
    raw = last.read_bytes()
    own = entity_text(raw)
    _, keys = donor_light(a.donor)        # row 410: the donor's sun as the tool must be told it
    lit_text = with_keys(own, keys)
    sunny = with_sun(lit_text)
    threads = str(bin(guard.affinity_mask()).count("1"))
    # the try's map carries no visibility, and without it the light tool lights directly only - no bounce, which the
    # finished map has (its light compile runs full vis first): measured, every wall of the first tries read dark
    vis = ["-vis", "-threads", threads, "-moddir", GAME, "-basedir", GAME, "-gamedir", GAME]
    rad = ["-rad", "-maxdata", "8388608", "-threads", threads, *flags.split(), "-moddir", GAME,
           "-basedir", GAME, "-gamedir", GAME]
    prt = last.with_suffix(".prt").read_bytes() if last.with_suffix(".prt").is_file() else None
    # row 411 (Fable's brief 8 D): vis and light in memory - only the lit result reaches the disk
    from mapgen_memfile import compile_bsp_in_memory
    runs, out = compile_bsp_in_memory(compiler, [vis, rad], with_entities(raw, sunny or lit_text), prt,
                                      label="diglight")
    if runs is None:
        (lit / "q2mg.bsp").write_bytes(with_entities(raw, sunny or lit_text))
        if prt:
            (lit / "q2mg.prt").write_bytes(prt)
        guard.run([compiler, *vis, str(lit / "q2mg.map")], capture_output=True, text=True, errors="replace",
                  timeout=7200)
        r = guard.run([compiler, *rad, str(lit / "q2mg.map")], capture_output=True, text=True, errors="replace",
                      timeout=7200)
        out = (lit / "q2mg.bsp").read_bytes()
    else:
        r = runs[-1]
    (lit / "rad.log").write_text(r.stdout, encoding="utf-8")
    (lit / "q2mg.bsp").write_bytes(with_entities(out or raw, own))
    lamps = re.findall(r'\{[^{}]*"classname" "light"[^{}]*\}', own)
    print(f"lit with '{flags}' (exit {r.returncode}); {len(lamps)} lights in the map,"
          f" {sum(1 for x in lamps if '_cone' in x)} downlights")
    for d in digs:
        own_end = d["shape"] == "annex" or (d["shape"] == "storeys" and abs(d["to"][2] - d["from"][2] - 160) < 1)
        doors = [d["from"]] if own_end else [d["from"], d["to"]]
        ok, said = room_against_door(lit / "q2mg.bsp", a.donor, d["box"], doors)
        print(f"  {'PASS' if ok else 'FAIL'} {d['shape']} {[round(v) for v in d['box'][:3]]}: {said}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
