r"""The descriptions of maps from scratch written before 3.57, said in words (the PO, 07.11: «в русском описании … есть
анг формулировки в студии»): the head line («8 игроков, FFA, generated» → «8 игроков, общий бой, свои текстуры студии:
Завод»), the rows whose values were the request's keys («Форма: space → space», «Украшений на стенах: none», «Мостики:
some», «Дальность джампадов: medium», «Режим: ffa»), the items by the form's names («ARMOR_BODY» → «Красная броня»), an open
space's rows it has no part in left out, the failed rows' English names replaced by where they are said in words. Only
the words change: every measured number stays. The file is kept once as `<file>.before_words`.

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


def redo(text: str, ru: bool, theme: str | None) -> str:
    lines = text.split("\n")
    shapes = [ROW.match(ln).group(2).strip() for ln in lines
              if ROW.match(ln) and ROW.match(ln).group(1) == w.LABELS["shape"][0 if ru else 1]]
    skip = w.SPACE_SKIP if "space" in shapes else w.TOWER_SKIP if "tower" in shapes else set()
    label_key = {v[0 if ru else 1]: k for k, v in w.LABELS.items()}
    out = []
    for ln in lines:
        if ln.startswith("  Главные предметы:") or ln.startswith("  Powerups:"):
            ln = SITES.sub(lambda x: " — " + w.pick(w.SITES, x.group(1), ru), ln)
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
