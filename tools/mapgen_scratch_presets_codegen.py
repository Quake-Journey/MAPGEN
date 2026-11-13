r"""Brief 24 D5 (Fable 06.11, the PO: «нужно ещё раз в 10 больше примеров заводских пресетов по новым картам … только чётко
проверь»): the 160 factory presets of a map from scratch, written into the Studio from the ONE table that was checked.

The table is Fable's oracle `tools/fable_oracles/mapgen_2026-11-06_presets_x10.py` (each preset through `make_plan` on
12 seeds: 160 of 160 PASS). This script reads its `add(cat, key, P(players, ...))` lines (the literal arguments, so a
size or a corridor share is written as the form's own choice, not recomputed) and its evaluated requests, and writes:
  * `Presets.ScratchFactory()` in MapgenStudio/Presets.cs - one `Sp(p => {...})` per preset, between the markers;
  * the names and the tips in MapgenStudio/Loc.cs, both languages, between the markers (the 18 presets of 3.48 keep
    their own hand-written words; the 142 new get a tip made from their values, in the form's own words).
Proof that the Studio asks what the oracle checked: `MapgenStudio.exe --presets-dump DIR` then
`tools/check_mapgen_presets.py DIR` (160 of 160 PASS), and `--compare` here (each dumped request = the oracle's).

    python tools/mapgen_scratch_presets_codegen.py            # write the C# and the words
    python tools/mapgen_scratch_presets_codegen.py --compare DIR   # DIR from --presets-dump: every request as checked
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ORACLE = TOOLS / "fable_oracles" / "mapgen_2026-11-06_presets_x10.py"
SPACE = TOOLS / "mapgen_scratch_presets_space.py"         # brief 25 A4: «Открытый космос», checked by its own gate
TOWER = TOOLS / "mapgen_scratch_presets_tower.py"         # brief 25 B: «Башня», checked by its own gate
PIECES = TOOLS / "mapgen_scratch_presets_pieces.py"       # the PO 13.11: a hundred presets of the scripted pieces
ITEMS = TOOLS / "mapgen_scratch_presets_items.py"         # the PO 12.11: «Приёмы известных карт», «Призы и вода», and the old
                                                          # presets the new rows change (its UPDATES)
STUDIO = TOOLS / "mapgen_studio" / "MapgenStudio"
CAT_KEY = {"liquids": "waters"}          # the base form has its own «liquids»: the scratch one is «waters»
PCT = ("sky", "water", "lava", "slime", "items_at_height")
KEEP = {"default", "duel_vertical", "duel_sky_arena", "duel_corridors", "duel_powerups", "ffa_arena8", "ffa_maze6",
        "ffa_ring8", "ffa_big12", "tdm_4v4", "world_snow", "world_hell", "world_bunker", "world_city", "world_gothic",
        "world_planet", "world_desert", "world_fantasy"}

NAMES = {  # key: (ru, en) - the Russian ones are Fable's table, the PO reads them
    "players_3": ("По умолчанию на 3", "Default for 3"), "players_4": ("По умолчанию на 4", "Default for 4"),
    "players_6": ("По умолчанию на 6", "Default for 6"), "players_8": ("По умолчанию на 8", "Default for 8"),
    "players_10": ("По умолчанию на 10", "Default for 10"), "players_12": ("По умолчанию на 12", "Default for 12"),
    "players_16": ("По умолчанию на 16", "Default for 16"),
    "duel_tight": ("Тесная", "Tight"), "duel_big": ("Просторная дуэль", "Roomy duel"), "duel_flat": ("Плоская", "Flat"),
    "duel_highrise": ("Высотка", "High-rise"), "duel_ring": ("Кольцо", "Ring"), "duel_open": ("Открытая арена", "Open arena"),
    "duel_water": ("С водой", "With water"), "duel_lava": ("С лавой", "With lava"),
    "duel_ladders": ("С лестницами-стремянками", "With ladders"), "duel_teleports": ("С телепортами", "With teleporters"),
    "duel_windows": ("Много окон", "Many windows"), "duel_doors": ("Много дверей", "Many doors"),
    "duel_rail": ("Рельсовая", "Railgun duel"), "duel_close": ("Ближний бой", "Close quarters"),
    "duel_pads": ("С трамплинами", "With jump pads"), "duel_dark": ("Тёмная", "Dark"),
    "ffa3_arena": ("Арена на 3", "Arena for 3"), "ffa4_arena": ("Арена на 4", "Arena for 4"),
    "ffa4_halves": ("Две половины на 4", "Two halves for 4"), "ffa4_ring": ("Кольцо на 4", "Ring for 4"),
    "ffa4_vertical": ("Вертикаль на 4", "Vertical for 4"), "ffa4_corridors": ("Коридоры на 4", "Corridors for 4"),
    "ffa4_open": ("Открытая на 4", "Open for 4"), "ffa4_water": ("С водой на 4", "With water for 4"),
    "ffa4_pads": ("Трамплины на 4", "Jump pads for 4"), "ffa3_small": ("Малая на 3", "Small for 3"),
    "ffa4_big": ("Большая на 4", "Big for 4"), "ffa4_powerups": ("Паверапы на 4", "Powerups for 4"),
    "ffa6_arena": ("Арена на 6", "Arena for 6"), "ffa6_halves": ("Две половины на 6", "Two halves for 6"),
    "ffa6_vertical": ("Вертикаль на 6", "Vertical for 6"), "ffa8_flat": ("Плоская на 8", "Flat for 8"),
    "ffa8_corridors": ("Коридоры на 8", "Corridors for 8"), "ffa8_sky": ("Под открытым небом на 8", "Open sky for 8"),
    "ffa8_water": ("С водой на 8", "With water for 8"), "ffa8_lava": ("С лавой на 8", "With lava for 8"),
    "ffa8_pads": ("Трамплины на 8", "Jump pads for 8"), "ffa8_teleports": ("Телепорты на 8", "Teleporters for 8"),
    "ffa8_ladders": ("Стремянки на 8", "Ladders for 8"), "ffa8_big": ("Большая на 8", "Big for 8"),
    "ffa8_small": ("Малая на 8", "Small for 8"), "ffa6_rail": ("Рельсовая на 6", "Railgun for 6"),
    "ffa8_ring_big": ("Большое кольцо на 8", "Big ring for 8"),
    "ffa10_arena": ("Арена на 10", "Arena for 10"), "ffa10_ring": ("Кольцо на 10", "Ring for 10"),
    "ffa12_ring": ("Кольцо на 12", "Ring for 12"), "ffa12_corridors": ("Коридоры на 12", "Corridors for 12"),
    "ffa16_arena": ("Арена на 16", "Arena for 16"), "ffa16_huge": ("Огромная на 16", "Huge for 16"),
    "ffa16_vertical": ("Вертикаль на 16", "Vertical for 16"), "ffa16_pads": ("Трамплины на 16", "Jump pads for 16"),
    "ffa10_water": ("С водой на 10", "With water for 10"),
    "tdm_2v2": ("Команда на команду 2×2", "Team 2v2"), "tdm_3v3": ("Команда на команду 3×3", "Team 3v3"),
    "tdm_5v5": ("Команда на команду 5×5", "Team 5v5"), "tdm_6v6": ("Команда на команду 6×6", "Team 6v6"),
    "tdm_8v8": ("Команда на команду 8×8", "Team 8v8"), "tdm_4v4_ring": ("Кольцо 4×4", "Ring 4v4"),
    "tdm_4v4_vertical": ("Вертикаль 4×4", "Vertical 4v4"), "tdm_3v3_corridors": ("Коридоры 3×3", "Corridors 3v3"),
    "tdm_5v5_open": ("Открытая 5×5", "Open 5v5"),
    "world_tech": ("Техническая база", "Tech base"), "world_industrial": ("Завод", "Factory"),
    "world_forest": ("Лесная поляна", "Forest glade"), "world_city_duel": ("Городские крыши", "City rooftops"),
    "world_planet_duel": ("Чужая планета: дуэль", "Alien planet: duel"),
    "world_fantasy_duel": ("Фэнтези-башня", "Fantasy tower"), "world_hell_duel": ("Адская дуэль", "Hell duel"),
    "world_snow8": ("Снежная крепость на 8", "Snow fortress for 8"), "world_bunker8": ("Бункер на 8", "Bunker for 8"),
    "world_gothic8": ("Готический собор на 8", "Gothic cathedral for 8"),
    "world_desert8": ("Пустынный город на 8", "Desert town for 8"), "world_tech8": ("Техническая база на 8", "Tech base for 8"),
    "world_industrial8": ("Завод на 8", "Factory for 8"), "world_forest8": ("Лес на 8", "Forest for 8"),
    "world_hell8": ("Адская арена на 8", "Hell arena for 8"), "world_planet8": ("Чужая планета на 8", "Alien planet for 8"),
    "water_lake": ("Озеро", "Lake"), "water_canals": ("Каналы", "Canals"), "water_flood": ("Затопленная", "Flooded"),
    "lava_river": ("Лавовая река", "Lava river"), "lava_pits": ("Лава и пропасти", "Lava and chasms"),
    "slime_sewer": ("Канализация", "Sewer"), "slime_pits": ("Слизь и пропасти", "Slime and chasms"),
    "three_liquids": ("Три жидкости", "Three liquids"), "dry": ("Сухая", "Dry"), "chasms": ("Пропасти", "Chasms"),
    "lava_arena8": ("Лавовая арена на 8", "Lava arena for 8"), "water_ffa8": ("Водная на 8", "Watery for 8"),
    "rockets_only": ("Только ракеты", "Rockets only"), "rail_only": ("Только рельса", "Railgun only"),
    "shotguns": ("Дробовики", "Shotguns"), "chaingun_duel": ("Пулемётная", "Chaingun"), "grenades": ("Гранаты", "Grenades"),
    "hyper": ("Гипербластер", "Hyperblaster"), "every_weapon_twice": ("Каждое оружие дважды", "Every weapon twice"),
    "no_bfg_ffa8": ("Без BFG на 8", "No BFG for 8"), "quad_arena8": ("Квад-арена на 8", "Quad arena for 8"),
    "hard_powerups8": ("Трудные паверапы на 8", "Hard powerups for 8"), "invulnerability": ("Неуязвимость", "Invulnerability"),
    "armour_only": ("Только броня", "Armour only"), "rich": ("Богатая", "Rich"), "scarce": ("Скудная", "Scarce"),
    "items_high": ("Предметы наверху", "Items up high"), "items_low": ("Предметы внизу", "Items down low"),
    "lifts8": ("Лифты", "Lifts"), "pads6": ("Трамплины", "Jump pads"), "teleports4": ("Телепорты", "Teleporters"),
    "ladders4": ("Стремянки", "Ladders"), "drops12": ("Спуски", "Drops"), "stairs24": ("Лестницы", "Stairs"),
    "ramps12": ("Пандусы", "Ramps"), "doors8": ("Двери", "Doors"), "windows12": ("Окна", "Windows"),
    "no_lifts": ("Без лифтов", "No lifts"), "seven_levels": ("Семь уровней", "Seven levels"), "two_levels": ("Два уровня", "Two levels"),
    "mech_all": ("Все механики", "Every mechanic"), "mech_none": ("Без механик", "No mechanics"),
    "mech_classic": ("Классика: часы, половины, уступ", "Classic: clock, halves, ledge"),
    "mech_pressure": ("Давление: аптечки, спавны, подходы", "Pressure: health, spawns, approaches"),
    "mech_tricks": ("Трюки: телепорты, трамплины, лифты", "Tricks: teleporters, jump pads, lifts"),
    "mech_ffa_all": ("Все механики на 8", "Every mechanic for 8"),
    "decor_many": ("Много декора", "Many ornaments"), "round_many": ("Круглые формы", "Round shapes"),
    "round_apses": ("Апсиды", "Apses"), "round_podiums": ("Подиумы и углы", "Platforms and corners"),
    "sunlit": ("Солнечная", "Sunlit"), "cold_tech": ("Холодная техника", "Cold tech"),
    "rust_industrial": ("Ржавый завод", "Rusty factory"), "green_bunker": ("Зелёный бункер", "Green bunker"),
    "grey_gothic": ("Серая готика", "Grey gothic"), "clean_tech": ("Чистая техника", "Clean tech"),
    "large_blocks": ("Крупные блоки", "Large blocks"), "walls_only": ("Текстуры только на стенах", "Textures on the walls only"),
    # brief 25 A4: «Открытый космос»
    "space_duel": ("Космос: дуэль", "Space: duel"), "space_yard": ("Самый длинный двор", "The longest yard"),
    "space_arena8": ("Космическая арена на 8", "Space arena for 8"), "space_bridges": ("Мостики в пустоте", "Bridges in the void"),
    "space_rails": ("Космос с перилами", "Space with railings"), "space_low": ("Низкие острова", "Low islands"),
    "space_high": ("Высокие острова", "High islands"), "space_tele": ("Космос с телепортами", "Space with teleporters"),
    "space_small": ("Маленький космос", "Small space"), "space_quad_hunt": ("Охота за квадом", "Quad hunt"),
    "space_planet": ("Острова чужой планеты", "Alien islands"), "space_tech": ("Орбитальная станция", "Orbital station"),
    "space_industrial": ("Космический завод на 8", "Space factory for 8"),
    # brief 25 B: «Башня»
    "tower_duel": ("Башня: дуэль", "Tower: duel"), "tower_tight": ("Тесная башня", "A tight tower"),
    "tower_2": ("Башня в два этажа", "A two-storey tower"), "tower_3": ("Башня в три этажа", "A three-storey tower"),
    "tower_roomy": ("Просторная башня", "A roomy tower"), "tower_atrium": ("Атриум и три площадки", "An atrium and three ledges"),
    "tower_quad": ("Квад на верхушке", "The quad at the top"), "tower_tech": ("Техно-башня", "A tech tower"),
    "tower_8": ("Башня на 8 с тремя шахтами", "A tower for 8 with three shafts"),
    "tower_4": ("Четыре этажа на 8", "Four storeys for 8"), "tower_16": ("Высотка на 16", "A high-rise for 16"),
    # brief 34 (the PO 08.11: «лифты в башне - пример параметра … и пресеты под это делать новые заводские»)
    "tower_skyscraper": ("Небоскрёб: лифты и лестницы", "Skyscraper: lifts and stairs"),
    "tower_pads": ("Башня на джампадах", "A tower of jump pads"), "tower_stairs": ("Башня с лестницами", "A tower of stairs"),
}

THEME = {"tech": ("Техника", "Tech"), "gothic": ("Готика", "Gothic"), "industrial": ("Завод", "Factory"),
         "base": ("Бункер", "Bunker"), "snow": ("Снег и лёд", "Snow and ice"), "forest": ("Лес", "Forest"),
         "city": ("Город", "City"), "planet": ("Другая планета", "Another planet"), "fantasy": ("Фэнтези", "Fantasy"),
         "desert": ("Пустыня", "Desert"), "hell": ("Ад", "Hell")}
GEN = {"colour": {"warm": ("тёплый цвет", "warm colour"), "cold": ("холодный цвет", "cold colour"),
                  "green": ("зелёный цвет", "green colour"), "rust": ("ржавый цвет", "rust colour"),
                  "grey": ("серый цвет", "grey colour")},
       "wear": {"clean": ("чистые", "clean"), "worn": ("потёртые", "worn"), "dirty": ("грязные, с ржавчиной", "dirty and rusty")},
       "scale": {"small": ("мелкий рисунок", "a small pattern"), "large": ("крупный рисунок", "a large pattern"),
                 "medium": ("средний рисунок", "a medium pattern")},
       "relief": {"soft": ("мягкий рельеф", "soft relief"), "sharp": ("резкий рельеф", "sharp relief"),
                  "medium": ("средний рельеф", "medium relief")},
       "share": {"walls": ("только на стенах и полу", "on the walls and floors only"),
                 "detail": ("только на деталях", "on the detail only"), "all": ("на всём", "on everything")}}
WEAPON = {"shotgun": ("дробовик", "shotgun"), "supershotgun": ("двустволка", "super shotgun"),
          "machinegun": ("пулемёт", "machinegun"), "chaingun": ("чейнган", "chaingun"),
          "grenadelauncher": ("гранатомёт", "grenade launcher"), "rocketlauncher": ("ракетница", "rocket launcher"),
          "hyperblaster": ("гипербластер", "hyperblaster"), "railgun": ("рельса", "railgun"), "bfg": ("BFG", "BFG")}
STACK = {"ra_mh": ("красная броня и мега", "body armour and mega"),
         "ra_mh_quad": ("красная броня, мега и квад", "body armour, mega and quad"),
         "mh_adren_2ya": ("мега, адреналин и две жёлтые брони", "mega, adrenaline and two combat armours"),
         "2ya_adren_quad": ("две жёлтые брони, адреналин и квад", "two combat armours, adrenaline and quad")}
ITEM = {"item_armor_body": ("красная броня", "body armour"), "item_armor_combat": ("жёлтая броня", "combat armour"),
        "item_armor_jacket": ("зелёная броня", "jacket armour"), "item_health_mega": ("мега", "mega health"),
        "item_quad": ("квад", "quad"), "item_invulnerability": ("неуязвимость", "invulnerability"),
        "item_adrenaline": ("адреналин", "adrenaline"), "item_pack": ("рюкзак", "ammo pack")}
MECH = {"clock": ("стек на часах", "stack on a clock"), "halves": ("две половины", "two halves"),
        "key_gun_ledge": ("пушка на уступе", "gun on a ledge"), "asymmetry": ("асимметрия маршрута", "route asymmetry"),
        "small_health": ("много мелких аптечек", "many small health spots"), "spawn_pressure": ("давление на спавны", "spawn pressure"),
        "dead_end_stack": ("тупик со стеком", "dead-end stack"), "three_approaches": ("три подхода", "three approaches"),
        "tele_mirror": ("телепорт к зеркальному стеку", "teleport to a mirrored stack"),
        "pad_pit": ("джампад над пропастью", "jump pad over a chasm"), "lift_exposure": ("лифт как уязвимость", "lift as exposure"),
        "ladder_item": ("стремянка под предметом", "ladder under an item")}
ROUND_KIND = {"corners": ("скруглённые углы", "rounded corners"), "apses": ("полукруглые торцы залов", "half-round hall ends"),
              "podiums": ("круглые возвышения", "round raised platforms")}


def plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    w = one if n10 == 1 and n100 != 11 else few if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else many
    return f"{n} {w}"


COUNTS = {  # key: (ru one, few, many, ru «без …»; en one, many, en «no …»)
    "lifts": ("лифт", "лифта", "лифтов", "без лифтов", "lift", "lifts", "no lifts"),
    "pads": ("джампад", "джампада", "джампадов", "без джампадов", "jump pad", "jump pads", "no jump pads"),
    "teleporters": ("телепорт", "телепорта", "телепортов", "без телепортов", "teleporter", "teleporters", "no teleporters"),
    "ladders": ("стремянка", "стремянки", "стремянок", "без стремянок", "ladder", "ladders", "no ladders"),
    "drops": ("спуск вниз", "спуска вниз", "спусков вниз", "без спусков", "one-way drop", "one-way drops", "no drops"),
    "stairs": ("лестничный пролёт", "лестничных пролёта", "лестничных пролётов", "без лестниц", "flight of stairs",
               "flights of stairs", "no stairs"),
    "ramps": ("пандус", "пандуса", "пандусов", "без пандусов", "ramp", "ramps", "no ramps"),
    "doors": ("дверь", "двери", "дверей", "без дверей", "door", "doors", "no doors"),
    "windows": ("окно", "окна", "окон", "без окон", "window", "windows", "no windows"),
    "long_lines": ("длинная линия", "длинные линии", "длинных линий", "без длинных линий", "long sight line",
                   "long sight lines", "no long sight lines"),
    "pits": ("смертельная яма", "смертельные ямы", "смертельных ям", "без ям", "deadly pit", "deadly pits", "no pits"),
}
DEFAULT_SHARDS = {True: 6, False: 8}


def _items_module():
    spec = importlib.util.spec_from_file_location(ITEMS.stem, ITEMS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_oracle() -> list[tuple[str, str, int, dict, dict]]:
    """Every table's rows: Fable's 160, then the space's (brief 25 A4), the tower's (brief 25 B) and the items' (the PO
    12.11) - the old ones the items' table updates with the new rows' values («обновить существующие пресеты на новые
    параметры … на дефолты или нужные значения»: the rest keep «По умолчанию», a factory preset is a fresh form)."""
    rows = read_table(ORACLE) + read_table(SPACE) + read_table(TOWER) + read_table(ITEMS) + read_table(PIECES)
    upd = _items_module().UPDATES
    out = []
    for cat, key, players, lit, q in rows:
        if key in upd:
            lit = {**lit, **upd[key]}
            q = {**q, **upd[key]}
        out.append((cat, key, players, lit, q))
    return out


def read_table(path: Path) -> list[tuple[str, str, int, dict, dict]]:
    """(category, key, players, literal keyword arguments, the evaluated request) per `add` line, in its order."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    asked = {k: q for _, k, q in mod.PRESETS}
    out = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == "add"):
            continue
        call = node.value
        if not isinstance(call.args[1], ast.Constant):          # the «players_N» loop
            continue
        cat, key = call.args[0].value, call.args[1].value
        p = call.args[2]
        players = p.args[0].value
        lit = {}
        for kw in p.keywords:
            try:
                lit[kw.arg] = ast.literal_eval(kw.value)
            except ValueError:
                lit[kw.arg] = None                               # a call (G, weapons, list(...)): read from the request
        out.append((cat, key, players, lit, asked[key]))
    # the loop's lines: `for n in (3, 4, ...): add("basic", f"players_{n}", P(n))`
    have = {k for _, k, *_ in out}
    loop = [(c, k, q["players"], {}, q) for c, k, q in mod.PRESETS if k not in have]
    order = [k for _, k, _ in mod.PRESETS]
    rows = {r[1]: r for r in out + loop}
    return [rows[k] for k in order]


PIECE_WORDS = {  # the PO 13.11: the scripted pieces in the presets' tips
    "trains": ("ездящих платформ", "riding platforms"), "stones": ("рядов тонущих плит", "rows of sinking stones"),
    "traps": ("комнат-ловушек", "trap rooms"), "rotators": ("вращающихся", "rotating pieces"),
    "shutters": ("створок по таймеру", "timed shutters"), "pickup_walls": ("стен от предмета", "walls opened by an item"),
    "bent_bridges": ("изогнутых мостов", "bent bridges"), "wall_steps": ("ступеней по стене", "wall steps"),
    "lasers": ("лазерных заслонов", "laser gates"), "pistons": ("поршней в проходе", "piston passages"),
    "pendulums": ("маятников", "pendulums"), "trapdoors": ("проваливающихся полов", "trapdoors"),
    "geysers": ("лавовых гейзеров", "lava geysers"), "turn_bridges": ("поворотных мостов", "turning bridges"),
    "currents": ("мостов-течений", "current bridges"), "waves": ("волн столбов", "pillar waves"),
    "train_path": ("путь платформ", "the platforms' way"), "stone_shape": ("плиты", "the stones"),
    "trap_trigger": ("ловушку закрывает", "the trap shut by"), "trap_hazard": ("в ловушке", "in the trap"),
    "rotator_kind": ("вращается", "rotating"), "pool_ladders": ("лесенки из бассейнов", "ladders out of pools"),
    "piece_speed": ("скорость конструкций", "the pieces' speed"), "piece_wait": ("паузы конструкций", "the pieces' pauses"),
    # the PO 13.11 after the first try
    "drills": ("буровых установок", "drilling rigs"), "cogs": ("шестерён на стенах", "cogs on walls"),
    "turrets": ("турелей в проходах", "turret passages"), "conveyors": ("конвейеров с грузами", "conveyors with crates"),
    "pendulum_kind": ("маятник", "the pendulum"), "piece_motion": ("движение", "the motion"),
    "hammer_blast": ("удар маятника с ударной волной", "the pendulum's blow with a shock wave"),
}
PIECE_VALUES = {
    "across": ("поперёк ямы", "across a pit"), "loop": ("по кругу", "round it"), "island": ("к островку", "to an island"),
    "row": ("вплотную", "side by side"), "gaps": ("через одну", "every other one"), "zigzag": ("зигзагом", "zigzag"),
    "buttons": ("кнопки", "buttons"), "plate": ("плита в полу", "a plate"), "item": ("взятый предмет", "the item taken"),
    "lava": ("лава", "lava"), "slime": ("кислота", "slime"), "crusher": ("давящий потолок", "a crushing ceiling"),
    "drum": ("барабан над ямой", "a drum over a pit"), "flap": ("заслонка", "a flap"), "fan": ("вентилятор", "a fan"),
    "hammer": ("молот", "a hammer"), "sledge": ("двуглавая кувалда", "a two-headed sledge"),
    "spiked": ("молот с шипами", "a spiked hammer"), "axe": ("топор", "an axe"), "labrys": ("двойной топор", "a double axe"),
    "sickle": ("серп", "a sickle"), "mace": ("булава", "a mace"), "saw": ("дисковая пила", "a saw"), "anchor": ("якорь", "an anchor"),
    "even": ("ровное", "even"),
}


def cs_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def setters(players: int, lit: dict, q: dict) -> list[str]:
    s = []
    if players != 2:
        s.append(f"p.Players = {players};")
    for k in lit:
        v = q.get(k)
        if k == "size":
            s.append(f"p.SizePercent = {lit[k]};")
        elif k == "corr":
            s.append(f"p.CorridorPercent = {lit[k]};")
        elif k == "open_":
            s.append(f"p.OpenPercent = {lit[k]};")
        elif k in PCT:
            prop = {"sky": "SkyPercent", "water": "WaterPercent", "lava": "LavaPercent", "slime": "SlimePercent",
                    "items_at_height": "ItemsAtHeight"}[k]
            s.append(f"p.{prop} = {round(v * 100)};")
        elif k == "health_per_spawn":
            s.append(f"p.HealthPerSpawn10 = {round(v * 10)};")
        elif k == "ammo_per_spawn":
            s.append(f"p.AmmoPerSpawn10 = {round(v * 10)};")
        elif k == "water_above_floor":
            s.append("p.WaterAboveFloor = true;")
        elif k == "style":
            s.append('p.Style = "generated";')
            for gk, gv in v["gen"].items():
                prop = {"theme": "GenTheme", "colour": "GenColour", "wear": "GenWear", "scale": "GenScale",
                        "relief": "GenRelief", "share": "GenShare"}[gk]
                s.append(f"p.{prop} = {cs_value(gv)};")
        elif k == "weapons":
            s.append("p.Weapons = new() { " + ", ".join(f'["{w}"] = {n}' for w, n in v.items()) + " };")
        elif k == "stack" and isinstance(v, dict):
            s.append('p.Stack = "custom";')
            s.append("p.StackCounts = new() { " + ", ".join(f'["{i}"] = {n}' for i, n in v.items()) + " };")
        elif k == "mechanics":
            s.append("p.Mechanics = new() { " + ", ".join(cs_value(m) for m in v) + " };" if v else "p.Mechanics = new();")
        elif k == "round_kinds":
            s.append("p.RoundKinds = new() { " + ", ".join(cs_value(m) for m in v) + " };")
        else:
            prop = {"levels": "Levels", "vertical_span": "VerticalSpan", "lifts": "Lifts", "pads": "Pads",
                    "teleporters": "Teleporters", "ladders": "Ladders", "drops": "Drops", "stairs": "Stairs",
                    "ramps": "Ramps", "doors": "Doors", "windows": "Windows", "long_lines": "LongLines", "pits": "Pits",
                    "shards": "Shards", "shape": "Shape", "mode": "Mode", "stack": "Stack", "powerup_access": "PowerupAccess",
                    "sun": "Sun", "tone": "Tone", "decor": "Decor", "round": "Round", "islands": "Islands",
                    "pad_only": "PadOnly", "edges": "Edges", "height_spread": "HeightSpread", "pad_reach": "PadReach",
                    "bridges": "Bridges", "storeys": "Storeys", "storey_height": "StoreyHeight", "shafts": "Shafts",
                    "perches": "Perches", "ships": "Ships", "prize_access": "PrizeAccess", "underwater": "Underwater",
                    "item_spacing": "ItemSpacing", "item_practice": "ItemPractice", "water_body": "WaterBody",
                    "trains": "Trains", "stones": "Stones", "traps": "Traps", "rotators": "Rotators", "shutters": "Shutters", "pickup_walls": "PickupWalls", "bent_bridges": "BentBridges", "wall_steps": "WallSteps", "lasers": "Lasers", "pistons": "Pistons", "pendulums": "Pendulums", "trapdoors": "Trapdoors", "geysers": "Geysers", "turn_bridges": "TurnBridges", "currents": "Currents", "waves": "Waves", "train_path": "TrainPath", "stone_shape": "StoneShape", "trap_trigger": "TrapTrigger", "trap_hazard": "TrapHazard", "rotator_kind": "RotatorKind", "pool_ladders": "PoolLadders", "piece_speed": "PieceSpeed", "piece_wait": "PieceWait", "drills": "Drills", "cogs": "Cogs", "turrets": "Turrets", "conveyors": "Conveyors", "pendulum_kind": "PendulumKind", "piece_motion": "PieceMotion", "hammer_blast": "HammerBlast"}[k]
            s.append(f"p.{prop} = {cs_value(v)};")
    return s


def tip(players: int, lit: dict, q: dict, lang: int) -> str:
    """One sentence from the values: who plays, then each value asked, in the form's own words."""
    ru = lang == 0
    mode = q.get("mode", "")
    if not lit:
        return (f"Все параметры по умолчанию для {plural(players, 'игрока', 'игроков', 'игроков')}: генератор решает сам"
                if ru else f"Every parameter at its default for {players} players: the generator decides")
    lead = (("Команда на команду " + f"{players // 2}×{players // 2}") if ru else f"Team game {players // 2}v{players // 2}") \
        if mode == "tdm" else ("Дуэль" if ru else "Duel") if players <= 2 \
        else (f"Общий бой на {players}" if ru else f"Free-for-all for {players}")
    parts = []
    duel = players <= 2
    for k in lit:
        v = q.get(k)
        if k == "mode":
            continue
        if k == "style":
            g = v["gen"]
            words = [f"текстуры студии «{THEME[g['theme']][0]}»" if ru else f"the Studio's «{THEME[g['theme']][1]}» textures"]
            words += [GEN[gk][gv][lang] for gk, gv in g.items() if gk != "theme"]
            parts.append(", ".join(words))
        elif k == "size":
            parts.append(f"карта {lit[k]} % от обычной" if ru else f"the map {lit[k]} % of the usual size")
        elif k == "shape":
            parts.append({"halves": ("две половины", "two halves"), "arena": ("одна арена", "one arena"),
                          "ring": ("помещения по кругу", "rooms round a ring"),
                          "space": ("острова в открытом космосе", "islands in open space"),
                          "tower": ("башня из целых этажей", "a tower of whole storeys")}[v][lang])
        elif k == "ships":
            parts.append((plural(v, "корабль", "корабля", "кораблей") + " в небе") if ru else f"{v} ships in the sky")
        elif k == "storeys":
            parts.append(plural(v, "этаж", "этажа", "этажей") if ru else f"{v} storeys")
        elif k == "storey_height":
            parts.append(f"этажи через {v} единиц" if ru else f"storeys {v} units apart")
        elif k == "shafts":
            parts.append((plural(v, "шахта", "шахты", "шахт") + " с атриумом") if ru else f"{v} shafts with the atrium")
        elif k == "perches":
            parts.append(("без площадок наверху" if ru else "no ledges at the top") if v == 0 else
                         (plural(v, "площадка", "площадки", "площадок") + " наверху только по джампаду") if ru
                         else f"{v} ledges at the top only by a jump pad")
        elif k == "islands":
            parts.append(plural(v, "остров", "острова", "островов") if ru else f"{v} islands")
        elif k == "pad_only":
            parts.append((f"не меньше {v} только по джампаду" if ru else f"at least {v} only by a jump pad"))
        elif k == "edges":
            parts.append({"open": ("открытые края", "open edges"), "some": ("местами перила", "railings in places"),
                          "railings": ("края в перилах", "railed edges")}[v][lang])
        elif k == "height_spread":
            parts.append(f"разброс высот {v}" if ru else f"a height spread of {v}")
        elif k == "pad_reach":
            parts.append({"short": ("короткие джампады", "short pads"), "medium": ("средние джампады", "medium pads"),
                          "long": ("дальние джампады", "long pads")}[v][lang])
        elif k == "bridges":
            parts.append({"none": ("без мостиков", "no bridges"), "some": ("немного мостиков", "some bridges"),
                          "many": ("много мостиков", "many bridges")}[v][lang])
        elif k == "corr":
            parts.append(f"коридоров {lit[k]} %" if ru else f"{lit[k]} % corridors")
        elif k == "open_":
            parts.append(("без открытых мест" if ru else "no open places") if lit[k] == 0 else
                         (f"открытых мест {lit[k]} %" if ru else f"{lit[k]} % open places"))
        elif k == "levels":
            parts.append(plural(v, "уровень высоты", "уровня высоты", "уровней высоты") if ru else f"{v} levels")
        elif k == "vertical_span":
            parts.append(f"перепад высот {v} единиц" if ru else f"a height span of {v} units")
        elif k == "sky":
            pct = round(v * 100)
            parts.append(("без неба" if ru else "no sky") if pct == 0 else
                         (f"под небом {pct} % пола" if ru else f"{pct} % of the floor under the sky"))
        elif k == "sun":
            parts.append({"yes": ("солнце", "the sun"), "no": ("без солнца", "no sun")}[v][lang])
        elif k == "tone":
            parts.append({"warm": ("тёплый свет", "warm light"), "cold": ("холодный свет", "cold light")}[v][lang])
        elif k in COUNTS:
            c = COUNTS[k]
            parts.append((c[3] if ru else c[6]) if v == 0 else
                         plural(v, c[0], c[1], c[2]) if ru else f"{v} {c[4] if v == 1 else c[5]}")
        elif k in ("water", "lava", "slime"):
            pct = round(v * 100)
            noun = {"water": ("вода", "water"), "lava": ("лава", "lava"), "slime": ("кислота", "slime")}[k]
            parts.append((f"без {'воды' if k == 'water' else 'лавы' if k == 'lava' else 'кислоты'}" if ru else f"no {noun[1]}")
                         if pct == 0 else (f"{noun[0]} на {pct} % пола" if ru else f"{noun[1]} over {pct} % of the floor"))
        elif k == "water_above_floor":
            parts.append("вода может стоять выше пола" if ru else "water may stand above the floor")
        elif k == "weapons":
            have = {w.split("_", 1)[1]: n for w, n in v.items()}
            nz = {w: n for w, n in have.items() if n}
            if len(set(have.values())) == 1:
                parts.append(f"каждое оружие ×{next(iter(have.values()))}" if ru else f"every weapon ×{next(iter(have.values()))}")
            elif have.get("bfg") == 0 and set(n for w, n in have.items() if w != "bfg") == {1}:
                parts.append("всё оружие по одному, без BFG" if ru else "every weapon once, no BFG")
            else:
                parts.append(("оружие — " if ru else "weapons - ")
                             + ", ".join(f"{WEAPON[w][lang]} ×{n}" for w, n in nz.items())
                             + (", другого нет" if ru else ", nothing else"))
        elif k == "stack":
            if isinstance(v, dict):
                parts.append(("стек — " if ru else "stack - ")
                             + ", ".join(ITEM[i][lang] + (f" ×{n}" if n > 1 else "") for i, n in v.items()))
            else:
                parts.append(("стек — " if ru else "stack - ") + STACK[v][lang])
        elif k == "powerup_access":
            parts.append({"easy": ("паверапы на постаментах", "the powerups on pedestals"),
                          "medium": ("паверапы в нишах", "the powerups in nooks"),
                          "hard": ("паверапы за дверями с кнопками", "the powerups behind doors with buttons")}[v][lang])
        elif k == "prize_access":
            parts.append({"people": ("призы достаются как на известных картах", "the prizes earned as on well-known maps"),
                          "nooks": ("призы в нишах: запрыгнуть, дверь с кнопкой", "the prizes in nooks: jump in, a door with a button"),
                          "water": ("все призы под водой", "every prize under water"),
                          "exposed": ("призы на открытом месте под обстрелом", "the prizes in the open under fire")}[v][lang])
        elif k == "underwater":
            parts.append(plural(v, "приз под водой", "приза под водой", "призов под водой") if ru
                         else f"{v} prize{'s' if v > 1 else ''} under water")
        elif k in PIECE_WORDS:
            n_ = v
            ru_, en_ = PIECE_WORDS[k]
            if isinstance(v, bool):
                parts.append(ru_ if ru else en_)
            elif k in ("piece_speed", "piece_wait"):
                parts.append((f"{ru_} {v} %" if ru else f"{en_} {v} %"))
            elif isinstance(v, str):
                parts.append((ru_ if ru else en_) + " — " + PIECE_VALUES.get(v, (v, v))[0 if ru else 1] if ru
                             else en_ + " - " + PIECE_VALUES.get(v, (v, v))[1])
            else:
                parts.append(f"{ru_}: {n_}" if ru else f"{en_}: {n_}")
        elif k == "water_body":
            parts.append({"people": ("глубокие бассейны, как на известных картах", "deep pools, as on well-known maps"),
                          "levels": ("бассейны на разных уровнях с подводными трубами", "pools on several levels with tubes under water"),
                          "shallow": ("мелкие ямы с водой по пояс", "shallow pits, waist-deep")}[v][lang])
        elif k == "item_spacing":
            parts.append({"people": ("ценные предметы врозь, как на известных картах", "valuable items apart as well-known maps keep them"),
                          "wide": ("ценные предметы просторнее", "valuable items wider apart")}[v][lang])
        elif k == "item_practice":
            fam = {"mix": ("всех известных карт", "all well-known maps"), "q2dm": ("q2dm1–q2dm8", "q2dm1-q2dm8"),
                   "q2duel": ("q2duel1–q2duel8", "q2duel1-q2duel8"), "q2rdm": ("q2rdm1–q2rdm15", "q2rdm1-q2rdm15"),
                   "ztn2dm": ("ztn2dm1–ztn2dm5", "ztn2dm1-ztn2dm5")}
            names_ = [fam.get(f, (f, f))[lang] for f in v.split("+")]
            parts.append(("приёмы раскладки " if ru else "the item practice of ") + (" и " if ru else " and ").join(names_))
        elif k == "items_at_height":
            pct = round(v * 100)
            parts.append(("все предметы на полу" if ru else "every item on the floor") if pct == 0 else
                         ("все предметы наверху" if ru else "every item up high") if pct == 100 else
                         (f"{pct} % предметов наверху" if ru else f"{pct} % of the items up high"))
        elif k == "health_per_spawn":
            parts.append(("много аптечек" if ru else "much health") if v > 1.3 else ("мало аптечек" if ru else "little health"))
        elif k == "ammo_per_spawn":
            parts.append(("много патронов" if ru else "much ammo") if v > 2.5 else ("мало патронов" if ru else "little ammo"))
        elif k == "shards":
            parts.append(("без осколков брони" if ru else "no armour shards") if v == 0 else
                         ("много осколков брони" if ru else "many armour shards") if v > DEFAULT_SHARDS[duel] else
                         ("мало осколков брони" if ru else "few armour shards"))
        elif k == "mechanics":
            parts.append(("без обязательных механик" if ru else "no mechanics required") if not v else
                         ("все механики" if ru else "every mechanic") if len(v) == len(MECH) else
                         ("механики — " if ru else "mechanics - ") + ", ".join(MECH[m][lang] for m in v))
        elif k == "decor":
            parts.append({"few": ("немного украшений на стенах", "a few wall ornaments"),
                          "some": ("украшения на стенах", "some wall ornaments"),
                          "many": ("много украшений на стенах", "many wall ornaments")}[v][lang])
        elif k == "round":
            parts.append({"few": ("немного скруглений", "a few round shapes"), "some": ("скругления", "some round shapes"),
                          "many": ("много скруглений", "many round shapes")}[v][lang])
        elif k == "round_kinds":
            parts.append(("только " if ru else "only ") + (" и " if ru else " and ").join(ROUND_KIND[r][lang] for r in v))
        else:
            raise SystemExit(f"no words for «{k}» ({v})")
    return lead + ": " + ", ".join(parts)


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def replace_between(text: str, begin: str, end: str, body: str) -> str:
    a = text.index(begin) + len(begin)
    b = text.index(end, a)
    return text[:a] + body + text[b:]


def write() -> int:
    rows = read_oracle()
    assert len(rows) == 412, len(rows)       # brief 34: three of the tower; the PO 12.11: a hundred of the items; 13.11: a hundred of the pieces
    NAMES.update(_items_module().NAMES)
    spec = importlib.util.spec_from_file_location(PIECES.stem, PIECES)
    pmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pmod)
    NAMES.update(pmod.NAMES)
    missing = [k for _, k, *_ in rows if k not in KEEP and k not in NAMES]
    if missing:
        raise SystemExit(f"no names for {missing}")
    # Presets.cs: the factory list
    p = STUDIO / "Presets.cs"
    cs = p.read_text(encoding="utf-8")
    lines = ["\n"]
    for cat, key, players, lit, q in rows:
        body = " ".join(setters(players, lit, q))
        lines.append(f'        ("{key}", "{CAT_KEY.get(cat, cat)}", Sp(p => {{ {body} }})),\n' if body
                     else f'        ("{key}", "{CAT_KEY.get(cat, cat)}", Sp(_ => {{ }})),\n')
    begin = "    // <generated by tools/mapgen_scratch_presets_codegen.py - the table checked by Fable's oracle>"
    end = "    // </generated>"
    p.write_text(replace_between(cs, begin, end, "".join(lines) + "    "), encoding="utf-8", newline="\n")
    # Loc.cs: the names and tips of the new ones, each language its block
    lp = STUDIO / "Loc.cs"
    loc = lp.read_text(encoding="utf-8")
    for lang, tag in ((0, "ru"), (1, "en")):
        out = ["\n"]
        for cat, key, players, lit, q in rows:
            if key in KEEP:
                continue
            out.append(f'        ["preset.scratch.{key}"] = "{esc(NAMES[key][lang])}",\n')
            out.append(f'        ["preset.scratch.{key}.tip"] = "{esc(tip(players, lit, q, lang))}",\n')
        loc = replace_between(loc, f"        // <generated presets {tag}: tools/mapgen_scratch_presets_codegen.py>",
                              f"        // </generated presets {tag}>", "".join(out) + "        ")
    lp.write_text(loc, encoding="utf-8", newline="\n")
    print(f"written: {len(rows)} presets, {len(rows) - len(KEEP)} new names and tips in two languages")
    return 0


def compare(dump: Path) -> int:
    """Every request the Studio dumped = the request the oracle checked (the language aside)."""
    bad = []
    rows = read_oracle()
    for cat, key, players, lit, q in rows:
        f = dump / "scratch" / f"{key}.json"
        if not f.is_file():
            bad.append(f"{key}: not dumped")
            continue
        got = json.loads(f.read_text(encoding="utf-8"))
        got.pop("lang", None)
        want = dict(q)
        for k, v in (("lava", 0.0), ("slime", 0.0), ("pits", 0)):     # ToPython always writes these three
            want.setdefault(k, v)
        want.setdefault("style", {"source": "generator"})
        if got != want:                                          # by value: the Studio writes 0, Python 0.0
            bad.append(f"{key}: studio {json.dumps(got, sort_keys=True)}\n      oracle {json.dumps(want, sort_keys=True)}")
    extra = sorted({f.stem for f in (dump / "scratch").glob("*.json")} - {k for _, k, *_ in rows})
    if extra:
        bad.append(f"dumped but not in the oracle: {extra}")
    for b in bad:
        print("FAIL", b)
    print(f"{'PASS' if not bad else 'FAIL'} {len(rows) - len([b for b in bad if not b.startswith('dumped')])} of {len(rows)} "
          f"requests as the oracle checked them")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", type=Path)
    a = ap.parse_args()
    sys.exit(compare(a.compare) if a.compare else write())
