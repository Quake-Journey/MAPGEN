"""Is every map we hand over a FINISHED map, and is it the one we checked?

Two of the six maps given to the PO on 2026-09-07 were draft artifacts: bsp and
a fast vis, no rad, a LIGHTING lump of zero bytes. They render flat grey and he
said so. Nothing caught it, because the installer took its reachability claim
from one run's saved report and copied a different file - the anchor sweep had
recorded the last attempt by directory order instead of the accepted one.

That is the defect this guard exists for, and it is a defect of PROVENANCE
rather than of geometry: the architecture of the two drafts measured 0 permille
from the accepted maps. What differed was everything the second half of the
compile produces.

    python tools/check_mapgen_delivery.py [--maps DIR] [--skip-red]
                                          [--skip-load]

Every `mgtest_*.bsp` in the release maps directory has to answer for itself:

    a LIGHTING lump with bytes in it - an unlit map is a draft;
    a VISIBILITY lump with bytes in it;
    a receipt beside it naming its sha256, which has to match the file;
    and, unless --skip-load, it loads in the real client.

The receipt is `mgtest_delivery.json`, written by
tools/mapgen_install_test_maps.py. A map with no line in it is a map somebody
copied in by hand, which is exactly how the drafts arrived.

Controlled REDs: a draft installed under an mgtest name is refused for its
lighting, and a receipt whose hash does not match the file is refused for that.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as load_guard          # noqa: E402

REPO = Path(__file__).resolve().parent.parent
from mapgen_load_guard import game_dir  # noqa: E402  (brief 13 W1: the game folder of this run)
MAPS = Path(game_dir()) / "maps"
RECEIPT = "mgtest_delivery.json"

LUMP_VISIBILITY = 3
LUMP_LIGHTING = 7

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail
                                                     else ""))
    if not ok:
        FAILED += 1
    return ok


def lump(path: Path, which: int) -> int:
    raw = path.read_bytes()
    if len(raw) < 8 + 19 * 8:
        return 0
    _, length = struct.unpack_from("<ii", raw, 8 + which * 8)
    return length


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def judge(maps: Path, receipt: dict, bsp: Path) -> list[str]:
    """Everything wrong with one delivered map, in words."""
    wrong = []
    if lump(bsp, LUMP_LIGHTING) == 0:
        wrong.append("no lighting - a DRAFT, not a finished map")
    if lump(bsp, LUMP_VISIBILITY) == 0:
        wrong.append("no visibility data")
    line = receipt.get(bsp.stem)
    if not line:
        wrong.append("no line in the delivery receipt - copied in by hand?")
    else:
        got = sha256_of(bsp)
        if got != line.get("sha256"):
            wrong.append(f"the receipt says {str(line.get('sha256'))[:16]},"
                         f" the file is {got[:16]}")
    return wrong


def build_probe(out, name: str, sources: list[str]) -> Path:
    exe = out / f"{name}.exe"
    run = load_guard.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(REPO / s) for s in sources] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-1500:])
        raise SystemExit(f"cannot build {name}")
    return exe


def run_probe(exe: Path, bsp: Path) -> str:
    run = load_guard.run([str(exe), str(bsp)], capture_output=True, text=True,
                         timeout=7200)
    return run.stdout + run.stderr


def probe_number(exe: Path, bsp: Path, rx) -> int:
    m = rx.search(run_probe(exe, bsp))
    return int(m.group(1)) if m else -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--maps", type=Path, default=MAPS)
    ap.add_argument("--skip-red", action="store_true")
    ap.add_argument("--skip-load", action="store_true")
    #
    # `--finished MAP.bsp ...` judges named files for the FINISHED properties
    # alone - a lighting lump and a visibility lump - and asks nothing about a
    # receipt or a band.
    #
    # It exists because the batch of 2026-09-10 never came through this guard:
    # it was installed by a delivery script that ran the texture-axis check
    # and the load check and nothing else, and one map in it had a lighting
    # lump of ZERO bytes because it was compiled with a guard's `-bsp`-only
    # helper. The PO looked at a flat grey level and said «снова утеряны все
    # лайтмапы». Any script that installs a map calls this.
    #
    ap.add_argument("--finished", type=Path, action="append", default=[])
    ap.add_argument("--work", type=Path,
                    default=Path(r"O:\Claude2\_agent_temp\claude"
                                 r"\mapgen1-20260907\delivery"))
    a = ap.parse_args()

    if a.finished:
        print("the maps named, judged as finished maps")
        for bsp in a.finished:
            if not bsp.is_file():
                check(f"{bsp.name} is there", False, str(bsp))
                continue
            light = lump(bsp, LUMP_LIGHTING)
            vis = lump(bsp, LUMP_VISIBILITY)
            check(f"{bsp.stem} is lit and has visibility data",
                  light > 0 and vis > 0,
                  f"lighting {light} bytes, vis {vis} bytes"
                  + ("" if light else " - a DRAFT, not a finished map"))
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1 if FAILED else 0

    a.work.mkdir(parents=True, exist_ok=True)

    receipt_path = a.maps / RECEIPT
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) \
        if receipt_path.is_file() else {}
    handed = sorted(a.maps.glob("mgtest_*.bsp"))

    print("what was handed over")
    check("there are maps to check", bool(handed), str(a.maps))
    check("and a receipt saying what they are", bool(receipt),
          str(receipt_path))
    for bsp in handed:
        wrong = judge(a.maps, receipt, bsp)
        check(f"{bsp.stem} is a finished map, and the one that was checked",
              not wrong,
              "; ".join(wrong) if wrong
              else f"lighting {lump(bsp, LUMP_LIGHTING):,}")

    # A file called f090 that is thirty permille from the donor is not an F90
    # map. The batch of 2026-09-07 handed one over "to show the spread of the
    # seeds", and the PO's first remark was that it looks like the donor.
    for bsp in handed:
        said = receipt.get(bsp.stem, {})
        band = said.get("band")
        check(f"{bsp.stem} is in the band its name claims",
              band == "in band",
              f"{said.get('divergence')} of {said.get('target')}"
              f" permille, {band}")

    # And no map is handed over that fails the gates of 2026-09-07 evening on
    # its own file: water standing in the air, or a machine that carries a
    # player into architecture. Both are measured on the artifact rather than
    # trusted from the run's receipt, because what the PO loads is the file.
    if handed:
        print("and none of them stands water in the air or blocks a lift")
        probes = a.work / "probes"
        probes.mkdir(parents=True, exist_ok=True)
        water = build_probe(probes, "water_probe", [
            "tools/mapgen_water_probe.c", "src/mapgen/mapgen_bsp.c",
            "src/shared/shared.c", "tools/mapgen_host_stubs.c"])
        lift = build_probe(probes, "lift_probe", [
            "tools/mapgen_lift_probe.c", "src/mapgen/mapgen_bsp.c",
            "src/mapgen/mapgen_movers.c", "src/mapgen/mapgen_trace.c",
            "src/shared/shared.c", "tools/mapgen_host_stubs.c"])
        for bsp in handed:
            faces = probe_number(water, bsp,
                                 re.compile(r"vertical liquid faces (\d+)"))
            check(f"{bsp.stem} keeps its water in its basins", faces == 0,
                  f"{faces} vertical liquid faces")
            riders = [int(m) for m in
                      re.findall(r"rider (\d+)  permille",
                                 run_probe(lift, bsp))]
            worst = max(riders) if riders else 0
            check(f"{bsp.stem} carries nobody through the world", worst == 0,
                  f"worst rider {worst} permille over {len(riders)} machines")

    if not a.skip_load and handed:
        print("and the client loads them")
        run = load_guard.run(
            [sys.executable, str(REPO / "tools" / "mapgen_verify_map_loads.py")]
            + [b.stem for b in handed] + ["--seconds", "180"],
            capture_output=True, text=True, timeout=7200)
        out = run.stdout + run.stderr
        for bsp in handed:
            check(f"{bsp.stem} loads",
                  f"LOADS   {bsp.stem} " in out or f"LOADS   {bsp.stem}\n"
                  in out, out[-200:])

    failures = FAILED
    cases = CASES
    if not a.skip_red and handed:
        print("controlled RED")
        sandbox = a.work / "maps"
        if sandbox.exists():
            shutil.rmtree(sandbox)
        sandbox.mkdir(parents=True)
        good = handed[0]
        shutil.copy2(good, sandbox / good.name)
        (sandbox / RECEIPT).write_text(
            json.dumps({good.stem: {"sha256": sha256_of(good)}}),
            encoding="utf-8")

        # A draft: the lighting lump emptied in place, which is exactly what a
        # bsp-and-fast-vis compile produces.
        raw = bytearray(good.read_bytes())
        struct.pack_into("<ii", raw, 8 + LUMP_LIGHTING * 8, 0, 0)
        draft = sandbox / good.name
        draft.write_bytes(bytes(raw))
        wrong = judge(sandbox, json.loads((sandbox / RECEIPT).read_text()),
                      draft)
        ok = any("no lighting" in w for w in wrong)
        print(f"  {'PASS' if ok else 'FAIL'}  RED a draft under an mgtest name"
              f" is refused  -- {wrong}")
        failures += 0 if ok else 1
        cases += 1

        # And a map whose receipt is about some other bytes.
        shutil.copy2(good, draft)
        (sandbox / RECEIPT).write_text(
            json.dumps({good.stem: {"sha256": "0" * 64}}), encoding="utf-8")
        wrong = judge(sandbox, json.loads((sandbox / RECEIPT).read_text()),
                      draft)
        ok = any("the receipt says" in w for w in wrong)
        print(f"  {'PASS' if ok else 'FAIL'}  RED a receipt about other bytes"
              f" is refused  -- {wrong}")
        failures += 0 if ok else 1
        cases += 1

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
