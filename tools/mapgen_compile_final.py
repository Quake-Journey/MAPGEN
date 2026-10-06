"""Compile a .map the way a DELIVERED map is compiled: bsp, then vis, then rad.

    python tools/mapgen_compile_final.py MAP.map [MAP.map ...]

The pinned compiler, one thread, the release game directory - the same three
stages `MAPCOMPILE_PROFILE_FINAL` schedules (`src/mapgen/mapgen_compiler.c`)
and the same flags the pipeline's own adapter passes
(`tools/mapgen_pipeline_driver.c`: `-bsp`, `-vis`, `-rad`).

This exists because a guard's `compile_map` helper runs `-bsp` ALONE - that is
all a guard needs, and it is right for a guard - and on 2026-09-10 a map built
with one of those helpers was handed to the PO. It had a lighting lump of zero
bytes and he saw a flat grey level: «снова утеряны все лайтмапы» (quake130).
Anything a person is going to look at goes through this.

And the name of the third stage matters: q2tool has no `-light` mode, and it
answers an unknown mode by doing nothing and exiting ZERO. It is `-rad`.
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIN = REPO / "tools" / "mapgen_compiler_pin.json"
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")

STAGES = ("-bsp", "-vis", "-rad")
LUMP_LIGHTING = 7
LUMP_VISIBILITY = 3


def pinned() -> tuple[Path, str]:
    sys.path.insert(0, str(REPO / "tools"))
    from mapgen_pinned_compiler import pinned_compiler
    return pinned_compiler(quiet=False)


def lump(path: Path, which: int) -> int:
    raw = path.read_bytes()
    if len(raw) < 8 + 19 * 8:
        return 0
    _, length = struct.unpack_from("<ii", raw, 8 + which * 8)
    return length


def compile_final(src: Path) -> tuple[bool, str]:
    exe, threads = pinned()
    for stage in STAGES:
        run = subprocess.run(
            [str(exe), stage, "-threads", threads, "-moddir", str(GAME),
             "-basedir", str(GAME), "-gamedir", str(GAME), str(src)],
            capture_output=True, text=True, timeout=7200)
        out = run.stdout + run.stderr
        if "leaked" in out:
            return False, f"{stage}: leaked"
    bsp = src.with_suffix(".bsp")
    if not bsp.is_file():
        return False, "no bsp"
    light = lump(bsp, LUMP_LIGHTING)
    vis = lump(bsp, LUMP_VISIBILITY)
    if light == 0:
        return False, "lighting lump is empty - the rad stage did nothing"
    if vis == 0:
        return False, "visibility lump is empty - the vis stage did nothing"
    return True, f"{bsp.stat().st_size} bytes, lighting {light}, vis {vis}"


def main() -> int:
    bad = 0
    for name in sys.argv[1:]:
        src = Path(name)
        ok, said = compile_final(src)
        print(("  OK    " if ok else "  FAIL  ") + f"{src.name}  -- {said}")
        if not ok:
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
