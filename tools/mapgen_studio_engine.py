r"""Fill MAPGEN Studio's `engine` folder from this tree (ledger row 394, Studio P2).

    python tools/mapgen_studio_engine.py STUDIO_DIR

Into STUDIO_DIR/engine: `pipeline.exe` built from this tree with its linker map (`pipeline.map`, what a crash
record is read against), the pinned, M0Q-qualified map compiler as `q2tool.exe`, the donors under `donors\`
(q2dm1 today), and `repo.txt` naming this tree - the delivery gates are its Python tools, run with the system Python
(bundling them is phase P6). `engine.txt` lists every file with its sha256.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from check_mapgen_pipeline import build  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

DONORS = [Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    engine = Path(sys.argv[1]) / "engine"
    engine.mkdir(parents=True, exist_ok=True)
    work = engine / "_build"
    exe = build(work)
    if not exe:
        print("cannot build the pipeline")
        return 1
    shutil.copyfile(exe, engine / "pipeline.exe")
    shutil.copyfile(exe.parent / "pipeline.map", engine / "pipeline.map")
    shutil.rmtree(work, ignore_errors=True)
    shutil.copyfile(pinned_compiler()[0], engine / "q2tool.exe")
    (engine / "donors").mkdir(exist_ok=True)
    for d in DONORS:
        shutil.copyfile(d, engine / "donors" / d.name)
    # row 405: each donor's light calibration beside it, by its sha256 (tools/mapgen_donor_light.json)
    import json
    table = json.loads((REPO / "tools" / "mapgen_donor_light.json").read_text(encoding="utf-8"))
    for bsp in (engine / "donors").glob("*.bsp"):
        entry = table.get(sha(bsp))
        fit = bsp.with_suffix(".light_fit.json")    # row 410: the Studio's own fit of a donor not in the table
        if entry is None and fit.is_file():
            own = json.loads(fit.read_text(encoding="utf-8"))
            entry = own if own.get("sha256") == sha(bsp) else None
        light = bsp.with_suffix(".light.txt")
        keys = bsp.with_suffix(".light_keys.txt")      # row 410: the donor's sun keys, key=value;key=value
        if entry:
            light.write_text(entry["flags"] + "\n", encoding="utf-8")
        elif light.exists():
            light.unlink()
        if entry and entry.get("keys"):
            keys.write_text(";".join(f"{k}={v}" for k, v in entry["keys"].items()) + "\n", encoding="utf-8")
        elif keys.exists():
            keys.unlink()
    (engine / "repo.txt").write_text(str(REPO), encoding="utf-8")
    lines = [f"{sha(p)}  {p.relative_to(engine)}" for p in sorted(engine.rglob("*"))
             if p.is_file() and p.name != "engine.txt"]
    (engine / "engine.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
