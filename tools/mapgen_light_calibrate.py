r"""Which light settings light a generated map like its donor (row 405, Fable's brief 5 section 7 L3).

    python tools/mapgen_light_calibrate.py LIT.bsp DONOR.bsp WORK_DIR "FLAGS" ["FLAGS" ...]

LIT.bsp is a finished map (bsp, full vis and light done, its own entity lump). For each FLAGS string (e.g. "",
"-sunradscale 1.0", "-sunradscale 1.0 -bounce 8") a copy gets the donor's sun the way the pipeline's light compile
gives it (`add_sun_for_light`: worldspawn "_sun", an info_null at a start, a light 8 units towards "_sun_angle"),
the pinned compiler's light pass alone runs on it with `-maxdata 8388608 -threads <P-cores>` and those flags, the
copy takes its own entity lump back, and `mapgen_light_ratio.py` compares it with the donor: one table per setting.
Runs under the load guard; one light pass at a time.
"""
from __future__ import annotations

import math
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as guard  # noqa: E402
from mapgen_light_profile import faithful  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

GAME = r"O:\Claude2\q2pro-release\baseq2"


def entity_text(d: bytes) -> str:
    o, n = struct.unpack_from("<ii", d, 8)
    return d[o:o + n].split(b"\0")[0].decode("latin-1")


def with_entities(d: bytes, text: str) -> bytes:
    out = bytearray(d)
    at = (len(out) + 3) & ~3
    data = text.encode("latin-1") + b"\0"
    out += b"\0" * (at - len(out)) + data
    struct.pack_into("<ii", out, 8, at, len(data))
    return bytes(out)


def with_keys(text: str, keys: dict | None) -> str:
    """Row 410: worldspawn keys replaced or added - the donor's sun as q2tools-220 must be told it."""
    if not keys:
        return text
    w = text.index("{")
    end = text.index("}", w)
    world = text[w:end]
    for k, v in keys.items():
        pat = r'"' + re.escape(k) + r'"\s+"[^"]*"'
        world = re.sub(pat, f'"{k}" "{v}"', world) if re.search(pat, world) else world + f'\n"{k}" "{v}"\n'
    return text[:w] + world + text[end:]


def donor_light(donor: Path) -> tuple[str, dict]:
    """Row 410: a donor's light-pass switches and sun keys, by its sha256, from tools/mapgen_donor_light.json - or
    from its own automatic fit beside it."""
    import hashlib
    import json
    table = json.loads((Path(__file__).resolve().parent / "mapgen_donor_light.json").read_text(encoding="utf-8"))
    sha = hashlib.sha256(donor.read_bytes()).hexdigest()
    entry = table.get(sha)
    if entry is None:
        # a donor not in the table: its own automatic fit beside it, made once on the first map built from it
        # (tools/mapgen_light_autofit.py), when it is of this very file
        fit = donor.with_suffix(".light_fit.json")
        if fit.is_file():
            own = json.loads(fit.read_text(encoding="utf-8"))
            if own.get("sha256") == sha:
                entry = own
    entry = entry or {}
    return entry.get("flags", ""), entry.get("keys", {})


def with_sun(text: str) -> str | None:
    world = text.index("{")
    head = text[world:text.index("}", world)]
    m = re.search(r'"_sun_angle"\s+"([-\d.]+)\s+([-\d.]+)"', head)
    if not m or re.search(r'"_sun"\s', head):
        return None
    yaw, pitch = float(m.group(1)), float(m.group(2))
    s = re.search(r'\{[^{}]*"classname"\s+"info_player_[^"]*"[^{}]*\}', text)
    o = re.search(r'"origin"\s+"([-\d.]+) ([-\d.]+) ([-\d.]+)"', s.group(0)) if s else None
    if not o:
        return None
    at = [float(v) for v in o.groups()]
    r = math.pi / 180.0
    to = [-math.cos(pitch * r) * math.cos(yaw * r), -math.cos(pitch * r) * math.sin(yaw * r), -math.sin(pitch * r)]
    light = [at[i] + to[i] * 8.0 for i in range(3)]
    return (text[:world + 1] + '\n"_sun" "mapgen_sun"' + text[world + 1:].rstrip("\0")
            + '{\n"classname" "light"\n"target" "mapgen_sun"\n"origin" "%.1f %.1f %.1f"\n}\n' % tuple(light)
            + '{\n"classname" "info_null"\n"targetname" "mapgen_sun"\n"origin" "%.1f %.1f %.1f"\n}\n' % tuple(at))


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    guard.pin_self()
    lit, donor, work = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    work.mkdir(parents=True, exist_ok=True)
    raw = lit.read_bytes()
    own = entity_text(raw)
    sunny = with_sun(own)
    compiler = str(pinned_compiler()[0])
    threads = str(bin(guard.affinity_mask()).count("1"))
    for i, flags in enumerate(sys.argv[4:]):
        d = work / f"v{i}"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        words = ["-rad", "-maxdata", "8388608", "-threads", threads, *flags.split(),
                 "-moddir", GAME, "-basedir", GAME, "-gamedir", GAME]
        # row 411 (Fable's brief 8 D): in memory - only the lit result reaches the disk
        from mapgen_memfile import compile_bsp_in_memory
        runs, out = compile_bsp_in_memory(compiler, [words], with_entities(raw, sunny) if sunny else raw,
                                          label="calibrate")
        if runs is None:
            (d / "q2mg.bsp").write_bytes(with_entities(raw, sunny) if sunny else raw)
            r = guard.run([compiler, *words, str(d / "q2mg.map")],
                          capture_output=True, text=True, errors="replace", timeout=7200)
            out = (d / "q2mg.bsp").read_bytes()
        else:
            r = runs[-1]
        (d / "rad.log").write_text(r.stdout, encoding="utf-8")
        (d / "q2mg.bsp").write_bytes(with_entities(out or raw, own))
        # row 410 (brief 7): per channel, burnt share and p90 on the faces both maps draw - the three-channel mean of
        # row 405 let a pass 1.8 times redder than cor's agree with it
        ok, how, _ = faithful(d / "q2mg.bsp", donor)
        said = [ln for ln in r.stdout.splitlines() if "Sun activated" in ln or "NOT FOUND" in ln]
        print(f"== '{flags}' (exit {r.returncode}{'; ' + '; '.join(sorted(set(said))) if said else ''})"
              f" {'FAITHFUL' if ok else 'not faithful'}")
        print("   " + how.replace("; ", "\n   "), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
