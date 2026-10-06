"""A donor's light is fitted once and then read, never fitted again (ledger row 410; the PO: «и что мы будем каждый
раз по 10 раз генерировать карту чтобы подобрать ей свет???»).

`mapgen_light_calibrate.donor_light` takes a donor's calibration from `tools/mapgen_donor_light.json` by its sha256,
else from its own fit beside it (`NAME.light_fit.json`, written by `tools/mapgen_light_autofit.py`) when that fit is
of this very file; `mapgen_light_autofit.py` on a donor already calibrated says KNOWN and runs no light pass; the
Studio runs the fit before the room-light step and relights the map only when it fitted. No light pass runs here.
RED: `donor_light` without the fit's fallback (a sandbox copy) - the fitted donor reads uncalibrated and would be
fitted again on every map.

    python tools/check_mapgen_light_fit.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
Q2DM1 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
COR = Path(r"O:\Claude2\q2pro-release\baseq2\maps\cor.bsp")
CASES = FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TOOLS))
    spec.loader.exec_module(mod)
    return mod


def cases(cal, work: Path, label: str = "") -> None:
    donor = work / "q2dm1.bsp"
    shutil.copyfile(Q2DM1, donor)
    fit = donor.with_suffix(".light_fit.json")
    fit.unlink(missing_ok=True)
    check(f"{label}a donor in no table and with no fit reads uncalibrated", cal.donor_light(donor) == ("", {}),
          str(cal.donor_light(donor)))
    sha = hashlib.sha256(donor.read_bytes()).hexdigest()
    fit.write_text(json.dumps({"sha256": sha, "flags": "-scale 2.2 -maxlight 196", "keys": {}}), encoding="utf-8")
    got = cal.donor_light(donor)
    check(f"{label}its own fit beside it is read", got == ("-scale 2.2 -maxlight 196", {}), str(got))
    fit.write_text(json.dumps({"sha256": "0" * 64, "flags": "-scale 9", "keys": {}}), encoding="utf-8")
    got = cal.donor_light(donor)
    check(f"{label}a fit of another file is not", got == ("", {}), str(got))
    fit.unlink()


def main() -> int:
    for p in (Q2DM1, COR):
        if not p.is_file():
            print(f"missing {p}")
            return 2
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        cal = load(TOOLS / "mapgen_light_calibrate.py", "cal_green")
        cases(cal, work)
        # the table wins over a fit beside the donor
        cor = work / "cor.bsp"
        shutil.copyfile(COR, cor)
        table = json.loads((TOOLS / "mapgen_donor_light.json").read_text(encoding="utf-8"))
        entry = table.get(hashlib.sha256(cor.read_bytes()).hexdigest(), {})
        cor.with_suffix(".light_fit.json").write_text(json.dumps(
            {"sha256": hashlib.sha256(cor.read_bytes()).hexdigest(), "flags": "-scale 9", "keys": {}}), encoding="utf-8")
        got = cal.donor_light(cor)
        check("the table wins over a fit beside the donor", bool(entry) and got[0] == entry.get("flags"), str(got))
        # a calibrated donor is not fitted again: KNOWN, no light pass, no files written
        before = sorted(p.name for p in work.iterdir())
        r = subprocess.run([sys.executable, str(TOOLS / "mapgen_light_autofit.py"), str(cor), str(cor),
                            str(work / "fitwork")], capture_output=True, text=True, timeout=120)
        after = sorted(p.name for p in work.iterdir())
        check("autofit on a calibrated donor says KNOWN and runs nothing",
              r.returncode == 0 and r.stdout.startswith("KNOWN") and before == after and not (work / "fitwork").exists(),
              (r.stdout + r.stderr).strip()[-200:])
        # the Studio: the fit before the room light, the relight only when it fitted
        gen = (TOOLS / "mapgen_studio" / "MapgenStudio" / "Generation.cs").read_text(encoding="utf-8")
        at_fit, at_rooms = gen.find("mapgen_light_autofit.py"), gen.find("'--donor',r'{donor}']+x")
        check("the Studio fits before its room-light step and relights only when it fitted",
              0 < at_fit < at_rooms and "x=['--relight-first'] if 'FITTED' in f.stdout else []" in gen,
              f"fit at {at_fit}, rooms at {at_rooms}")
        # RED: the fallback taken out
        red = work / "red"
        red.mkdir()
        src = (TOOLS / "mapgen_light_calibrate.py").read_text(encoding="utf-8")
        cut = src.replace("    if entry is None:\n", "    if False:\n", 1)
        check("RED: the mutation is where it says", cut != src)
        (red / "mapgen_light_calibrate.py").write_text(cut, encoding="utf-8")
        shutil.copyfile(TOOLS / "mapgen_donor_light.json", red / "mapgen_donor_light.json")
        global FAILED, CASES
        f0, c0 = FAILED, CASES
        cases(load(red / "mapgen_light_calibrate.py", "cal_red"), work, "RED ")
        red_failed = FAILED - f0
        FAILED, CASES = f0, c0
        check("RED: without the fallback the fitted donor reads uncalibrated", red_failed >= 1,
              f"{red_failed} of its cases failed")
    print(f"{CASES - FAILED}/{CASES} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
