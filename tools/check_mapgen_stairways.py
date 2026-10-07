r"""Stairways up a room's wall (Fable's brief 11 D1, ledger row 412j).

The PO, 06.10, with his picture of q2dm1 where new stairs climb the courtyard's walls to new landings:
«пристройки-лестницы», a count 0..10 (default 0), and «доработки по лестницам и разрушаемости должны быть
универсальны, а не только для q2dm1». So the same rules are asked on two different donors - q2dm1 and q3t2 (seed 42,
ambition 58, `--stairways 3`):
* the plan deals stairways on each, every one with its purpose (a pickup moved onto the landing, or a ledge met);
* each stairway, applied alone and compiled, is sealed (no leak); its landing is solid from its top down to the floor
  at its middle and its four corners (nothing floats - brief 9's lesson), every step is solid from the floor, there is
  a player's headroom over the landing, and the pickup it was dealt for stands on it (floor under its feet, air at
  its origin);
* its back meets the wall: one unit behind its back, along the flight and the landing, low and high, is rock - no
  slot between the steps and a wall that recedes under its face (brief 12 L4: q2dm1's third stairway was refused by
  the transaction for that crack);
* with no `--stairways` the plan deals none (0 is the default and draws nothing).
Brief 14 F3 (the PO, quake223 at 1398 1729 926: «Левые текстуры на лестнице» - stairway 5 of his mg_1_6662 wore
`blum15_1`, a wall of lit panels, for its sides): every dealt stairway of the cases above and of q2dm1 6662/99 with
10 stairways wears ONE floor material for treads and sides, never a light, sky, liquid, glass or nodraw texture of
the donor nor a `ceil*` one. RED: the sides from the nearest wall again - the PO's case goes red.
RED: the same generator with the landing's support taken out (`g_stair_support`, a sandbox copy): the landing is a
slab in the air - the case above goes red. The back's check has no RED here: none of the five stairways dealt on the
two donors at 42/58 stands at a receding wall, with the back's reach or without it (measured 07.10) - its proof is the
generated q2dm1 20/42, whose third stairway the transaction refused for that crack (row 412m).

    python tools/check_mapgen_stairways.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from check_mapgen_dig import bsp_tree, compile_map, tree_solid  # noqa: E402
from check_mapgen_recut import build_driver  # noqa: E402
from mapgen_delivery_gates import plan_stairways  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

REPO = TOOLS.parent
DONORS = Path(r"O:\Claude2\MapgenStudio\engine\donors")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\stairways")
CASES = [("q2dm1", "42", "58"), ("q3t2", "42", "58")]
EDIT = re.compile(r"^  edit (\d+)  stairway  (-?\d+) (-?\d+) (-?\d+) \.\. (-?\d+) (-?\d+) (-?\d+)  (\d+) high$", re.M)
ENT = re.compile(r"\{[^{}]*\}")
FAILED = TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED, TOTAL
    TOTAL += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def drive(exe: Path, *args: str) -> str:
    r = subprocess.run([str(exe), *args], capture_output=True, text=True, errors="replace", timeout=3600)
    return r.stdout + r.stderr


def slot_behind(tree, s: dict, box: list[float]) -> str:
    """Air one unit behind the stairway's back (the side of its box against the wall), along it, low and high."""
    lo, hi = box[:3], box[3:]
    fx, fy, tx, ty = s["foot"][0], s["foot"][1], s["top"][0], s["top"][1]
    ra = 0 if abs(tx - fx) >= abs(ty - fy) else 1
    wa = 1 - ra
    floor = s["foot"][2]
    mid_u = (lo[ra] + hi[ra]) / 2
    sides = []
    for edge, out in ((lo[wa], -1.0), (hi[wa], 1.0)):
        p = [0.0, 0.0, floor + 40.0]
        p[ra] = mid_u
        p[wa] = edge + out * 1.0
        sides.append((tree_solid(tree, tuple(p)), edge, out))
    walls = [x for x in sides if x[0]]
    if len(walls) != 1:
        return ""                                   # no single wall side met at the middle: not this question
    _, edge, out = walls[0]
    # the whole body is solid from the floor to its first tread's top (16): behind it, at 4 and 12 over the floor
    u = lo[ra] + 6.0
    while u <= hi[ra] - 6.0:
        for z in (floor + 4.0, floor + 12.0):
            p = [0.0, 0.0, z]
            p[ra] = u
            p[wa] = edge + out * 1.0
            if not tree_solid(tree, tuple(p)):
                return f"a slot behind it at {p[0]:.0f} {p[1]:.0f} {p[2]:.0f}"
        u += 8.0
    return ""


def standing(tree, s: dict) -> list[str]:
    """What is wrong with the compiled stairway: the landing solid down to the floor, the steps, the headroom."""
    bad = []
    lo, hi = s["landing"][:3], s["landing"][3:]
    floor = s["foot"][2]
    pts = [((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)] + [(x, y) for x in (lo[0] + 6, hi[0] - 6)
                                                          for y in (lo[1] + 6, hi[1] - 6)]
    for x, y in pts:
        holes = [z for z in range(int(floor) + 4, int(hi[2]) - 2, 12) if not tree_solid(tree, (x, y, z))]
        if holes:
            bad.append(f"the landing floats at {x:.0f} {y:.0f} (air at {holes[0]})")
            break
    top = s["top"]
    if any(tree_solid(tree, (top[0], top[1], top[2] + h)) for h in (8, 40, 64)):
        bad.append("no headroom over the landing")
    fx, fy, tx, ty, n = s["foot"][0], s["foot"][1], top[0], top[1], s["steps"]
    run = max(1.0, ((tx - fx) ** 2 + (ty - fy) ** 2) ** 0.5)
    for i in range(n):
        f = (24.0 + 32.0 * (i + 0.5)) / run          # the flight starts 24 past the foot, a tread is 32
        x, y = fx + (tx - fx) * f, fy + (ty - fy) * f
        if not tree_solid(tree, (x, y, floor + 6)):
            bad.append(f"step {i + 1} missing at {x:.0f} {y:.0f}")
            break
    return bad


def pickup_stands(tree, mp: Path, s: dict) -> str:
    if s["ledge"]:
        return ""
    cls, _, to = s["move"]
    text = mp.read_text(encoding="utf-8", errors="replace")
    for e in ENT.findall(text):
        if f'"classname" "{cls}"' not in e:
            continue
        m = re.search(r'"origin" "(\S+) (\S+) (\S+)"', e)
        if m and all(abs(float(m.group(i + 1)) - to[i]) <= 1.0 for i in range(3)):
            o = [float(v) for v in m.groups()]
            if tree_solid(tree, o):
                return f"{cls} is inside solid"
            if not any(tree_solid(tree, (o[0], o[1], o[2] - d)) for d in range(8, 40, 4)):
                return f"{cls} has no floor under it"
            return ""
    return f"no {cls} at {' '.join(f'{v:.0f}' for v in to)}"


def run(exe: Path, work: Path, tag: str) -> dict:
    out = {}
    for donor, seed, amb in CASES:
        bsp = DONORS / f"{donor}.bsp"
        text = drive(exe, str(bsp), "--seed", seed, "--ambition", amb, "--stairways", "3", "--list")
        plan = plan_stairways(text)
        edits = [m for m in EDIT.finditer(text)]
        results = []
        for k, s in enumerate(plan):
            L = s["landing"]
            hit = next((m for m in edits
                         if all(abs(float(m.group(2 + i)) - v) <= 1.0 for i, v in enumerate([L[0], L[1]]))
                         or (float(m.group(2)) - 1 <= L[0] and L[3] <= float(m.group(5)) + 1
                             and float(m.group(3)) - 1 <= L[1] and L[4] <= float(m.group(6)) + 1)), None)
            edit = hit.group(1) if hit else None
            if edit is None:
                results.append((s, ["no edit found for it"]))
                continue
            mp = work / f"{tag}_{donor}_{k}.map"
            said = drive(exe, str(bsp), "--seed", seed, "--ambition", amb, "--stairways", "3", "--apply", edit,
                         "--out", str(mp))
            if re.search(r"^apply \d+: OK, changed no", said, re.M):
                why = re.search(r"^declined: (.*)$", said, re.M)
                results.append((s, ["declined: " + (why.group(1) if why else "?")]))
                continue
            out_bsp = mp.with_suffix(".bsp")
            out_bsp.unlink(missing_ok=True)
            log = compile_map(mp)
            if "leaked" in log or not out_bsp.is_file():
                results.append((s, ["leaked" if "leaked" in log else "no bsp"]))
                continue
            tree = bsp_tree(out_bsp)
            bad = standing(tree, s)
            slot = slot_behind(tree, s, [float(hit.group(2 + i)) for i in range(6)])
            stand = pickup_stands(tree, mp, s)
            results.append((s, bad + ([slot] if slot else []) + ([stand] if stand else [])))
        out[donor] = (text, results)
    return out


WEARS = re.compile(r"^  stairway (\d+) wears: (\S+) and (\S+)", re.M)
SPECIAL = 0x0001 | 0x0004 | 0x0008 | 0x0010 | 0x0020 | 0x0080


def special_textures(bsp: Path) -> set[str]:
    """The donor's textures that light, are sky, liquid, glass or nodraw (its texinfo flags)."""
    import struct
    d = bsp.read_bytes()
    to, tn = struct.unpack_from("<ii", d, 8 + 8 * 5)
    out = set()
    for i in range(tn // 76):
        flags, value = struct.unpack_from("<ii", d, to + i * 76 + 32)
        if flags & SPECIAL or value > 0:
            out.add(d[to + i * 76 + 40:to + i * 76 + 72].split(b"\0")[0].decode("latin-1"))
    return out


def wears_wrong(text: str, bsp: Path) -> list[str]:
    """Each dealt stairway whose treads and sides differ or wear a texture a stairway must not."""
    bad, special = [], special_textures(bsp)
    for n, tread, side in WEARS.findall(text):
        why = [w for w, cond in (("treads and sides differ", tread != side),
                                 ("a light/sky/liquid/glass texture", tread in special or side in special),
                                 ("a ceiling texture", any(x.split("/")[-1].startswith("ceil") for x in (tread, side))))
               if cond]
        if why:
            bad.append(f"stairway {n} {tread} / {side}: {', '.join(why)}")
    return bad


PO_CASE = ("q2dm1", "6662", "99")


def said(s: dict) -> str:
    return (f"{' '.join(f'{v:.0f}' for v in s['foot'])} up to {' '.join(f'{v:.0f}' for v in s['top'])},"
            f" {s['steps']} steps {s['wide']:.0f} wide, " + ("a ledge" if s["ledge"] else s["move"][0]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    (a.work / "bin").mkdir(parents=True, exist_ok=True)
    exe = build_driver(REPO, a.work / "bin")
    # 0 is the default: no stairway dealt, nothing drawn
    plain = drive(exe, str(DONORS / "q2dm1.bsp"), "--seed", "42", "--ambition", "58", "--list")
    check("q2dm1 without --stairways: no stairway in the plan", not plan_stairways(plain)
          and "families:" in plain and "stairway=" not in plain)
    po_text = drive(exe, str(DONORS / "q2dm1.bsp"), "--seed", PO_CASE[1], "--ambition", PO_CASE[2], "--stairways", "10",
                    "--list")
    green = run(exe, a.work, "green")
    wrong = [w for donor, (text, _) in green.items() for w in wears_wrong(text, DONORS / f"{donor}.bsp")]
    wrong += wears_wrong(po_text, DONORS / "q2dm1.bsp")
    check("every stairway wears one floor material, no lamp, sky, liquid, glass or ceiling texture (q2dm1 6662/99 too)",
          not wrong and len(WEARS.findall(po_text)) >= 1, "; ".join(wrong) or f"{len(WEARS.findall(po_text))} on 6662/99")
    for donor, (text, results) in green.items():
        check(f"{donor}: stairways dealt, each with its purpose", len(results) >= 1,
              "; ".join(said(s) for s, _ in results) or next(iter(re.findall(r"^  stairways.*$", text, re.M)), ""))
        for s, bad in results:
            check(f"{donor}: the stairway {said(s)} compiles sealed, stands on the floor, holds its pickup",
                  not bad, "; ".join(bad) or "as dealt")
    if not a.no_red:
        before = hash_tree(REPO)
        box = Sandbox(REPO, "stairways")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            line = b"static const bool g_stair_support = true;"
            if check("RED: the landing's support is where the mutation says", data.count(line) == 1):
                target.write_bytes(data.replace(line, b"static const bool g_stair_support = false;", 1))
                (a.work / "red_bin").mkdir(parents=True, exist_ok=True)
                red = run(build_driver(box.root, a.work / "red_bin"), a.work, "red")
                floats = [(s, bad) for _, res in red.values() for s, bad in res
                          if any("floats" in b for b in bad)]
                total = sum(len(res) for _, res in red.values())
                check("RED: with the support taken out every landing floats - the case above goes red",
                      total > 0 and len(floats) == total, f"{len(floats)} of {total} float")
            side = b'snprintf(s.tex_side, sizeof(s.tex_side), "%s", s.tex_tread);'
            data = target.read_bytes().replace(b"static const bool g_stair_support = false;",
                                               b"static const bool g_stair_support = true;", 1)
            if check("RED: the sides' material is where the mutation says", data.count(side) == 1):
                target.write_bytes(data.replace(side, b"{ const float back_[3] = { 0.5f * (s.lo[0] + s.hi[0]), 0.5f * (s.lo[1] + s.hi[1]), z + 64.0f };"
                                                 b" nearest_wall_texture(donor, back_, s.tex_side, sizeof(s.tex_side)); }", 1))
                (a.work / "red_bin2").mkdir(parents=True, exist_ok=True)
                red2 = build_driver(box.root, a.work / "red_bin2")
                rt = drive(red2, str(DONORS / "q2dm1.bsp"), "--seed", PO_CASE[1], "--ambition", PO_CASE[2],
                           "--stairways", "10", "--list")
                rw = wears_wrong(rt, DONORS / "q2dm1.bsp")
                check("RED: sides from the nearest wall - the PO's 6662/99 wears what it must not, the case goes red",
                      bool(rw), "; ".join(rw[:4]))
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    print(f"{TOTAL - FAILED}/{TOTAL} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
