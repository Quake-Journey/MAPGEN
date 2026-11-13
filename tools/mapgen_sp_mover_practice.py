"""The game's own single-player maps (base1, base2, boss1 …, read from the game's PAK0.PAK, read only) - their moving and
scripted things: what moves (trains, doors, rotating parts, plats, waters, conveyors, falling objects), what fires them
(timers, triggers, buttons, relays, counters), and the scripted effects (lasers, blasters, explosions, earthquakes,
banners, ships flying a path, steam, sparks). The PO 13.11: «посмотри вот например в синг картах тоже приемчики какие
были в скриптованных движущихся объектах … это тоже дообогатит твои знания о том что можно делать, но это просто
варианты».

    python tools/mapgen_sp_mover_practice.py [PAK0.PAK]   -> tools/mapgen_sp_mover_practice.json and a summary
"""
from __future__ import annotations

import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

PAK = Path(r"O:\Claude2\q2pro-release\baseq2\PAK0.PAK")
OUT = Path(__file__).resolve().parent / "mapgen_sp_mover_practice.json"
SCRIPTED = ("func_", "target_", "trigger_", "misc_", "path_corner", "turret_", "point_combat")


def pak_bsps(path: Path):
    raw = path.read_bytes()
    ident, dofs, dlen = struct.unpack_from("<4sii", raw, 0)
    assert ident == b"PACK", ident
    for i in range(dlen // 64):
        name, ofs, ln = struct.unpack_from("<56sii", raw, dofs + i * 64)
        name = name.split(b"\0")[0].decode("latin1")
        if name.lower().startswith("maps/") and name.lower().endswith(".bsp"):
            yield Path(name).stem.lower(), raw[ofs:ofs + ln]


def entities(bsp: bytes) -> list:
    off, ln = struct.unpack_from("<ii", bsp, 8)
    text = bsp[off:off + ln].split(b"\0")[0].decode("latin1")
    out = []
    for m in re.finditer(r"\{([^{}]*)\}", text):
        out.append(dict(re.findall(r'"([^"]*)"\s+"([^"]*)"', m.group(1))))
    return out


def main() -> int:
    pak = Path(sys.argv[1]) if len(sys.argv) > 1 else PAK
    per_map = {}
    total = Counter()
    fired_by = defaultdict(Counter)
    examples = defaultdict(list)
    for name, bsp in sorted(pak_bsps(pak)):
        ents = entities(bsp)
        named = defaultdict(list)
        for e in ents:
            if e.get("targetname"):
                named[e["targetname"]].append(e)
        cls = Counter(e.get("classname", "") for e in ents if e.get("classname", "").startswith(SCRIPTED))
        per_map[name] = dict(cls)
        total.update(cls)
        # what fires each moving or scripted thing: the classes whose target names it
        for e in ents:
            c = e.get("classname", "")
            if not c.startswith(("func_", "target_", "misc_")) or not e.get("targetname"):
                continue
            for x in ents:
                if x.get("target") == e["targetname"] or x.get("killtarget") == e["targetname"]:
                    fired_by[c][x.get("classname", "")] += 1
        # examples of the less common things, with their keys
        for e in ents:
            c = e.get("classname", "")
            if c in ("func_conveyor", "func_object", "func_explosive", "misc_viper", "misc_strogg_ship", "misc_banner",
                     "misc_satellite_dish", "target_earthquake", "target_blaster", "target_explosion", "target_laser",
                     "target_splash", "target_lightramp", "func_killbox", "trigger_elevator", "misc_bigviper",
                     "turret_breach", "target_spawner", "func_wall", "func_door_secret", "func_rotating",
                     "func_door_rotating", "func_water", "func_train", "func_timer") and len(examples[c]) < 6:
                examples[c].append({"map": name, **{k: v for k, v in e.items() if k != "model"}})
    data = {"source": str(pak), "maps": len(per_map), "total": dict(total.most_common()),
            "fired_by": {k: dict(v.most_common(6)) for k, v in fired_by.items()},
            "examples": examples, "per_map": per_map}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(per_map)} maps; scripted and moving classes, all maps:")
    for c, n in total.most_common(45):
        maps = sum(1 for m in per_map.values() if c in m)
        print(f"  {c:26s} {n:5d}  in {maps:2d} maps   fired by: "
              + ", ".join(f"{k} {v}" for k, v in fired_by.get(c, {}).items() if k)[:110])
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
