"""Every name the generator reports has the Studio's words for it, in both languages (ledger row 410).

The PO, 05.10, saw «[stage.resume.now]» on the run page; the same scan found the generator's «baseline-faithful»
stage (the base of koldduel1, cor and q3t2), eleven edit kinds (a bridge, a pit, a ramp ...) and the «-» of an
uninterrupted run's end with no words at all - each would have shown as a key in brackets, the last one inside the
map's own description. The Studio's string table (`tools/mapgen_studio/MapgenStudio/Loc.cs`) is read against:

* the stages the pipeline writes (`progress_line("stage=...`): each has `stage.X.now`, or is one of the lines that are
  not a stage of the run (`try`, `baseline-faithful`, `resume-diverged`, `resume-failed`) and the Studio's progress
  reader leaves the stage alone for any name without words (`Loc.Has($"stage.{stage}.now")`);
* every edit kind (`MapGenGeometryEdit_KindName`): `kind.X`;
* the pipeline's results a run can end with but no map (`result.X`) - every ERR_ name but the caller's own mistakes;
* every key the Studio's code names literally, in Russian and in English, and the two tables hold the same keys.

RED: the table without `stage.resume.now` (a sandbox copy) - the case goes red.

    python tools/check_mapgen_studio_names.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STUDIO = REPO / "tools" / "mapgen_studio" / "MapgenStudio"
NOT_STAGES = {"try", "baseline-faithful", "resume-diverged", "resume-failed"}
CALLER_ERRORS = {"ERR_ARGS", "ERR_UNKNOWN", "ERR_NOT_MEASURED"}
CASES = FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def tables(loc: str) -> tuple[set, set]:
    ru_at, en_at = loc.index("Dictionary<string, string> Ru"), loc.index("Dictionary<string, string> En")
    key = re.compile(r'\["([^"]+)"\]\s*=')
    return set(key.findall(loc[ru_at:en_at])), set(key.findall(loc[en_at:]))


def names(loc: str, label: str = "") -> None:
    ru, en = tables(loc)
    check(f"{label}the Russian and the English tables hold the same keys", ru == en,
          f"only ru {sorted(ru - en)[:5]}, only en {sorted(en - ru)[:5]}")
    pipe = (REPO / "src" / "mapgen" / "mapgen_pipeline.c").read_text(encoding="utf-8", errors="replace")
    stages = set(re.findall(r'progress_line\("stage=([a-z-]+)', pipe))
    lacking = sorted(s for s in stages - NOT_STAGES if f"stage.{s}.now" not in ru)
    check(f"{label}every stage the pipeline writes has its words ({len(stages)} names)", bool(stages) and not lacking,
          f"without: {lacking}")
    edit = (REPO / "src" / "mapgen" / "mapgen_geometry_edit.c").read_text(encoding="utf-8", errors="replace")
    at = edit.index("const char *MapGenGeometryEdit_KindName(")
    kinds = set(re.findall(r'return "([a-z-]+)";', edit[at:at + 4000]))
    lacking = sorted(k for k in kinds if f"kind.{k}" not in ru)
    check(f"{label}every edit kind has its words ({len(kinds)} kinds)", len(kinds) > 10 and not lacking,
          f"without: {lacking}")
    results = set(re.findall(r'return "(ERR_[A-Z_]+)";', pipe)) - CALLER_ERRORS
    lacking = sorted(r for r in results if f"result.{r}" not in ru)
    check(f"{label}every result a run can end with has its words ({len(results)})", bool(results) and not lacking,
          f"without: {lacking}")
    used = set()
    for cs in STUDIO.glob("*.cs"):
        s = cs.read_text(encoding="utf-8")
        for pat in (r'Loc\.(?:T|F|Has)\(\s*"([^"]+)"', r'Ui\.(?:Button|Section)\(\s*"([a-z][\w.]+)"',
                    r'\.Tip\(\s*"([^"]+)"', r'Ui\.Button\(\s*"[^"]+",\s*"([^"]+)"'):
            used |= set(re.findall(pat, s))
    lacking = sorted(k for k in used if k not in ru or k not in en)
    check(f"{label}every key the Studio names has its words in both languages ({len(used)} keys)", not lacking,
          f"without: {lacking[:8]}")


def main() -> int:
    loc = (STUDIO / "Loc.cs").read_text(encoding="utf-8")
    names(loc)
    gen = (STUDIO / "Generation.cs").read_text(encoding="utf-8")
    check("the progress reader leaves the stage alone for a name without words",
          'if (Loc.Has($"stage.{stage}.now"))' in gen)
    # RED: one stage's words taken out
    red = re.sub(r'\s*\["stage\.resume\.now"\] = "[^"]*",', "", loc, count=1)
    check("RED: the mutation is where it says", red != loc)
    global FAILED, CASES
    f0, c0 = FAILED, CASES
    names(red, "RED ")
    red_failed = FAILED - f0
    FAILED, CASES = f0, c0
    check("RED: without stage.resume.now the stages' case goes red", red_failed >= 1, f"{red_failed} failed")
    print(f"{CASES - FAILED}/{CASES} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
