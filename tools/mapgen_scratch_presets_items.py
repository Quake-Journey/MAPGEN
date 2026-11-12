r"""The PO 12.11: 100 factory presets of a map from scratch on the items' pick-up worth - the table the Studio's presets are
written from (tools/mapgen_scratch_presets_codegen.py), in the form of Fable's oracle table of 06.11
(`add(category, key, P(players, ...))`, values as the form's rows give them):

  «practice» (50) - «я хочу еще 50 пресетов, которые будут переиспользовать практики расположения/доступности айтемов,
                  армора, оружия и паверапов из карт людей - q2dmX, q2duelX, q2rdmX, ztn2dmX, omf, koldduel1, ptrip,
                  match1 … Это не значит что нужно клонировать … делал миксы пресетов» - each a family's practice (or two
                  mixed: «item_practice») on a map of the play that family is made for, mixed with the form's other rows;
  «prizes» (50)  - «в пресетах тоже добавишь еще 50 сверх тех 50» - the new rows themselves: how the prizes are earned
                  (in nooks, under water, in the open), how many under water, the majors wider apart, with the rest.

`UPDATES`: the old presets the new rows change («не забудь обновить существующие пресеты на новые параметры - чтобы они
сбрасывали их на дефолты или нужные значения») - every other one keeps the defaults (a factory preset is made from a
fresh form: its new rows at «По умолчанию»). Each preset goes through `make_plan` on 12 seeds by
`python tools/mapgen_scratch_presets_items.py` (the gate of the 160: failed on 6 or fewer, no refusal on every seed made).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("presets_x10", Path(__file__).resolve().parent / "fable_oracles" / "mapgen_2026-11-06_presets_x10.py")
_ox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ox)
P, G = _ox.P, _ox.G

PRESETS: list[tuple[str, str, dict]] = []


def add(cat: str, key: str, q: dict) -> None:
    PRESETS.append((cat, key, q))


# ---- «Приёмы известных карт»: a family's practice on the play it is made for, mixed with the form's other rows -------------
add("practice_a", "pr_q2dm_ffa6", P(6, item_practice="q2dm"))
add("practice_a", "pr_q2dm_ffa8", P(8, item_practice="q2dm"))
add("practice_a", "pr_q2dm_ring8", P(8, shape="ring", item_practice="q2dm"))
add("practice_a", "pr_q2dm_halves8", P(8, shape="halves", item_practice="q2dm"))
add("practice_a", "pr_q2dm_vertical6", P(6, levels=6, vertical_span=768, lifts=3, stairs=8, item_practice="q2dm"))
add("practice_a", "pr_q2dm_water8", P(8, water=20, levels=3, underwater=1, item_practice="q2dm", water_body="levels"))
add("practice_a", "pr_q2dm_lava6", P(6, lava=10, pits=1, water=0, item_practice="q2dm"))
add("practice_a", "pr_q2dm_tdm", P(8, mode="tdm", item_practice="q2dm"))
add("practice_a", "pr_q2dm_wide8", P(8, item_spacing="wide", item_practice="q2dm"))
add("practice_a", "pr_q2duel", P(2, item_practice="q2duel"))
add("practice_a", "pr_q2duel_vertical", P(2, levels=6, vertical_span=768, lifts=3, stairs=8, item_practice="q2duel"))
add("practice_a", "pr_q2duel_ring", P(2, shape="ring", item_practice="q2duel"))
add("practice_a", "pr_q2duel_corridors", P(2, corr=60, open_=0, doors=2, item_practice="q2duel"))
add("practice_a", "pr_q2duel_open", P(2, shape="arena", prize_access="exposed", item_practice="q2duel"))
add("practice_a", "pr_q2duel_water", P(2, water=20, levels=3, underwater=1, item_practice="q2duel"))
add("practice_a", "pr_q2duel_wide", P(2, item_spacing="wide", item_practice="q2duel"))
add("practice_a", "pr_q2duel_teleports", P(2, teleporters=2, item_practice="q2duel"))
add("practice_a", "pr_q2rdm_ffa4", P(4, item_practice="q2rdm"))
add("practice_a", "pr_q2rdm_ffa6", P(6, item_practice="q2rdm"))
add("practice_a", "pr_q2rdm_ffa8", P(8, item_practice="q2rdm"))
add("practice_a", "pr_q2rdm_halves6", P(6, shape="halves", item_practice="q2rdm"))
add("practice_a", "pr_q2rdm_pads6", P(6, pads=4, item_practice="q2rdm"))
add("practice_a", "pr_q2rdm_vertical8", P(8, levels=6, vertical_span=768, lifts=4, stairs=12, item_practice="q2rdm"))
add("practice_a", "pr_q2rdm_nooks4", P(4, prize_access="nooks", item_practice="q2rdm"))
add("practice_b", "pr_ztn2dm_ffa4", P(4, item_practice="ztn2dm"))
add("practice_b", "pr_ztn2dm_ffa6", P(6, item_practice="ztn2dm"))
add("practice_b", "pr_ztn2dm_ring6", P(6, shape="ring", item_practice="ztn2dm"))
add("practice_b", "pr_ztn2dm_drops4", P(4, drops=8, levels=5, item_practice="ztn2dm"))
add("practice_b", "pr_ztn2dm_lifts6", P(6, lifts=4, item_practice="ztn2dm"))
add("practice_b", "pr_ztn2dm_water4", P(4, water=20, levels=3, underwater=1, item_practice="ztn2dm"))
add("practice_b", "pr_kold_duel", P(2, item_practice="koldduel1"))
add("practice_b", "pr_kold_vertical", P(2, levels=6, vertical_span=768, lifts=3, item_practice="koldduel1"))
add("practice_b", "pr_kold_lifts", P(2, lifts=3, ladders=1, item_practice="koldduel1"))
add("practice_b", "pr_ptrip_duel", P(2, item_practice="ptrip"))
add("practice_b", "pr_ptrip_small3", P(3, size=80, item_practice="ptrip"))
add("practice_b", "pr_match1_ffa4", P(4, item_practice="match1"))
add("practice_b", "pr_match1_tele4", P(4, teleporters=2, item_practice="match1"))
add("practice_b", "pr_omf_ffa4", P(4, item_practice="omf"))
add("practice_b", "pr_omf_water6", P(6, water=20, levels=3, underwater=1, item_practice="omf"))
add("practice_b", "pr_mix_duel_ztn", P(2, item_practice="q2duel+ztn2dm"))
add("practice_b", "pr_mix_ffa8_dm_rdm", P(8, item_practice="q2dm+q2rdm"))
add("practice_b", "pr_mix_duel_kold", P(2, levels=5, lifts=3, item_practice="q2duel+koldduel1"))
add("practice_b", "pr_mix_ffa6_dm_ztn", P(6, item_practice="q2dm+ztn2dm"))
add("practice_b", "pr_mix_ffa6_rdm_omf", P(6, item_practice="q2rdm+omf"))
add("practice_b", "pr_mix_ffa3_ptrip_match", P(3, item_practice="ptrip+match1"))
add("practice_b", "pr_mix_ffa4_dm_duel", P(4, item_practice="q2dm+q2duel"))
add("practice_b", "pr_mix_ffa8_ring_ztn_rdm", P(8, shape="ring", item_practice="ztn2dm+q2rdm"))
add("practice_b", "pr_mix_duel_water", P(2, water=20, levels=3, underwater=2, item_practice="q2dm+q2duel"))
add("practice_b", "pr_all_duel_wide", P(2, item_spacing="wide", item_practice="mix"))
add("practice_b", "pr_all_ffa8_wide", P(8, item_spacing="wide", item_practice="mix"))

# ---- «Призы и вода»: the new rows themselves ------------------------------------------------------------------------
add("prizes_nooks", "pz_duel_nooks", P(2, prize_access="nooks"))
add("prizes_nooks", "pz_duel_nooks_hard", P(2, prize_access="nooks", powerup_access="hard"))
add("prizes_nooks", "pz_ffa4_nooks", P(4, prize_access="nooks"))
add("prizes_nooks", "pz_ffa8_nooks", P(8, prize_access="nooks"))
add("prizes_nooks", "pz_tdm_nooks", P(8, mode="tdm", prize_access="nooks"))
add("prizes_water", "pz_duel_dive1", P(2, underwater=1))
add("prizes_water", "pz_duel_dive2", P(2, underwater=2))
add("prizes_water", "pz_duel_dive3", P(2, underwater=3))
add("prizes_water", "pz_ffa4_dive1", P(4, underwater=1))
add("prizes_water", "pz_ffa4_dive2", P(4, underwater=2))
add("prizes_water", "pz_ffa6_dive2", P(6, underwater=2))
add("prizes_water", "pz_ffa8_dive2", P(8, underwater=2))
add("prizes_water", "pz_ffa8_dive3", P(8, underwater=3))
add("prizes_water", "pz_duel_water_all", P(2, prize_access="water"))
add("prizes_water", "pz_ffa4_water_all", P(4, prize_access="water"))
add("prizes_water", "pz_ffa8_water_all", P(8, prize_access="water"))
add("prizes_water", "pz_duel_lake_dive", P(2, water=30, levels=3, underwater=2))
add("prizes_water", "pz_ffa8_lake_dive", P(8, water=30, levels=3, underwater=2, water_body="levels"))
add("prizes_water", "pz_duel_dive_vertical", P(2, levels=6, vertical_span=768, lifts=3, underwater=1))
add("prizes_water", "pz_ffa6_dive_ring", P(6, shape="ring", underwater=2))
add("prizes_water", "pz_ffa8_dive_halves", P(8, shape="halves", underwater=2))
add("prizes_water", "pz_tdm_dive", P(8, mode="tdm", underwater=2))
add("prizes_water", "pz_duel_dive_dark", P(2, sky=0, sun="no", tone="cold", underwater=1))
add("prizes_water", "pz_duel_dive_wide", P(2, underwater=1, item_spacing="wide"))
add("prizes_nooks", "pz_duel_exposed", P(2, prize_access="exposed"))
add("prizes_nooks", "pz_ffa4_exposed", P(4, prize_access="exposed"))
add("prizes_nooks", "pz_ffa8_exposed", P(8, prize_access="exposed"))
add("prizes_nooks", "pz_arena_exposed", P(4, shape="arena", prize_access="exposed"))
add("prizes_nooks", "pz_duel_exposed_rail", P(2, prize_access="exposed", long_lines=5, open_=30))
add("prizes_nooks", "pz_ffa8_exposed_sky", P(8, prize_access="exposed", sky=70, sun="yes"))
add("prizes_nooks", "pz_duel_wide", P(2, item_spacing="wide"))
add("prizes_nooks", "pz_ffa4_wide", P(4, item_spacing="wide"))
add("prizes_nooks", "pz_ffa8_wide", P(8, item_spacing="wide"))
add("prizes_nooks", "pz_ffa16_wide", P(16, item_spacing="wide"))
add("prizes_nooks", "pz_duel_people", P(2, prize_access="people"))
add("prizes_nooks", "pz_ffa8_people", P(8, prize_access="people"))
add("prizes_nooks", "pz_duel_nooks_wide", P(2, prize_access="nooks", item_spacing="wide"))
add("prizes_nooks", "pz_ffa8_nooks_wide", P(8, prize_access="nooks", item_spacing="wide"))
add("prizes_nooks", "pz_duel_nooks_quad", P(2, prize_access="nooks", stack="ra_mh_quad"))
add("prizes_nooks", "pz_ffa8_nooks_quad", P(8, prize_access="nooks", stack="ra_mh_quad"))
add("prizes_water", "pz_duel_dive_quad", P(2, underwater=2, stack="ra_mh_quad"))
add("prizes_water", "pz_ffa8_dive_quad", P(8, underwater=2, stack="ra_mh_quad"))
add("prizes_water", "pz_duel_dive_rail", P(2, underwater=1, long_lines=4))
add("prizes_nooks", "pz_ffa6_exposed_tele", P(6, prize_access="exposed", teleporters=2))
add("prizes_water", "pz_ffa4_dive_lifts", P(4, underwater=1, lifts=4))
add("prizes_water", "pz_duel_dive_mech", P(2, underwater=1, mechanics=["clock", "halves", "small_health", "spawn_pressure"]))
add("prizes_water", "pz_ffa10_dive2", P(10, underwater=2))
add("prizes_nooks", "pz_ffa12_nooks", P(12, prize_access="nooks"))
add("prizes_water", "pz_ffa12_dive3", P(12, underwater=3))
add("prizes_nooks", "pz_tdm_exposed", P(8, mode="tdm", prize_access="exposed"))

# ---- the old presets the new rows change (the rest keep «По умолчанию») ---------------------------------------------
UPDATES = {
    # a map with water: a prize under it (as q2dm1's railgun, q2dm5's mega)
    "duel_water": {"underwater": 1}, "ffa4_water": {"underwater": 1}, "ffa8_water": {"underwater": 1},
    "ffa10_water": {"underwater": 1}, "water_lake": {"underwater": 2}, "water_canals": {"underwater": 1, "water_body": "levels"},
    "water_ffa8": {"underwater": 2, "water_body": "levels"},
    # the hard powerups: every prize in its nook
    "hard_powerups8": {"prize_access": "nooks"},
    # the open arenas: the prizes in the open under fire (q2duel5)
    "duel_open": {"prize_access": "exposed"}, "ffa4_open": {"prize_access": "exposed"},
}

NAMES = {  # key: (ru, en)
    "pr_q2dm_ffa6": ("Как q2dm, на 6", "As q2dm, for 6"), "pr_q2dm_ffa8": ("Как q2dm, на 8", "As q2dm, for 8"),
    "pr_q2dm_ring8": ("Как q2dm, кольцо на 8", "As q2dm, ring for 8"),
    "pr_q2dm_halves8": ("Как q2dm, две половины на 8", "As q2dm, two halves for 8"),
    "pr_q2dm_vertical6": ("Как q2dm, вертикаль на 6", "As q2dm, vertical for 6"),
    "pr_q2dm_water8": ("Как q2dm, с водой и призом под водой", "As q2dm, water and a prize under it"),
    "pr_q2dm_lava6": ("Как q2dm, с лавой на 6", "As q2dm, lava for 6"),
    "pr_q2dm_tdm": ("Как q2dm, команды 4×4", "As q2dm, teams 4v4"),
    "pr_q2dm_wide8": ("Как q2dm, просторнее", "As q2dm, wider apart"),
    "pr_q2duel": ("Как q2duel", "As q2duel"), "pr_q2duel_vertical": ("Как q2duel, вертикаль", "As q2duel, vertical"),
    "pr_q2duel_ring": ("Как q2duel, кольцо", "As q2duel, ring"),
    "pr_q2duel_corridors": ("Как q2duel, коридоры", "As q2duel, corridors"),
    "pr_q2duel_open": ("Как q2duel, призы под обстрелом", "As q2duel, prizes under fire"),
    "pr_q2duel_water": ("Как q2duel, приз под водой", "As q2duel, a prize under water"),
    "pr_q2duel_wide": ("Как q2duel, просторнее", "As q2duel, wider apart"),
    "pr_q2duel_teleports": ("Как q2duel, с телепортами", "As q2duel, with teleporters"),
    "pr_q2rdm_ffa4": ("Как q2rdm, на 4", "As q2rdm, for 4"), "pr_q2rdm_ffa6": ("Как q2rdm, на 6", "As q2rdm, for 6"),
    "pr_q2rdm_ffa8": ("Как q2rdm, на 8", "As q2rdm, for 8"),
    "pr_q2rdm_halves6": ("Как q2rdm, две половины на 6", "As q2rdm, two halves for 6"),
    "pr_q2rdm_pads6": ("Как q2rdm, с джампадами на 6", "As q2rdm, jump pads for 6"),
    "pr_q2rdm_vertical8": ("Как q2rdm, вертикаль на 8", "As q2rdm, vertical for 8"),
    "pr_q2rdm_nooks4": ("Как q2rdm, призы в нишах", "As q2rdm, prizes in nooks"),
    "pr_ztn2dm_ffa4": ("Как ztn2dm, на 4", "As ztn2dm, for 4"), "pr_ztn2dm_ffa6": ("Как ztn2dm, на 6", "As ztn2dm, for 6"),
    "pr_ztn2dm_ring6": ("Как ztn2dm, кольцо на 6", "As ztn2dm, ring for 6"),
    "pr_ztn2dm_drops4": ("Как ztn2dm, со спусками", "As ztn2dm, with drops"),
    "pr_ztn2dm_lifts6": ("Как ztn2dm, с лифтами", "As ztn2dm, with lifts"),
    "pr_ztn2dm_water4": ("Как ztn2dm, приз под водой", "As ztn2dm, a prize under water"),
    "pr_kold_duel": ("Как koldduel1", "As koldduel1"), "pr_kold_vertical": ("Как koldduel1, вертикаль", "As koldduel1, vertical"),
    "pr_kold_lifts": ("Как koldduel1, лифты и стремянка", "As koldduel1, lifts and a ladder"),
    "pr_ptrip_duel": ("Как ptrip", "As ptrip"), "pr_ptrip_small3": ("Как ptrip, малая на 3", "As ptrip, small for 3"),
    "pr_match1_ffa4": ("Как match1, на 4", "As match1, for 4"),
    "pr_match1_tele4": ("Как match1, с телепортами", "As match1, with teleporters"),
    "pr_omf_ffa4": ("Как omf, на 4", "As omf, for 4"), "pr_omf_water6": ("Как omf, приз под водой", "As omf, a prize under water"),
    "pr_mix_duel_ztn": ("q2duel и ztn2dm, дуэль", "q2duel and ztn2dm, duel"),
    "pr_mix_ffa8_dm_rdm": ("q2dm и q2rdm, на 8", "q2dm and q2rdm, for 8"),
    "pr_mix_duel_kold": ("q2duel и koldduel1, этажи и лифты", "q2duel and koldduel1, levels and lifts"),
    "pr_mix_ffa6_dm_ztn": ("q2dm и ztn2dm, на 6", "q2dm and ztn2dm, for 6"),
    "pr_mix_ffa6_rdm_omf": ("q2rdm и omf, на 6", "q2rdm and omf, for 6"),
    "pr_mix_ffa3_ptrip_match": ("ptrip и match1, на 3", "ptrip and match1, for 3"),
    "pr_mix_ffa4_dm_duel": ("q2dm и q2duel, на 4", "q2dm and q2duel, for 4"),
    "pr_mix_ffa8_ring_ztn_rdm": ("ztn2dm и q2rdm, кольцо на 8", "ztn2dm and q2rdm, ring for 8"),
    "pr_mix_duel_water": ("q2dm и q2duel, два приза под водой", "q2dm and q2duel, two prizes under water"),
    "pr_all_duel_wide": ("Все известные карты, дуэль просторнее", "All well-known maps, a wider duel"),
    "pr_all_ffa8_wide": ("Все известные карты, на 8 просторнее", "All well-known maps, wider for 8"),
    "pz_duel_nooks": ("Дуэль: призы в нишах", "Duel: prizes in nooks"),
    "pz_duel_nooks_hard": ("Дуэль: ниши за дверями", "Duel: nooks behind doors"),
    "pz_ffa4_nooks": ("Призы в нишах на 4", "Prizes in nooks for 4"),
    "pz_ffa8_nooks": ("Призы в нишах на 8", "Prizes in nooks for 8"),
    "pz_tdm_nooks": ("Команды: призы в нишах", "Teams: prizes in nooks"),
    "pz_duel_dive1": ("Дуэль: приз под водой", "Duel: a prize under water"),
    "pz_duel_dive2": ("Дуэль: два приза под водой", "Duel: two prizes under water"),
    "pz_duel_dive3": ("Дуэль: три приза под водой", "Duel: three prizes under water"),
    "pz_ffa4_dive1": ("Приз под водой на 4", "A prize under water for 4"),
    "pz_ffa4_dive2": ("Два приза под водой на 4", "Two prizes under water for 4"),
    "pz_ffa6_dive2": ("Два приза под водой на 6", "Two prizes under water for 6"),
    "pz_ffa8_dive2": ("Два приза под водой на 8", "Two prizes under water for 8"),
    "pz_ffa8_dive3": ("Три приза под водой на 8", "Three prizes under water for 8"),
    "pz_duel_water_all": ("Дуэль: все призы под водой", "Duel: every prize under water"),
    "pz_ffa4_water_all": ("Все призы под водой на 4", "Every prize under water for 4"),
    "pz_ffa8_water_all": ("Все призы под водой на 8", "Every prize under water for 8"),
    "pz_duel_lake_dive": ("Дуэль: озеро и призы на дне", "Duel: a lake and prizes at the bottom"),
    "pz_ffa8_lake_dive": ("Озеро и призы на дне на 8", "A lake and prizes at the bottom for 8"),
    "pz_duel_dive_vertical": ("Дуэль: вертикаль и приз под водой", "Duel: vertical, a prize under water"),
    "pz_ffa6_dive_ring": ("Кольцо и призы под водой на 6", "Ring and prizes under water for 6"),
    "pz_ffa8_dive_halves": ("Две половины и призы под водой", "Two halves and prizes under water"),
    "pz_tdm_dive": ("Команды: призы под водой", "Teams: prizes under water"),
    "pz_duel_dive_dark": ("Дуэль: тёмная, приз под водой", "Duel: dark, a prize under water"),
    "pz_duel_dive_wide": ("Дуэль: приз под водой, просторнее", "Duel: a prize under water, wider"),
    "pz_duel_exposed": ("Дуэль: призы под обстрелом", "Duel: prizes under fire"),
    "pz_ffa4_exposed": ("Призы под обстрелом на 4", "Prizes under fire for 4"),
    "pz_ffa8_exposed": ("Призы под обстрелом на 8", "Prizes under fire for 8"),
    "pz_arena_exposed": ("Арена: призы посередине", "Arena: prizes in the middle"),
    "pz_duel_exposed_rail": ("Дуэль: рельсотрон под обстрелом", "Duel: the railgun under fire"),
    "pz_ffa8_exposed_sky": ("Под небом: призы под обстрелом", "Under the sky: prizes under fire"),
    "pz_duel_wide": ("Дуэль: предметы просторнее", "Duel: items wider apart"),
    "pz_ffa4_wide": ("Предметы просторнее на 4", "Items wider apart for 4"),
    "pz_ffa8_wide": ("Предметы просторнее на 8", "Items wider apart for 8"),
    "pz_ffa16_wide": ("Предметы просторнее на 16", "Items wider apart for 16"),
    "pz_duel_people": ("Дуэль: призы как на известных картах", "Duel: prizes as on well-known maps"),
    "pz_ffa8_people": ("Призы как на известных картах на 8", "Prizes as on well-known maps for 8"),
    "pz_duel_nooks_wide": ("Дуэль: ниши, просторнее", "Duel: nooks, wider"),
    "pz_ffa8_nooks_wide": ("Ниши, просторнее, на 8", "Nooks, wider, for 8"),
    "pz_duel_nooks_quad": ("Дуэль: квад и броня в нишах", "Duel: quad and armour in nooks"),
    "pz_ffa8_nooks_quad": ("Квад и броня в нишах на 8", "Quad and armour in nooks for 8"),
    "pz_duel_dive_quad": ("Дуэль: квад под водой", "Duel: the quad under water"),
    "pz_ffa8_dive_quad": ("Квад под водой на 8", "The quad under water for 8"),
    "pz_duel_dive_rail": ("Дуэль: рельсотрон под водой", "Duel: the railgun under water"),
    "pz_ffa6_exposed_tele": ("Под обстрелом с телепортами", "Under fire with teleporters"),
    "pz_ffa4_dive_lifts": ("Лифты и приз под водой", "Lifts and a prize under water"),
    "pz_duel_dive_mech": ("Дуэль: часы, половины, приз под водой", "Duel: clock, halves, a prize under water"),
    "pz_ffa10_dive2": ("Два приза под водой на 10", "Two prizes under water for 10"),
    "pz_ffa12_nooks": ("Призы в нишах на 12", "Prizes in nooks for 12"),
    "pz_ffa12_dive3": ("Три приза под водой на 12", "Three prizes under water for 12"),
    "pz_tdm_exposed": ("Команды: призы под обстрелом", "Teams: prizes under fire"),
}


def every_preset() -> list:
    """`--all`: every factory preset of a map from scratch - Fable's 160, the space's, the tower's (with UPDATES, each
    held to its own table's gate: failed on half the seeds or fewer, no refusal of the request on every seed) and this
    table's hundred (its gate: the notes too)."""
    tools = Path(__file__).resolve().parent
    rows = []
    for path in (tools / "fable_oracles" / "mapgen_2026-11-06_presets_x10.py", tools / "mapgen_scratch_presets_space.py",
                 tools / "mapgen_scratch_presets_tower.py"):
        spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rows += [(c, k, {**q, **UPDATES.get(k, {})}, "old") for c, k, q in mod.PRESETS]
    return rows + [(c, k, q, "new") for c, k, q in PRESETS]


def main() -> int:
    import multiprocessing
    import mapgen_load_guard
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    mapgen_load_guard.pin_self()
    assert len(PRESETS) == 100 and len({k for _, k, _ in PRESETS}) == 100, len(PRESETS)
    missing = [k for _, k, _ in PRESETS if k not in NAMES]
    assert not missing, missing
    args = [x for x in sys.argv[1:] if x not in ("--all", "--old")]
    only = set(args)
    rows = every_preset() if {"--all", "--old"} & set(sys.argv[1:]) else [(c, k, q, "new") for c, k, q in PRESETS]
    if "--old" in sys.argv[1:]:
        rows = [r for r in rows if r[3] == "old"]
    todo = [t for t in rows if not only or t[1] in only]
    bad = []
    import os
    with multiprocessing.Pool(int(os.environ.get("MAPGEN_PRESET_WORKERS") or 6)) as pool:
        for key, line, ok in pool.imap(_check, todo):
            print(line, flush=True)
            if not ok:
                bad.append(key)
    print(f"{'PASS' if not bad else 'FAIL'}: {len(todo) - len(bad)} of {len(todo)} presets make skeletons"
          + (f"; failed: {', '.join(bad)}" if bad else ""))
    return 0 if not bad else 1


def _check(t) -> tuple:
    import mapgen_scratch_plan as pm
    cat, key, q, table = t
    t0 = time.time()
    failed, made, refused, near, fell, kinds = 0, 0, {}, 0, 0, {}
    for s in range(700, 712):
        Pl = pm.make_plan(dict(q), s)
        if Pl.failed:
            failed += 1
            continue
        pm.score(Pl)
        made += 1
        # every table's gate: the request's refusals; this table's also what its own rows ask and the plan could not
        # make (a prize's way fallen back to a nook) - not the plan's other notes (a pad «0 of 1» on a pool map is the
        # planner's of every version, his mg_new_27829 of 3.65 too)
        said = set(Pl.params.get("refused") or [])
        if table == "new":
            said |= {n for n in Pl.notes if n.startswith(("призы в нише с прыжком вместо", "prizes in a nook jumped into instead"))}
        for r in said:
            refused[r[:60]] = refused.get(r[:60], 0) + 1
        near += len(Pl.metrics.get("majors_near") or [])
        fell += len(Pl.metrics.get("prize_fell_back") or [])
        for _c, k in Pl.metrics.get("prize_kinds") or []:
            kinds[k] = kinds.get(k, 0) + 1
    always = [r for r, n in refused.items() if made and n == made]
    ok = failed <= 6 and not always
    line = (f"{'PASS' if ok else 'FAIL'} {cat:9} {key:28} made {made}/12 failed {failed}  majors near {near}  "
            f"ways {kinds}  fell back {fell}  {time.time() - t0:.0f} s" + (f"  always refused: {always}" if always else ""))
    return key, line, ok


if __name__ == "__main__":
    sys.exit(main())
