r"""How people's maps look, measured from their compiled BSP: which textures they wear by role, how many, what colour
and brightness, what colour their light is, and how bright a surface comes out on screen (texture x lightmap).

The PO, 05.11, of the 3.41 maps from scratch: «монохромное», «глаза выбеливают твои карты», «посмотри как выглядят
q2dm*, q2duel*, ztn2dm*, koldduel1, omf, ptrip, match1, kaktus - где ты видишь такое?». The maps from scratch wore the
pack's grey photographs (lum 124..150) under white light; people's maps wear dark coloured textures (lum ~60..90) under
tinted light. This measure is the reference the style of a map from scratch is taken from and checked against.

    python tools/mapgen_people_style.py --write            # measure PEOPLE, write tools/mapgen_people_style.json
    python tools/mapgen_people_style.py maps/x.bsp ...     # measure any maps, print the rows

Texture colour: the mapgen pack from its catalogue (the jpg the game shows), every other texture from its .wal under
textures/ or inside the game's paks, decoded with the game's palette (pics/colormap.pcx).
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import struct
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
BASEQ2 = Path(os.environ.get("MAPGEN_GAME") or r"O:\Claude2\q2pro-release\baseq2")
DONORS = Path(os.environ.get("MAPGEN_DONORS") or r"O:\Claude2\MapgenStudio\engine\donors")
OUT = TOOLS / "mapgen_people_style.json"
CATALOGUE = TOOLS / "mapgen_textures_catalogue.json"

# the PO's list, 05.11 (the ones present in the game folder, its paks or the Studio's donors)
PEOPLE = {
    "duel": ["q2duel1", "q2duel2", "q2duel3", "q2duel4", "q2duel5", "q2duel6", "q2duel7", "q2duel8", "ztn2dm1",
             "ztn2dm2", "ztn2dm3", "ztn2dm4", "ztn2dm5", "koldduel1", "omf", "ptrip", "match1", "kaktus"],
    "ffa": ["q2dm1", "q2dm2", "q2dm3", "q2dm4", "q2dm5", "q2dm6", "q2dm7", "q2dm8"],
}

S_LIGHT, S_SKY, S_WARP, S_TRANS33, S_TRANS66, S_NODRAW = 0x1, 0x4, 0x8, 0x10, 0x20, 0x80


class Game:
    """The game's files: loose under baseq2, then its paks (later paks win, as the game loads them)."""

    def __init__(self, base: Path | None = None):
        # read when made, not when imported: the from-scratch run names its client's baseq2 (MAPGEN_GAME), where the
        # Studio's own generated textures lie (3.45)
        base = Path(base) if base else Path(os.environ.get("MAPGEN_GAME") or BASEQ2)
        self.base = base
        self.paks = {}
        for pk in sorted(glob.glob(str(base / "*.pak")) + glob.glob(str(base / "*.PAK")), key=str.lower):
            try:
                with open(pk, "rb") as f:
                    head = f.read(12)
                    if head[:4] != b"PACK":
                        continue
                    off, ln = struct.unpack_from("<ii", head, 4)
                    f.seek(off)
                    d = f.read(ln)
            except OSError:
                continue
            for i in range(ln // 64):
                name, o, l = struct.unpack_from("<56sii", d, 64 * i)
                self.paks[name.split(b"\0")[0].decode("latin1").lower()] = (pk, o, l)
        pal = self.read("pics/colormap.pcx")
        self.palette = pal[-768:] if pal else bytes(range(256)) * 3

    def read(self, name: str):
        p = self.base / name
        if p.is_file():
            return p.read_bytes()
        e = self.paks.get(name.lower())
        if e:
            with open(e[0], "rb") as f:
                f.seek(e[1])
                return f.read(e[2])
        return None


PNG_CACHE = TOOLS / "mapgen_people_textures.json"

# GDI+ through PowerShell: the mean colour of each picture, by drawing it into 16 x 16 with a high-quality filter
_MEANS_PS = r"""
Add-Type -AssemblyName System.Drawing
$out = New-Object System.Collections.Generic.List[string]
foreach ($p in Get-Content -LiteralPath $args[0]) {
  try {
    $img = [System.Drawing.Image]::FromFile($p)
    $bmp = New-Object System.Drawing.Bitmap 16, 16
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBilinear
    $g.DrawImage($img, 0, 0, 16, 16)
    $r = 0; $gg = 0; $b = 0
    for ($y = 0; $y -lt 16; $y++) { for ($x = 0; $x -lt 16; $x++) { $c = $bmp.GetPixel($x, $y); $r += $c.R; $gg += $c.G; $b += $c.B } }
    $out.Add("$p`t$($r / 256)`t$($gg / 256)`t$($b / 256)")
    $g.Dispose(); $bmp.Dispose(); $img.Dispose()
  } catch { }
}
Set-Content -LiteralPath $args[1] -Value $out -Encoding utf8
"""


def build_png_cache(game: "Game") -> dict:
    """The colour of every replacement picture the game shows instead of a .wal (Q2PRO draws a .png / .jpg of the
    same name when there is one: pak99_textures.pak holds 1782 of them for the stock textures) - extracted to a
    temporary folder and averaged by GDI+; written to tools/mapgen_people_textures.json."""
    import subprocess
    import tempfile
    names = {}
    for n in game.paks:
        if n.startswith("textures/") and n.endswith((".png", ".jpg")):
            names[n[len("textures/"):-4]] = n
    for p in (game.base / "textures").rglob("*"):
        if p.suffix.lower() in (".png", ".jpg") and p.is_file():
            rel = p.relative_to(game.base).as_posix().lower()
            names[rel[len("textures/"):-4]] = rel
    tmp = Path(tempfile.mkdtemp(prefix="mapgen_people_"))
    try:
        files = {}
        for k, (tex, rel) in enumerate(sorted(names.items())):
            b = game.read(rel)
            if not b:
                continue
            f = tmp / f"{k}{Path(rel).suffix}"
            f.write_bytes(b)
            files[str(f)] = tex
        (tmp / "list.txt").write_text("\n".join(files), encoding="utf-8")
        script = tmp / "means.ps1"
        script.write_text(_MEANS_PS, encoding="utf-8")
        subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script), str(tmp / "list.txt"),
                        str(tmp / "means.tsv")], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        cache = {}
        for line in (tmp / "means.tsv").read_text(encoding="utf-8-sig").splitlines():
            parts = line.split("\t")
            if len(parts) == 4 and parts[0] in files:
                cache[files[parts[0]]] = [round(float(x.replace(",", ".")), 1) for x in parts[1:]]
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    PNG_CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    return cache


_CAT = None
_PNG = None


def png_colours() -> dict:
    global _PNG
    if _PNG is None:
        _PNG = json.loads(PNG_CACHE.read_text(encoding="utf-8")) if PNG_CACHE.is_file() else {}
    return _PNG


def catalogue() -> dict:
    global _CAT
    if _CAT is None:
        c = json.loads(CATALOGUE.read_text(encoding="utf-8"))
        _CAT = {t["name"].lower(): t["rgb"] for t in c["textures"]}
    return _CAT


class Colours:
    def __init__(self, game: Game):
        self.game = game
        self.cache = {}

    def rgb(self, name: str):
        name = name.lower()
        if name in self.cache:
            return self.cache[name]
        # what the game draws: the pack's jpg, else a replacement picture of the same name, else the .wal
        rgb = catalogue().get(name) or png_colours().get(name)
        if rgb is None:
            b = self.game.read(f"textures/{name}.wal")
            if b and len(b) > 100:
                w, h = struct.unpack_from("<II", b, 32)
                off0 = struct.unpack_from("<I", b, 40)[0]
                px = b[off0:off0 + w * h]
                if px:
                    pal = self.game.palette
                    s = [0, 0, 0]
                    step = max(1, len(px) // 4096)
                    n = 0
                    for i in range(0, len(px), step):
                        p = px[i]
                        s[0] += pal[3 * p]
                        s[1] += pal[3 * p + 1]
                        s[2] += pal[3 * p + 2]
                        n += 1
                    rgb = [x / n for x in s]
        self.cache[name] = rgb
        return rgb


def lum(rgb) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def sat(rgb) -> float:
    mx = max(rgb)
    return 0.0 if mx <= 0 else (mx - min(rgb)) / mx


def hue(rgb) -> float:
    r, g, b = rgb
    return math.degrees(math.atan2(math.sqrt(3) * (g - b), 2 * r - g - b)) % 360


def faces(data: bytes):
    """Every drawn face: (texture, flags, role, area, lightmap mean rgb or None, smallest brush-like extent)."""
    L = [data[struct.unpack_from("<i", data, 8 + 8 * i)[0]:][:struct.unpack_from("<i", data, 12 + 8 * i)[0]]
         for i in range(19)]
    planes = [struct.unpack_from("<4fi", L[1], i * 20) for i in range(len(L[1]) // 20)]
    verts = [struct.unpack_from("<3f", L[2], i * 12) for i in range(len(L[2]) // 12)]
    tex = []
    for i in range(len(L[5]) // 76):
        v = struct.unpack_from("<8fii32si", L[5], i * 76)
        tex.append((v[:8], v[8], v[10].split(b"\0")[0].decode("latin1").lower()))
    edges = [struct.unpack_from("<HH", L[11], i * 4) for i in range(len(L[11]) // 4)]
    surf = [struct.unpack_from("<i", L[12], i * 4)[0] for i in range(len(L[12]) // 4)]
    lm = L[7]
    # the world model's faces only (doors and lifts are brush models; they count too, they are seen)
    for i in range(len(L[6]) // 20):
        pn, side, fe, ne, ti, s0, s1, s2, s3, lofs = struct.unpack_from("<HhiHh4Bi", L[6], i * 20)
        vecs, flags, name = tex[ti]
        pts = [verts[edges[abs(surf[fe + k])][0 if surf[fe + k] >= 0 else 1]] for k in range(ne)]
        a = [0.0, 0.0, 0.0]
        for k in range(1, len(pts) - 1):
            u = [pts[k][j] - pts[0][j] for j in range(3)]
            w = [pts[k + 1][j] - pts[0][j] for j in range(3)]
            a[0] += u[1] * w[2] - u[2] * w[1]
            a[1] += u[2] * w[0] - u[0] * w[2]
            a[2] += u[0] * w[1] - u[1] * w[0]
        area = 0.5 * math.sqrt(sum(x * x for x in a))
        nz = planes[pn][2] * (-1 if side else 1)
        role = "floor" if nz > 0.7 else "ceil" if nz < -0.7 else "wall"
        if flags & S_SKY:
            role = "sky"
        elif flags & S_NODRAW:
            continue
        elif flags & S_LIGHT and not flags & S_WARP:
            role = "lamp"
        elif flags & S_WARP:
            role = "liquid"
        elif flags & (S_TRANS33 | S_TRANS66):
            role = "glass"
        light = None
        if lofs >= 0 and s0 != 255 and role in ("floor", "wall", "ceil"):
            ss = [p[0] * vecs[0] + p[1] * vecs[1] + p[2] * vecs[2] + vecs[3] for p in pts]
            ts = [p[0] * vecs[4] + p[1] * vecs[5] + p[2] * vecs[6] + vecs[7] for p in pts]
            w = math.ceil(max(ss) / 16) - math.floor(min(ss) / 16) + 1
            h = math.ceil(max(ts) / 16) - math.floor(min(ts) / 16) + 1
            n = w * h
            blob = lm[lofs:lofs + 3 * n]
            if len(blob) == 3 * n and n:
                light = [sum(blob[j::3]) / n for j in range(3)]
        # how thin the face is: its smaller side (a trim's face is a strip)
        if pts:
            span = [max(p[j] for p in pts) - min(p[j] for p in pts) for j in range(3)]
            span.sort()
            thin = span[1]
        else:
            thin = 0
        yield name, flags, role, area, light, thin


def measure(path: Path, colours: Colours) -> dict:
    data = path.read_bytes()
    by_role = {}
    seen = []                      # (area, on-screen lum)
    tex_area = {}
    lights = [0.0, 0.0, 0.0, 0.0]  # area-weighted lightmap rgb + area
    thin_area = {}
    for name, flags, role, area, light, thin in faces(data):
        if role not in ("floor", "wall", "ceil") or area <= 0:
            continue
        by_role.setdefault(role, {}).setdefault(name, 0.0)
        by_role[role][name] += area
        tex_area[name] = tex_area.get(name, 0.0) + area
        if thin <= 24 and role == "wall":
            thin_area[name] = thin_area.get(name, 0.0) + area
        rgb = colours.rgb(name)
        if light is not None:
            for j in range(3):
                lights[j] += light[j] * area
            lights[3] += area
            if rgb:
                # the GL renderer: texture x lightmap (lightmap 128 = the texture as drawn ... 255 = twice), clamped
                on = [min(255.0, rgb[j] * light[j] / 128.0) for j in range(3)]
                seen.append((area, lum(on)))
    tot = sum(tex_area.values())
    known = {n: a for n, a in tex_area.items() if colours.rgb(n)}
    kt = sum(known.values()) or 1.0
    top = sorted(tex_area.items(), key=lambda kv: -kv[1])

    def wmean(f, items):
        s = sum(a for _, a in items) or 1.0
        return sum(f(n) * a for n, a in items) / s
    seen.sort(key=lambda t: t[1])
    sa = sum(a for a, _ in seen) or 1.0

    def seen_q(q):
        acc = 0.0
        for a, v in seen:
            acc += a
            if acc >= q * sa:
                return v
        return seen[-1][1] if seen else 0.0
    light_rgb = [lights[j] / max(1.0, lights[3]) for j in range(3)]
    hues = {}
    for n, a in known.items():
        rgb = colours.rgb(n)
        if sat(rgb) >= 0.15:
            k = int(hue(rgb) // 30)
            hues[k] = hues.get(k, 0.0) + a
    roles = {}
    for r, d in by_role.items():
        it = [(n, a) for n, a in d.items() if colours.rgb(n)]
        rt = sum(d.values()) or 1.0
        top6 = sorted(d.items(), key=lambda kv: -kv[1])[:6]
        roles[r] = {"share": round(sum(d.values()) / tot, 3),
                    "textures": [n for n, _ in top6], "shares": [round(a / rt, 3) for _, a in top6],
                    "lum": round(wmean(lambda n: lum(colours.rgb(n)), it), 1) if it else None,
                    "sat": round(wmean(lambda n: sat(colours.rgb(n)), it), 3) if it else None}
    return {
        "map": path.stem,
        "textures": sum(1 for _, a in top if a / tot >= 0.005),
        "top1": round(top[0][1] / tot, 3) if top else 0,
        "top3": round(sum(a for _, a in top[:3]) / tot, 3),
        "coloured": round(sum(a for n, a in known.items() if sat(colours.rgb(n)) >= 0.2) / kt, 3),
        "tex_lum": round(wmean(lambda n: lum(colours.rgb(n)), list(known.items())), 1),
        "tex_sat": round(wmean(lambda n: sat(colours.rgb(n)), list(known.items())), 3),
        "hues": sorted(k for k, a in hues.items() if a / kt >= 0.05),
        "light_rgb": [round(x, 1) for x in light_rgb],
        "light_sat": round(sat(light_rgb), 3),
        "seen_p50": round(seen_q(0.5), 1),
        "seen_p90": round(seen_q(0.9), 1),
        "seen_white": round(sum(a for a, v in seen if v >= 200) / sa, 3),
        "known": round(kt / tot, 3) if tot else 0,
        "roles": roles,
        "trims": [n for n, _ in sorted(thin_area.items(), key=lambda kv: -kv[1])[:4]],
    }


def find_map(name: str, game: Game):
    for p in (game.base / "maps" / f"{name}.bsp", DONORS / f"{name}.bsp"):
        if p.is_file():
            return p
    b = game.read(f"maps/{name}.bsp")
    if b:
        tmp = Path(os.environ.get("TEMP", ".")) / f"mapgen_people_{name}.bsp"
        tmp.write_bytes(b)
        return tmp
    return None


def bands(rows: list) -> dict:
    """Each measure's range over people's maps (min, max) - the band a map from scratch is held to."""
    out = {}
    for k in ("textures", "top1", "coloured", "tex_lum", "tex_sat", "light_sat", "seen_p50", "seen_p90", "seen_white"):
        vs = [r[k] for r in rows if r.get("known", 0) >= 0.7]
        if vs:
            out[k] = [min(vs), max(vs)]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("maps", nargs="*")
    ap.add_argument("--write", action="store_true", help="measure the PO's list and write the reference json")
    ap.add_argument("--pictures", action="store_true", help="first average the game's replacement pictures")
    a = ap.parse_args(argv)
    game = Game()
    if a.pictures:
        print(f"{len(build_png_cache(game))} replacement pictures averaged")
    colours = Colours(game)
    if a.write:
        ref = {"_about": "people's maps as they look (tools/mapgen_people_style.py); the PO's list 05.11",
               "maps": {}, "bands": {}}
        for cls, names in PEOPLE.items():
            rows = []
            for n in names:
                p = find_map(n, game)
                if p is None:
                    print(f"{n}: not found", file=sys.stderr)
                    continue
                r = measure(p, colours)
                r["map"] = n
                r["class"] = cls
                ref["maps"][n] = r
                rows.append(r)
                if str(p).startswith(os.environ.get("TEMP", "\0")):
                    p.unlink(missing_ok=True)
            ref["bands"][cls] = bands(rows)
        ref["bands"]["all"] = bands(list(ref["maps"].values()))
        OUT.write_text(json.dumps(ref, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        rows = list(ref["maps"].values())
        print(f"wrote {OUT} ({len(rows)} maps)")
    else:
        rows = []
        for m in a.maps:
            p = Path(m) if Path(m).is_file() else find_map(m, game)
            if p is None:
                print(f"{m}: not found", file=sys.stderr)
                continue
            rows.append(measure(p, colours))
    print(f"{'map':14s} {'tex':>3s} {'top1':>5s} {'colrd':>5s} {'tlum':>5s} {'tsat':>5s} {'lsat':>5s} "
          f"{'seen50':>6s} {'seen90':>6s} {'white':>5s} {'known':>5s}  light")
    for r in rows:
        print(f"{r['map']:14s} {r['textures']:3d} {r['top1']:5.0%} {r['coloured']:5.0%} {r['tex_lum']:5.0f} "
              f"{r['tex_sat']:5.2f} {r['light_sat']:5.2f} {r['seen_p50']:6.0f} {r['seen_p90']:6.0f} "
              f"{r['seen_white']:5.0%} {r['known']:5.0%}  {r['light_rgb']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
