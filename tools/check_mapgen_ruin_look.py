r"""The ruin's look (Fable's brief 12, ledger row 412n) - driver only, no compile.

The PO, 07.10, on mg_b11_q2dm1 and mg_b11_q3t2: «много повторяющихся текстур разрушений, это выглядит механически»
(quake206..211: the same hole four times up one wall, a grid of blobs over a floor) and «на полах лежат полосатые
бруски-куски, без текстур, аляпистые» (quake212..214: boxes in a slatted panel the pack had called stone). On the
generated q2dm1 (20 %, variant 42), q2dm1 and q3t2 as they are, the destroy driver at 100 (seed 42):
* (a) no tiled stamp: a copy drawn with a hole, a crater, a burn or one of the PO's pictures is worn by placed plates
  alone (detail brushes, one face of each) - every face of the map's own brushes wears a crack network or nothing;
* (b) the cracked share of the map's own drawn faces at most 0.40;
* (c) the patches: some on every map, no two within 256, each a plate 1 thick on one face;
* (d) the debris: chunks - at least nine in ten of the small detail brushes have 8 or 9 sides (a box cut at its
  corners), none over 34 high; each wears a dusted copy of a texture the map itself draws, or an isotropic pack rock
  (its grain under 0.6) - never a directional picture (a corridor's fill, a block by design, is counted apart);
* (e) the copies drawn at the game's own resolution where the game has the original's picture (its .png).
RED, two, each in a sandbox: the stamps back in the crack list - (a) goes red; the chunks' corner cuts taken out -
(d) goes red.

    python tools/check_mapgen_ruin_look.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_destroy as md  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

REPO = TOOLS.parent
DONORS = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\MapgenStudio\engine\donors")
GENERATED = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\fixtures\gen_q2dm1_20_42.bsp")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\ruin_look")
CASES = {"generated q2dm1": GENERATED, "q2dm1": DONORS / "q2dm1.bsp", "q3t2": DONORS / "q3t2.bsp"}
DETAIL = 0x08000000
NETWORK = re.compile(r"^(crack|dust)\d+$")
FAILED = TOTAL = 0
SIDE = re.compile(r"^\(\s*([-\d.e]+)\s+([-\d.e]+)\s+([-\d.e]+)\s*\)\s*\(\s*([-\d.e]+)\s+([-\d.e]+)\s+([-\d.e]+)\s*\)\s*"
                  r"\(\s*([-\d.e]+)\s+([-\d.e]+)\s+([-\d.e]+)\s*\)\s*(\S+)\s*\[(.*?)\]\s*\[(.*?)\]\s*(\S+)\s+(\S+)\s+(\S+)"
                  r"\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*$")


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED, TOTAL
    TOTAL += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def brushes(mapfile: Path) -> list[dict]:
    """The world's brushes of a Valve 220 .map: each its sides (plane, texture, contents) and its corners."""
    out, cur, depth, entity = [], None, 0, 0
    for line in mapfile.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s == "{":
            depth += 1
            if depth == 1:
                entity += 1
            if depth == 2:
                cur = []
            continue
        if s == "}":
            if depth == 2 and cur is not None and entity == 1:
                out.append(shape(cur))
            depth -= 1
            continue
        if depth == 2 and cur is not None:
            m = SIDE.match(s)
            if m:
                pts = [tuple(float(m.group(i + j)) for j in range(3)) for i in (1, 4, 7)]
                cur.append({"pts": pts, "tex": m.group(10), "contents": int(m.group(16))})
    return out


def plane_of(pts):
    """The compiler's own reading of a side's three points: normal (p0 - p1) x (p2 - p1), outward."""
    p0, p1, p2 = pts
    u = (p0[0] - p1[0], p0[1] - p1[1], p0[2] - p1[2])
    v = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    ln = sum(c * c for c in n) ** 0.5 or 1.0
    n = tuple(c / ln for c in n)
    return n, n[0] * p1[0] + n[1] * p1[1] + n[2] * p1[2]


def shape(sides: list[dict]) -> dict:
    """The brush's corners (every three planes' meeting point inside all of them) and its box."""
    planes = [plane_of(s["pts"]) for s in sides]
    corners = []
    for (n1, d1), (n2, d2), (n3, d3) in itertools.combinations(planes, 3):
        det = (n1[0] * (n2[1] * n3[2] - n2[2] * n3[1]) - n1[1] * (n2[0] * n3[2] - n2[2] * n3[0])
               + n1[2] * (n2[0] * n3[1] - n2[1] * n3[0]))
        if abs(det) < 1e-6:
            continue
        p = [(d1 * (n2[1] * n3[2] - n2[2] * n3[1]) - n1[1] * (d2 * n3[2] - n2[2] * d3) + n1[2] * (d2 * n3[1] - n2[1] * d3))
             / det,
             (n1[0] * (d2 * n3[2] - n2[2] * d3) - d1 * (n2[0] * n3[2] - n2[2] * n3[0]) + n1[2] * (n2[0] * d3 - d2 * n3[0]))
             / det,
             (n1[0] * (n2[1] * d3 - d2 * n3[1]) - n1[1] * (n2[0] * d3 - d2 * n3[0]) + d1 * (n2[0] * n3[1] - n2[1] * n3[0]))
             / det]
        if all(n[0] * p[0] + n[1] * p[1] + n[2] * p[2] <= d + 0.05 for n, d in planes):
            corners.append(p)
    lo = [min(c[a] for c in corners) for a in range(3)] if corners else [0, 0, 0]
    hi = [max(c[a] for c in corners) for a in range(3)] if corners else [0, 0, 0]
    real = sum(1 for n, d in planes if sum(1 for c in corners if abs(n[0] * c[0] + n[1] * c[1] + n[2] * c[2] - d) < 0.05) >= 3)
    return {"sides": sides, "lo": lo, "hi": hi, "faces": real,
            "detail": bool(sides and sides[0]["contents"] & DETAIL)}


def needs_of(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) >= 3:
            out[p[0]] = {"orig": p[1], "mask": p[2], "rep": int(p[3]) if len(p) > 3 else 1}
    return out


def run(exe: Path, src: Path, work: Path, tag: str, pack: Path, plist: Path) -> tuple[Path, Path, str]:
    into = work / "into"
    out = work / f"{tag}.map"
    needs = work / f"{tag}.needs.txt"
    r = subprocess.run([str(exe), str(src), str(out), "--destruction", "100", "--seed", "42", "--pack", str(plist),
                        "--needs", str(needs), "--game", str(md.GAME), "--masks", str(pack / "textures" / "mapgen" / "masks"),
                        "--into", str(into)], capture_output=True, text=True, errors="replace", timeout=3600)
    m = md.DESTROYED.search(r.stdout)
    return out, needs, (m.group(1).split(" refused ")[0] if m else (r.stdout + r.stderr)[-300:])


def judge(name: str, mapfile: Path, needs_path: Path, catalogue: dict, into: Path, report: bool = True) -> dict:
    bs = brushes(mapfile)
    needs = needs_of(needs_path)
    coh = {t["name"]: t.get("coherence", 0.0) for t in catalogue["textures"]}
    own_textures = {s["tex"] for b in bs if not b["detail"] for s in b["sides"]}
    stamp_on_map, stamp_plates = [], []
    cracked = drawn = 0
    for b in bs:
        stamps = [s for s in b["sides"] if s["tex"] in needs and not NETWORK.match(needs[s["tex"]]["mask"])]
        if stamps and (not b["detail"] or len(stamps) > 1):
            stamp_on_map.append(stamps[0]["tex"])
        if stamps and b["detail"]:
            stamp_plates.append(b)
        if not b["detail"]:
            for s in b["sides"]:
                tex = s["tex"]
                if tex.startswith("mgd/") and tex in needs and NETWORK.match(needs[tex]["mask"]):
                    cracked += 1
                    drawn += 1
                elif not re.search(r"clip|hint|skip|nodraw|trigger|origin|sky|water|wter|lava|slime|caulk", tex, re.I):
                    drawn += 1
    patches = [b for b in stamp_plates if min(b["hi"][a] - b["lo"][a] for a in range(3)) <= 1.05]
    mids = [[(b["lo"][a] + b["hi"][a]) / 2 for a in range(3)] for b in patches]
    close = min((sum((p[a] - q[a]) ** 2 for a in range(3)) ** 0.5 for p, q in itertools.combinations(mids, 2)),
                default=1e9)
    # the ruin's pieces: small detail brushes wearing one texture all over - a dusted copy or a pack texture (the
    # generated map's own detail, its faces cracked here and there, wears several)
    debris = [b for b in bs if b["detail"] and b not in stamp_plates
              and max(b["hi"][a] - b["lo"][a] for a in range(2)) <= 64.0
              and len({s["tex"] for s in b["sides"]}) == 1
              and (b["sides"][0]["tex"].startswith("mapgen/")
                   or (b["sides"][0]["tex"] in needs and needs[b["sides"][0]["tex"]]["mask"].startswith("dust")))]
    # a corridor's fill (the ruin kind: a block from wall to wall up to the ceiling) is a block by design, not debris
    fills = [b for b in debris if b["faces"] == 6 and b["hi"][2] - b["lo"][2] > 40.0]
    debris = [b for b in debris if b not in fills]
    cut = sum(1 for b in debris if b["faces"] >= 8)
    tall = [b for b in debris if b["hi"][2] - b["lo"][2] > 34.05]
    wrong = []
    for b in debris:
        tex = b["sides"][0]["tex"]
        if tex.startswith("mgd/"):
            n = needs.get(tex)
            if not n or not n["mask"].startswith("dust") or (n["orig"] not in own_textures
                                                            and not n["orig"].startswith("mapgen/")):
                wrong.append(tex)
        elif coh.get(tex, 1.0) >= 0.6:
            wrong.append(tex)
    # piles: debris whose middles lie within 64 of each other, grouped; sizes across (the larger of x, y extents)
    groups, seen = [], set()
    for i, b in enumerate(debris):
        if i in seen:
            continue
        grp, todo = [], [i]
        seen.add(i)
        while todo:
            k = todo.pop()
            grp.append(k)
            for j, c in enumerate(debris):
                if j not in seen and abs((debris[k]["lo"][2]) - c["lo"][2]) < 8 and all(
                        abs((debris[k]["lo"][a] + debris[k]["hi"][a]) / 2 - (c["lo"][a] + c["hi"][a]) / 2) < 64
                        for a in range(2)):
                    seen.add(j)
                    todo.append(j)
        groups.append(grp)
    # the copies whose original the game draws from a picture of its own (q3t2's textures have none)
    pictured = [t for t, n in needs.items() if md.game_file(md.GAME, f"textures/{n['orig']}.png") is not None]
    pngs = sum(1 for t in pictured if (into / "textures" / f"{t}.png").is_file())
    res = {"stamp_on_map": stamp_on_map, "share": cracked / max(1, drawn), "patches": len(patches), "close": close,
           "debris": len(debris), "cut": cut, "tall": len(tall), "wrong": wrong, "piles": len(groups), "pngs": pngs,
           "needs": len(needs)}
    if report:
        check(f"{name}: (a) no tiled stamp - every hole, crater, burn and picture copy on a placed plate alone",
              not stamp_on_map, f"{len(stamp_plates)} plates" + (f"; on the map's own faces: {stamp_on_map[:4]}"
                                                                  if stamp_on_map else ""))
        check(f"{name}: (b) the cracked share of the map's drawn faces at most 0.40", res["share"] <= 0.40,
              f"{cracked} of {drawn} = {res['share']:.2f}")
        check(f"{name}: (c) patches placed, 1 thick, none within 256 of another", len(patches) > 0 and close >= 256.0,
              f"{len(patches)} patches, the nearest two {close:.0f} apart")
        check(f"{name}: (d) debris are chunks (9 in 10 with 8..9 faces), none over 34 high, each in what broke",
              debris and cut >= 0.9 * len(debris) and not tall and not wrong,
              f"{len(debris)} pieces in {len(groups)} piles, {cut} cut, {len(tall)} tall; {len(fills)} corridor fills"
              + (f", wrong texture: {wrong[:3]}" if wrong else ""))
        check(f"{name}: (e) every copy drawn at the game's resolution where the game has the original's picture",
              pngs == len(pictured), f"{pngs} .png of {len(pictured)} copies with a pictured original"
              f" ({len(needs)} copies in all)")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    if a.work.exists():
        shutil.rmtree(a.work)
    (a.work / "green").mkdir(parents=True)
    pack = md.pack_dir(None)
    catalogue = json.loads((pack / "textures" / "mapgen" / "catalogue.json").read_text(encoding="utf-8"))
    plist = a.work / "pack.txt"
    md.pack_list(pack, plist)

    def prepare(work: Path) -> None:
        md.install(work / "into", pack)
        (work / "into" / "textures" / "mgd").mkdir(parents=True, exist_ok=True)

    prepare(a.work / "green")
    exe = md.driver(a.work / "green")
    for name, src in CASES.items():
        tag = name.replace(" ", "_")
        mapfile, needs, said = run(exe, src, a.work / "green", tag, pack, plist)
        print(f"  {name} at 100: {said}", flush=True)
        judge(name, mapfile, needs, catalogue, a.work / "green" / "into")
    if not a.no_red:
        before = hash_tree(REPO)
        box = Sandbox(REPO, "ruin_look")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            clean = target.read_bytes()
            masks = b'static const char *const MASKS[6] = { "crack1", "crack2", "crack3", "crack4", "crack5", "crack6" };'
            if check("RED: the crack list is where the mutation says", clean.count(masks) == 1):
                target.write_bytes(clean.replace(masks, b'static const char *const MASKS[6] = { "crack1", "hole1", '
                                                        b'"po01", "crack4", "po05", "soot1" };', 1))
                (a.work / "red_stamps").mkdir()
                prepare(a.work / "red_stamps")
                saved = md.REPO
                md.REPO = box.root
                try:
                    rexe = md.driver(a.work / "red_stamps")
                finally:
                    md.REPO = saved
                mapfile, needs, _ = run(rexe, GENERATED, a.work / "red_stamps", "gen", pack, plist)
                r = judge("red", mapfile, needs, catalogue, a.work / "red_stamps" / "into", report=False)
                check("RED: stamps in the crack list - tiled stamps on the map's own faces, (a) goes red",
                      len(r["stamp_on_map"]) > 0, f"{len(r['stamp_on_map'])} faces")
            cuts = b"const int cuts = 2 + (destroy_rand(d) < 0.5f ? 1 : 0);"
            if check("RED: the chunks' corner cuts are where the mutation says", clean.count(cuts) == 1):
                target.write_bytes(clean.replace(cuts, b"const int cuts = 0 * (destroy_rand(d) < 0.5f ? 1 : 0);", 1))
                (a.work / "red_cuts").mkdir()
                prepare(a.work / "red_cuts")
                saved = md.REPO
                md.REPO = box.root
                try:
                    rexe = md.driver(a.work / "red_cuts")
                finally:
                    md.REPO = saved
                mapfile, needs, _ = run(rexe, GENERATED, a.work / "red_cuts", "gen", pack, plist)
                r = judge("red", mapfile, needs, catalogue, a.work / "red_cuts" / "into", report=False)
                check("RED: without the cuts the debris are boxes again - (d) goes red",
                      r["debris"] > 0 and r["cut"] < 0.9 * r["debris"], f"{r['cut']} of {r['debris']} cut")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    print(f"{TOTAL - FAILED}/{TOTAL} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
