r"""The descriptions of maps from scratch written before 3.57, said in words (the PO, 07.11: «в русском описании … есть
анг формулировки в студии»): the head line («8 игроков, FFA, generated» → «8 игроков, общий бой, свои текстуры студии:
Завод»), the rows whose values were the request's keys («Форма: space → space», «Украшений на стенах: none», «Мостики:
some», «Дальность джампадов: medium», «Режим: ffa»), the items by the form's names («ARMOR_BODY» → «Красная броня»), an open
space's rows it has no part in left out, the failed rows' English names replaced by where they are said in words. Only
the words change: every measured number stays. The file is kept once as `<file>.before_words`.

3.58 (the PO 07.11 on the guide; brief 31): «карты людей» is our own word - the maps the generator is measured against
are «известные карты» / «well-known maps». The descriptions say «как у людей 50..100%», «≤4 как у людей», «отделка как
у карты людей q2dm1», «Цвет света: … → как у карты людей» (and the English ones carried the Russian bands): said as
`mapgen_scratch.write_record` says them now. Numbers untouched.

3.58 addendum: the English descriptions carried more Russian, written into both languages since 3.45 - the powerups'
row («смешанно → мега — в нише, красная броня — на постаменте»), «Скругления» («нет», «углов 2, полукруглых торцов 1,
возвышений 0»), an open space's edges («открытые → 80% края над пустотой»), «≥50% (план 67%)», a tower's «не меньше
50%»: said in English as the record says them now (`mapgen_scratch_words`: ACCESS, CYCLE, POWERUP_SHORT, SITES, ROUND,
EDGES). Numbers untouched.

    python tools/mapgen_redescribe.py DATA_DIR [--dry]

DATA_DIR is a Studio's `data` folder (its `descriptions` and `runs`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_scratch_words as w  # noqa: E402

HEAD = re.compile(r"^(Сделано с нуля|Made from scratch): (\d+) (?:игроков|игрока|игрок|players?), ([A-Za-z]+), (.*)\.$")
ROW = re.compile(r"^  (.+?): (.*) → (.*)$")
FAILED = re.compile(r"^(Проверка карты с нуля: не прошло|From-scratch check: failed) (.+)$")
NOT_MADE = re.compile(r"^(  Не сделано: |  Not made: )([a-z_]+): (.*)$")
SITES = re.compile(r" — (easy|medium|hard|cycle|medium \(jump in\)|hard \(jump in\)|easy \(no nook\))(?=,|$)")
ITEM_KEYS = {k.replace("item_", "").replace("weapon_", "").upper(): k for k in w.ITEMS}


def theme_of(runs: Path, name: str) -> str | None:
    req = runs / name / "scratch_request.json"
    if not req.is_file():
        return None
    st = json.loads(req.read_text(encoding="utf-8")).get("style") or {}
    return (st.get("gen") or {}).get("theme") if isinstance(st, dict) else None


KNOWN_BAND = re.compile(r"(≤\d+) как у людей")


def known_words(ln: str, ru: bool) -> str:
    """3.58: «как у людей …» / «как у карты людей» / «people's map» as the record says them now (w.known, w.SOURCES)."""
    if "людей" not in ln and "people's" not in ln:
        return ln
    ln = KNOWN_BAND.sub(lambda m: f"{w.KNOWN[0 if ru else 1]} {m.group(1)}", ln)
    ln = ln.replace("как у людей ", w.KNOWN[0 if ru else 1] + " ")
    if ru:
        return ln.replace("как у карты людей", "как у известной карты")
    return ln.replace("dressed as people's map", "dressed as the well-known map").replace("as the people's map",
                                                                                        "as on the well-known map")


ROUND_MADE = re.compile(r"углов (\d+), полукруглых торцов (\d+), возвышений (\d+)")


def _pairs(*tables) -> list[tuple[str, str]]:
    """(ru, en) of the tables' values, the longest Russian first (a phrase never cut by a shorter one inside it)."""
    out = {}
    for tb in tables:
        for v in (tb.values() if isinstance(tb, dict) else [tb]):
            if v[0] and v[0] != v[1]:
                out[v[0]] = v[1]
    return sorted(out.items(), key=lambda x: -len(x[0]))


POWERUP_WORDS = _pairs(w.SITES, w.POWERUP_SHORT, w.ACCESS, w.CYCLE)
ROUND_WORDS = _pairs(w.ROUND, w.NONE)
EDGE_WORDS = _pairs(w.EDGES)


def english_rows(ln: str) -> str:
    """3.58 addendum: an English description's rows that the record wrote in Russian, in English (numbers kept)."""
    def swap(text: str, pairs) -> str:
        for a, b in pairs:
            text = text.replace(a, b)
        return text
    m = ROW.match(ln)
    if not m:
        return ln
    label, a, b = m.group(1), m.group(2), m.group(3)
    if label == "Powerups":
        a, b = swap(a, POWERUP_WORDS), swap(b, POWERUP_WORDS)
    elif label == "Round shapes":
        a = swap(a, ROUND_WORDS)
        b = ROUND_MADE.sub(lambda x: f"rounded corners {x.group(1)}, round ends {x.group(2)}, podiums {x.group(3)}", b)
    elif label == "Edges":
        a = swap(a, EDGE_WORDS)
        b = b.replace(" края над пустотой", " of the edge over the void")
    elif label == "Spawns at height":
        a = a.replace("(план ", "(plan ")
    elif label == "Floor over floor":
        a = re.sub(r"^не меньше (\d+%)$", r"\1 at least", a)
    else:
        return ln
    return f"  {label}: {a} → {b}"


CLASS = re.compile(r"\b(weapon|item)[_ ]([a-z]+(?:[_ ](?!—)[a-z]+)?)\b")


def class_words(x, ru: bool) -> str:
    """«weapon railgun», «weapon_railgun», «item_armor_body» by the item's name; a second word that is not the class's
    («weapon_railgun under») is kept as it was."""
    words = x.group(2).replace(" ", "_").split("_")
    for n in (len(words), 1):
        cls = f"{x.group(1)}_{'_'.join(words[:n])}"
        if cls in w.ITEMS:
            rest = x.group(2)[len("_".join(words[:n])):]
            return w.item(cls, ru).lower() + rest
    return x.group(0)


def redo(text: str, ru: bool, theme: str | None) -> str:
    lines = text.split("\n")
    shapes = [ROW.match(ln).group(2).strip() for ln in lines
              if ROW.match(ln) and ROW.match(ln).group(1) == w.LABELS["shape"][0 if ru else 1]]
    skip = w.SPACE_SKIP if "space" in shapes else w.TOWER_SKIP if "tower" in shapes else set()
    label_key = {v[0 if ru else 1]: k for k, v in w.LABELS.items()}
    out = []
    for ln in lines:
        ln = known_words(ln, ru)
        if not ru:
            ln = english_rows(ln)
        if ln.startswith("  Главные предметы:") or ln.startswith("  Powerups:"):
            ln = SITES.sub(lambda x: " — " + w.pick(w.SITES, x.group(1), ru), ln)
        # 3.67 (his mg_new_56432 of 12.11, made by 3.66): a prize in a nook or fallen back said by its class -
        # «weapon railgun — в нише», «вместо: weapon_railgun под водой» - by its name
        if ln.startswith(("  Главные предметы:", "  Powerups:", "  Не сделано: призы", "  Not made: prizes")):
            ln = CLASS.sub(lambda x: class_words(x, ru), ln)
        m = HEAD.match(ln)
        if m:
            mode = m.group(3).lower()
            rest = m.group(4)
            src = rest.split(" ")[0] if rest.split(" ")[0] in w.SOURCES else None
            dressing = w.source(src, theme, [], ru) + rest[len(src):] if src else rest
            out.append(f"{m.group(1)}: {w.players(int(m.group(2)), ru)}, {w.pick(w.MODES, mode, ru, m.group(3))}, {dressing}.")
            continue
        m = ROW.match(ln)
        if m:
            label, a, b = m.group(1), m.group(2), m.group(3)
            key = label_key.get(label)
            if key in skip:
                continue
            if key:
                got = w.value(key, b.strip(), ru)
                if key == "pad_reach" and b.strip() == "0":
                    got = "не измерено" if ru else "not measured"      # 3.52-3.56 did not measure it on the finished map
                out.append(f"  {label}: {w.value(key, a.strip(), ru)} → {got}")
                continue
            if label in ITEM_KEYS:
                out.append(f"  {w.item(ITEM_KEYS[label], ru)}: {a} → {b}")
                continue
            out.append(ln)
            continue
        m = NOT_MADE.match(ln)
        if m:
            import mapgen_scratch as sc
            names = sc.MECH_RU if ru else sc.MECH_EN
            if m.group(2) in names:
                out.append(f"{m.group(1)}{names[m.group(2)]}: {m.group(3)}")
                continue
        m = FAILED.match(ln)
        if m and not re.match(r"^\d+ —|^\d+ -", m.group(2)):
            out.append("Проверка карты с нуля: не всё прошло — что именно и почему, сказано в «Проверках карты»." if ru
                       else "From-scratch check: not all passed - which and why, in the map's checks.")
            continue
        out.append(ln)
    return "\n".join(out)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    desc, runs = a.data / "descriptions", a.data / "runs"
    changed = 0
    for p in sorted(desc.glob("*.txt")):
        m = re.match(r"^(.+)\.(ru|en)\.txt$", p.name)
        if not m:
            continue
        text = p.read_text(encoding="utf-8")
        if "Сделано с нуля:" not in text and "Made from scratch:" not in text:
            continue
        new = redo(text, m.group(2) == "ru", theme_of(runs, m.group(1)))
        if new == text:
            continue
        changed += 1
        print(f"{p.name}: {sum(1 for x, y in zip(text.split(chr(10)), new.split(chr(10))) if x != y)}+ lines")
        if not a.dry:
            keep = p.with_name(p.name + ".before_words")
            if not keep.exists():
                keep.write_text(text, encoding="utf-8")
            p.write_text(new, encoding="utf-8")
    print(f"{changed} descriptions {'would change' if a.dry else 'rewritten'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
