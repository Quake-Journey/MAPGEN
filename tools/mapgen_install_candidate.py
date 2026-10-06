"""Install a map that passed `tools/mapgen_delivery_gates.py` for the PO under a new name, then the two gates that
need the game itself.

    python tools/mapgen_install_candidate.py CANDIDATE.bsp NAME

This is the install that ran for mg_20e, mg_20f and mg_20g from the session's scratch folder, until that folder was
wiped (ledger row 312). In order:

  - refuse a name the PO already tests or kept (mg_20 to mg_20g, ai1): a new map gets a new name;
  - keep whatever file held NAME beside the candidate as previous_NAME.bsp;
  - copy the candidate to q2pro-release/baseq2/maps/NAME.bsp and print its sha256;
  - hash the PO's four config files;
  - `mapgen_verify_map_loads.py NAME --seconds 180` - the client loads it;
  - `check_mapgen_glass_alive.py NAME --lifts N` - on a hidden dedicated server, with N the func_plat count of the
    file itself: its panes and lifts are alive after spawn and the game freed no pickup;
  - hash the configs again, and remove the demos and logs those two left.

Exit 1 when either game gate fails or a config changed. Both launches go through `mapgen_load_guard` inside the
tools they call, one at a time.
"""
import hashlib
import shutil
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as g  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
TOOLS = REPO / "tools"
CFGS = [GAME / "q2config.cfg", GAME / "q2pro-x" / "q2pro-x.cfg",
        GAME / "q2pro-x" / "q2pro-x.local.cfg", GAME / "autoexec.cfg"]
PROTECTED = {"mg_20", "mg_20b", "mg_20c", "mg_20d", "mg_20e", "mg_20f", "mg_20g", "ai1"}


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def step(where: Path, label: str, argv: list, timeout: int = 3600) -> int:
    t = time.time()
    r = g.run([str(a) for a in argv], capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    (where / (label + ".txt")).write_text(out, encoding="utf-8")
    print(f"===== {label}: exit {r.returncode}, {time.time() - t:.0f} s", flush=True)
    for ln in out.strip().splitlines()[-6:]:
        print("   ", ln[:230], flush=True)
    return r.returncode


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, name = Path(sys.argv[1]), sys.argv[2]
    if name.lower() in PROTECTED:
        print(f"refused: {name} is a map the PO already has; install under a new name")
        return 2
    if not src.is_file():
        print(f"refused: no candidate at {src}")
        return 2
    where = src.parent
    dst = GAME / "maps" / f"{name}.bsp"
    if dst.is_file():
        kept = where / f"previous_{name}.bsp"
        shutil.copyfile(dst, kept)
        print(f"the previous {name}.bsp kept as {kept} sha256 {sha(dst)[:16]}", flush=True)
    shutil.copyfile(src, dst)
    print(f"===== installed {dst}: sha256 {sha(dst)[:16]} ({dst.stat().st_size} bytes)", flush=True)
    d = dst.read_bytes()
    o, n = struct.unpack_from("<ii", d, 8)
    lifts = d[o:o + n].decode("latin1").count('"classname" "func_plat"')
    before = {str(c): sha(c) for c in CFGS if c.is_file()}
    loads = step(where, "loads", [sys.executable, TOOLS / "mapgen_verify_map_loads.py", name, "--seconds", "180"],
                 timeout=7200)
    alive = step(where, "alive", [sys.executable, TOOLS / "check_mapgen_glass_alive.py", name, "--lifts", str(lifts),
                                  "--json", where / f"alive_{name}.json"])
    after = {str(c): sha(c) for c in CFGS if c.is_file()}
    changed = [k for k in before if before[k] != after.get(k)]
    print("===== PO configs:", "unchanged" if not changed else f"CHANGED {changed}", f"({len(before)} hashed)",
          flush=True)
    for junk in list((GAME / "demos").glob("alive_*.mvd2")) + [GAME / "mgalive.log", GAME / "mgloadcheck.log"]:
        try:
            junk.unlink()
            print("removed our", junk.name, flush=True)
        except OSError:
            pass
    print(f"DONE loads {loads} alive {alive}, lifts {lifts}", flush=True)
    return 0 if loads == 0 and alive == 0 and not changed else 1


if __name__ == "__main__":
    sys.exit(main())
