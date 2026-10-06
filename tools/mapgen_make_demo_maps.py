#!/usr/bin/env python3
"""Generate, compile and install a handful of maps to look at.

This is not the product. The product is the menu-driven feature of contract
27, and this is the scaffolding that lets the maps be SEEN long before it
exists - because what the generated maps are actually like is not something
any test in this tree can tell anybody.

It runs the same chain the worker will: generate a `.map`, compile it with the
pinned compiler from tools/mapgen_compiler_pin.json at the pinned thread
count, and put the `.bsp` where the game can load it. Nothing here bypasses
the generator; the arguments a menu would collect are passed on the command
line instead.

    python tools/mapgen_make_demo_maps.py --count 4
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude"
                    r"\mapgen1-20260831\demo_maps")
GAMEDIR = Path(r"O:\Claude2\q2pro-release\baseq2")
MAPS_OUT = GAMEDIR / "maps"

PIN = json.loads((REPO / "tools" / "mapgen_compiler_pin.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(REPO / "tools"))
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER, THREADS = pinned_compiler()

# The corpus: deathmatch maps installed in this baseq2 whose textures the
# target resolves - measured, not assumed. Every one of these was checked with
# tools/mapgen_target_manifest.py and reported zero unresolvable materials.
# The maps the PO named as good ones to debug against. Three of them are the
# stock Quake II maps and are not loose files - they live inside pak1.pak, so
# they are extracted into this task's own temp root rather than unpacked into
# his release tree.
# PO 2026-09-01: narrowed to ONE map, so the variations can be judged against
# a single reference instead of against a blend of ten.
CORPUS = ["q2dm1.bsp"]

CORPUS_CACHE = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")


def extract_from_paks(name: str) -> Path | None:
    """Pull one map out of the first pak that holds it, once."""
    import struct

    cached = CORPUS_CACHE / name
    if cached.is_file():
        return cached

    wanted = f"maps/{name}".lower()
    for pak in sorted(GAMEDIR.glob("*.pak")) + sorted(GAMEDIR.glob("*.PAK")):
        raw = pak.read_bytes()
        if raw[:4] != b"PACK":
            continue
        dir_off, dir_len = struct.unpack_from("<ii", raw, 4)
        for i in range(dir_len // 64):
            entry = dir_off + i * 64
            stored = raw[entry:entry + 56].split(b"\0")[0].decode("latin-1")
            if stored.lower().replace("\\", "/") != wanted:
                continue
            off, size = struct.unpack_from("<ii", raw, entry + 56)
            CORPUS_CACHE.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(raw[off:off + size])
            return cached
    return None


def find_corpus() -> list[Path]:
    found, missing = [], []
    for name in CORPUS:
        path = MAPS_OUT / name
        if path.is_file():
            found.append(path)
            continue
        unpacked = extract_from_paks(name)
        if unpacked:
            found.append(unpacked)
        else:
            missing.append(name)
    if missing:
        print(f"not found loose or in any pak: {', '.join(missing)}")
    return found


def build_generator(work: Path) -> Path | None:
    cc = shutil.which("gcc")
    if not cc:
        return None
    exe = work / "mapgen_generate.exe"
    # Named rather than globbed: the worker-side modules (the controller, the
    # helper process, the IPC) belong to a different milestone and pull in
    # Windows entry points a command-line generator has no business having.
    GENERATOR_MODULES = [
        "mapgen_mapfile.c", "mapgen_entities.c", "mapgen_brush.c",
        "mapgen_layout.c", "mapgen_topology.c", "mapgen_recipe.c",
        "mapgen_synthesis.c",
        "mapgen_mix.c", "mapgen_random.c", "mapgen_lineage.c",
        "mapgen_training.c", "mapgen_snapshot.c", "mapgen_digest.c",
        "mapgen_features.c", "mapgen_wiring.c", "mapgen_space.c",
        "mapgen_trace.c", "mapgen_genome.c", "mapgen_bsp.c",
    ]
    sources = [REPO / "tools" / "mapgen_generate.c"] + [
        REPO / "src" / "mapgen" / name for name in GENERATOR_MODULES]
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
         "-I", str(REPO / "inc"), *[str(s) for s in sources],
         "-o", str(exe), "-lz"],
        capture_output=True, text=True)
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-2000:])
        return None
    return exe


def compile_map(map_path: Path) -> bool:
    """qbsp, then vis, then light - each with the pinned thread count."""
    for stage in ("-bsp", "-vis", "-rad"):
        target = map_path if stage == "-bsp" else map_path.with_suffix(".bsp")
        p = subprocess.run(
            [str(COMPILER), stage, "-threads", THREADS,
             "-moddir", str(GAMEDIR), "-basedir", str(GAMEDIR),
             "-gamedir", str(GAMEDIR), str(target)],
            capture_output=True, text=True, timeout=1800)
        text = p.stdout + p.stderr
        if p.returncode < 0 or p.returncode > 1:
            print(f"  {stage}: the compiler DIED (exit {p.returncode})")
            return False
        if p.returncode != 0 or "ERROR" in text:
            print(f"  {stage} refused it:")
            print("   " + "\n   ".join(text.strip().splitlines()[-6:]))
            return False
        # Contract 17: a missing texture is only a warning upstream, and the
        # adapter treats it as fatal. So does this.
        if "couldn't locate texture" in text:
            print(f"  {stage}: a texture did not resolve; refusing the map")
            return False
        if "leaked" in text.lower():
            print(f"  {stage}: the map leaks; refusing it")
            return False

    # And a map nobody can see is not a candidate either.
    #
    # The intensity is drawn from the corpus, and a value that suits the map it
    # was learned from can still leave a bigger room black. Measured on real
    # maps for the threshold: aerowalk 60.7, q2dm1e 52.1. This belongs in M5's
    # validator; it lives here until that exists.
    average = lightmap_average(map_path.with_suffix(".bsp"))
    if average < 15.0:
        print(f"  the map is too dark to play: lightmap average {average:.1f}"
              f" (a real map is around 50)")
        return False
    return True


def lightmap_average(bsp: Path) -> float:
    """The mean lightmap byte, straight out of the compiled file."""
    import struct
    data = bsp.read_bytes()
    # Lump 7 is LUMP_LIGHTING.
    off, size = struct.unpack_from("<II", data, 8 + 7 * 8)
    if not size:
        return 0.0
    return sum(data[off:off + size]) / size


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--goal", type=int, default=4, help="4 = FFA")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--retries", type=int, default=6,
                        help="candidates to try before giving up on one map")
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK,
                        help="where the maps are built; outside the repo")
    args = parser.parse_args()

    if not COMPILER.is_file():
        print(f"the pinned compiler is not where the pin says: {COMPILER}")
        return 1
    corpus = find_corpus()
    if not corpus:
        print(f"no corpus map resolved in {MAPS_OUT} or in any pak")
        return 1
    print(f"corpus: {', '.join(p.name for p in corpus)}")

    # Outside the repository, deliberately.
    #
    # This used to be REPO / "_agent_temp_demo", and a build checkpoint that
    # staged everything dirty swept thirty-five compiler pointfiles and a
    # target manifest into the implementation history with it. Scratch that
    # lives in the worktree will be committed by something, eventually.
    work = args.work
    work.mkdir(parents=True, exist_ok=True)
    generator = build_generator(work)
    if not generator:
        print("could not build the generator")
        return 1

    manifest = work / "target_manifest.txt"
    sys.path.insert(0, str(REPO / "tools"))
    from mapgen_target_manifest import resolvable_textures
    names = sorted(resolvable_textures(GAMEDIR))
    manifest.write_text("\n".join(names) + "\n", encoding="ascii")
    print(f"target manifest: {len(names)} textures the game can resolve")

    made = []
    for i in range(args.count):
        started = time.time()
        installed = None

        # Contract 16 stage 14: a candidate the compiler refuses is a rejected
        # candidate, and the answer is another candidate. Each retry is a
        # different seed, so it is a genuinely different map rather than the
        # same one hopefully behaving.
        for retry in range(args.retries):
            seed = (args.seed + i * 0x9E3779B9 + retry * 0x85EBCA6B) & 0xFFFFFFFF
            out_map = work / f"q2mg_{seed:08x}.map"
            p = subprocess.run(
                [str(generator), str(out_map), str(manifest), str(seed),
                 str(args.scale), str(args.goal), *[str(c) for c in corpus]],
                capture_output=True, text=True, timeout=3600)
            print(p.stdout.strip())
            if p.returncode != 0:
                print(p.stderr.strip()[-500:])
                continue
            if not compile_map(out_map):
                continue
            bsp = out_map.with_suffix(".bsp")
            installed = MAPS_OUT / bsp.name
            shutil.copy2(bsp, installed)
            made.append(installed)
            print(f"  -> {installed.name}  {installed.stat().st_size:,} bytes"
                  f"  ({time.time() - started:.1f}s, {retry + 1} candidate"
                  f"{'s' if retry else ''})")
            break
        if installed is None:
            print(f"  no candidate survived {args.retries} attempts")

    print()
    if made:
        print("Installed, loadable with `map <name>`:")
        for path in made:
            print(f"  {path.stem}")
    else:
        print("nothing was installed")
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
