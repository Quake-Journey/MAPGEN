"""A hundred presets of the scripted pieces (the PO 13.11: «мне нужны доп 100 новых пресетов которые настраивают вариации
подобного. Именно вариации, а не 100% повторение кусков этих блоков»). Four categories of 25: the pieces that move, the
traps, the architecture, and all together - each mixing the pieces with the form's other rows (players, liquids,
levels, sky, shape, speeds and pauses), none a copy of a map. The codegen (tools/mapgen_scratch_presets_codegen.py)
writes them into the Studio with the other tables.

    python tools/mapgen_scratch_presets_pieces.py            # each makes skeletons on 12 seeds, its pieces built
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
_spec = importlib.util.spec_from_file_location("presets_x10", Path(__file__).resolve().parent / "fable_oracles" / "mapgen_2026-11-06_presets_x10.py")
_ox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ox)
P = _ox.P

PRESETS: list = []


def add(cat: str, key: str, q: dict) -> None:
    PRESETS.append((cat, key, q))


# ---- «Конструкции: движение» ----------------------------------------------------------------------------------------
add("pieces_motion", "pc_duel_trains", P(2, trains=1, lava=10))
add("pieces_motion", "pc_duel_island", P(2, trains=1, train_path="island", lava=10))
add("pieces_motion", "pc_ffa4_trains2", P(4, trains=2, lava=10, slime=5))
add("pieces_motion", "pc_ffa6_loops", P(6, trains=2, train_path="loop", slime=10))
add("pieces_motion", "pc_ffa8_trains3", P(8, trains=3, lava=10, slime=5))
add("pieces_motion", "pc_duel_stones", P(2, stones=1, lava=10))
add("pieces_motion", "pc_duel_stones_gaps", P(2, stones=1, stone_shape="gaps", lava=10))
add("pieces_motion", "pc_ffa4_stones_zz", P(4, stones=2, stone_shape="zigzag", slime=10))
add("pieces_motion", "pc_ffa6_stones_fast", P(6, stones=2, lava=10, piece_wait=50))
add("pieces_motion", "pc_duel_waves", P(2, waves=1, lava=10))
add("pieces_motion", "pc_ffa6_waves2", P(6, waves=2, lava=10))
add("pieces_motion", "pc_duel_current", P(2, currents=1, lava=10))
add("pieces_motion", "pc_ffa4_currents", P(4, currents=2, slime=10))
add("pieces_motion", "pc_ffa4_turnbridge", P(4, turn_bridges=1, lava=10))
add("pieces_motion", "pc_ffa8_turnbridges", P(8, turn_bridges=1, lava=15))
add("pieces_motion", "pc_duel_drum", P(2, rotators=1, rotator_kind="drum", lava=10))
add("pieces_motion", "pc_ffa6_drums", P(6, rotators=2, rotator_kind="drum", lava=10))
add("pieces_motion", "pc_duel_ride_stones", P(2, trains=1, stones=1, lava=10))
add("pieces_motion", "pc_ffa4_ride_wave", P(4, trains=1, waves=1, lava=10, slime=5))
add("pieces_motion", "pc_ffa6_slow", P(6, trains=2, stones=1, lava=10, piece_speed=50, piece_wait=200))
add("pieces_motion", "pc_ffa8_fast", P(8, trains=2, waves=1, currents=1, lava=10, piece_speed=200, piece_wait=50))
add("pieces_motion", "pc_ffa4_levels", P(4, trains=1, stones=1, levels=4, lava=10))
add("pieces_motion", "pc_ffa6_sky", P(6, trains=2, waves=1, sky=70, lava=10))
add("pieces_motion", "pc_tdm_motion", P(8, mode="tdm", trains=2, stones=1, lava=10))
add("pieces_motion", "pc_ffa10_motion", P(10, trains=2, stones=2, waves=1, lava=10, slime=5))

# ---- «Конструкции: ловушки» -----------------------------------------------------------------------------------------
add("pieces_traps", "pc_duel_trap", P(2, traps=1))
add("pieces_traps", "pc_duel_trap_lava", P(2, traps=1, trap_trigger="buttons", trap_hazard="lava"))
add("pieces_traps", "pc_ffa4_trap_slime", P(4, traps=1, trap_trigger="plate", trap_hazard="slime"))
add("pieces_traps", "pc_ffa6_trap_crush", P(6, traps=1, trap_trigger="item", trap_hazard="crusher"))
add("pieces_traps", "pc_ffa8_traps2", P(8, traps=2))
add("pieces_traps", "pc_duel_trapdoor", P(2, trapdoors=1, lava=10))
add("pieces_traps", "pc_ffa6_trapdoors", P(6, trapdoors=2, lava=10))
add("pieces_traps", "pc_duel_lasers", P(2, lasers=1))
add("pieces_traps", "pc_ffa4_lasers2", P(4, lasers=2))
add("pieces_traps", "pc_ffa6_lasers_fast", P(6, lasers=2, piece_wait=50))
add("pieces_traps", "pc_duel_pistons", P(2, pistons=1))
add("pieces_traps", "pc_ffa4_pistons", P(4, pistons=2, piece_speed=150))
add("pieces_traps", "pc_duel_geyser", P(2, geysers=1))
add("pieces_traps", "pc_ffa6_geysers", P(6, geysers=3))
add("pieces_traps", "pc_ffa4_pendulum", P(4, pendulums=1, bent_bridges=1, lava=10))
add("pieces_traps", "pc_ffa8_pendulums", P(8, pendulums=2, lava=10))
add("pieces_traps", "pc_duel_trap_lasers", P(2, traps=1, lasers=1))
add("pieces_traps", "pc_ffa4_trap_geyser", P(4, traps=1, geysers=2, trap_hazard="lava"))
add("pieces_traps", "pc_ffa6_lasers_pistons", P(6, lasers=1, pistons=1))
add("pieces_traps", "pc_ffa6_trapdoor_pend", P(6, trapdoors=1, pendulums=1, lava=10))
add("pieces_traps", "pc_ffa8_all_traps", P(8, traps=1, trapdoors=1, lasers=1, geysers=1, lava=10))
add("pieces_traps", "pc_tdm_traps", P(8, mode="tdm", traps=2, lasers=1))
add("pieces_traps", "pc_ffa10_traps", P(10, traps=2, geysers=2, lasers=1))
add("pieces_traps", "pc_ffa4_slow_traps", P(4, traps=1, lasers=1, piece_wait=200))
add("pieces_traps", "pc_ffa6_quick_traps", P(6, traps=1, pistons=2, piece_speed=200, piece_wait=50))

# ---- «Конструкции: архитектура» -------------------------------------------------------------------------------------
add("pieces_arch", "pc_duel_bent", P(2, bent_bridges=1, lava=10))
add("pieces_arch", "pc_ffa6_bent2", P(6, bent_bridges=2, lava=10, slime=5))
add("pieces_arch", "pc_duel_steps", P(2, wall_steps=1))
add("pieces_arch", "pc_ffa6_steps", P(6, wall_steps=2))
add("pieces_arch", "pc_duel_ladders", P(2, pool_ladders=True, water=15))
add("pieces_arch", "pc_ffa6_ladders", P(6, pool_ladders=True, water=20, water_body="levels"))
add("pieces_arch", "pc_duel_shutters", P(2, shutters=1))
add("pieces_arch", "pc_ffa4_shutters", P(4, shutters=2))
add("pieces_arch", "pc_duel_pickup_wall", P(2, pickup_walls=1))
add("pieces_arch", "pc_ffa6_pickup_walls", P(6, pickup_walls=2))
add("pieces_arch", "pc_duel_flaps", P(2, rotators=1, rotator_kind="flap"))
add("pieces_arch", "pc_ffa6_flaps", P(6, rotators=2, rotator_kind="flap"))
add("pieces_arch", "pc_duel_fans", P(2, rotators=1, rotator_kind="fan"))
add("pieces_arch", "pc_ffa4_fans", P(4, rotators=2, rotator_kind="fan"))
add("pieces_arch", "pc_duel_bent_steps", P(2, bent_bridges=1, wall_steps=1, lava=10))
add("pieces_arch", "pc_ffa4_shutter_wall", P(4, shutters=1, pickup_walls=1))
add("pieces_arch", "pc_ffa6_pool_steps", P(6, pool_ladders=True, wall_steps=1, water=15))
add("pieces_arch", "pc_ffa8_architecture", P(8, bent_bridges=1, wall_steps=2, shutters=1, pickup_walls=1, lava=10))
add("pieces_arch", "pc_duel_halves_arch", P(2, shape="halves", shutters=1, wall_steps=1))
add("pieces_arch", "pc_ffa6_ring_arch", P(6, shape="ring", bent_bridges=1, pickup_walls=1, lava=10))
add("pieces_arch", "pc_ffa4_vertical_arch", P(4, levels=4, wall_steps=2, rotators=1, rotator_kind="flap"))
add("pieces_arch", "pc_ffa6_sky_arch", P(6, sky=70, bent_bridges=1, shutters=1, lava=10))
add("pieces_arch", "pc_tdm_arch", P(8, mode="tdm", shutters=2, wall_steps=1))
add("pieces_arch", "pc_ffa10_arch", P(10, bent_bridges=2, wall_steps=2, pickup_walls=2, lava=10))
add("pieces_arch", "pc_ffa4_water_arch", P(4, pool_ladders=True, water=20, underwater=1, shutters=1))

# ---- «Конструкции: всё вместе» --------------------------------------------------------------------------------------
add("pieces_mix", "pc_duel_showcase", P(2, trains=1, traps=1, geysers=1, lava=10))
add("pieces_mix", "pc_duel_q2dm3_like", P(2, trains=1, traps=1, slime=10, lava=5))
add("pieces_mix", "pc_duel_q2dm6_like", P(2, stones=1, shutters=1, pickup_walls=1, rotators=1, rotator_kind="drum", lava=10))
add("pieces_mix", "pc_duel_q2dm4_like", P(2, bent_bridges=1, pool_ladders=True, rotators=1, rotator_kind="flap", water=15, lava=5))
add("pieces_mix", "pc_ffa4_showcase", P(4, trains=1, traps=1, lasers=1, geysers=1, lava=10))
add("pieces_mix", "pc_ffa4_lava_world", P(4, trains=1, stones=1, waves=1, trapdoors=1, lava=15))
add("pieces_mix", "pc_ffa4_slime_world", P(4, trains=1, currents=1, traps=1, trap_hazard="slime", slime=15))
add("pieces_mix", "pc_ffa6_showcase", P(6, trains=1, traps=1, lasers=1, geysers=1, lava=10))
add("pieces_mix", "pc_ffa6_machines", P(6, rotators=2, lasers=1, shutters=1))
add("pieces_mix", "pc_ffa6_crossings", P(6, trains=1, stones=1, turn_bridges=1, currents=1, lava=15))
add("pieces_mix", "pc_ffa6_danger", P(6, traps=1, trapdoors=1, geysers=2, lava=10))
add("pieces_mix", "pc_ffa8_showcase", P(8, trains=2, stones=1, traps=1, lasers=1, geysers=1, lava=10, slime=5))
add("pieces_mix", "pc_ffa8_amusement", P(8, trains=1, waves=1, rotators=1, rotator_kind="drum", lava=15))
add("pieces_mix", "pc_ffa8_fortress", P(8, traps=2, shutters=2, pistons=1, pickup_walls=1))
add("pieces_mix", "pc_ffa8_lava_works", P(8, trains=1, stones=1, waves=1, currents=1, geysers=2, lava=15))
add("pieces_mix", "pc_ffa10_showcase", P(10, trains=2, traps=2, stones=1, lasers=1, pendulums=1, lava=10))
add("pieces_mix", "pc_ffa12_showcase", P(12, trains=3, traps=2, waves=1, geysers=2, lava=15, slime=5))
add("pieces_mix", "pc_tdm_showcase", P(8, mode="tdm", trains=2, traps=1, shutters=1, lava=10))
add("pieces_mix", "pc_duel_halves_mix", P(2, shape="halves", trains=1, traps=1, lava=10))
add("pieces_mix", "pc_ffa6_ring_mix", P(6, shape="ring", stones=1, lasers=1, geysers=1, lava=10))
add("pieces_mix", "pc_ffa4_vertical_mix", P(4, levels=4, trains=1, wall_steps=1, pistons=1, lava=10))
add("pieces_mix", "pc_ffa6_slow_mix", P(6, trains=2, traps=1, stones=1, lava=10, piece_speed=50, piece_wait=200))
add("pieces_mix", "pc_ffa6_fast_mix", P(6, trains=2, lasers=1, geysers=1, lava=10, piece_speed=200, piece_wait=50))
add("pieces_mix", "pc_ffa4_water_mix", P(4, pool_ladders=True, water=20, water_body="levels", traps=1, lasers=1))
add("pieces_mix", "pc_ffa8_everything", P(8, trains=1, stones=1, traps=1, rotators=1, shutters=1, pickup_walls=1,
                                           bent_bridges=1, wall_steps=1, lasers=1, geysers=1, lava=10, slime=5))

# ---- «Конструкции: машины и механизмы» (the PO 13.11 after the first try: «и под новые механизмы тоже делай пресеты +
# параметры») - drilling rigs, cogs, turrets, conveyors, the pendulums' heads, the blast, the motion
add("pieces_machines", "pc_duel_drill", P(2, drills=1))
add("pieces_machines", "pc_ffa4_drills2", P(4, drills=2))
add("pieces_machines", "pc_ffa6_drill_field", P(6, drills=3))
add("pieces_machines", "pc_duel_cogs", P(2, cogs=1))
add("pieces_machines", "pc_ffa6_workshop", P(6, cogs=2, drills=1))
add("pieces_machines", "pc_ffa8_factory", P(8, conveyors=1, cogs=2, drills=1, turrets=1))
add("pieces_machines", "pc_duel_conveyor", P(2, conveyors=1))
add("pieces_machines", "pc_ffa6_conveyors2", P(6, conveyors=2))
add("pieces_machines", "pc_ffa4_turrets", P(4, turrets=1))
add("pieces_machines", "pc_ffa6_turret_run", P(6, turrets=2, lasers=1))
add("pieces_machines", "pc_duel_sickle", P(2, pendulums=1, pendulum_kind="sickle", bent_bridges=1, lava=10))
add("pieces_machines", "pc_ffa4_hammers", P(4, pendulums=2, pendulum_kind="hammer", lava=10))
add("pieces_machines", "pc_ffa6_saws", P(6, pendulums=2, pendulum_kind="saw", lava=10))
add("pieces_machines", "pc_ffa4_mace_blast", P(4, pendulums=1, pendulum_kind="mace", hammer_blast=True, lava=10))
add("pieces_machines", "pc_duel_anchor", P(2, pendulums=1, pendulum_kind="anchor", lava=10))
add("pieces_machines", "pc_ffa6_labrys", P(6, pendulums=2, pendulum_kind="labrys", hammer_blast=True, lava=15))
add("pieces_machines", "pc_ffa8_blast_hammers", P(8, pendulums=2, hammer_blast=True, lava=15))
add("pieces_machines", "pc_ffa6_mine", P(6, drills=2, conveyors=1, lava=5))
add("pieces_machines", "pc_tdm_factory", P(8, mode="tdm", conveyors=1, turrets=1, cogs=1))
add("pieces_machines", "pc_ffa4_even_machines", P(4, pistons=1, drills=1, piece_motion="even"))
add("pieces_machines", "pc_ffa6_smooth_pistons", P(6, pistons=1, waves=1, lava=10))
add("pieces_machines", "pc_ffa8_forge", P(8, drills=1, pistons=1, pendulums=1, pendulum_kind="sledge", lava=15))
add("pieces_machines", "pc_duel_machine_room", P(2, cogs=1, turrets=1, drills=1))
add("pieces_machines", "pc_ffa10_industry", P(10, conveyors=2, drills=2, cogs=2, turrets=1))
add("pieces_machines", "pc_ffa6_wonders", P(6, conveyors=1, drills=1, cogs=1, pendulums=1, traps=1, lava=10))

NAMES = {  # key: (ru, en)
    "pc_duel_trains": ("Дуэль: платформы над лавой", "Duel: platforms over lava"),
    "pc_duel_island": ("Дуэль: платформа к островку", "Duel: a ride to an island"),
    "pc_ffa4_trains2": ("Платформы над лавой и кислотой на 4", "Platforms over lava and slime for 4"),
    "pc_ffa6_loops": ("Платформы по кругу над кислотой", "Platforms riding loops over slime"),
    "pc_ffa8_trains3": ("Три ездящие платформы на 8", "Three riding platforms for 8"),
    "pc_duel_stones": ("Дуэль: тонущие плиты", "Duel: sinking stones"),
    "pc_duel_stones_gaps": ("Дуэль: плиты через одну", "Duel: stones every other cell"),
    "pc_ffa4_stones_zz": ("Плиты зигзагом над кислотой", "Zigzag stones over slime"),
    "pc_ffa6_stones_fast": ("Быстро тонущие плиты", "Quick sinking stones"),
    "pc_duel_waves": ("Дуэль: волна столбов", "Duel: a pillar wave"),
    "pc_ffa6_waves2": ("Две волны столбов в лаве", "Two pillar waves in lava"),
    "pc_duel_current": ("Дуэль: мост-течение", "Duel: a current bridge"),
    "pc_ffa4_currents": ("Мосты-течения над кислотой", "Current bridges over slime"),
    "pc_ffa4_turnbridge": ("Поворотный мост на 4", "A turning bridge for 4"),
    "pc_ffa8_turnbridges": ("Поворотный мост на 8", "A turning bridge for 8"),
    "pc_duel_drum": ("Дуэль: барабан над лавой", "Duel: a drum over lava"),
    "pc_ffa6_drums": ("Барабаны над лавой на 6", "Drums over lava for 6"),
    "pc_duel_ride_stones": ("Дуэль: платформа и плиты", "Duel: a ride and stones"),
    "pc_ffa4_ride_wave": ("Платформа и волна столбов", "A ride and a pillar wave"),
    "pc_ffa6_slow": ("Неспешные конструкции на 6", "Slow pieces for 6"),
    "pc_ffa8_fast": ("Быстрые конструкции на 8", "Fast pieces for 8"),
    "pc_ffa4_levels": ("Конструкции на четырёх уровнях", "Pieces on four levels"),
    "pc_ffa6_sky": ("Платформы под открытым небом", "Platforms under the open sky"),
    "pc_tdm_motion": ("Команды: движущиеся конструкции", "Teams: moving pieces"),
    "pc_ffa10_motion": ("Движение на 10", "Motion for 10"),
    "pc_duel_trap": ("Дуэль: комната-ловушка", "Duel: a trap room"),
    "pc_duel_trap_lava": ("Дуэль: ловушка с лавой по кнопкам", "Duel: a lava trap on buttons"),
    "pc_ffa4_trap_slime": ("Ловушка с кислотой от плиты", "A slime trap on a plate"),
    "pc_ffa6_trap_crush": ("Давящая ловушка от предмета", "A crushing trap fired by the item"),
    "pc_ffa8_traps2": ("Две комнаты-ловушки на 8", "Two trap rooms for 8"),
    "pc_duel_trapdoor": ("Дуэль: проваливающийся пол", "Duel: a trapdoor"),
    "pc_ffa6_trapdoors": ("Проваливающиеся полы на 6", "Trapdoors for 6"),
    "pc_duel_lasers": ("Дуэль: лазерный заслон", "Duel: a laser gate"),
    "pc_ffa4_lasers2": ("Лазерные заслоны на 4", "Laser gates for 4"),
    "pc_ffa6_lasers_fast": ("Частые лазеры на 6", "Quick lasers for 6"),
    "pc_duel_pistons": ("Дуэль: поршни в проходе", "Duel: pistons in a passage"),
    "pc_ffa4_pistons": ("Быстрые поршни на 4", "Fast pistons for 4"),
    "pc_duel_geyser": ("Дуэль: лавовый гейзер", "Duel: a lava geyser"),
    "pc_ffa6_geysers": ("Три гейзера на 6", "Three geysers for 6"),
    "pc_ffa4_pendulum": ("Маятник над изогнутым мостом", "A pendulum over a bent bridge"),
    "pc_ffa8_pendulums": ("Маятники над мостами на 8", "Pendulums over bridges for 8"),
    "pc_duel_trap_lasers": ("Дуэль: ловушка и лазер", "Duel: a trap and a laser"),
    "pc_ffa4_trap_geyser": ("Ловушка с лавой и гейзеры", "A lava trap and geysers"),
    "pc_ffa6_lasers_pistons": ("Лазеры и поршни", "Lasers and pistons"),
    "pc_ffa6_trapdoor_pend": ("Проваливающийся пол и маятник", "A trapdoor and a pendulum"),
    "pc_ffa8_all_traps": ("Все ловушки на 8", "Every trap for 8"),
    "pc_tdm_traps": ("Команды: ловушки", "Teams: traps"),
    "pc_ffa10_traps": ("Ловушки на 10", "Traps for 10"),
    "pc_ffa4_slow_traps": ("Медленные ловушки на 4", "Slow traps for 4"),
    "pc_ffa6_quick_traps": ("Резкие ловушки на 6", "Sharp traps for 6"),
    "pc_duel_bent": ("Дуэль: изогнутый мост", "Duel: a bent bridge"),
    "pc_ffa6_bent2": ("Изогнутые мосты на 6", "Bent bridges for 6"),
    "pc_duel_steps": ("Дуэль: ступени по стене", "Duel: wall steps"),
    "pc_ffa6_steps": ("Ступени по стенам на 6", "Wall steps for 6"),
    "pc_duel_ladders": ("Дуэль: лесенки из бассейнов", "Duel: ladders out of pools"),
    "pc_ffa6_ladders": ("Бассейны на уровнях и лесенки", "Pools on levels with ladders"),
    "pc_duel_shutters": ("Дуэль: створки по таймеру", "Duel: timed shutters"),
    "pc_ffa4_shutters": ("Створки по таймеру на 4", "Timed shutters for 4"),
    "pc_duel_pickup_wall": ("Дуэль: стена от предмета", "Duel: a wall opened by an item"),
    "pc_ffa6_pickup_walls": ("Стены от предметов на 6", "Walls opened by items for 6"),
    "pc_duel_flaps": ("Дуэль: заслонка в проходе", "Duel: a flap in a passage"),
    "pc_ffa6_flaps": ("Заслонки в проходах на 6", "Flaps in passages for 6"),
    "pc_duel_drill": ("Дуэль: буровая установка", "Duel: a drilling rig"),
    "pc_ffa4_drills2": ("Две буровые на 4", "Two drilling rigs for 4"),
    "pc_ffa6_drill_field": ("Буровое поле на 6", "A drilling field for 6"),
    "pc_duel_cogs": ("Дуэль: шестерни на стене", "Duel: cogs on a wall"),
    "pc_ffa6_workshop": ("Мастерская: шестерни и бур", "A workshop: cogs and a drill"),
    "pc_ffa8_factory": ("Фабрика на 8", "A factory for 8"),
    "pc_duel_conveyor": ("Дуэль: конвейер с грузами", "Duel: a conveyor with crates"),
    "pc_ffa6_conveyors2": ("Два конвейера на 6", "Two conveyors for 6"),
    "pc_ffa4_turrets": ("Турели в проходе на 4", "Turrets in a passage for 4"),
    "pc_ffa6_turret_run": ("Турели и лазер на 6", "Turrets and a laser for 6"),
    "pc_duel_sickle": ("Дуэль: серп над изогнутым мостом", "Duel: a sickle over a bent bridge"),
    "pc_ffa4_hammers": ("Молоты над мостами на 4", "Hammers over bridges for 4"),
    "pc_ffa6_saws": ("Пилы над мостами на 6", "Saws over bridges for 6"),
    "pc_ffa4_mace_blast": ("Булава с ударной волной", "A mace with a shock wave"),
    "pc_duel_anchor": ("Дуэль: якорь над лавой", "Duel: an anchor over lava"),
    "pc_ffa6_labrys": ("Двойные топоры с ударной волной", "Double axes with a shock wave"),
    "pc_ffa8_blast_hammers": ("Маятники с ударной волной на 8", "Pendulums with a shock wave for 8"),
    "pc_ffa6_mine": ("Шахта: буры и конвейер", "A mine: drills and a conveyor"),
    "pc_tdm_factory": ("Команды: фабрика", "Teams: a factory"),
    "pc_ffa4_even_machines": ("Машины с ровным ходом", "Machines moving evenly"),
    "pc_ffa6_smooth_pistons": ("Поршни и волна с разгоном", "Pistons and a wave, easing"),
    "pc_ffa8_forge": ("Кузница на 8", "A forge for 8"),
    "pc_duel_machine_room": ("Дуэль: машинный зал", "Duel: a machine room"),
    "pc_ffa10_industry": ("Промзона на 10", "An industrial zone for 10"),
    "pc_ffa6_wonders": ("Чудеса механики на 6", "Wonders of machinery for 6"),
    "pc_duel_fans": ("Дуэль: вентилятор у предмета", "Duel: a fan by an item"),
    "pc_ffa4_fans": ("Вентиляторы у предметов на 4", "Fans by items for 4"),
    "pc_duel_bent_steps": ("Дуэль: мост и ступени", "Duel: a bridge and steps"),
    "pc_ffa4_shutter_wall": ("Створки и стена от предмета", "Shutters and a wall opened by an item"),
    "pc_ffa6_pool_steps": ("Бассейны, лесенки и ступени", "Pools, ladders and steps"),
    "pc_ffa8_architecture": ("Архитектура на 8", "Architecture for 8"),
    "pc_duel_halves_arch": ("Дуэль: половины и створки", "Duel: halves and shutters"),
    "pc_ffa6_ring_arch": ("Кольцо и изогнутый мост", "A ring and a bent bridge"),
    "pc_ffa4_vertical_arch": ("Вертикаль со ступенями", "Vertical with steps"),
    "pc_ffa6_sky_arch": ("Мост под небом и створки", "A bridge under the sky and shutters"),
    "pc_tdm_arch": ("Команды: створки и ступени", "Teams: shutters and steps"),
    "pc_ffa10_arch": ("Архитектура на 10", "Architecture for 10"),
    "pc_ffa4_water_arch": ("Вода, лесенки и створки", "Water, ladders and shutters"),
    "pc_duel_showcase": ("Дуэль: витрина конструкций", "Duel: a showcase of pieces"),
    "pc_duel_q2dm3_like": ("Дуэль: в духе q2dm3", "Duel: in the spirit of q2dm3"),
    "pc_duel_q2dm6_like": ("Дуэль: в духе q2dm6", "Duel: in the spirit of q2dm6"),
    "pc_duel_q2dm4_like": ("Дуэль: в духе q2dm4", "Duel: in the spirit of q2dm4"),
    "pc_ffa4_showcase": ("Витрина конструкций на 4", "A showcase of pieces for 4"),
    "pc_ffa4_lava_world": ("Лавовый мир на 4", "A lava world for 4"),
    "pc_ffa4_slime_world": ("Кислотный мир на 4", "A slime world for 4"),
    "pc_ffa6_showcase": ("Витрина конструкций на 6", "A showcase of pieces for 6"),
    "pc_ffa6_machines": ("Машинерия на 6", "Machinery for 6"),
    "pc_ffa6_crossings": ("Переправы на 6", "Crossings for 6"),
    "pc_ffa6_danger": ("Опасные места на 6", "Dangerous places for 6"),
    "pc_ffa8_showcase": ("Витрина конструкций на 8", "A showcase of pieces for 8"),
    "pc_ffa8_amusement": ("Аттракционы на 8", "Rides for 8"),
    "pc_ffa8_fortress": ("Крепость с ловушками на 8", "A fortress of traps for 8"),
    "pc_ffa8_lava_works": ("Лавовый завод на 8", "Lava works for 8"),
    "pc_ffa10_showcase": ("Витрина конструкций на 10", "A showcase of pieces for 10"),
    "pc_ffa12_showcase": ("Витрина конструкций на 12", "A showcase of pieces for 12"),
    "pc_tdm_showcase": ("Команды: витрина конструкций", "Teams: a showcase of pieces"),
    "pc_duel_halves_mix": ("Дуэль: половины, платформа, ловушка", "Duel: halves, a ride, a trap"),
    "pc_ffa6_ring_mix": ("Кольцо с плитами и лазером", "A ring with stones and a laser"),
    "pc_ffa4_vertical_mix": ("Вертикаль с платформой и поршнями", "Vertical with a ride and pistons"),
    "pc_ffa6_slow_mix": ("Неспешная витрина на 6", "A slow showcase for 6"),
    "pc_ffa6_fast_mix": ("Резкая витрина на 6", "A sharp showcase for 6"),
    "pc_ffa4_water_mix": ("Вода на уровнях и ловушка", "Water on levels and a trap"),
    "pc_ffa8_everything": ("Всего понемногу на 8", "A bit of everything for 8"),
}


def main() -> int:
    """Each preset makes skeletons on 12 seeds and builds the pieces it asks on most of them."""
    import multiprocessing
    import os
    assert len(PRESETS) == 125 and len({k for _, k, _ in PRESETS}) == 125, len(PRESETS)
    missing = [k for _, k, _ in PRESETS if k not in NAMES]
    assert not missing, missing
    only = set(sys.argv[1:])
    todo = [t for t in PRESETS if not only or t[1] in only]
    bad = []
    with multiprocessing.Pool(int(os.environ.get("MAPGEN_PRESET_WORKERS") or 6)) as pool:
        for key, line, ok in pool.imap(_check, todo):
            print(line, flush=True)
            if not ok:
                bad.append(key)
    print(f"{'PASS' if not bad else 'FAIL'}: {len(todo) - len(bad)} of {len(todo)} presets make skeletons with their pieces"
          + (f"; failed: {', '.join(bad)}" if bad else ""))
    return 0 if not bad else 1


def _check(t) -> tuple:
    import mapgen_scratch_plan as pm
    cat, key, q = t
    t0 = time.time()
    made = failed = whole = 0
    for s in range(700, 712):
        P = pm.make_plan(dict(q), s)
        if P.failed:
            failed += 1
            continue
        made += 1
        whole += 0 if P.metrics.get("pieces_missing") else 1
    # the gate: half the seeds make a plan, and a third of those hold every piece asked (the Studio takes the best of 36)
    ok = made >= 6 and whole >= max(1, made // 3)
    return key, (f"{'PASS' if ok else 'FAIL'} {cat:14s} {key:26s} made {made}/12, every piece on {whole}  "
                 f"{time.time() - t0:.0f} s"), ok


if __name__ == "__main__":
    sys.exit(main())
