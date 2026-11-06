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
ITEMS = {"item_armor_body": ("Красная броня", "Body armour"), "item_armor_combat": ("Жёлтая броня", "Combat armour"),
         "item_armor_jacket": ("Зелёная броня", "Jacket armour"), "item_health_mega": ("Мега", "Mega health"),
         "item_quad": ("Квад", "Quad damage"), "item_invulnerability": ("Неуязвимость", "Invulnerability"),
         "item_adrenaline": ("Адреналин", "Adrenaline"), "item_pack": ("Рюкзак", "Ammo pack"),
         "weapon_shotgun": ("Дробовик", "Shotgun"), "weapon_supershotgun": ("Двустволка", "Super shotgun"),
         "weapon_machinegun": ("Пулемёт", "Machinegun"), "weapon_chaingun": ("Чейнган", "Chaingun"),
         "weapon_grenadelauncher": ("Гранатомёт", "Grenade launcher"), "weapon_rocketlauncher": ("Ракетница", "Rocket launcher"),
         "weapon_hyperblaster": ("Гипербластер", "Hyperblaster"), "weapon_railgun": ("Рельса", "Railgun"),
         "weapon_bfg": ("BFG", "BFG")}
SOURCES = {"people": ("отделка как у карты людей", "dressed as people's map"),
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


def value(key: str, v, ru: bool):
    """A request's value in words where it is a key of the form; else as it is."""
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


def item(cls: str, ru: bool) -> str:
    return pick(ITEMS, cls, ru, cls.replace("item_", "").replace("weapon_", "").upper())


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
