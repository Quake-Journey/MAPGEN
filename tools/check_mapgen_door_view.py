r"""Brief 36 item 2: a door of a map seen in the game, both sides, shut and rising - the pictures the measure cannot give.

The client has no command that puts the camera somewhere (as the Studio's covers): each side is a copy of the map whose
only spawn points stand in front of the door, outside its trigger, facing it. One watched launch of the client (the
Studio's guard: configs read-only, no fixed client port, a window) per map: on each copy a shot of the door shut, the
view pitched up a little; on a second copy the start inside the door's trigger, pitched up, a shot every fifteenth of a
second while the door rises and one when it is up. The map copies, the config and the shots are taken out of the client after; the client's configs are compared
byte for byte before and after.

    python tools/check_mapgen_door_view.py BSP OUT [--door N] [--client DIR]
The pictures go to OUT (door_<a|b>_<shut|rising>_<k>.png). Run only while the game is not running from DIR - the caller checks.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))


def entities(bsp: bytes) -> list[dict]:
    o, n = struct.unpack_from("<ii", bsp, 8)
    text = bsp[o:o + n].split(b"\0")[0].decode("latin-1")
    return [dict(re.findall(r'"([^"]*)"\s+"([^"]*)"', blk)) for blk in re.findall(r"\{([^{}]*)\}", text)]


def with_start(bsp: bytes, x: float, y: float, z: float, yaw: float) -> bytes:
    ents = [e for e in entities(bsp) if not e.get("classname", "").startswith("info_player_")]
    for cls in ("info_player_deathmatch", "info_player_start"):
        ents.append({"classname": cls, "origin": f"{x:.0f} {y:.0f} {z:.0f}", "angle": f"{yaw:.0f}"})
    text = "".join("{\n" + "".join(f'"{k}" "{v}"\n' for k, v in e.items()) + "}\n" for e in ents) + "\0"
    lump = text.encode("latin-1")
    at = (len(bsp) + 3) & ~3
    out = bytearray(bsp) + b"\0" * (at - len(bsp)) + lump
    struct.pack_into("<ii", out, 8, at, len(lump))
    return bytes(out)


def doors(bsp: bytes) -> list:
    """[(mins, maxs, across axis)] of the map's func_doors, from the models lump."""
    mo, mn = struct.unpack_from("<ii", bsp, 8 + 13 * 8)
    models = [struct.unpack_from("<9f3i", bsp, mo + i * 48) for i in range(mn // 48)]
    out = []
    for e in entities(bsp):
        if e.get("classname") == "func_door" and e.get("model", "").startswith("*") and not e.get("targetname"):
            m = models[int(e["model"][1:])]
            lo, hi = m[0:3], m[3:6]
            out.append((lo, hi, 0 if hi[0] - lo[0] < hi[1] - lo[1] else 1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bsp", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--door", type=int, default=0)
    ap.add_argument("--client", type=Path, default=Path(r"O:\Claude2\q2pro-release"))
    ap.add_argument("--away", type=float, default=150.0, help="the shut view's start from the door's middle, across it")
    ap.add_argument("--pitch", type=int, default=12, help="frames of +lookup (150 degrees a second at 60) on the rising view")
    ap.add_argument("--near", type=float, default=56.0, help="the rising view's start: inside the door's trigger, clear of a 64 door")
    a = ap.parse_args()
    bsp = a.bsp.read_bytes()
    ds = doors(bsp)
    if not ds:
        print("FAIL no plain door in", a.bsp)
        return 1
    lo, hi, ax = ds[a.door % len(ds)]
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    print(f"door {a.door % len(ds)} of {len(ds)}: {[round(v) for v in lo]}..{[round(v) for v in hi]}, across {'xy'[ax]}")
    base = a.client / "baseq2"
    maps = base / "maps"
    shots = base / "screenshots"
    exe = a.client / "Q2PRO-X.exe"
    configs = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in base.rglob("*.cfg") if "mgs_" not in p.name}
    a.out.mkdir(parents=True, exist_ok=True)
    temp = []
    # the two sides, each twice: the start `away` from the door's middle across it (outside its trigger: the door shut),
    # and `near` (inside its trigger: the door rising from the first frame) - on its floor, facing it
    sides = []
    for k, sign in enumerate((-1, 1)):
        for where, dist in (("shut", a.away), ("rising", a.near)):
            p = list(c)
            p[ax] += sign * dist
            yaw = (0 if ax == 0 else 90) + (0 if sign < 0 else 180)
            name = f"mgs_door_{len(sides)}"
            path = maps / f"{name}.bsp"
            path.write_bytes(with_start(bsp, p[0], p[1], lo[2] + 26, yaw))
            temp.append(path)
            sides.append((name, "ab"[k] + "_" + where))
    cfg = ["cl_gun 0", "crosshair 0", "scr_draw2d 0", "con_notifytime 0", "cl_maxfps 60", "r_maxfps 60", "coop 0",
           "deathmatch 0", "cl_pitchspeed 150"]   # single player: no green login flash at the start
    for k, (name, what) in enumerate(sides):
        nxt = f"mgs_go{k + 1}"
        if what.endswith("shut"):
            # level, then the view pitched up 30 degrees
            steps = ["wait 120", "screenshotpng", "wait 6", "+lookup", "wait 12", "-lookup", "wait 6", "screenshotpng", "wait 6"]
        else:
            # pitched up at once, then a shot every 4 frames (1/15 s) while the door rises, and one when it is up
            steps = ["+lookup", f"wait {a.pitch}", "-lookup"]
            for _ in range(8):
                steps += ["screenshotpng", "wait 4"]
            steps += ["wait 60", "screenshotpng", "wait 6"]
        steps.append(nxt)
        cfg.append(f'alias mgs_go{k} "alias mgs_at mgs_at{k}; map {name}"')
        cfg.append(f'alias mgs_at{k} "{"; ".join(steps)}"')
    cfg.append(f"alias mgs_go{len(sides)} quit")
    cfg.append("set cl_beginmapcmd mgs_at")
    cfg.append("mgs_go0")
    cfg_path = base / "mgs_door.cfg"
    cfg_path.write_text("\n".join(cfg) + "\n", encoding="latin-1")
    temp.append(cfg_path)
    before = set(shots.glob("*.png")) if shots.is_dir() else set()
    t0 = time.time()
    run = subprocess.run([str(exe), "+set", "q2prox_config_readonly", "1", "+set", "net_clientport", "-1",
                          "+set", "vid_fullscreen", "0", "+exec", "mgs_door.cfg"], cwd=str(a.client), timeout=240,
                         capture_output=True)
    new = sorted((p for p in shots.glob("*.png") if p not in before and p.stat().st_mtime >= t0 - 1),
                 key=lambda p: p.stat().st_mtime)
    # 2 shots of each shut view, 9 of each rising one, in the order the views were taken
    names = []
    for _name, what in sides:
        n = 2 if what.endswith("shut") else 9
        names += [f"door_{what}_{i:02d}.png" for i in range(n)]
    for p, dst in zip(new, names):
        shutil.move(str(p), a.out / dst)
    for p in temp:
        p.unlink(missing_ok=True)
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in base.rglob("*.cfg") if "mgs_" not in p.name}
    print(f"client exit {run.returncode}; {len(new)} shots into {a.out}; temp files left: "
          f"{[str(p) for p in temp if p.exists()]}; configs equal before and after: {configs == after}")
    return 0 if new and configs == after else 1


if __name__ == "__main__":
    sys.exit(main())
