"""S3 of a MAPGEN-1 row: the product pipeline once, then every delivery gate on the map it made.

Rounds 34 to 36 ran this from the session's scratch folder, which was wiped while round 36's pipeline ran (ledger row
312); it lives here now.

    python tools/mapgen_round_s3.py ROUND_DIR [--fidelity 20] [--seed 1020] [--donor q2dm1.bsp] [--timeout 5400]

ROUND_DIR/job is the pipeline's job folder (its ledger.txt, its baseline, one folder per attempt), ROUND_DIR/
pipeline.txt its console, ROUND_DIR/deliver/candidate.bsp the map it made, ROUND_DIR/deliver/gates.txt the gates'
answer (`tools/mapgen_delivery_gates.py`). Exit 0 only when the pipeline made a map and every gate passed. Nothing is
installed: `tools/mapgen_install_candidate.py` does that, after a person has read the gates.
"""
import argparse
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as g  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
LINE = re.compile(r"^\s*(\d+)\s+(\S+)\s+(ACCEPTED|REJECTED_\w+)\s+(\d+)(.*)$", re.M)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("round_dir", type=Path)
    ap.add_argument("--fidelity", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1020)
    ap.add_argument("--donor", type=Path, default=DONOR)
    ap.add_argument("--timeout", type=int, default=5400)
    a = ap.parse_args()
    from check_mapgen_pipeline import build as build_pipeline
    from mapgen_pinned_compiler import pinned_compiler

    w = a.round_dir
    job, deliver = w / "job", w / "deliver"
    for d in (w, job, deliver):
        d.mkdir(parents=True, exist_ok=True)
    name = f"q2mg_f{a.fidelity:02d}"
    exe = build_pipeline(w)
    if not exe:
        print("cannot build the pipeline driver", flush=True)
        return 1
    print("pipeline driver:", exe, flush=True)
    began = time.time()
    r = g.run([str(exe), str(pinned_compiler()[0]), str(a.donor), str(job), name, str(a.fidelity), str(a.seed),
               "--moddir", str(GAME), "--final"], capture_output=True, text=True, timeout=a.timeout)
    out = (r.stdout or "") + (r.stderr or "")
    (w / "pipeline.txt").write_text(out, encoding="utf-8")
    print(f"===== pipeline: exit {r.returncode}, {time.time() - began:.0f} s", flush=True)
    for ln in out.strip().splitlines()[-12:]:
        print("   ", ln[:240], flush=True)
    # row 392: a crash leaves its record in the job folder - read it against this very build
    if (job / "crash.txt").is_file():
        from mapgen_crash_symbolicate import symbolicate
        print("===== CRASH RECORD", flush=True)
        for ln in symbolicate(job / "crash.txt", exe, exe.parent / "pipeline.map"):
            print("   ", ln[:240], flush=True)
    ledger = (job / "ledger.txt").read_text(encoding="utf-8", errors="replace") if (job / "ledger.txt").is_file() \
        else ""
    by = {}
    for m in LINE.finditer(ledger):
        by.setdefault(m.group(2), Counter())[m.group(3)] += 1
    for fam, c in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"    {fam:<20} " + ", ".join(f"{k} {v}" for k, v in c.most_common()), flush=True)
    art = re.search(r"^  artifact\s+(.+)$", out, re.M)
    artifact = Path(art.group(1).strip()) if art else None
    if not artifact or not artifact.is_file():
        print("NO MAP", flush=True)
        return 1
    candidate = deliver / "candidate.bsp"
    shutil.copyfile(artifact, candidate)
    print(f"candidate {candidate} from {artifact}", flush=True)
    began = time.time()
    r = g.run([sys.executable, str(REPO / "tools" / "mapgen_delivery_gates.py"), str(candidate), "--job", str(job)],
              capture_output=True, text=True, timeout=7200)
    gates = (r.stdout or "") + (r.stderr or "")
    (deliver / "gates.txt").write_text(gates, encoding="utf-8")
    print(f"===== gates: exit {r.returncode}, {time.time() - began:.0f} s", flush=True)
    for ln in gates.strip().splitlines():
        print("   ", ln[:400], flush=True)
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
