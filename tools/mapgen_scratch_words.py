"""The words of a map from scratch's description (RU / EN) - the Studio's own (`Loc.cs`: the form's names of the modes,
the shapes, the themes, the items and the weapons), so the description says what the form said.

The PO, 07.11 («в русском описании … есть анг формулировки в студии»): the record wrote the request's keys as values -
«8 игроков, FFA, generated», «Форма: space → space», «Украшений на стенах: none», «Мостики: some», «Дальность
джампадов: medium», «ARMOR_BODY: 1 → 1», the failed rows by their English names. `mapgen_scratch.write_record` says
them here; `tools/mapgen_redescribe.py` rewrites the descriptions written before.
"""
from __future__ import annotations

MODES = {"duel": ("дуэль", "duel"), "ffa": ("общий бой", "free for all"), "tdm": ("команда на команду", "team against team")}
SHAPES = {"halves": ("две половины", "two halves"), "arena": ("одна арена", "one arena"), "ring": ("кольцо", "a ring"),
          "space": ("открытый космос", "open space"), "tower": ("башня", "a tower")}
THEMES = {"tech": ("Техника", "Tech"), "gothic": ("Готика", "Gothic"), "industrial": ("Завод", "Factory"),
          "base": ("Бункер", "Bunker"), "snow": ("Снег и лёд", "Snow and ice"), "forest": ("Лес", "Forest"),
          "city": ("Город", "City"), "planet": ("Другая планета", "Another planet"), "fantasy": ("Фэнтези", "Fantasy"),
          "desert": ("Пустыня", "Desert"), "hell": ("Ад", "Hell")}
AMOUNTS = {"none": ("нет", "none"), "few": ("мало", "few"), "some": ("немного", "some"), "many": ("много", "many"),
           "": ("нет", "none"), "default": ("по умолчанию", "by default")}
# where a powerup was put (mapgen_scratch_plan.powerup_sites: «easy», «medium», «medium (jump in)», «easy (no nook)» …)
SITES = {"easy": ("на постаменте", "on a pedestal"), "medium": ("в нише", "in a nook"),
         "hard": ("за дверью с кнопкой", "behind a door with a button"), "cycle": ("по очереди в нише", "in turns in a nook"),
         "medium (jump in)": ("в нише, приподнятой над полом (запрыгнуть)", "in a nook raised over the floor (jump in)"),
         "hard (jump in)": ("за дверью с кнопкой, приподнятой над полом", "behind a door with a button, raised over the floor"),
         "easy (no nook)": ("на постаменте (ниша не поместилась)", "on a pedestal (no nook fitted)")}
REACH = {"short": ("короткие", "short"), "medium": ("средние", "medium"), "long": ("длинные", "long")}
# 3.58 addendum (the English description carried these in Russian): how the powerups were asked to lie, by the form's
# words; the powerups by their short names in the row «Главные предметы»; the round shapes asked; an open space's edges
ACCESS = {"easy": ("просто", "in the open"), "medium": ("в нишах", "in nooks"),
          "hard": ("за дверями с кнопками", "behind doors with buttons"), "mixed": ("смешанно", "mixed")}
CYCLE = (", по очереди в одной нише", ", in turns in one nook")
POWERUP_SHORT = {"item_health_mega": ("мега", "mega"), "item_armor_body": ("красная броня", "body armour"),
                 "item_quad": ("квад", "quad"), "item_invulnerability": ("неуязвимость", "invulnerability"),
                 "item_power_shield": ("силовой щит", "power shield")}
ROUND = {"few": ("немного", "a few"), "some": ("заметно", "noticeably"), "many": ("много", "many")}
NONE = ("нет", "none")
EDGES = {"open": ("открытые", "open"), "some": ("местами перила", "railings in places"),
         "railings": ("в основном перила", "mostly railings")}
ITEMS = {"item_armor_body": ("Красная броня", "Body armour"), "item_armor_combat": ("Жёлтая броня", "Combat armour"),
         "item_armor_jacket": ("Зелёная броня", "Jacket armour"), "item_health_mega": ("Мега", "Mega health"),
         "item_quad": ("Квад", "Quad damage"), "item_invulnerability": ("Неуязвимость", "Invulnerability"),
         "item_adrenaline": ("Адреналин", "Adrenaline"), "item_pack": ("Рюкзак", "Ammo pack"),
         "weapon_shotgun": ("Дробовик", "Shotgun"), "weapon_supershotgun": ("Двустволка", "Super shotgun"),
         "weapon_machinegun": ("Пулемёт", "Machinegun"), "weapon_chaingun": ("Чейнган", "Chaingun"),
         "weapon_grenadelauncher": ("Гранатомёт", "Grenade launcher"), "weapon_rocketlauncher": ("Ракетница", "Rocket launcher"),
         "weapon_hyperblaster": ("Гипербластер", "Hyperblaster"), "weapon_railgun": ("Рельса", "Railgun"),
         "weapon_bfg": ("BFG", "BFG")}
SOURCES = {"people": ("отделка как у известной карты", "dressed as the well-known map"),
           "maps": ("отделка по выбранным картам", "dressed as the chosen maps"),
           "mixed": ("отделка смешанная", "mixed dressing"),
           "generator": ("отделка генератора", "the generator's dressing"),
           "pack": ("отделка набором генератора", "the generator's pack"),
           "generated": ("свои текстуры студии", "the Studio's own textures")}

# the rows of the rooms' plan an open space has no part in (mapgen_scratch_space.SPACE_FORCED): not in its description
SPACE_SKIP = {"stairs", "ramps", "lifts", "pads", "ladders", "drops", "doors", "windows", "round", "rooms_over",
              "corridor_turns", "water", "lava", "slime", "pits", "decor", "openness", "long_lines", "stacked"}
# a tower's (mapgen_scratch_tower.tower_defaults): its walls may be decorated, its storeys stand over each other
TOWER_SKIP = {"stairs", "ramps", "lifts", "pads", "ladders", "drops", "doors", "windows", "round", "rooms_over",
              "corridor_turns", "water", "lava", "slime", "pits"}


def pick(table: dict, key, ru: bool, fallback=None):
    v = table.get(key)
    if v is None:
        return key if fallback is None else fallback
    return v[0 if ru else 1]


def players(n: int, ru: bool) -> str:
    """«2 игрока», «5 игроков», «21 игрок» - the Russian plural."""
    if not ru:
        return f"{n} player" + ("" if n == 1 else "s")
    tail = n % 100
    if 11 <= tail <= 14:
        word = "игроков"
    elif n % 10 == 1:
        word = "игрок"
    elif 2 <= n % 10 <= 4:
        word = "игрока"
    else:
        word = "игроков"
    return f"{n} {word}"


# 3.58 (the PO 07.11 on the guide: «карты людей» reads as our own jargon): the maps the generator is measured against
# are «известные карты» / «well-known maps» in everything a player reads; the record said «как у людей» in both languages
KNOWN = ("как у известных карт", "as well-known maps")


def known(band: str) -> tuple[str, str]:
    """A band of the well-known maps as a row's asked value, in both languages («как у известных карт 50..100%»)."""
    return (f"{KNOWN[0]} {band}", f"{KNOWN[1]} {band}")


def value(key: str, v, ru: bool):
    """A request's value in words where it is a key of the form; else as it is."""
    if isinstance(v, tuple) and len(v) == 2:
        return v[0 if ru else 1]          # said in both languages (known())
    if not isinstance(v, str):
        return v
    if key == "shape":
        return pick(SHAPES, v, ru)
    if key == "mode":
        return pick(MODES, v, ru)
    if key in ("decor", "bridges"):
        return pick(AMOUNTS, v, ru)
    if key == "pad_reach":
        return pick(REACH, v, ru)
    return v


def access(key, cycle: bool) -> tuple[str, str]:
    """«Главные предметы» asked: «в нишах, по очереди в одной нише» / «in nooks, in turns in one nook»."""
    a = ACCESS.get(key, (str(key), str(key)))
    return (a[0] + (CYCLE[0] if cycle else ""), a[1] + (CYCLE[1] if cycle else ""))


def powerup_sites(sites) -> tuple[str, str]:
    """«Главные предметы» made: «мега — в нише, красная броня — на постаменте» in both languages."""
    def one(cls, kind, ru):
        short = POWERUP_SHORT.get(cls)
        # a prize that is not a powerup (the railgun in a nook, 3.66) by its name, not its class (his mg_new_56432 of
        # 12.11: «weapon railgun — в нише»)
        name = short[0 if ru else 1] if short else item(cls, ru).lower()
        return f"{name} — {pick(SITES, kind, ru)}"
    return tuple(", ".join(one(c, k, ru) for c, k in sites) for ru in (True, False))


def round_made(rm: dict) -> tuple[str, str] | str:
    """«Скругления» made: «углов 2, полукруглых торцов 1, возвышений 0» / «rounded corners 2, round ends 1, podiums 0»."""
    if not rm:
        return "-"
    c, a, p = rm.get("corners", 0), rm.get("apses", 0), rm.get("podiums", 0)
    return (f"углов {c}, полукруглых торцов {a}, возвышений {p}", f"rounded corners {c}, round ends {a}, podiums {p}")


# brief 32 (the PO 08.11): the sizes of the pads, the teleporters' frames and the spawns' plates - the record's rows when
# one was asked (the request's key, mapgen_scratch_fixtures.SIZE_KEYS' name, the row in both languages)
SIZE_ROWS = (("pad_disc_size", "disc", "Размер круглых джампадов", "Round jump pads' size"),
             ("pad_wedge_size", "wedge", "Размер наклонных джампадов", "Slanted jump pads' size"),
             ("tele_frame_size", "tele", "Размер рам телепортов", "Teleporter frames' size"),
             ("spawn_plate_size", "spawn", "Площадки под точками появления", "Plates under the spawn points"))


def size_asked(what: str, pct) -> tuple[str, str]:
    """A size asked in words: «150 %»; a spawn plate not asked «нет» / «none»."""
    return NONE if what == "spawn" and not pct else (f"{pct} %", f"{pct} %")


def size_made(built: list) -> tuple[str, str]:
    """Brief 32: how many came out at which size, the biggest first: «2 по 150 %, 1 по 100 %» / «2 at 150 %, 1 at
    100 %»; a spawn with no plate «без площадки — 1» / «no plate - 1»; none of them on the map «таких нет» / «none»."""
    if not built:
        return ("таких нет", "none on the map")
    counts = {}
    for v in built:
        counts[v] = counts.get(v, 0) + 1
    ru, en = [], []
    for v in sorted(counts, reverse=True):
        n = counts[v]
        if v:
            ru.append(f"{n} по {v} %")
            en.append(f"{n} at {v} %")
        else:
            ru.append(f"без площадки — {n}")
            en.append(f"no plate - {n}")
    return (", ".join(ru), ", ".join(en))


def ways_asked(q: dict) -> tuple[str, str]:
    """Brief 34: a tower's ways asked - stairs (-1: one a storey), lifts, pads."""
    st = q.get("stairs")
    st_ru = "по лестнице на этаж" if st is None or int(st) < 0 else f"лестниц {int(st)}"
    st_en = "a flight a storey" if st is None or int(st) < 0 else f"{int(st)} flights"
    return (f"{st_ru}, лифтов {int(q.get('lifts') or 0)}, джампадов {int(q.get('pads') or 0)}",
            f"{st_en}, {int(q.get('lifts') or 0)} lifts, {int(q.get('pads') or 0)} pads")


def ways_made(w: dict) -> tuple[str, str]:
    """Brief 34: the ways made - «лестниц 2, лифтов 1, джампадов 1 (+3 на площадки)»."""
    tail_ru = f" (+{w['perch_pads']} на площадки)" if w.get("perch_pads") else ""
    tail_en = f" (+{w['perch_pads']} to the ledges)" if w.get("perch_pads") else ""
    return (f"лестниц {w.get('stairs', 0)}, лифтов {w.get('lifts', 0)}, джампадов {w.get('pads', 0)}{tail_ru}",
            f"{w.get('stairs', 0)} flights, {w.get('lifts', 0)} lifts, {w.get('pads', 0)} pads{tail_en}")


def item(cls: str, ru: bool) -> str:
    return pick(ITEMS, cls, ru, cls.replace("item_", "").replace("weapon_", "").upper())


# the PO 12.11: the water as well-known maps build it (mapgen_scratch_plan: deep pools, tubes under water)
WATER_BODIES = {"people": ("глубокие, как на известных картах", "deep, as on well-known maps"),
                "levels": ("на разных уровнях, с трубами", "several levels, with tubes"),
                "shallow": ("мелкие ямы по пояс", "shallow pits, waist-deep")}


def water_body(key) -> tuple[str, str]:
    return WATER_BODIES.get(key or "people", WATER_BODIES["people"])


def water_made(pools: list, tubes: list, prize_tubes: list) -> tuple[str, str]:
    """«бассейнов 2 (25 и 16 клеток по 64, глубина 224), подводных труб 2 (512, 448 ед.)»."""
    if not pools:
        return NONE
    sizes_ru = " и ".join(str(p[0]) for p in pools)
    sizes_en = " and ".join(str(p[0]) for p in pools)
    deep = sorted({int(p[1]) for p in pools})
    ln = [int(n) * 64 for n in tubes] + [int(n) * 64 for _c, n in prize_tubes]
    ru = f"бассейнов {len(pools)} ({sizes_ru} клеток по 64, глубина {', '.join(map(str, deep))})"
    en = f"{len(pools)} pools ({sizes_en} cells of 64, {', '.join(map(str, deep))} deep)"
    heights = sorted({int(p[2]) for p in pools})
    if len(heights) > 1:
        ru += f" на {len(heights)} высотах"
        en += f" on {len(heights)} heights"
    if ln:
        ru += f", подводных труб {len(ln)} ({', '.join(map(str, ln))} ед.)"
        en += f", {len(ln)} tubes under water ({', '.join(map(str, ln))} u)"
    return ru, en


def under_made(kinds: list, prize_tubes: list) -> tuple[str, str]:
    """«1: рельса — в комнате за подводной трубой 512 ед.»; a prize at a pool's bottom «на дне бассейна»."""
    tube = {c: int(n) * 64 for c, n in prize_tubes}
    wet = [c for c, k in kinds if k == "water"]
    if not wet:
        return "0", "0"
    ru = ", ".join(f"{item(c, True).lower()} — " + (f"в комнате за подводной трубой {tube[c]} ед." if c in tube else "на дне бассейна")
                   for c in wet)
    en = ", ".join(f"{item(c, False).lower()} - " + (f"in a room past a tube under water {tube[c]} u" if c in tube else "at a pool's bottom")
                   for c in wet)
    return f"{len(wet)}: {ru}", f"{len(wet)}: {en}"


def source(src: str | None, theme: str | None, maps: list, ru: bool) -> str:
    words = pick(SOURCES, src, ru, src or "")
    if src == "generated" and theme:
        words += ": " + pick(THEMES, theme, ru, theme)
    if maps:
        words += " " + ", ".join(maps)
    return words


# the record's labels (mapgen_scratch.write_record) of the rows the words above say, and of the rows an open space skips -
# for tools/mapgen_redescribe.py, which rewrites the descriptions written before 3.57
LABELS = {"shape": ("Форма", "Shape"), "mode": ("Режим", "Mode"), "decor": ("Украшений на стенах", "Wall decorations"),
          "bridges": ("Мостики", "Bridges"), "pad_reach": ("Дальность джампадов", "Jump pads' reach"),
          "stairs": ("Лестниц (пролётов)", "Flights of steps"), "ramps": ("Пандусов", "Ramps"), "lifts": ("Лифтов", "Lifts"),
          "pads": ("Джампадов", "Jump pads"), "ladders": ("Лестниц-стремянок", "Ladders"),
          "drops": ("Спусков (в одну сторону)", "One-way drops"), "doors": ("Дверей", "Doors"), "windows": ("Окон", "Windows"),
          "round": ("Скругления", "Round shapes"), "rooms_over": ("Комнат над комнатами", "Rooms over rooms"),
          "corridor_turns": ("Коридоров с поворотом", "Corridors with a turn"), "water": ("Вода", "Water"),
          "lava": ("Лава", "Lava"), "slime": ("Кислота", "Slime"), "pits": ("Смертельных ям", "Deadly pits"),
          "openness": ("Коридоры / залы / открытые", "Corridors / halls / open"),
          "long_lines": ("Длинных линий прострела", "Long sight lines"), "stacked": ("Пол над полом", "Floor over floor")}
