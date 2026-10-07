r"""New water, slime and lava as the PO asks for them (ledger row 412).

The PO, 06.10: «А добавление новых жидкостей можно регулировать? Есть такой параметр? ... например вообще выключать
или менять количество - так, чтобы весь уровень залить водой в максимуме», «нужны аналогичные параметры для заливки
лавой и кислотой». `--new-water / --new-slime / --new-lava N`: the share of the rooms a flood may take, 0..100, or the
default (not given).

On q2dm1 (seed 42, ambition 80), the plan only (the recut driver's `--list`):
* the default deals floods as before (some), and raises pools;
* all three at 0: no flood and no raised pool;
* water 0, lava 100: no flood of water (`e2u3/bluwter`), and lava or slime where a flood is laid;
* water 100: at least as many floods as the default - every room that passes the floods' own gates.
* brief 13 W7 (the PO's mg_1_6662: lava and slime asked, water seen - q2dm1 has a start in every room and every
  hazard flood was turned to water by the start rule): q2dm1 seed 6662 at ambition 99, water 15, slime 30, lava 75 -
  slime and lava floods laid (they retreat from the starts), no «water instead»;
RED, two, in a sandbox copy: a kind at 0 still wanting one room - all three at 0 deals floods; the old rule (a hazard
near a start turned to water) - no slime and no lava at the PO's settings. Each case above goes red.

    python tools/check_mapgen_new_liquid.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from check_mapgen_recut import build_driver  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

REPO = TOOLS.parent
DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\MapgenStudio\engine\donors\q2dm1.bsp")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\new_liquid")
FLOOD = re.compile(r"^  flood offered: (\S+)", re.M)
RELEVEL = re.compile(r"^  edit \d+  relevel", re.M)
FAILED = TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED, TOTAL
    TOTAL += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def plan(exe: Path, *extra: str, seed: str = "42", ambition: str = "80") -> tuple[list[str], int]:
    run = guard.run([str(exe), str(DONOR), "--seed", seed, "--ambition", ambition, "--list", *extra],
                    capture_output=True, text=True, timeout=900)
    text = run.stdout + run.stderr
    return FLOOD.findall(text), len(RELEVEL.findall(text))


def said(f: list[str], r: int) -> str:
    return f"{len(f)} floods ({', '.join(sorted(set(f))) or 'none'}), {r} raised pools"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    (a.work / "bin").mkdir(parents=True, exist_ok=True)
    exe = build_driver(REPO, a.work / "bin")
    base_f, base_r = plan(exe)
    check("q2dm1: the default deals floods and raises pools, as before", len(base_f) > 0 and base_r > 0,
          said(base_f, base_r))
    none_f, none_r = plan(exe, "--new-water", "0", "--new-slime", "0", "--new-lava", "0")
    check("q2dm1: water, slime and lava at 0 - no flood, no raised pool", not none_f and none_r == 0,
          said(none_f, none_r))
    lava_f, lava_r = plan(exe, "--new-water", "0", "--new-lava", "100")
    check("q2dm1: water 0, lava 100 - no new water anywhere, lava laid", "e2u3/bluwter" not in lava_f
          and "e2u3/tlava1_3" in lava_f and lava_r == 0, said(lava_f, lava_r))
    max_f, max_r = plan(exe, "--new-water", "100")
    check("q2dm1: water 100 - as many floods as the default or more", len(max_f) >= len(base_f),
          said(max_f, max_r))
    po = ("--liquids", "mix", "--new-water", "15", "--new-slime", "30", "--new-lava", "75")
    po_f, po_r = plan(exe, *po, seed="6662", ambition="99")
    check("q2dm1 6662/99, slime 30, lava 75 (the PO's mg_1_6662): slime and lava laid, kept off the starts",
          "e2u3/sewer1" in po_f and "e2u3/tlava1_3" in po_f, said(po_f, po_r))
    if not a.no_red:
        before = hash_tree(REPO)
        box = Sandbox(REPO, "newliquid")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            line = b"kind[k].want = g_new_liquid[k] == 0 ? 0u"
            if check("RED: the zero is where the mutation says", data.count(line) == 1):
                target.write_bytes(data.replace(line, b"kind[k].want = g_new_liquid[k] == 0 ? 1u", 1))
                (a.work / "red_bin").mkdir(parents=True, exist_ok=True)
                red = build_driver(box.root, a.work / "red_bin")
                rf, rr = plan(red, "--new-water", "0", "--new-slime", "0", "--new-lava", "0")
                check("RED: with a kind at 0 still wanting a room, floods are dealt - the case above goes red",
                      bool(rf), said(rf, rr))
            old = b"        if (kind[k].hazard) {\n            uint32_t length = 0, gone = 0;"
            data = target.read_bytes().replace(b"kind[k].want = g_new_liquid[k] == 0 ? 1u",
                                               b"kind[k].want = g_new_liquid[k] == 0 ? 0u", 1)
            if check("RED: the start retreat is where the mutation says", data.count(old) == 1):
                # the old rule: a hazard by a start turned to water (k = 0), the room flooded with water instead
                target.write_bytes(data.replace(old, b"        if (kind[k].hazard && (k = 0, false)) {\n"
                                                     b"            uint32_t length = 0, gone = 0;", 1))
                (a.work / "red_bin2").mkdir(parents=True, exist_ok=True)
                red2 = build_driver(box.root, a.work / "red_bin2")
                rf2, rr2 = plan(red2, *po, seed="6662", ambition="99")
                check("RED: hazards turned to water by the start rule - no slime, no lava; the case above goes red",
                      "e2u3/sewer1" not in rf2 and "e2u3/tlava1_3" not in rf2, said(rf2, rr2))
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    print(f"{TOTAL - FAILED}/{TOTAL} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
