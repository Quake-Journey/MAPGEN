"""The anchors, through the WORKER, which is the path the product actually uses.

Section 8 item five of the 2026-09-01 directive asks for
100/90/75/50/25/0 Recipe, report and map artifacts "created through the
integrated worker path, not the standalone fork tool". `mapgen_anchor_sweep.py`
drives the pipeline directly, which is one layer short of that: it proves the
pipeline, not the process the product launches.

This drives the real thing. `mapgen_host_test_driver` starts the packaged
worker over the same IPC the Controller uses, sends a START_GENERATE with the
same `key value` request the Controller sends, and waits for the staged result.
What comes back is what a run of the product would produce.

    python tools/mapgen_worker_anchor_sweep.py <donor.bsp> <work dir>
        [--fidelities 100,90,75,50,25] [--seed N] [--donor OTHER.bsp ...]
        [--json FILE]

Fidelity zero is not run by default: it invents a map and needs a snapshot and
a target manifest, and without them it would report the fork path's answer to a
question it was never asked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")

# The worker, and the host that launches it. Both are product code; the driver
# is the only test-owned piece and it does nothing but speak the protocol.
DRIVER = [
    "tools/mapgen_host_test_driver.c",
    # The process module is platform work and is added by
    # src/windows/meson.build rather than by a list in the root, which is why
    # it is named here explicitly: the first version left it out and the
    # driver failed to link on every MapGenProcess_ symbol it uses.
    "src/windows/mapgen_process.c",
    "src/mapgen/mapgen_ipc.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]


def sha256_of(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(sources: list[str], out: Path, extra: list[str] | None = None) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"),
         "-I" + str(REPO / "src" / "mapgen"), "-DUSE_LITTLE_ENDIAN=1",
         "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
        + (extra or [])
        + [str(REPO / s) for s in sources] + ["-o", str(out), "-lm", "-lz"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2500:]


def worker_sources() -> list[str]:
    """Every module the packaged worker links, read from meson.build.

    Read rather than listed, because a list here would be a second opinion
    about what the worker is - and this sweep exists to run the REAL one. The
    first version of this read three list names, one of which does not exist,
    and came back with the MAPGEN modules and none of the worker's own.

    `q2pro-x-mapgen` names its own files inline and appends `mapgen_src` and
    `mapgen_common_src`, so all three are taken: the executable's argument list
    up to its first keyword argument, plus the lists it refers to.
    """
    text = (REPO / "meson.build").read_text(encoding="utf-8")
    out: list[str] = []

    at = text.find("executable('q2pro-x-mapgen'")
    if at < 0:
        raise SystemExit("meson.build does not declare q2pro-x-mapgen")
    # Its sources end where its first keyword argument begins.
    stop = text.find("dependencies:", at)
    out += re.findall(r"'([^']+\.c)'", text[at:stop if stop > at else at])

    for name in ("mapgen_src", "mapgen_common_src"):
        m = re.search(rf"^{name} = \[(.*?)^\]", text, re.S | re.M)
        if m:
            out += re.findall(r"'([^']+\.c)'", m.group(1))

    seen = list(dict.fromkeys(out))
    if not any(s.endswith("mapgen_worker/main.c") for s in seen):
        raise SystemExit("the worker's own entry point is not in the list")
    return seen


def run_anchor(driver: Path, worker: Path, work: Path, donor: Path,
               fidelity: int, seed: int, others: list[Path],
               snapshot: Path | None = None,
               manifest: Path | None = None,
               goal: int = 4) -> dict:
    job = work / f"f{fidelity:03d}"
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    name = f"q2mg_w{fidelity}"

    request = [
        f"donor {donor}",
        f"jobdir {job}",
        f"mapname {name}",
        f"compiler {COMPILER}",
        f"moddir {GAME}",
        f"fidelity {fidelity}",
        f"seed {seed}",
        f"goal {goal}",
    ] + [f"otherdonor {o}" for o in others]

    # Fidelity zero invents a map, so it needs what was learned and what the
    # target can resolve. Both are the caller's to supply; without them the run
    # would report the fork path's answer to a question nobody asked.
    if snapshot:
        request.append(f"snapshot {snapshot}")
    if manifest:
        request.append(f"manifest {manifest}")

    started = time.time()
    run = subprocess.run([str(driver), str(worker), str(job), "generate",
                          *request],
                         capture_output=True, text=True, timeout=7200)
    took = time.time() - started

    got: dict = {"fidelity": fidelity, "seconds": round(took, 1),
                 "summary": "", "staged": False, "error": ""}
    summary: list[str] = []
    inside = False
    for line in run.stdout.splitlines():
        if line.startswith("--- summary ---"):
            inside = True
            continue
        if line.startswith("--- end ---"):
            inside = False
            continue
        if inside:
            summary.append(line)
        if line.startswith("staged="):
            got["staged"] = True
        if line.startswith("error_detail="):
            got["error"] = line.split("=", 1)[1]
    got["summary"] = "\n".join(summary)

    #
    # The worker's own words. `result` and not `verdict`, and the map lives in
    # the directory of the attempt that was accepted rather than in the job
    # root - the first version of this looked for both under the wrong names
    # and reported a successful run as "?" with no artifact.
    #
    for key in ("result", "divergence", "target", "inband", "publishable",
                "bsp", "bspsha", "recipe", "certificates", "candidateaxes",
                "places", "spawns", "component", "oneway", "lethal",
                "items", "itemsunreachable"):
        m = re.search(rf"^{key}\s+(\S+)", got["summary"], re.M)
        if m:
            got[key] = m.group(1)

    # Hashed here as well as taken from the summary, so the two have to agree:
    # a worker that reported a hash it did not write would pass a check that
    # only read what it said.
    if got.get("bsp"):
        bsp = Path(got["bsp"])
        if bsp.exists():
            got["artifact_sha256"] = sha256_of(bsp)
            got["artifact_bytes"] = bsp.stat().st_size
            got["hash_agrees"] = (got.get("bspsha") == got["artifact_sha256"])
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("donor", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--fidelities", default="100,90,75,50,25")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--donor", dest="others", type=Path, action="append",
                    default=[])
    # Fidelity zero invents rather than forks, so it needs what was
    # learned and what the target can resolve.
    ap.add_argument("--snapshot", type=Path, default=None)
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--goal", type=int, default=4)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    print(f"donor {args.donor}")
    print(f"  sha256 {sha256_of(args.donor)}")
    print(f"  seed {args.seed}")
    for o in args.others:
        print(f"  other donor {o}")
        print(f"    sha256 {sha256_of(o)}")

    driver = args.work / "bin" / "host.exe"
    err = build(DRIVER, driver)
    if err:
        print(err)
        return 1
    worker = args.work / "bin" / "q2pro-x-mapgen.exe"
    # Not appended: the executable's own list already names it, and adding it
    # again links shared.c twice.
    err = build(worker_sources(), worker)
    if err:
        print("the worker did not build:")
        print(err)
        return 1
    print(f"worker {worker}")
    print(f"  sha256 {sha256_of(worker)}")

    rows = []
    for text in args.fidelities.split(","):
        f = int(text.strip())
        got = run_anchor(driver, worker, args.work, args.donor, f, args.seed,
                         args.others, args.snapshot, args.manifest, args.goal)
        rows.append(got)
        print(f"F{f:<4} {got.get('result', got.get('error') or '?'):<12}"
              f" divergence {got.get('divergence', '?'):>4}"
              f" of {got.get('target', '?'):<4} {got.get('seconds')}s")
        if got.get("artifact_sha256"):
            print(f"       {got['artifact_sha256']}"
                  f"  {got.get('artifact_bytes')} bytes"
                  f"  hash agrees: {'yes' if got.get('hash_agrees') else 'NO'}")
        print(f"       places {got.get('places', '?')},"
              f" component {got.get('component', '?')},"
              f" {got.get('itemsunreachable', '?')} of"
              f" {got.get('items', '?')} pickups out of reach,"
              f" certificates {got.get('certificates', '?')}")
        if got.get("error"):
            print(f"       error {got['error']}")

    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"\nwritten to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
