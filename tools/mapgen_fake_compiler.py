#!/usr/bin/env python3
"""Fake Quake II map compiler for the MAPGEN-1 M0 qualification harness.

This is a REAL process, not an injected in-process seam. Hard Rule #51: an
injected seam proves the algorithm and never the call - it has no concept of an
exit code, a hung child, a flooded pipe or a path that escapes the job root.
Every behavior below is therefore produced by an actual subprocess that the
harness must survive.

The behaviors are not invented. Each one is either a documented requirement of
contract section 17 or a source fact recorded in the C0 audit:

    success                    a valid compile the harness must accept
    zero_exit_no_output        exit 0, writes nothing            (section 17)
    zero_exit_leak             exit 0 + leak marker + .pts       (C0 finding F1)
    zero_exit_missing_texture  exit 0 + "couldn't locate texture"(C0 finding F2)
    zero_exit_wrong_semantics  exit 0, parseable BSP, wrong content
    nonzero_exit               ordinary compiler failure
    crash                      abnormal termination
    hang                       never exits; the harness must time it out
    log_flood                  megabytes of stdout
    stale_output               leaves a pre-existing .bsp untouched
    damaged_output             truncated / corrupt .bsp
    escape_path                tries to write outside the job root
    wrong_format               ignores -qbsp and writes the other format
    zero_exit_leak_marker_only leak in the log, no .pts   (isolates the log scan)
    zero_exit_leak_pts_only    .pts but a silent log      (isolates the file check)
    vis_noop                   later passes leave the BSP byte-identical
    final_no_vis               final profile output with no visibility data
    final_no_light             final profile output with no lighting data
    degenerate_output          a readable BSP with no world in it

Usage (argv deliberately mirrors the real tool's shape):
    mapgen_fake_compiler.py --behavior <name> -bsp -threads N
                            -moddir DIR -basedir DIR <input.map>
"""

from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mapgen_bsp_synth import synth_empty_world, synth_solid_cube  # noqa: E402

LEAK_MARKER = "**** leaked ****"
MISSING_TEXTURE_MARKER = "WARNING: couldn't locate texture"


def write_output(bsp_path, args: dict, **kw) -> None:
    """Write this stage's BSP.

    A real compiler's VIS and RAD passes rewrite the file - they add the
    visibility and lighting lumps. The fake must do the same, otherwise the
    runner's "a later stage that leaves the file byte-identical did not run"
    rule would have nothing honest to measure. The stage name goes into
    worldspawn so each pass genuinely changes the bytes while the result stays
    deterministic for a given stage sequence.
    """
    stage_tag = "+".join(args["stages"]) or "none"
    entities = kw.pop(
        "entities",
        [
            {"classname": "worldspawn", "message": "mapgen synthetic fixture", "_stage": stage_tag},
            {"classname": "info_player_start", "origin": "0 0 128", "angle": "0"},
        ],
    )
    bsp_path.write_bytes(synth_solid_cube(extended=args["qbsp"], entities=entities, **kw))


def parse_args(argv: list[str]) -> dict:
    out = {
        "behavior": "success",
        "threads": 1,
        "moddir": "",
        "basedir": "",
        "stages": [],
        "input": None,
        "qbsp": False,
    }
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--behavior":
            i += 1
            out["behavior"] = argv[i]
        elif a == "-threads":
            i += 1
            out["threads"] = int(argv[i])
        elif a == "-moddir":
            i += 1
            out["moddir"] = argv[i]
        elif a == "-basedir":
            i += 1
            out["basedir"] = argv[i]
        elif a == "-gamedir":
            i += 1
        elif a in ("-bsp", "-vis", "-rad"):
            out["stages"].append(a[1:])
        elif a == "-qbsp":
            out["qbsp"] = True
        elif a == "-fast":
            pass
        elif a.startswith("-"):
            pass
        else:
            out["input"] = a
        i += 1
    return out


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    behavior = args["behavior"]
    if args["input"] is None:
        print("no input file")
        return 1

    source = Path(args["input"])
    if source.suffix:
        source = source.with_suffix("")
    bsp_path = source.with_suffix(".bsp")
    pts_path = source.with_suffix(".pts")

    print(f"moddir = {args['moddir']}")
    print(f"basedir = {args['basedir']}")
    print(f"Using {args['threads']} processor threads")
    for stage in args["stages"]:
        print(f"<<<<<<<<<<<<<<<<<<<<<<<<<<<<<< BEGIN {stage} >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")

    if behavior == "hang":
        # Never exits. The harness must kill the process tree and report a
        # timeout rather than blocking forever.
        while True:
            time.sleep(3600)

    if behavior == "crash":
        sys.stdout.flush()
        os.abort()

    if behavior == "nonzero_exit":
        print("************ ERROR ************")
        print("Entity 0, Brush 3, Line 42: plane with no normal")
        return 1

    if behavior == "zero_exit_no_output":
        # The exact shape contract section 17 warns about: a clean-looking run
        # that produced nothing at all.
        print("writing bsp")
        return 0

    if behavior == "zero_exit_leak":
        print(LEAK_MARKER)
        pts_path.write_text("-64 -64 0\n64 64 128\n", encoding="ascii")
        return 0

    if behavior == "zero_exit_leak_marker_only":
        # Leak announced in the log, no .pts written, and a perfectly readable
        # BSP left behind. Only the stdout scan can catch this one - it exists
        # so that removing the stdout scan cannot hide behind the .pts check.
        print(LEAK_MARKER)
        write_output(bsp_path, args)
        return 0

    if behavior == "zero_exit_leak_pts_only":
        # The mirror image: a leak file appears but the log says nothing.
        pts_path.write_text("-64 -64 0\n64 64 128\n", encoding="ascii")
        write_output(bsp_path, args)
        return 0

    if behavior == "vis_noop":
        # The BSP pass produces a map and every later pass silently does
        # nothing. Contract section 17 requires stale or unexpected output to
        # be rejected: a VIS stage that leaves the file byte-identical did not
        # run, whatever it printed.
        if "bsp" in args["stages"]:
            write_output(bsp_path, args)
        return 0

    if behavior == "degenerate_output":
        # Structurally valid, semantically empty: a readable BSP with no world
        # at all. MEASURED on q2tools-220: a worldspawn with zero brushes
        # compiles to exactly this shape with exit code ZERO.
        stage_tag = "+".join(args["stages"]) or "none"
        bsp_path.write_bytes(
            synth_empty_world(
                extended=args["qbsp"],
                entities=[{"classname": "worldspawn", "_stage": stage_tag}],
            )
        )
        return 0

    if behavior == "final_no_vis":
        write_output(bsp_path, args, with_visibility=False)
        return 0

    if behavior == "final_no_light":
        write_output(bsp_path, args, with_lighting=False)
        return 0

    if behavior == "stale_output":
        # Writes nothing: any .bsp already present is a leftover, and treating
        # it as this attempt's output is how a leaked run looks successful.
        print("nothing to do")
        return 0

    if behavior == "damaged_output":
        # Truncated, and different on every pass, so the case reaches the
        # unreadable-output guard instead of tripping the "a later stage left
        # the file byte-identical" guard first.
        stage_tag = "+".join(args["stages"]) or "none"
        blob = synth_solid_cube(
            extended=args["qbsp"],
            entities=[{"classname": "worldspawn", "_stage": stage_tag}],
        )
        bsp_path.write_bytes(blob[: len(blob) // 3])
        return 0

    if behavior == "escape_path":
        target = source.parent.parent / "escaped_from_the_job_root.bsp"
        try:
            target.write_bytes(b"escaped")
            print(f"wrote {target}")
        except OSError as exc:
            print(f"could not escape: {exc}")
        write_output(bsp_path, args)
        return 0

    if behavior == "log_flood":
        rng = random.Random(1)
        line = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(78))
        for _ in range(40000):
            print(line)
        write_output(bsp_path, args)
        return 0

    if behavior == "zero_exit_missing_texture":
        print(f"{MISSING_TEXTURE_MARKER} q2mgfx/absent")
        write_output(bsp_path, args)
        return 0

    if behavior == "zero_exit_wrong_semantics":
        # Parses cleanly, exits 0, and is still wrong: no player start at all.
        write_output(
            bsp_path,
            args,
            entities=[{"classname": "worldspawn", "message": "no start here", "_stage": "+".join(args["stages"]) or "none"}],
        )
        return 0

    if behavior == "wrong_format":
        # Ignores -qbsp and writes the other format. A compiler that quietly
        # produces standard IBSP when the recipe pinned QBSP (or the reverse)
        # would break the engine's limit assumptions, and exit 0 while doing it.
        flipped = dict(args)
        flipped["qbsp"] = not args["qbsp"]
        write_output(bsp_path, flipped)
        print(f"{bsp_path.name} written")
        return 0

    if behavior == "success":
        write_output(bsp_path, args)
        print(f"{bsp_path.name} written")
        return 0

    print(f"unknown behavior {behavior!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
