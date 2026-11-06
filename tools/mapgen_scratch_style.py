r"""Brief 19 D4: the style of a map made from scratch - which textures its walls, floors, ceilings, trims, lamps, sky
and liquids wear.

Three sources, one parameter («Текстуры»):
  * «как у карт людей» (the default, key "generator") - the dressing of one of people's maps the PO named (05.11:
    q2dm*, q2duel*, ztn2dm*, koldduel1, omf, ptrip, match1, kaktus), chosen by the run's number among the maps of the
    map's class: its wall, floor and ceiling textures by area, a different one for halls, rooms and corridors, its
    trim (the texture on its narrow faces), its lamps and the colour of its light (tools/mapgen_people_style.json).
    Until 3.41 this was the pack's own taste (`textures/mapgen`): grey photographs three to four times lighter than
    people's textures under white light - «монохромное», «глаза выбеливают» (the PO, 05.11);
  * «по картам ...» - the skins of the maps the PO names, by role: what their floors, walls, ceilings wear most, their
    lamp textures with the light they give, their sky. Only their SKINS: no brush of theirs is carried (D6);
  * «смешанно» - the maps' skins for the walls and floors, the pack's darkest coloured ones (its dk and soot
    variants as dark as people's textures) for ceilings and trims;
  * «сгенерированные студией» (3.45, the PO 05.11: «нужен подраздел генерации текстур карт с нуля самой студией …
    параметры для этого задай») - the Studio's own textures (tools/mapgen_texgen.py, the noise of Procedural-PBR, MIT):
    a theme, a colour, wear, the size of the detail, the relief; on everything, or only on the detail (the trims,
    posts, frames, treads - a people's map's walls and floors), or only on the walls and floors (its ceilings and
    trims).

A palette is a dict of role -> list of `Surf`: up to four walls (the spaces take them in turn), four floors (the halls
the first, the rooms the others in turn, the corridors the last), three ceilings by kind of space, the detail
(`trim`: skirting and cornice, posts and beams, doorway frames, step risers - the source map's trims and accents) and
the treads of the steps (brief 21 F1: 3.42 wore 4..8 textures, people's maps 9..38).
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from mapgen_scratch_build import Surf, S_LIGHT, S_SKY, S_NODRAW, S_WARP, S_TRANS33  # noqa: E402

CATALOGUE = TOOLS / "mapgen_textures_catalogue.json"

# the sky gives no light of its own: as a light (300, then 120) it burnt the strip of every court wall that meets it
# white (brief 20 D3, trials 04.11: 1.5..4 % of the walls' lightmap at 255, all of it touching the sky; with none -
# walls 0 %, floors 0 % at 255, median 67..76, people's 61..86). The sun and the lamps light the courts
SKY = Surf("e1u1/sky1", S_SKY | S_NODRAW, 0)
WATER = Surf("e2u3/bluwter", S_WARP | S_TRANS33, 0)
# q2dm3's own values (lava 700, slime 250) burnt the floor at a pool's rim white: our pools lie 32 under their
# rim, theirs far deeper (brief 20 D3, the styled duel 05.11: 6.4 % of the floor at 255, all by its lava)
LAVA = Surf("e1u1/brlava", S_LIGHT | S_WARP, 250)
SLIME = Surf("e2u3/sewer1", S_LIGHT | S_WARP, 120)
CLIP = Surf("e2u3/clip", S_NODRAW, 0)
TRIGGER = Surf("e2u3/trigger", S_NODRAW, 0)
# Quake II's own lamps for the pack style (the pack has no emitting textures)
LAMPS = [Surf("e1u1/ceil1_4", S_LIGHT, 600), Surf("e2u3/ceil1_14", S_LIGHT, 600), Surf("e1u2/ceil1_7", S_LIGHT, 600)]
SKY_ENVS = ["unit1_", "space1", "unit5_", "unit9_", "night1", "jal"]

# the pack's materials that read as walls, floors and trims, in pairs that sit together
WALL_FAMILIES = ["concrete", "stone", "brick", "panel", "metal", "rock", "wood"]
FLOOR_FOR = {"concrete": ["concrete", "gravel", "stone"], "stone": ["stone", "gravel", "ground"],
             "brick": ["stone", "concrete", "gravel"], "panel": ["metal", "panel", "concrete"],
             "metal": ["metal", "panel", "concrete"], "rock": ["ground", "gravel", "rock"],
             "wood": ["wood", "stone", "concrete"]}


def _catalogue():
    c = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    return [t for t in c["textures"] if t.get("status") == "accepted"]


def _pick(rnd, tex, material, kind=None, lum=(70, 180), coh=0.25, variant="base"):
    pool = [t for t in tex if t["material"] == material and t.get("variant") == variant
            and lum[0] <= t.get("lum", 0) <= lum[1] and t.get("coherence", 0) >= coh
            and (kind is None or t.get("kind") == kind)]
    if not pool:
        pool = [t for t in tex if t["material"] == material and t.get("variant") == variant]
    return rnd.choice(pool)["name"] if pool else None


def _pick_dark(rnd, tex, materials, lum=(28, 62), sat=0.18):
    """A pack texture as dark and as coloured as people's (their textures: lum 20..42, saturation 0.24..0.51)."""
    pool = [t for t in tex if t["material"] in materials and t.get("variant") in ("dk", "soot")
            and lum[0] <= t.get("lum", 0) <= lum[1] and _sat(t["rgb"]) >= sat]
    return rnd.choice(pool)["name"] if pool else None


def _sat(rgb) -> float:
    mx = max(rgb)
    return 0.0 if mx <= 0 else (mx - min(rgb)) / mx


def palette_pack_dark(seed: int) -> dict:
    """The pack's ceilings and trims for «смешанно», dark and coloured like people's textures."""
    rnd = random.Random(seed * 7919 + 13)
    tex = _catalogue()
    ceils = [Surf(_pick_dark(rnd, tex, ("stone", "concrete", "rock", "brick", "metal")) or "mapgen/metal05_dk", scale=0.5)
             for _ in range(3)]
    trim = Surf(_pick_dark(rnd, tex, ("metal", "panel")) or "mapgen/metal05_dk", scale=0.5)
    return {"ceil": ceils, "trim": [trim]}


def people_class(players) -> str:
    return "duel" if int(players or 2) <= 2 else "ffa"


def light_tint(rgb) -> tuple:
    """A people's map's light colour (its lightmap's mean) as a light's _color, a third of the way back to white:
    the lamps' own textures and the coloured walls tint the bounce on top of it."""
    mx = max(rgb) or 1.0
    return tuple(round(0.3 + 0.7 * c / mx, 2) for c in rgb)


MAIN_SHARE = 0.08      # a texture dresses a whole kind of space only with this share of its role on the source map
ACCENT_SHARE = 0.015   # ... and an accent of theirs (under MAIN_SHARE) goes on the detail: pilasters, frames, beams


def _interleave(lists: list, n: int) -> list:
    out = []
    for k in range(max((len(x) for x in lists), default=0)):
        for x in lists:
            if k < len(x) and x[k] not in out:
                out.append(x[k])
    return out[:n]


def dress_lists(measures: list) -> dict:
    """Brief 21 F1 (Fable's review of 3.42): the look took one wall, one floor and one ceiling texture per kind of
    space and one trim - 4..8 textures on a map, people's maps hold 9..38. From people's measured maps
    (`mapgen_people_style.measure`: textures by role with their shares, and the textures on narrow faces): up to four
    wall textures each holding MAIN_SHARE of their role (the spaces take them in turn), three floors and three
    ceilings the same way, and the detail - their trims and accents (ACCENT_SHARE..MAIN_SHARE of the walls) - for the
    skirting, the pilasters and beams, the doorway frames. Two maps share every role in turn."""
    def main(m, role, n):
        rr = (m.get("roles") or {}).get(role) or {}
        tx, sh = rr.get("textures") or [], rr.get("shares") or []
        got = [t for t, s_ in zip(tx, sh) if s_ >= MAIN_SHARE][:n]
        # a map whose walls spread over many textures (ztn2dm1: none over 7 %) still gives three: one wall on every
        # space put 45 % of the surface on one texture (a trial 05.11). Floors and ceilings keep their own - a floor
        # accent of 5 % on every room's floor made it 42 % of q2duel2's look
        for t, s_ in zip(tx, sh):
            if role != "wall" or len(got) >= min(n, 3):
                break
            if t not in got and s_ >= 0.03:
                got.append(t)
        return got or tx[:1]
    walls = _interleave([main(m, "wall", 4) for m in measures], 4)
    floors = _interleave([main(m, "floor", 4) for m in measures], 4)
    ceils = _interleave([main(m, "ceil", 3) for m in measures], 3)
    used = set(walls) | set(floors) | set(ceils)
    detail_src = []
    for m in measures:
        rr = (m.get("roles") or {}).get("wall") or {}
        acc = [t for t, s_ in zip(rr.get("textures") or [], rr.get("shares") or []) if ACCENT_SHARE <= s_ < MAIN_SHARE]
        # a trim that is the halls' own wall would vanish into it: the detail is what stands out of the wall - their
        # textures not on a whole space yet first (kaktus's trims were its walls and floors: 7 textures on a trial)
        cand = [t for t in list(m.get("trims") or []) + acc if t and t not in walls[:1]]
        detail_src.append([t for t in cand if t not in used] + [t for t in cand if t in used])
    detail = _interleave(detail_src, 4)
    if not detail:
        detail = (walls[1:2] or walls[:1])
    # the treads of the steps: a floor accent of theirs (a stair texture, a grating - q2duel4's stairs1_1, q2duel3's
    # floor2_1), else their second floor
    treads = []
    for m in measures:
        rr = (m.get("roles") or {}).get("floor") or {}
        treads.append([t for t, s_ in zip(rr.get("textures") or [], rr.get("shares") or [])
                       if ACCENT_SHARE <= s_ < MAIN_SHARE and t not in floors])
    tread = _interleave(treads, 2) or floors[1:2]

    def weights(role, chosen):
        # each chosen texture's share of its role on the source maps (the mean over the maps): the builder gives the
        # spaces their texture so the areas follow these shares (05.11: ztn2dm2's 12 % grey floor put on every room
        # and corridor made the map 31 % coloured, ztn2dm2's own 50 % and more)
        out = []
        for t in chosen:
            v = 0.0
            for m in measures:
                rr = (m.get("roles") or {}).get(role) or {}
                for t_, s_ in zip(rr.get("textures") or [], rr.get("shares") or []):
                    if t_ == t:
                        v += s_
            out.append(max(0.02, v / max(1, len(measures))))
        return out
    return {"wall": walls, "floor": floors, "ceil": ceils, "detail": detail, "tread": tread,
            "wall_w": weights("wall", walls), "floor_w": weights("floor", floors)}


def resolve_map(entry: str, game=None):
    """A style's map as the Studio hands it: a path to a .bsp, or a name - looked for in the game's maps, the engine's
    donors and the game's paks (brief 21+, the PO 05.11: «карты нужно давать выбирать любые, хоть одну хоть
    множество»). Returns (path, temporary?) or (None, False)."""
    import mapgen_people_style as people
    p = Path(entry)
    if p.suffix.lower() == ".bsp" and p.is_file():
        return p, False
    g = people.Game(Path(game)) if game else people.Game()
    found = people.find_map(p.stem if p.suffix else entry, g)
    if found is None:
        return None, False
    return found, "mapgen_people_" in Path(found).name


def palette_people(seed: int, players=2, game=None, maps=None) -> dict:
    """The generator's taste, learned from people's maps (the PO, 05.11: «я тебе ставил четкую задачу - использовать
    опыт людей при генерации новых карт, это касалось и стиля оформления»): one of their maps, by the run's number,
    gives its textures by role and by area, its trim, its lamps, its sky and the colour of its light. `maps` - the maps
    the user ticked (any, one or several; brief 21+): one of them by the run's number, measured here when the
    reference table does not hold it; none ticked - the PO's 26 of the reference table, of the map's class."""
    import mapgen_people_style as people
    ref = json.loads(people.OUT.read_text(encoding="utf-8"))
    if maps:
        rnd = random.Random(seed * 2654435761 % (1 << 32) + 5)
        entry = rnd.choice(list(maps))
        path, temp = resolve_map(entry, game)
        if path is None:
            raise SystemExit(f"style map not found: {entry}")
        try:
            name = Path(path).stem.replace("mapgen_people_", "")
            r = ref["maps"].get(name) or people.measure(Path(path), people.Colours(people.Game(Path(game)) if game else people.Game()))
            pal = palette_from_maps([path], seed)
        finally:
            if temp:
                Path(path).unlink(missing_ok=True)
        return _people_palette(pal, r, name)
    cls = people_class(players)
    names, seen = [], set()
    for n in sorted(ref["maps"]):
        r = ref["maps"][n]
        # one map under two names counts once (q2duel8 is ztn2dm3: the same light, the same textures)
        twin = (tuple(r.get("light_rgb") or ()), tuple((r.get("roles") or {}).get("wall", {}).get("textures") or ()))
        # ... and not the greyest of them: ztn2dm2 is 50 % coloured, on the band's edge - dressed from it a map came
        # out 43 % (05.11, brief 21)
        if r.get("class") == cls and r.get("known", 0) >= 0.9 and twin not in seen and r.get("coloured", 1) >= 0.55:
            seen.add(twin)
            names.append(n)
    rnd = random.Random(seed * 2654435761 % (1 << 32) + 5)
    name = rnd.choice(names)
    r = ref["maps"][name]
    g = people.Game(Path(game)) if game else people.Game()
    path = people.find_map(name, g)
    try:
        pal = palette_from_maps([path], seed) if path else palette_from_maps([], seed)
    finally:
        if path and "mapgen_people_" in Path(path).name:
            Path(path).unlink(missing_ok=True)
    return _people_palette(pal, r, name)


def _people_palette(pal: dict, r: dict, name: str) -> dict:
    # a texture on a whole kind of space only if they gave it a real part of that role (8 %): an accent of theirs
    # (q2duel7's hazard stripes, 3 % of its floors) stays an accent - on a pilaster or a frame, never a whole floor
    dl = dress_lists([r])
    pal.update({
        "source": "people", "maps": [name],
        "wall": [Surf(t) for t in dl["wall"]] or pal["wall"],
        "floor": [Surf(t) for t in dl["floor"]] or pal["floor"],
        "ceil": [Surf(t) for t in dl["ceil"]] or pal["ceil"],
        "trim": [Surf(t) for t in dl["detail"]] or pal["trim"],
        "tread": [Surf(t) for t in dl["tread"]],
        "wall_w": dl["wall_w"], "floor_w": dl["floor_w"],
        "tone": "people", "light_colour": light_tint(r["light_rgb"]),
        # their light compile's calibration was fitted to THEIR lights (q2dm8: scale 3.1), not to our lamps. Our lamps
        # were set for the pack's light textures, whose bounce lit the floors; under people's dark textures the floor
        # fell to a median 35..45 (people's 55..120). Trials 05.11 on three duel skeletons: x1.6 gave 57..91, x2 71..114;
        # x1.8 sits mid-band. -maxlight 196 is id's own ceiling (the q2dm1 fit found it): no floor burnt white
        "rad_flags": "-scale 1.8 -maxlight 196",
        # a court under the sky keeps a low sun, tinted as their light (their maps have no sun keys of ours)
        "sun": True,
    })
    return pal


def palette_generator(seed: int) -> dict:
    """The pack's own taste (until 3.41 the default): a wall family, a floor family that goes with it, darker variants
    for trims. Kept for the tests that need the pack in a map; no parameter of the Studio chooses it any more."""
    rnd = random.Random(seed * 7919 + 11)
    tex = _catalogue()
    fam = rnd.choice(WALL_FAMILIES)
    walls, floors, ceils = [], [], []
    for k in range(3):
        w = _pick(rnd, tex, fam if k < 2 else rnd.choice(WALL_FAMILIES))
        f = _pick(rnd, tex, rnd.choice(FLOOR_FOR[fam]))
        walls.append(Surf(w or "mapgen/concrete04", scale=0.5))
        floors.append(Surf(f or "mapgen/stone05", scale=0.5))
        ceils.append(Surf(_pick(rnd, tex, fam, variant="dk") or walls[-1].tex, scale=0.5))
    trim = Surf(_pick(rnd, tex, "metal", coh=0.5) or "mapgen/metal02", scale=0.5)
    return {"source": "generator", "family": fam, "wall": walls, "floor": floors, "ceil": ceils, "trim": [trim],
            "lamp": [rnd.choice(LAMPS)], "sky": [SKY], "sky_env": rnd.choice(SKY_ENVS),
            "water": [WATER], "lava": [LAVA], "slime": [SLIME]}


def palette_from_maps(paths: list, seed: int) -> dict:
    """The skins of existing maps by role, read from their compiled brushes (D4 (a)); no geometry of theirs."""
    import mapgen_bsp_oracle as oracle
    rnd = random.Random(seed * 104729 + 3)
    roles = {"floor": {}, "wall": {}, "ceil": {}, "lamp": {}, "sky": {}}
    sky_env = None
    sun_keys, ambience, rad_flags = {}, [], ""
    for p in paths:
        b = oracle.load(Path(p))
        ws = b.entities()[0] if b.entities() else {}
        sky_env = sky_env or ws.get("sky")
        # the light of the source maps (D4): their sun, their looped ambience, their light calibration if fitted
        if not sun_keys:
            sun_keys = {k: v for k, v in ws.items() if k.startswith("_sun") and k != "_sun"}
        for e in b.entities()[1:]:
            if e.get("classname") == "target_speaker" and int(e.get("spawnflags", "0") or 0) & 1 and e.get("noise"):
                if e["noise"] not in ambience:
                    ambience.append(e["noise"])
        lt = Path(p).with_suffix(".light.txt")
        if not rad_flags and lt.is_file():
            rad_flags = lt.read_text(encoding="utf-8").strip()
        for br in b.brushes:
            if not (br.contents & 1):
                continue
            for s in range(br.firstside, br.firstside + br.numsides):
                side = b.brushsides[s]
                t = b.texinfo[side.texinfo]
                pl = b.planes[side.planenum]
                if t.flags & S_SKY:
                    roles["sky"][(t.texture, t.flags, t.value)] = roles["sky"].get((t.texture, t.flags, t.value), 0) + 1
                    continue
                if t.flags & S_NODRAW:
                    continue
                if t.flags & S_LIGHT:
                    key = (t.texture, t.flags, t.value)
                    roles["lamp"][key] = roles["lamp"].get(key, 0) + 1
                    continue
                nz = -pl.normal[2] if side.planenum & 1 else pl.normal[2]
                r = "floor" if nz > 0.7 else "ceil" if nz < -0.7 else "wall"
                roles[r][t.texture] = roles[r].get(t.texture, 0) + 1

    def top(d, n):
        return [k for k, _ in sorted(d.items(), key=lambda kv: -kv[1])[:n]]
    walls = [Surf(t) for t in top(roles["wall"], 4)] or [Surf("e1u1/metal3_1")]
    floors = [Surf(t) for t in top(roles["floor"], 4)] or [Surf("e1u1/floor1_3")]
    ceils = [Surf(t) for t in top(roles["ceil"], 3)] or walls[:1]
    # our lamp panels are 32 u - a source map's 10000 on one burnt the walls round it (05.11): the generator's value
    lamps = [Surf(t, f, LAMPS[0].value) for (t, f, v) in top(roles["lamp"], 3)] or LAMPS[:1]
    # the source map's sky texture, with no light of its own as ours (brief 20 D3: q2dm1's sky at 300..500 burnt the
    # strip of every court wall meeting it, 1.2 % on the styled duel 05.11) - the sun and the lamps light the courts
    skies = [Surf(t, S_SKY | S_NODRAW, 0) for (t, f, v) in top(roles["sky"], 1)] or [SKY]
    rnd.shuffle(walls)
    # the colour of their light (brief 20 follow-up, 05.11): the mean of their lightmaps, as the lamps' colour
    tint = None
    trims = walls[3:4] or walls[:1]
    treads = []
    shares = {}
    walls, floors, ceils = walls[:3], floors[:3], ceils[:3]
    try:
        import mapgen_people_style as people
        game = people.Game()
        cols = people.Colours(game)
        ms = [people.measure(Path(p), cols) for p in paths]
        rgbs = [m_["light_rgb"] for m_ in ms]
        if rgbs:
            tint = light_tint([sum(c[j] for c in rgbs) / len(rgbs) for j in range(3)])
        # brief 21 F1: their textures by area, each role from both maps in turn, their trims and accents on the
        # detail (3.42's styled duel on q2dm1 + ztn2dm3 wore 4 textures - the face counts' top three per role)
        if ms:
            dl = dress_lists(ms)
            walls = [Surf(t) for t in dl["wall"]] or walls
            floors = [Surf(t) for t in dl["floor"]] or floors
            ceils = [Surf(t) for t in dl["ceil"]] or ceils
            trims = [Surf(t) for t in dl["detail"]] or trims
            treads = [Surf(t) for t in dl["tread"]]
            shares = {"wall_w": dl["wall_w"], "floor_w": dl["floor_w"]}
    except Exception:  # noqa: BLE001 - without the measure the lamps stay white and the face counts dress, as before
        tint = None
    return {"source": "maps", "maps": [Path(p).stem.replace("mapgen_people_", "") for p in paths], "wall": walls, "floor": floors,
            "ceil": ceils, "trim": trims, "tread": treads, **shares, "lamp": lamps, "sky": skies,
            "sky_env": sky_env or "unit1_", "water": [WATER], "lava": [LAVA], "slime": [SLIME],
            "sun": bool(sun_keys.get("_sun_angle") or sun_keys.get("_sun_light")), "sun_keys": sun_keys,
            "ambience": ambience, "rad_flags": rad_flags, "tone": "people" if tint else "neutral",
            "light_colour": tint}


# the generated set's light: its colour as the lamps' tint (people's light is tinted - brief 20 follow-up)
GEN_LIGHT = {"warm": (1.0, 0.86, 0.66), "rust": (1.0, 0.78, 0.6), "cold": (0.72, 0.84, 1.0),
             "green": (0.8, 1.0, 0.78), "grey": (1.0, 0.95, 0.88)}


def palette_generated(style: dict, seed: int, players=2, game=None) -> dict:
    """The Studio's own textures (3.45): the set made (once per its parameters and the run's number) into the game's
    textures/mapgen_gen/<set>/, by role. `gen.share`: «all» - every surface; «detail» - a people's map's walls,
    floors and ceilings, the set on the trims, posts, frames and treads; «walls» - the set on the walls and floors,
    the people's map's ceilings and trims."""
    import mapgen_texgen as tg
    import mapgen_people_style as people
    gen = dict((style or {}).get("gen") or {})
    share = gen.get("share") if gen.get("share") in ("all", "detail", "walls") else "all"
    set_seed = int(gen.get("seed") or seed)
    g = Path(game) if game else people.Game().base
    _key, roles = tg.install_set(g, gen, set_seed)
    own = {r: [Surf(t) for t in roles.get(r, [])] for r in ("wall", "floor", "ceil", "detail", "tread")}
    colour = gen.get("colour") if gen.get("colour") in GEN_LIGHT else None
    theme = tg.theme_of(gen, set_seed)
    if colour is None and theme in tg.THEME_LIGHT:
        light = tg.THEME_LIGHT[theme]                  # a world of its own: its own light (3.46)
    else:
        if colour is None:
            # «auto»: the colour the set took (tg.base_colour picks it by the set's number)
            colour = ["warm", "cold", "green", "rust", "warm", "grey"][int(tg._rng(set_seed, "auto").integers(0, 6))]
        light = GEN_LIGHT[colour]
    if share == "all":
        rnd = random.Random(seed * 7919 + 17)
        pal = {"source": "generated", "maps": [], "wall": own["wall"], "floor": own["floor"], "ceil": own["ceil"],
               "trim": own["detail"], "tread": own["tread"], "lamp": [rnd.choice(LAMPS)], "sky": [SKY],
               "sky_env": rnd.choice(SKY_ENVS), "water": [WATER], "lava": [LAVA], "slime": [SLIME],
               "sun": True, "sun_keys": {}, "ambience": [], "tone": "people", "light_colour": light,
               # dark as people's textures (brightness 20..52), a little lighter than theirs on the mean (38): x1.8, as
               # under theirs (3.42), lit the floor at a median 137 (people's 55..120, the tech duel 05.11) - x1.4
               # a snow world's textures are two times as light (lum 56..107): its light the lower
               "rad_flags": "-scale 1.0 -maxlight 196" if theme == "snow" else "-scale 1.4 -maxlight 196"}
        return pal
    pal = palette_people(seed, players, game, maps=(style or {}).get("maps") or None)
    if share == "detail":
        pal.update({"trim": own["detail"], "tread": own["tread"]})
    else:
        pal.update({"wall": own["wall"], "floor": own["floor"], "wall_w": None, "floor_w": None})
    pal["source"] = f"generated+{pal.get('source', 'people')}"
    return pal


# brief 26: the fixtures' light on a map not styled by the Studio's own set - a cold white-blue, q2_q3dm17's
FX_NEUTRAL = (0.72, 0.84, 1.0)


def palette(style: dict, seed: int, players=2, game=None) -> dict:
    """The style's surfaces by role; with `fx`, the jump pads' and teleporters' own textures (brief 26) in the light's
    colour of a generated set, else in FX_NEUTRAL - made into the game's textures/mapgen_gen once per colour."""
    pal = _palette(style, seed, players, game)
    try:
        import mapgen_texgen as tg
        import mapgen_people_style as people
        rgb = tuple(pal.get("light_colour") or FX_NEUTRAL) if str(pal.get("source", "")).startswith("generated") \
            else FX_NEUTRAL
        base = Path(game) if game else people.Game().base
        pal["fx"] = tg.install_fixtures(base, rgb)
    except (OSError, SystemExit) as e:          # no game palette to write a .wal by: the old plates, said
        pal["fx"] = None
        pal["fx_why"] = str(e)
    return pal


def _palette(style: dict, seed: int, players=2, game=None) -> dict:
    src = (style or {}).get("source", "generator")
    if src == "generated":
        return palette_generated(style, seed, players, game)
    if src in ("maps", "mixed") and style.get("maps"):
        # any map, by path or by name (the game's maps, the donors, the paks)
        paths, temps = [], []
        for entry in style["maps"]:
            p, t = resolve_map(entry, game)
            if p is not None:
                paths.append(p)
                if t:
                    temps.append(p)
        try:
            pal = palette_from_maps(paths, seed)
        finally:
            for p in temps:
                Path(p).unlink(missing_ok=True)
        if src == "mixed":
            # (c) mixed: the maps' skins for walls and floors, the pack's dark coloured ones for ceilings and trims
            pal.update(palette_pack_dark(seed))
            pal["source"] = "mixed"
        return pal
    if src == "pack":
        pal = palette_generator(seed)
        pal.update({"sun": True, "tone": "neutral", "ambience": [], "rad_flags": "", "sun_keys": {}})
        return pal
    return palette_people(seed, players, game, maps=(style or {}).get("maps") or None)


def describe(pal: dict) -> str:
    return (f"{pal['source']} " + (f"({', '.join(pal.get('maps', []))}) " if pal.get("maps") else "")
            + f"walls {', '.join(s.tex for s in pal['wall'])}; floors {', '.join(s.tex for s in pal['floor'])}; "
            f"ceilings {', '.join(s.tex for s in pal['ceil'])}; lamps {', '.join(s.tex for s in pal['lamp'])}; "
            f"sky {pal['sky_env']}"
            + (f"; sun {pal['sun_keys']}" if pal.get("sun_keys") else "")
            + (f"; light {pal['rad_flags']}" if pal.get("rad_flags") else "")
            + (f"; ambience {', '.join(pal['ambience'])}" if pal.get("ambience") else ""))
