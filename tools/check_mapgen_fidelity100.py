"""GF4S: is a fidelity-100 candidate the donor, on the compiled output?

Not "does it look like it" and not "did the generator say so". Every claim here
is measured against the donor's own compiled BSP, with the input and output
hashes recorded so the run can be repeated and the numbers checked.

    python tools/check_mapgen_fidelity100.py [--donor PATH] [--work DIR]

Cases:
    the round trip compiles, vis'es and lights;
    the solid behind every surface the donor draws is still there;
    nothing the donor draws is left undrawn on its own plane, and no gap a
        player can see through is larger than the measured ceiling;
    the drawn surfaces agree, invariant to how the compiler split them;
    the brush models and their entity logic come back;
    every surface keeps its material, its flags and its value;
    the entity set is the donor's, less the ordinals the compiler reassigns.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
DEFAULT_DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831"
                     r"\corpus\q2dm1.bsp")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\gf4s")

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    return ok


def build(work: Path) -> dict[str, Path]:
    out = work / "bin"
    out.mkdir(parents=True, exist_ok=True)
    src = {
        "fork": ["tools/mapgen_geometry_fork.c", "src/mapgen/mapgen_geometry.c",
                 "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c", "src/mapgen/mapgen_bsp.c",
                 "src/mapgen/mapgen_trace.c",
                 "src/mapgen/mapgen_rooms.c",
                 "src/mapgen/mapgen_bundle.c",
                 "src/mapgen/mapgen_closure.c"],
        "cover": ["tools/mapgen_coverage_oracle.c",
                  "src/mapgen/mapgen_geometry.c", "src/mapgen/mapgen_bsp.c"],
        "wall": ["tools/mapgen_wall_audit.c", "src/mapgen/mapgen_bsp.c",
                 "src/mapgen/mapgen_trace.c",
                 "src/mapgen/mapgen_rooms.c"],
        "render": ["tools/mapgen_render_audit.c",
                   "src/mapgen/mapgen_geometry.c", "src/mapgen/mapgen_bsp.c"],
        "holes": ["tools/mapgen_visible_holes.c", "src/mapgen/mapgen_bsp.c"],
    }
    built = {}
    for name, files in src.items():
        exe = out / f"{name}.exe"
        run = subprocess.run(
            ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
             "-I" + str(REPO / "inc")] + [str(REPO / f) for f in files]
            + ["-o", str(exe), "-lm"], capture_output=True, text=True)
        if run.returncode != 0:
            print(run.stderr[-1500:])
            raise SystemExit(f"cannot build {name}")
        built[name] = exe
    return built


def compile_stage(target: Path, stage: str, extra=()) -> str | None:
    run = subprocess.run(
        [str(COMPILER), stage, *extra, "-threads", "4", "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(target)],
        capture_output=True, text=True, timeout=3600)
    text = run.stdout + run.stderr
    if run.returncode != 0 or "ERROR" in text:
        return "refused"
    if "leaked" in text.lower():
        return "leaked"
    return None


def lump(raw: bytes, index: int) -> bytes:
    off, length = struct.unpack_from("<ii", raw, 8 + index * 8)
    return raw[off:off + length]


def surfaces(path: Path) -> Counter:
    """Every drawn surface as (texture, flags, value), counted by area.

    Area rather than face count, because the compiler is free to split one
    surface into three and a count would call that a difference.
    """
    raw = path.read_bytes()
    ti, faces = lump(raw, 5), lump(raw, 6)
    verts, edges, surfedges = lump(raw, 2), lump(raw, 11), lump(raw, 12)
    out: Counter = Counter()
    for f in range(len(faces) // 20):
        _, _, first, count, index = struct.unpack_from("<Hhihh", faces, f * 20)
        if count < 3 or index < 0:
            continue
        flags, value = struct.unpack_from("<ii", ti, index * 76 + 32)
        name = struct.unpack_from("<32s", ti, index * 76 + 40)[0]
        name = name.split(b"\0")[0].decode("latin1")
        points = []
        for k in range(count):
            se = struct.unpack_from("<i", surfedges, (first + k) * 4)[0]
            v0, v1 = struct.unpack_from("<HH", edges, abs(se) * 4)
            v = v1 if se < 0 else v0
            points.append(struct.unpack_from("<fff", verts, v * 12))
        area = 0.0
        for k in range(1, len(points) - 1):
            e1 = [points[k][a] - points[0][a] for a in range(3)]
            e2 = [points[k + 1][a] - points[0][a] for a in range(3)]
            cr = (e1[1] * e2[2] - e1[2] * e2[1],
                  e1[2] * e2[0] - e1[0] * e2[2],
                  e1[0] * e2[1] - e1[1] * e2[0])
            area += 0.5 * sum(c * c for c in cr) ** 0.5
        out[(name, flags, value)] += area
    return out


def entities(path: Path) -> list[dict[str, str]]:
    raw = lump(path.read_bytes(), 0).split(b"\0")[0].decode("latin1")
    out = []
    for block in re.findall(r"\{[^}]*\}", raw):
        pairs = dict(re.findall(r'"([^"]*)"\s+"([^"]*)"', block))
        out.append(pairs)
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--donor", default=str(DEFAULT_DONOR))
    parser.add_argument("--work", default=str(DEFAULT_WORK))
    args = parser.parse_args(argv)

    donor = Path(args.donor)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    print("=== MAPGEN-1 GF4S: fidelity 100 on the compiled output")
    print(f"donor {donor}")
    print(f"  sha256 {sha256(donor)}")

    tools = build(work)

    candidate_map = work / "fidelity100.map"
    run = subprocess.run([str(tools["fork"]), str(donor), str(candidate_map),
                          "100", "1"], capture_output=True, text=True)
    if not check("the donor's geometry is readable and writable",
                 run.returncode == 0, run.stderr.strip()[-160:]):
        return 1

    for stage, extra in (("-bsp", ()), ("-vis", ()),
                         ("-rad", ("-bounce", "8", "-scale", "2", "-extra"))):
        target = candidate_map if stage == "-bsp" else candidate_map.with_suffix(".bsp")
        reason = compile_stage(target, stage, extra)
        if not check(f"the rebuild survives {stage}", reason is None, reason or ""):
            return 1
    candidate = candidate_map.with_suffix(".bsp")
    print(f"candidate {candidate}")
    print(f"  sha256 {sha256(candidate)}")

    wall = subprocess.run([str(tools["wall"]), str(donor), str(candidate)],
                          capture_output=True, text=True)
    check("the solid behind every surface the donor draws is still there",
          wall.returncode == 0,
          wall.stdout.strip().splitlines()[0] if wall.stdout else "")

    self_test = subprocess.run([str(tools["cover"]), str(donor), str(donor),
                                "8", "2"], capture_output=True, text=True)
    check("the coverage oracle finds the donor covers itself",
          self_test.returncode == 0,
          self_test.stdout.strip().splitlines()[0] if self_test.stdout else "")

    #
    # The hole case, asked of the strict oracle.
    #
    # It used to be asked of `mapgen_coverage_oracle`, which accepts a
    # candidate face two units off-plane and a whole sampling step outside its
    # own edge - and which therefore reported "0 no longer covered" of 1151333
    # points on the map the PO photographed a strip of sky in. The wall had
    # come back drawn on a neighbouring plane half a unit in, and every point
    # of it counted as covered.
    #
    # `mapgen_visible_holes` allows 0.06 units off-plane and 0.35 of rim, so it
    # sees everything the lenient oracle sees and this defect as well. The
    # coverage run below is kept as independent evidence and its self-test
    # above is kept as a check on the oracle itself; neither decides the case
    # any more.
    #
    holes = subprocess.run([str(tools["holes"]), str(donor), str(candidate),
                            "1", "0.35"], capture_output=True, text=True)
    head = re.search(r"(\d+) no longer drawn on their own plane", holes.stdout)
    undrawn = int(head.group(1)) if head else -1
    worst = 0
    for line in holes.stdout.splitlines():
        row = re.match(r"\s+(\d+) sq units .*?->\s+(.*?)(?:, ([\d.]+) behind)?$",
                       line.rstrip())
        if row and (row.group(3) is None or float(row.group(3)) > 1.0):
            worst = max(worst, int(row.group(1)))
    # The same two ceilings check_mapgen_visible_holes.py holds, and for the
    # same reason. Since local patch P12 stopped the compiler cutting every
    # winding out of a quad 2^20 units wide in single precision, q2dm1 draws
    # every point of its donor, so the budget is 0; the see-through ceiling is
    # 64 rather than 0 only so an equivalent re-split cannot fail on its own.
    check("nothing the donor draws is left undrawn beyond its budget",
          undrawn == 0, str(undrawn))
    check("no gap a player can see through above 64 square units",
          worst <= 64, str(worst))

    cover = subprocess.run([str(tools["cover"]), str(donor), str(candidate),
                            "8", "2"], capture_output=True, text=True)
    print("        (the lenient coverage oracle says: "
          + (cover.stdout.strip().splitlines()[0].split(": ")[-1]
             if cover.stdout.strip() else "nothing") + ")")

    # Materials, flags and values, by area rather than by face count.
    dsurf, csurf = surfaces(donor), surfaces(candidate)
    missing = [k for k in dsurf if k not in csurf]
    check("every material the donor draws is still drawn", not missing,
          f"{len(missing)} missing, e.g. {missing[:2]}")

    drifted = []
    for key, area in dsurf.items():
        other = csurf.get(key, 0.0)
        if area > 0 and abs(other - area) / area > 0.10:
            drifted.append((key[0], round(area), round(other)))
    check("each material covers about the same area as in the donor",
          not drifted, f"{len(drifted)} drifted, e.g. {drifted[:2]}")

    dflags = {(k[0], k[1], k[2]) for k in dsurf}
    cflags = {(k[0], k[1], k[2]) for k in csurf}
    check("no material changed its surface flags or value",
          {(n, f, v) for n, f, v in dflags if n in {x[0] for x in cflags}}
          <= cflags, "a flag or value differs on some material")

    # Brush models and the entities bound to them.
    dmodels = struct.unpack_from("<ii", lump(donor.read_bytes(), 13), 0)
    (dm, cm) = (len(lump(donor.read_bytes(), 13)) // 48,
                len(lump(candidate.read_bytes(), 13)) // 48)
    check("the rebuild has the donor's brush models", dm == cm, f"{dm} vs {cm}")
    del dmodels

    dents, cents = entities(donor), entities(candidate)
    dclass = Counter(e.get("classname", "?") for e in dents)
    cclass = Counter(e.get("classname", "?") for e in cents)
    check("every entity class survives with the same count",
          dclass == cclass,
          str((dclass - cclass) or (cclass - dclass))[:140])

    movers = [e for e in dents if e.get("classname", "").startswith("func_")]
    cmovers = [e for e in cents if e.get("classname", "").startswith("func_")]
    keys_kept = all(
        all(v == c.get(k) for k, v in d.items() if k != "model")
        for d, c in zip(sorted(movers, key=lambda e: sorted(e.items())),
                        sorted(cmovers, key=lambda e: sorted(e.items()))))
    check("every mover keeps its keys, the compiler's own ordinal aside",
          len(movers) == len(cmovers) and keys_kept,
          f"{len(movers)} donor movers, {len(cmovers)} in the rebuild")

    render = subprocess.run([str(tools["render"]), str(donor), str(candidate)],
                            capture_output=True, text=True)
    line = [ln for ln in render.stdout.splitlines() if "vanished" in ln]
    vanished = int(re.search(r"(\d+) vanished", line[0]).group(1)) if line else -1
    check("no drawn surface vanishes outright", vanished == 0,
          line[0].strip() if line else "the audit said nothing")

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    print("RESULT: " + ("PASS" if FAILED == 0 else "FAIL"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
