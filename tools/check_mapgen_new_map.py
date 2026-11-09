r"""Brief 19 D7: a map made from scratch is held to what people's maps are, measured the same way.

`tools/mapgen_map_survey.py` measures a compiled map by the method of Fable's research of 04.11 (120 human-made maps);
the bands below are that research's medians and quartiles, widened to the range most human maps of the class fall
in. A new map passes when every band holds for its player class - and, where its parameters asked for something
else (more levels, long sight lines, a dead-end stack), when the measure shows what was asked.

    python tools/check_mapgen_new_map.py MAP.bsp [--players N] [--asked request.json]
    python tools/check_mapgen_new_map.py --humans          the bands over people's maps: how many of each pass
    python tools/check_mapgen_new_map.py --red [MAP.bsp]   the box-synthesis map must FAIL (q2mg_f000 by default)

The RED is the September generator's map: one box per 1536-unit cell, tubes between, 6 M u² of floor for eight
players, two levels, a third of the visible pairs over 1000 units, the guns out of reach. The map of 07.09 that the
PO walked was cleaned away with its folder; `q2mg_f000.bsp` in his maps is the same generator's map of 01.09.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_map_survey as survey  # noqa: E402

# the game's maps and the Studio's bases: the released Studio names its own (MAPGEN_GAME, MAPGEN_DONORS)
MAPS = Path(os.environ.get("MAPGEN_GAME") or r"O:\Claude2\q2pro-release\baseq2") / "maps"
DONORS = Path(os.environ.get("MAPGEN_DONORS") or r"O:\Claude2\MapgenStudio\engine\donors")
RED = MAPS / "q2mg_f000.bsp"
HUMANS = {"duel": ["q2duel5", "ztn2dm3", "omf", "q2duel1", "koldduel1", "pro_q2t4", "q2rdm2"],
          "ffa": ["q2dm1", "q2dm3", "trdm01a", "q2dm8", "q2dm6"]}


def player_class(players: int) -> str:
    return "duel" if players <= 2 else "ffa8" if players <= 8 else "ffa11" if players <= 11 else "ffa16"


# (low, high) for each measure; None = no bound that side
BANDS = {
    "duel": {"walk_area_mu2": (1.1, 3.2), "levels": (3, 6), "vertical_span": (160, 512),
             "width_median": (176, 300), "share_corridor": (0.25, 0.55), "share_medium": (0.35, 0.65),
             "share_open": (0.0, 0.25), "headroom_median": (112, 288), "visible_pairs": (0.06, 0.20),
             "visible_over_1000": (None, 0.06), "majors_at_height": (0.35, None), "exits_median": (2, None),
             "dead_end_majors": (None, 0.40), "pairs_with_alternative": (0.60, None),
             "major_major_median_s": (2.5, 7.0), "spawn_to_weapon_s": (None, 3.0), "spawn_to_stack_s": (None, 3.5),
             "spawn_to_spawn_s": (1.0, 4.0), "dark_floor_share": (None, 0.16), "spawns_at_height": (0.5, 0.9)},
}
BANDS["ffa8"] = dict(BANDS["duel"], walk_area_mu2=(1.8, 4.6), vertical_span=(192, 640), spawn_to_stack_s=(None, 5.0),
                     major_major_median_s=(3.0, 9.0), spawn_to_weapon_s=(None, 3.5), visible_pairs=(0.05, 0.20))
BANDS["ffa11"] = dict(BANDS["ffa8"], walk_area_mu2=(2.5, 5.5))
BANDS["ffa16"] = dict(BANDS["ffa8"], walk_area_mu2=(3.0, 7.0))


# brief 25 A3: «Открытый космос» - islands in the void, measured on q2_q3dm17 (the people's survey: open 0.93, width
# median 1328, visible pairs 0.61, over 1000 u 0.35, exits 2, dead-end majors 0.29, alternatives 0.62, major to major
# 7.0 s, spawn to weapon 3.4, to stack 3.9, spawn to spawn 2.0) and on the generator's first space maps of 06.11 (five:
# dead-end majors 0.55..0.82 - a perch has one way off; alternatives 0.33..0.81; spawn to stack up to 5.3) - one human
# sample, so the margins are wide; rooms' bands that mean nothing over the void (headroom, spawns at height) left out
SPACE_VOID_MIN = {"open": 0.30, "some": 0.15, "railings": 0.05}


def space_bands(players: int, asked: dict) -> dict:
    b = dict(BANDS[player_class(players)])
    b.update(levels=(3, 9), width_median=(448, None), share_corridor=(0.0, 0.15), share_medium=(0.0, 0.4),
             share_open=(0.6, 1.0), visible_pairs=(0.3, None), visible_over_1000=(None, 0.6), majors_at_height=(0.5, None),
             exits_median=(1, None), dead_end_majors=(None, 0.85), pairs_with_alternative=(0.3, None),
             major_major_median_s=(2.5, 9.0), spawn_to_weapon_s=(None, 3.5), spawn_to_stack_s=(None, 6.0),
             spawn_to_spawn_s=(1.0, 4.0))
    b.pop("headroom_median", None)
    b.pop("spawns_at_height", None)
    spread = int(asked.get("height_spread") or 800)
    b["vertical_span"] = (0.5 * spread, 1.2 * spread)
    return b


def tower_bands(players: int, asked: dict) -> dict:
    """Brief 25 B: «Башня» - whole storeys over one footprint, measured on pro_q2t4 (three floors 152 apart, 73 % of the
    floor with floor over or under it, spawns on all three): the class's bands, with the floor over floor at least
    half, the levels the storeys (the perches over the top one more), the span the storeys' heights, the spawns over
    the storeys (a third of them on the ground at most and at least one up)."""
    b = dict(BANDS[player_class(players)])
    n = int(asked.get("storeys") or 3)
    sh = int(asked.get("storey_height") or 192)
    b.update(levels=(n - 1, n + 2), vertical_span=((n - 1) * sh * 0.9, (n - 1) * sh + 260), stacked_share=(0.5, None),
             spawns_at_height=(0.3, 0.95))
    return b


def space_rows(r: dict, asked: dict) -> list:
    """The space's own: the islands asked, the pad-only ones, the edge over the void, every pad landing."""
    sp = r.get("space")
    if not sp:
        return [("space: its own measure", False, "not measured")]
    isl = sp["islands"]
    want = int(asked.get("islands") or 8)
    po = int(asked.get("pad_only") or 0)
    edges = asked.get("edges") or "open"
    flown = sum(1 for p_ in sp.get("pads") or [] if p_.get("points", 0) > 3)
    landed = (sp.get("movers") or {}).get("pads", 0)
    return [
        (f"space: islands {want} asked (+-2)", abs(isl["count_over_0.02mu2"] - want) <= 2, str(isl["count_over_0.02mu2"])),
        (f"space: islands only a pad reaches, {po} asked at least", isl["reached_only_by_pad_or_teleport"] >= po,
         str(isl["reached_only_by_pad_or_teleport"])),
        (f"space: the edge over the void at least {SPACE_VOID_MIN.get(edges, 0.3):.2f} of the outline ({edges})",
         sp["outline_void_share"] >= SPACE_VOID_MIN.get(edges, 0.3), str(sp["outline_void_share"])),
        ("space: every pad flies onto a floor", flown == landed and landed > 0, f"{landed} of {flown}"),
    ]


def tower_rows(r: dict, asked: dict, plan: dict) -> list:
    """The tower's own: the perches asked, every pad landing on a floor (its pads lift a man a storey or two)."""
    sp = r.get("space")
    if not sp:
        return [("tower: its own measure", False, "not measured")]
    flown = sum(1 for p_ in sp.get("pads") or [] if p_.get("points", 0) > 3)
    landed = (sp.get("movers") or {}).get("pads", 0)
    want = int(asked.get("perches") or 0)
    got = int((plan or {}).get("perches") or 0)
    pads_planned = int((plan or {}).get("pads") or 0)
    return [
        # brief 34: a tower of stairs and lifts may have no pad at all
        ("tower: every pad flies onto a floor", flown == landed and (landed > 0 or pads_planned == 0), f"{landed} of {flown}"),
        (f"tower: ledges only a pad reaches, {want} asked", got >= want, str(got)),
    ]


def in_box(p, box) -> bool:
    """A point (x y z, feet or eye) inside a box x0 y0 x1 y1 z0 z1."""
    return bool(box) and box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3] and box[4] <= p[2] <= box[5]


def engine_traps(path: str):
    """The engine's own walk (the game's movement over the compiled map, tools/mapgen_reach_gate.c): how many places a
    player can reach and not leave, not counting deadly ones, and each place - or None without the helper. The
    survey's walk jumps 44 at most; the game's player climbs more (270 u/s, a step of 18 during the arc), and on
    ztn2dm3 the survey found 28 «trapped» points the engine's walk leaves (04.11)."""
    helpers = Path(os.environ.get("MAPGEN_HELPERS") or (TOOLS.parent / "engine" / "helpers"))
    exe = helpers / "reach_gate.exe"
    if not path or not exe.is_file():
        return None
    try:
        run = subprocess.run([str(exe), str(path), "--all-traps"], capture_output=True, text=True, timeout=3600,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"one-way (\d+) \((\d+) lethal\)", run.stdout)
    if not m:
        return None
    pts = [(float(a), float(b), float(z)) for a, b, z in
           re.findall(r"^\s+at (-?[\d.]+) (-?[\d.]+) (-?[\d.]+)", run.stdout, re.M)]
    n = int(m.group(1)) - int(m.group(2))
    return n, pts, len(pts) >= n


def P_OPEN_LOW(asked) -> bool:
    """A corridor share asked under 0.25 needs no corridor piece (brief 21)."""
    o = (asked or {}).get("openness")
    return bool(o) and float(o[0]) < 0.25


def judge(r: dict, players: int, asked: dict | None = None, plan: dict | None = None) -> list[tuple[str, bool, str]]:
    """The bands of the class, with what the parameters asked in their place; `asked` is the run's request (the
    parameters as tools/mapgen_scratch_plan.defaults resolved them), `plan` the skeleton's metrics (the counts a
    compiled map does not show by itself: flights, ramps, drops, windows, decorations)."""
    asked = asked or {}
    space = asked.get("shape") == "space"
    tower = asked.get("shape") == "tower"
    bands = space_bands(players, asked) if space else tower_bands(players, asked) if tower else dict(BANDS[player_class(players)])
    # what the parameters asked takes the band's place (a tower's levels and span are its storeys')
    if asked.get("levels") and not space and not tower:
        n = int(asked["levels"])
        bands["levels"] = (n - 1, n + 1)
    n_lines = int(asked.get("long_lines") or 0)
    if n_lines >= 3 and not space:
        bands["visible_over_1000"] = (None, 0.12)
    mech = set(asked.get("mechanics") or [])
    if "dead_end_stack" in mech:
        bands["dead_end_majors"] = (None, 0.55)
    if (asked.get("powerup_access") or "easy") != "easy" or asked.get("powerup_cycle"):
        # brief 21+: the powerups' nooks are dead ends by design (q2dm5's mega, q2dm8's cycle)
        bands["dead_end_majors"] = (None, 0.6)
    if asked.get("floor_area") and asked.get("floor_area_asked"):
        f = float(asked["floor_area"])
        bands["walk_area_mu2"] = (f * 0.85, f * 1.15)
    if asked.get("vertical_span") and not space and not tower:
        v = int(asked["vertical_span"])
        bands["vertical_span"] = (v * 0.75, v * 1.25)
    if asked.get("openness"):
        o = [float(x) for x in asked["openness"]]
        for key, v in zip(("share_corridor", "share_medium", "share_open"), o):
            bands[key] = (max(0.0, v - 0.15), min(1.0, v + 0.15))
    if float(asked.get("water") or 0) >= 0.08 or float(asked.get("lava") or 0) + float(asked.get("slime") or 0) >= 0.08:
        # much liquid asked: the floor people walk is smaller than the plan's, by what the liquid took
        lo, hi = bands["walk_area_mu2"]
        bands["walk_area_mu2"] = (lo * 0.7, hi)
    out = []
    for key, (lo, hi) in bands.items():
        v = r.get(key)
        if v is None:
            out.append((key, False, "not measured"))
            continue
        ok = (lo is None or v >= lo) and (hi is None or v <= hi)
        rng = f"{'' if lo is None else lo}..{'' if hi is None else hi}"
        out.append((key, ok, f"{v} (band {rng})"))
    unreach = r.get("majors_unreachable") or []
    out.append(("every major item reachable from the spawns", not unreach, ", ".join(unreach) or "all"))
    spawns = r.get("spawns", 0)
    want_sp = asked.get("spawns")
    out.append(("spawns as asked", spawns == int(want_sp) if want_sp else spawns >= max(2, players), str(spawns)))
    seen = r.get("spawn_pairs_seen_under_300")
    if seen is not None:
        out.append(("no spawn in another's sight under 300 u", seen == 0, str(seen)))
    out += asked_got(r, asked, plan or {})
    out += mechanics(r, dict(asked, _plan=plan or {}), players)
    fx = (plan or {}).get("fixtures")
    if fx:
        # brief 26 (the PO 06.11: q2_q3dm17's pads and portals «красиво, эффектно, мощно. А у нас что?»): every pad its
        # disc or wedge, every teleporter its frame - or the record says why not
        said_why = len(fx.get("why") or []) >= fx.get("bare", 0)
        ok = (fx["discs"] + fx["wedges"] == fx["pads"]
              and fx["frames"] + fx["posts"] + fx["bare"] == fx["teleporters"] and said_why)
        out.append(("fixtures: every pad has its disc or wedge, every teleporter its frame (or the record says why not)", ok,
                    f"pads {fx['pads']}: {fx['discs']} discs, {fx['wedges']} wedges; teleporters {fx['teleporters']}: "
                    f"{fx['frames']} framed, {fx['posts']} posts only, {fx['bare']} bare"
                    + (f" ({'; '.join(fx['why'][:2])})" if fx.get("why") else "")))
    # brief 34 (the PO 08.11: «джампады … как кучу … выкатили в одном месте»; «не напихивать на уровне кучу повторяемых
    # объектов»): pads apart, like things not piled, every pad with a reason
    fm = r.get("fx_measure")
    if fm:
        gap = fm.get("pads_min_apart")
        out.append(("pads apart: two jump pads on one floor at least 192 apart (pro_q2t4: 527)", gap is None or gap >= 191,
                    f"{gap} (band 192..)" if gap is not None else "no two on one floor"))
        kind, most = fm.get("worst") or ("pad", 0)
        out.append(("repetition: no more than two like things within four cells on one floor", most <= 2,
                    f"{kind} {most} (band ..2)"))
    if plan and plan.get("pads_no_reason") is not None:
        n_ = int(plan["pads_no_reason"])
        out.append(("ways: no jump pad beside another way to the same place", n_ == 0, f"{n_} (band ..0)"))
    want_ships = int(asked.get("ships") or 0)
    if want_ships:
        # the PO 06.11: the ships asked fly - or the record says why fewer (no court under the sky tall enough)
        got = int((plan or {}).get("ships") or 0)
        said = any("корабли" in x for x in (plan or {}).get("refused") or [])
        out.append((f"ships in the sky: {want_ships} asked", got == want_ships or said, f"{got}" + (" (the record says why)" if said else "")))
    if space:
        out += space_rows(r, asked)
    if tower:
        out += tower_rows(r, asked, plan or {})
    return out


def asked_got(r: dict, asked: dict, plan: dict | None = None) -> list:
    """What the parameters asked (brief 19 §4), against what the compiled map holds - each count, share and set; the
    few the map cannot show by itself (flights, ramps, drops, windows, decorations) from the skeleton's record."""
    out = []
    plan = plan or {}
    said_counts = " ".join(plan.get("refused") or [])
    mv = r.get("movers") or {}
    words = {"lifts": "лифтов", "pads": "джампадов", "teleporters": "телепортов", "ladders": "стремянок",
             "doors": "дверей", "pits": "смертельных ям"}
    # brief 34: a tower's lift stops on every storey - a train the walk rides, counted with the plats
    for key, measured, label in (("lifts", mv.get("plats", 0) + mv.get("trains", 0), "lifts (func_plat) ridden in the walk"),
                                 ("pads", mv.get("pads", 0), "jump pads with a landing in the walk"),
                                 ("teleporters", mv.get("teleporters", 0) // 2, "teleporter pairs crossed"),
                                 ("ladders", mv.get("ladders", 0), "ladders climbed in the walk"),
                                 ("doors", r.get("doors", 0), "doors (func_door)"),
                                 # brief 25: the space's kill volume under the map is its shape, not a pit
                                 ("pits", r.get("deadly_volumes", 0) - (1 if asked.get("shape") == "space" else 0),
                                  "deadly pits (trigger_hurt)")):
        want = asked.get(key)
        if want is None:
            continue
        ok = measured == int(want) if key in ("doors", "pits") else measured >= int(want)
        # D5: fewer than asked, said with its reason in the record (the skeleton found no more room) - honest
        why = not ok and measured < int(want) and words.get(key, "#") in said_counts
        out.append((f"{label}: {want} asked" + (" - fewer, said why in the record" if why else ""), ok or why,
                    str(measured)))
    for kind in ("water", "lava", "slime"):
        want = float(asked.get(kind) or 0)
        got = r.get(f"{kind}_share")
        if got is None or kind not in asked:
            continue
        if want > 0:
            ok = want * 0.5 <= got <= want * 2.0
            why = not ok and got < want * 0.5 and {"water": "вода:", "lava": "лава:", "slime": "кислота:"}[kind] in said_counts
            # «<kind> asked», not «<kind>»: the engine's own «water: ...» and «sky: ...» gates hold those names, and the
            # Studio showed their words over these rows (04.11: «Нет вертикальных поверхностей воды» on the water share)
            out.append((f"{kind} asked: {want:.0%} of the floor (within half of it, never over twice)"
                        + (" - less, said why in the record" if why else ""), ok or why, f"{got:.1%}"))
        elif kind != "water":
            out.append((f"{kind} asked: none", got == 0, f"{got:.1%}"))
    # brief 20 D2: a dead end under a drop is asked to be one, left by a rocket jump no walk rides - the places inside
    # its room are allowed, none elsewhere (04.11 test duel: all 192 of the engine's places inside its box)
    box = (plan or {}).get("dead_end_box") if "dead_end_stack" in set(asked.get("mechanics") or []) else None
    eng = engine_traps(r.get("path") or "")
    if r.get("trapped_points") is not None:
        pts = r.get("trapped_at") or []
        outside = sum(1 for p in pts if not in_box(p, box)) if box else r["trapped_points"]
        # the survey's walk jumps 44, the game's player gets onto 60 (tools/mapgen_jump_height_probe.py): where the
        # engine's walk - the game's own movement - finds no trap, the survey's points are ledges a jump leaves (05.11:
        # 9 on the styled duel, the engine 0). Without the engine's helper the survey's word stands
        eng_clear = eng is not None and (eng[0] == 0 or (box and eng[2] and all(in_box(p, box) for p in eng[1])))
        out.append(("traps: no place one can reach and not leave", outside == 0 or eng_clear,
                    f"{r['trapped_points']} points of 32 u" + (f", {r['trapped_points'] - outside} of them inside the dead end asked" if box else "")
                    + (" - left by a jump the game's movement makes (the engine's walk: none)" if outside and eng_clear else "")))
    if eng is not None:
        n, pts, listed = eng
        if not box:
            out.append(("traps-engine: none by the game's own movement", n == 0, f"{n} place(s)"))
        elif listed:
            outside = sum(1 for p in pts if not in_box(p, box))
            out.append(("traps-engine: none by the game's own movement", outside == 0,
                        f"{n} place(s), {n - outside} of them inside the dead end asked"))
        else:
            out.append(("traps-engine: none by the game's own movement", False,
                        f"{n} place(s), the helper listed only some - an older reach_gate without --all-traps"))
    if r.get("floor_burnt_share") is not None:
        # brief 20 D3: people's floors (17 maps, 04-05.11): none at 255, median 60..117, the top tenth 130..196; their
        # walls none at 255. RED: the 3.40 duel (31 % of the floor at 255, median 140) and FFA-8 (26 %)
        fb, p50, p90 = float(r["floor_burnt_share"]), int(r["floor_light_p50"]), int(r["floor_light_p90"])
        sb = float(r.get("side_burnt_share") or 0)
        out.append(("lit: floors and walls not burnt white, the floor as bright as people's",
                    fb <= 0.01 and sb <= 0.01 and 55 <= p50 <= 120 and p90 <= 200,
                    f"floor at 255 {fb:.1%}, median {p50}, top tenth {p90}; walls at 255 {sb:.1%}"))
    look = r.get("look") or {}
    if look.get("coloured") is not None:
        # the PO, 05.11, of the 3.41 maps: «монохромное», «глаза выбеливают твои карты», «посмотри как выглядят q2dm*,
        # q2duel*, ztn2dm*, koldduel1, omf, ptrip, match1, kaktus». Their bands (tools/mapgen_people_style.json, 26
        # maps): coloured surface 50..100 %, textures lum 20..42, on screen (texture x light) median 7..25 and top
        # tenth 15..55, the largest texture 11..45 % of the surface, light saturation 0.13..0.95. RED: the 3.41 duel
        # (9 % coloured, lum 115, on screen 49) and FFA-8 (23 %, 95, 39)
        # 3.46: the Studio's own snow textures are a light, pale world by design (the PO asked for «снежные
        # поверхности»): their bands wider - lum to 90, coloured from 20 %, on screen to 40 / 80
        st_ = (asked or {}).get("style") or {}
        snow = st_.get("source") == "generated" and (st_.get("gen") or {}).get("theme") == "snow"
        out.append(("colour: most of the surface coloured, as on people's maps",
                    float(look["coloured"]) >= (0.2 if snow else 0.5),
                    f"{float(look['coloured']):.0%} coloured (people's 50..100 %" + ("; a snow world 20 %+)" if snow else ")")))
        out.append(("texture brightness: textures no lighter than people's", float(look["tex_lum"]) <= (90 if snow else 48),
                    f"mean {float(look['tex_lum']):.0f} (people's 20..42" + ("; a snow world to 90)" if snow else ")")))
        out.append(("on screen: as bright as people's maps, not washed out",
                    6 <= float(look["seen_p50"]) <= (40 if snow else 26) and float(look["seen_p90"]) <= (80 if snow else 60),
                    f"median {float(look['seen_p50']):.0f}, top tenth {float(look['seen_p90']):.0f} (people's 7..25, 15..55)"))
        out.append(("one texture: none over 45 % of the surface", float(look["top1"]) <= 0.45,
                    f"the largest {float(look['top1']):.0%}, {look.get('textures')} textures (people's 11..45 %, 9..38)"))
        out.append(("light colour: tinted, as people's light", float(look["light_sat"]) >= 0.13,
                    f"saturation {float(look['light_sat']):.2f} (people's 0.13..0.95)"))
        # brief 21 F1 (Fable's review of 3.42): the count no other row sees - 3.42's styled duel wore 4 textures,
        # people's maps 9..38 (each holding 0.5 % of the surface at least); the bar is Fable's 8, a margin under
        # people's fewest (q2duel3, kaktus 9). RED: the 3.42 styled duel
        out.append(("textures: as many as people's maps", int(look.get("textures") or 0) >= 8,
                    f"{look.get('textures')} textures over 0.5 % of the surface (people's 9..38)"))
    elif look.get("error"):
        out.append(("colour: most of the surface coloured, as on people's maps", False, f"not measured: {look['error']}"))
    if plan and int(plan.get("stacked_asked") or 0) > 0 and r.get("stacked_share") is not None:
        # brief 21 (brief 20 D5 «rooms over rooms»): floor over floor measured on the map - people's 26 maps keep
        # 0..64 % of their reachable floor over or under another floor 128 apart (median 35 %; q2duel4 0, q2dm5 2.8 %,
        # q2dm6 3.3 %, ztn2dm2 4.4 %, the rest 20 % and more). The bar is their low end; RED: the 3.42 maps (0)
        sh = float(r["stacked_share"])
        out.append(("rooms over rooms: floor over floor, as people's maps", sh >= 0.03,
                    f"{sh:.0%} of the floor over or under another (people's 0..64 %, median 35 %); "
                    f"rooms over rooms {plan.get('stacked_rooms')} of {plan.get('stacked_asked')}"))
    if plan and plan.get("round") is not None and (asked or {}).get("round"):
        # 3.46 (the PO 05.11, medusa_b1): the round shapes asked are on the map - a corner, an apse or a podium at least
        rm = plan["round"]
        n = sum(int(v or 0) for v in rm.values())
        # brief 22 D7: the kinds asked and not made named (still a pass with one kind made: the map's rooms decide)
        missing = [k_ for k_ in (asked.get("round_kinds") or []) if not rm.get(k_)]
        out.append(("round shapes: as asked (rounded corners, apses, podiums)", n >= 1,
                    f"corners {rm.get('corners', 0)}, apses {rm.get('apses', 0)}, podiums {rm.get('podiums', 0)} "
                    f"({asked.get('round')}: {', '.join(asked.get('round_kinds') or [])})"
                    + (f"; not made: {', '.join(missing)} - the reason in the record" if missing else "")))
    if r.get("buttons"):
        # brief 22 D1 (Fable 06.11): every powerup button free on its wall - none inside a lamp post, a pilaster, a decor
        # panel or a chamfer (15 of 102 in 3.46's plans; such a door never opens from outside)
        bb = r.get("buttons_buried") or []
        out.append(("buttons clear: no wall piece over a powerup's button", not bb,
                    f"{r['buttons']} buttons" + (f", buried: {'; '.join(bb[:3])}" if bb else ", all free")))
    if plan and plan.get("powerup_sites") is not None and r.get("powerups") is not None:
        # brief 21+ (the PO 05.11: «обособленное место … помечать такие места, делая их значимыми»): every powerup in a
        # place of its own as the access asked - lit; medium and hard in a nook; hard behind a door its button opens
        sites = plan["powerup_sites"]
        lit = all(p["lit"] >= 1 for p in r["powerups"])
        down = [f"{c_.replace('item_', '')}: {k_}" for c_, k_ in sites if "no nook" in k_]
        hard_ok = all(p["button"] for p in r["powerups"] if p.get("door"))
        asked_hard = sum(1 for _c, k_ in sites if k_ == "hard")
        doors_ = sum(1 for p in r["powerups"] if p.get("door"))
        out.append(("powerups: each in a place of its own, marked, as hard to reach as asked",
                    lit and not down and hard_ok and doors_ >= asked_hard,
                    "; ".join(f"{c_.replace('item_', '')} {k_}" for c_, k_ in sites)
                    + (f" (not had: {', '.join(down)})" if down else "") + ("" if lit else " - one unlit")))
    if r.get("dead_ends") is not None:
        # brief 21 D2, the PO 05.11 («из неё нет выхода кроме как входа»): with any one doorway closed, no room's worth
        # of floor loses its way to the rest of the map (the asked dead end's drop is not closed). RED: the 3.43 duel
        # (four one-door spaces) and mg_new_style (two)
        out.append(("dead ends: no room with one way in", not r["dead_ends"],
                    "; ".join(f"{w} ({n} points)" for w, n in r["dead_ends"][:4]) or "none"))
    if plan and plan.get("plain_rooms") is not None:
        # brief 21 D5, the PO 05.11 («голые стены, аптечка в конце», «нет ничего, что цепляло бы»): no hall or room is
        # a closed box - each has a window, an overlook, a bay, a terrace, an arcade or a room over or under it.
        # RED: the 3.43 duel (by its skeleton)
        out.append(("plain rooms: none is a closed box", int(plan["plain_rooms"]) == 0,
                    f"{plan['plain_rooms']} halls or rooms with nothing but walls and doorways"))
    if plan and plan.get("corridor_turns") is not None and not (P_OPEN_LOW(asked)):
        # brief 21 (brief 20 D5 «corridors»): corridor pieces with a turn - the narrow floor of people's maps is
        # corridors, ours was the narrow ends of rooms (the share row above measures the floor; this one the pieces)
        out.append(("corridors with a turn", int(plan["corridor_turns"]) >= 1,
                    f"{plan['corridor_turns']} corridor pieces with a turn (an L or a U)"))
    if plan and plan.get("pool_share_max") is not None:
        out.append(("pools: none over a third of its hall", float(plan["pool_share_max"]) <= 0.34,
                    f"the largest {float(plan['pool_share_max']):.0%} of its hall"))
    if r.get("hanging_brushes") is not None:
        # brief 20 D4, the PO 04.11 («висящих в воздухе архитектурных штучек»): nothing stands out of a wall half way
        # up or hangs from a ceiling on a rod. RED: the 3.36 maps (42, 55, 54); people's maps hold their detail
        # (0..56) - this is the PO's rule for our maps, not a band of theirs
        # brief 25: the islands of an open space hang in the air by design - the rule is the rooms'
        out.append(("nothing hanging: no piece out of a wall with air under it, none on a rod",
                    r["hanging_brushes"] == 0 or asked.get("shape") == "space",
                    f"{r['hanging_brushes']}" + (f": {', '.join(f'{h[3]} at {h[0]} {h[1]} {h[2]}' for h in r.get('hanging_at', [])[:3])}" if r["hanging_brushes"] else "")))
    if r.get("lifts_through_rock") is not None:
        out.append(("lifts: each rides through air only", not r["lifts_through_rock"],
                    "; ".join(r["lifts_through_rock"]) or "all clear"))
    if r.get("movers_overlap") is not None:
        # brief 21 D1: RED = the 3.43 mg_new_style (two lifts sharing a cell of room 0, the PO's video of 05.11)
        out.append(("movers apart: no lift or door overlaps another", not r["movers_overlap"],
                    "; ".join(r["movers_overlap"][:4]) or "none"))
    if r.get("spawns_by_movers") is not None:
        out.append(("spawns: none beside a teleporter, its exit or a jump pad (192 u)", r["spawns_by_movers"] == 0,
                    str(r["spawns_by_movers"])))
    if r.get("vertical_liquid_faces") is not None and not asked.get("water_above_floor"):
        # the PO, 04.11: liquid lies in hollows - none stands above a floor's edge unless the option allows it
        out.append(("liquids in hollows: no liquid face standing in the air", r["vertical_liquid_faces"] == 0,
                    f"{r['vertical_liquid_faces']} faces, {r.get('vertical_liquid_area')} sq u"))
    if asked.get("shape") == "space":
        pass                  # brief 25 A3: the air between islands is the fight - the long lines are its nature
    elif asked.get("long_lines_default") and r.get("long_lines") is not None:
        # brief 21: none asked - as people's maps (18 duels 0..7, 14 of them 4 or fewer; 8 FFA 1..6)
        got = int(r["long_lines"])
        top = 4 if int(asked.get("players") or 2) <= 2 else 6
        out.append(("long sight lines over 1000 u: as people's maps", got <= top, f"{got} (people's: {top} at most)"))
    elif asked.get("long_lines") is not None and r.get("long_lines") is not None:
        want = int(asked["long_lines"])
        got = int(r["long_lines"])
        # people's maps: duel 2..3, FFA 4..8 corridors of sight (mapgen_map_survey.distinct_lines); asked N - a duel
        # N or N + 1 (brief 20 D5: 2 asked gave 5), a larger map N .. N + 3; none asked - two at most
        top = want + (1 if int(asked.get("players") or 2) <= 2 else 3)
        out.append((f"long sight lines over 1000 u: {want} asked", (want <= got <= top) if want else got <= 2,
                    f"{got} (allowed {want}..{top})" if want else str(got)))
    if asked.get("sky") is not None and r.get("sky_share") is not None:
        want = float(asked["sky"])
        got = float(r["sky_share"])
        out.append((f"sky asked: over {want:.0%} of the standing places (+-15 points)", abs(got - want) <= 0.15,
                    f"{got:.0%}"))
    sites = r.get("sites") or {}
    for cls, n in (asked.get("weapons") or {}).items():
        out.append((f"{cls}: x{n} asked", sites.get(cls, 0) == int(n), str(sites.get(cls, 0))))
    if asked.get("items_at_height") is not None and r.get("majors_at_height") is not None:
        want = float(asked["items_at_height"])
        out.append((f"major items at height: {want:.0%} asked (+-25 points)", abs(r["majors_at_height"] - want) <= 0.25,
                    f"{r['majors_at_height']:.0%}"))
    shape = asked.get("shape")
    if shape == "halves" and plan.get("half_crossings") is not None:
        # brief 19 §6 «две половины»: two volumes joined by two chokepoints at most (the skeleton's routes across)
        hc = plan["half_crossings"]
        out.append(("shape «halves»: one or two routes between the halves (by the skeleton)", 1 <= hc <= 2, str(hc)))
    if shape == "ring":
        ok = (r.get("pairs_with_alternative") or 0) >= 0.8 and min(
            (it.get("exits") or 0 for it in r.get("items") or [] if it.get("exits") is not None), default=0) >= 2
        out.append(("shape «ring»: every major on a loop (alternatives >= 80 %, two ways out of each)", ok,
                    f"{r.get('pairs_with_alternative')}"))
    said = " ".join(plan.get("refused") or [])
    for key, label, word in (("stairs", "flights of steps", "лестниц"), ("ramps", "ramps", "пандус"),
                             ("drops", "one-way drops", "спуск"), ("windows", "windows", "окна")):
        want = asked.get(key)
        got = plan.get(f"{key}_got")
        if want is None or got is None or asked.get(f"{key}_default"):
            continue                # the generator's own default (by the levels) is no order of the PO's
        ok = got >= int(want) if key in ("stairs", "drops") else got == int(want)
        # D5: a shortfall the run said in words, with its reason, is honest - the record carries it
        why = word in said and not ok
        out.append((f"{label}: {want} asked (by the skeleton)" + (" - fewer, said why in the record" if why else ""),
                    ok or why, str(got)))
    for line in (asked.get("refused") or []) + list(plan.get("refused") or []):
        out.append((f"refused: {line}", True, "said in the record"))
    return out


def _t(r, i, j):
    m = r.get("item_times") or []
    try:
        return m[i][j]
    except (IndexError, TypeError):
        return None


def mechanics(r: dict, asked: dict, players: int) -> list:
    """Brief 19 §6, the mechanics switched on, in their measurable form on the compiled map."""
    mech = set(asked.get("mechanics") or [])
    items = r.get("items") or []
    idx = {}
    for i, it in enumerate(items):
        idx.setdefault(it["class"], []).append(i)
    out = []
    duel = players <= 2
    if "clock" in mech:
        a = (idx.get("item_armor_body") or idx.get("item_armor_combat") or [None])[0]
        b_ = (idx.get("item_health_mega") or idx.get("item_adrenaline") or [None])[0]
        if a is None or b_ is None:
            out.append(("mechanic «clock»: two stack items", False, "missing"))
        else:
            t = min(x for x in (_t(r, a, b_), _t(r, b_, a)) if x is not None) if (_t(r, a, b_) or _t(r, b_, a)) else None
            lo, hi = (5.0, 9.0) if duel else (4.0, 12.0)
            out.append((f"mechanic «clock»: the two stack items {lo:g}..{hi:g} s apart", t is not None and lo <= t <= hi,
                        f"{t} s"))
            ha, hb = items[a]["height"], items[b_]["height"]
            ea, eb = items[a].get("exits") or 0, items[b_].get("exits") or 0
            # 3.45: a powerup in its nook (the access asked, the PO 05.11 - q2dm5's mega, q2dm8's cycle) has the
            # nook's one opening by design; the room before it is what has its ways out
            nooked = {c_ for c_, k_ in ((asked.get("_plan") or {}).get("powerup_sites") or [])
                      if str(k_).startswith(("medium", "hard", "cycle"))}
            need_a = 1 if items[a]["class"] in nooked else 2
            need_b = 1 if items[b_]["class"] in nooked else 2
            out.append(("mechanic «clock»: both 64 up or more, each with two ways out (brief 19 §6; one from a nook)",
                        ha >= 64 and hb >= 64 and ea >= need_a and eb >= need_b,
                        f"heights {ha}/{hb}, exits {ea}/{eb}" + (" (nook)" if nooked & {items[a]["class"], items[b_]["class"]} else "")))
    if "halves" in mech:
        k = (idx.get("weapon_railgun") or [None])[0]
        a = (idx.get("item_armor_body") or idx.get("item_health_mega") or [None])[0]
        t = _t(r, k, a) if k is not None and a is not None else None
        out.append(("mechanic «halves»: the key gun and the stack on different halves (RG<->RA >= 7 s, brief 19 §6)",
                    t is not None and t >= 7.0, f"{t} s"))
    if "key_gun_ledge" in mech:
        k = (idx.get("weapon_railgun") or [None])[0]
        ok, said = False, "no railgun"
        if k is not None:
            h = items[k].get("above_around", items[k]["height"])
            arm = [i for c in ("item_armor_combat", "item_armor_jacket") for i in idx.get(c, [])]
            near = min((x for x in (_t(r, k, i) for i in arm) if x is not None), default=None)
            ok = h >= 128 and near is not None and near <= 2.2
            said = f"{h} over the floor around, an armour {near} s away"
        out.append(("mechanic «key gun on a ledge»: 128 up or more (brief 19 §6), an armour within 2.2 s", ok, said))
    if "asymmetry" in mech:
        best = 0.0
        n = len(items)
        for i in range(n):
            for j in range(n):
                tij, tji = _t(r, i, j), _t(r, j, i)
                if tij and tji and tji >= 0.6:
                    best = max(best, tij / tji)
        out.append(("mechanic «route asymmetry»: one item pair 2.5 times as long one way (brief 19 §6)", best >= 2.5,
                    f"{best:.2f}x"))
    if "small_health" in mech:
        n = r.get("small_health_sites", 0)
        out.append(("mechanic «many small health spots»: 5 or more", n >= 5, str(n)))
    if "spawn_pressure" in mech:
        med, mx = r.get("spawn_to_spawn_s"), r.get("spawn_to_spawn_max_nearest_s")
        out.append(("mechanic «spawn pressure»: spawns 1..3 s from the nearest, none over 4 s",
                    med is not None and mx is not None and 1.0 <= med <= 3.0 and mx <= 4.0, f"median {med}, worst {mx}"))
    if "dead_end_stack" in mech:
        # one way out - or none the walk rides: the way out of a dead end under a drop is a rocket jump (koldduel1's
        # mega), which the survey's walk does not model, so its ring at 1.5 s is empty
        st = [i for c in ("item_armor_body", "item_health_mega") for i in idx.get(c, [])]
        ok = any((items[i]["exits"] or 0) <= 1 for i in st)
        out.append(("mechanic «dead-end stack»: a stack item with one way out (or out by a rocket jump)", ok,
                    str([items[i]["exits"] for i in st])))
    refused = " ".join((asked.get("refused") or []) + list((asked.get("_plan") or {}).get("mech_missing") or []))

    def said_why(name):
        # D5: a mechanic the run could not build on this map, said with its reason in the record, is honest
        return name in refused
    ends = r.get("tele_ends") or []
    if "three_approaches" in mech:
        k = (idx.get("weapon_chaingun") or idx.get("weapon_railgun") or [None])[0]
        e = items[k]["exits"] if k is not None else None
        out.append(("mechanic «three approaches»: three ways to the key item", e is not None and e >= 3, str(e)))
        facing = [x for x in ends if x.get("faces")]
        out.append(("mechanic «three approaches»: a teleporter's exit within 400 u facing the key item",
                    bool(facing) or said_why("three_approaches"), f"{len(facing)} exits" if facing else "said why"
                    if said_why("three_approaches") else "none"))
    mv = r.get("movers") or {}
    if "tele_mirror" in mech:
        both = [x for x in ends if x.get("armour_s") is not None and x["armour_s"] <= 3.0
                and x.get("health_s") is not None and x["health_s"] <= 3.0]
        out.append(("mechanic «teleport to a mirrored stack»: armour and health within 3 s at both ends",
                    len(both) >= 2 or said_why("tele_mirror"), f"{len(both)} of {len(ends)} exits"))
    if "pad_pit" in mech:
        n = r.get("pads_over_deadly", 0)
        out.append(("mechanic «pad over a pit»: a pad's flight over a deadly chasm or lava", n >= 1 or said_why("pad_pit"),
                    str(n) if n or not said_why("pad_pit") else "said why"))
    if "lift_exposure" in mech:
        lo_ = r.get("majors_lift_only") or []
        out.append(("mechanic «lift as exposure»: a major item only a lift reaches", bool(lo_) or said_why("lift_exposure"),
                    ", ".join(lo_) or ("said why" if said_why("lift_exposure") else "none")))
    if "ladder_item" in mech:
        by = r.get("majors_by_ladder") or []
        out.append(("mechanic «ladder under a held item»: a major item on the ledge a ladder climbs to",
                    bool(by) or said_why("ladder_item"), ", ".join(by) or ("said why" if said_why("ladder_item") else "none")))
    ad = idx.get("item_adrenaline") or []
    if ad:
        # brief 19 §6 «adrenaline tucked»: the lowest level, 3 s or more from every major
        maj = [i for i, it in enumerate(items) if it["class"] not in ("item_adrenaline", "item_armor_jacket")]
        t_ad = min((x for x in (_t(r, ad[0], j) for j in maj) if x is not None), default=None)
        out.append(("mechanic «adrenaline tucked»: on the lowest level, 3 s or more from every major",
                    items[ad[0]]["height"] <= 32 and (t_ad is None or t_ad >= 3.0),
                    f"height {items[ad[0]]['height']}, nearest major {t_ad} s"))
    return out


def report(path: Path, players: int, asked: dict | None, plan: dict | None = None, doors: list | None = None,
           skeleton_map: Path | None = None) -> int:
    r = survey.survey(path, doors=doors)
    r["path"] = str(path)
    if skeleton_map and skeleton_map.is_file():
        # brief 34: the pads apart and like things together, measured on the map the skeleton wrote (the engine moves
        # none of them on a map from scratch) - the Studio's own check of a run lacked both rows on his tower (3.60)
        import mapgen_scratch_fixtures as fx_mod
        r["fx_measure"] = fx_mod.measure_map(skeleton_map.read_text(encoding="latin-1"))
    if (asked or {}).get("shape") in ("space", "tower"):
        # the space's islands and both shapes' pads' flights on the delivered map too - the Studio's own check of a run
        # said «space: its own measure - not measured» on the PO's first space map (3.52, 06.11)
        import mapgen_space_survey as space_survey
        r["space"] = space_survey.space_part(Path(path))
    res = judge(r, players, asked, plan)
    fails = 0
    for name, ok, said in res:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  -- {said}")
        fails += 0 if ok else 1
    return fails


def main() -> int:
    # the Studio reads this through the console's code page: a sign it cannot write must never stop the check (04.11:
    # «u²» killed it half way, the rest of the map's checks unasked)
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("map", nargs="?", type=Path)
    ap.add_argument("--players", type=int, default=2)
    ap.add_argument("--asked", type=Path, help="the run's request (JSON): what the parameters asked")
    ap.add_argument("--plan", type=Path, help="the run's skeleton.txt: the counts only the skeleton holds")
    ap.add_argument("--humans", action="store_true")
    ap.add_argument("--red", action="store_true")
    a = ap.parse_args()
    if a.humans:
        for cls, names in HUMANS.items():
            players = 2 if cls == "duel" else 8
            tally: dict[str, int] = {}
            for name in names:
                p = MAPS / f"{name}.bsp"
                if not p.is_file():
                    p = DONORS / f"{name}.bsp"
                if not p.is_file():
                    continue
                res = judge(survey.survey(p), players)
                bad = [n for n, ok, _ in res if not ok]
                print(f"{cls:5s} {name:10s} {len(res) - len(bad)}/{len(res)}  out: {', '.join(bad) or '-'}", flush=True)
                for n, ok, _ in res:
                    tally[n] = tally.get(n, 0) + (1 if ok else 0)
            print(f"{cls}: per band, maps inside: " + ", ".join(f"{k} {v}" for k, v in tally.items()), flush=True)
        return 0
    if a.red:
        path = a.map or RED
        print(f"RED: {path.name} must fail the bands brief 19 D7 names - size, levels, width, sight, exits")
        res = judge(survey.survey(path), 8, None)
        for name, ok_, said in res:
            print(f"  {'PASS' if ok_ else 'FAIL'}  {name}  -- {said}")
        failed = {n for n, ok_, s in res if not ok_ and s != "not measured"}
        groups = {"size": {"walk_area_mu2"}, "levels": {"levels"},
                  "width": {"width_median", "share_corridor", "share_medium", "share_open"},
                  "sight": {"visible_pairs", "visible_over_1000"}, "exits": {"exits_median", "dead_end_majors"}}
        missed = [g for g, keys in groups.items() if not (keys & failed)]
        ok = not missed
        print(f"{'PASS' if ok else 'FAIL'}: the box synthesis fails "
              + ("every named band" if ok else f"all but {', '.join(missed)}"))
        return 0 if ok else 1
    if not a.map:
        ap.print_help()
        return 2
    asked = json.loads(a.asked.read_text(encoding="utf-8")) if a.asked else None
    players = int((asked or {}).get("players", a.players))
    plan = None
    doors = None
    if a.plan and a.plan.is_file():
        for line in a.plan.read_text(encoding="utf-8").splitlines():
            if line.startswith("metrics "):
                plan = json.loads(line[8:])
        # brief 21 D2: the skeleton's doorways, for the dead-end measure on the map (the Studio's own check of a run)
        import mapgen_scratch as scratch_mod
        doors = scratch_mod.skeleton_doors(a.plan)
    print(f"a map from scratch, measured as people's maps were (brief 19 D7): {a.map.name}, {players} players")
    skel_map = None
    if a.plan:
        skel_map = a.plan.parent / f"{(asked or {}).get('name') or a.map.stem}.map"
    fails = report(a.map, players, asked, plan, doors, skel_map)
    # «SUMMARY», not a bare PASS/FAIL: the Studio reads every PASS/FAIL line as a check
    print(f"SUMMARY from scratch: {fails} failed")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
