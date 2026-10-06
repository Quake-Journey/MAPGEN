#!/usr/bin/env python3
"""Format-neutral Quake II authoring fixtures for MAPGEN-1 (phase M0).

These helpers emit Valve 220 `.map` text and minimal `.wal` texture stubs. They
depend on the Quake II authoring FORMAT, never on the compiler under
qualification: an artifact produced by an unqualified compiler may not be its
own golden oracle (contract section 17), so the inputs and the expectations must
both be built independently of it.

Format facts used here, all verified against the C0 quarantine checkout of
qbism/q2tools-220 @ 07d8d893 and against inc/format/bsp.h in this repository:

  * `"mapversion" "220"` in worldspawn selects the Valve 220 texture axes
    (q2tools-220 `src/map.c:565,858-860`);
  * a Valve 220 face is
        ( p1 ) ( p2 ) ( p3 ) TEX [ ux uy uz uoff ] [ vx vy vz voff ] rot su sv
    (`src/map.c:571-620`);
  * three OPTIONAL trailing integers `contents flags value` override whatever
    the texture's `.wal` declares (`src/map.c:627-634`). Emitting them makes a
    fixture's collision semantics explicit in the source text instead of
    implicit in a binary asset, which is what "format-neutral" has to mean for
    a validator's expectations;
  * `miptex_t` is name[32], width, height, offsets[4], animname[32], flags,
    contents, value, followed by four mip levels of 8-bit indices
    (`src/qfiles.h:194-202`).

Geometry convention: brushes are axis-aligned boxes given as (mins, maxs) in
Quake units, and each of the six faces is emitted with a plane whose normal
points OUT of the solid, which is what the compilers expect. The compiler
derives that normal as (p0 - p1) x (p2 - p1) (q2tools-220 `src/map.c:245-257`),
so the ORDER of the three points is load-bearing, not decorative: the first
version of this file had the two X faces wound the wrong way, every brush came
out with no volume, and only a real compile revealed it - the text was valid
Valve 220 the whole time.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# Quake II content flags (inc/format/bsp.h and q2tools-220 src/qfiles.h agree).
CONTENTS_SOLID = 1
CONTENTS_WINDOW = 2
CONTENTS_AUX = 4
CONTENTS_LAVA = 8
CONTENTS_SLIME = 16
CONTENTS_WATER = 32
CONTENTS_MIST = 64
CONTENTS_PLAYERCLIP = 0x10000
CONTENTS_MONSTERCLIP = 0x20000

# Surface flags.
SURF_LIGHT = 0x1
SURF_SLICK = 0x2
SURF_SKY = 0x4
SURF_WARP = 0x8
SURF_TRANS33 = 0x10
SURF_TRANS66 = 0x20
SURF_FLOWING = 0x40
SURF_NODRAW = 0x80
SURF_HINT = 0x100
SURF_SKIP = 0x200

# The six axis-aligned face directions, each as three points on the plane in
# clockwise order when viewed from OUTSIDE the box, plus the texture axes to use.
# Order is fixed so regeneration is byte-identical.
_FACE_DIRS = (
    ("up", (0, 0, 1)),
    ("down", (0, 0, -1)),
    ("north", (0, 1, 0)),
    ("south", (0, -1, 0)),
    ("east", (1, 0, 0)),
    ("west", (-1, 0, 0)),
)


def _fmt(v: float) -> str:
    """Locale-independent, negative-zero-free number formatting.

    Contract section 10 requires locale-independent serialization and
    normalized negative zero. Doing it here means the fixtures themselves obey
    the determinism rule they exist to test.
    """
    if v == int(v):
        iv = int(v)
        if iv == 0:
            iv = 0  # kills -0
        return str(iv)
    text = f"{v:.6f}".rstrip("0").rstrip(".")
    if text in ("-0", "-0.0"):
        text = "0"
    return text


def _pt(p: tuple[float, float, float]) -> str:
    return f"( {_fmt(p[0])} {_fmt(p[1])} {_fmt(p[2])} )"


@dataclass(frozen=True)
class FaceOverride:
    """Explicit contents/flags/value for one named face direction."""

    texture: str | None = None
    contents: int | None = None
    flags: int | None = None
    value: int | None = None


@dataclass
class Box:
    """An axis-aligned solid box, emitted as one brush."""

    mins: tuple[float, float, float]
    maxs: tuple[float, float, float]
    texture: str = "e1u1/c_met5_2"
    contents: int = CONTENTS_SOLID
    flags: int = 0
    value: int = 0
    overrides: dict[str, FaceOverride] = field(default_factory=dict)

    def face_points(self, direction: tuple[int, int, int]):
        x0, y0, z0 = self.mins
        x1, y1, z1 = self.maxs
        dx, dy, dz = direction
        if dz == 1:
            return ((x0, y0, z1), (x0, y1, z1), (x1, y1, z1))
        if dz == -1:
            return ((x0, y1, z0), (x0, y0, z0), (x1, y0, z0))
        if dy == 1:
            return ((x1, y1, z1), (x0, y1, z1), (x0, y1, z0))
        if dy == -1:
            return ((x0, y0, z1), (x1, y0, z1), (x1, y0, z0))
        if dx == 1:
            return ((x1, y0, z1), (x1, y1, z1), (x1, y1, z0))
        return ((x0, y1, z1), (x0, y0, z1), (x0, y0, z0))

    @staticmethod
    def texture_axes(direction: tuple[int, int, int]):
        """Valve 220 U/V axes for an axis-aligned face."""
        dx, dy, dz = direction
        if dz:
            return (1, 0, 0), (0, -1, 0)
        if dy:
            return (1, 0, 0), (0, 0, -1)
        return (0, 1, 0), (0, 0, -1)

    def emit(self) -> list[str]:
        lines = ["{"]
        for name, direction in _FACE_DIRS:
            ov = self.overrides.get(name, FaceOverride())
            tex = ov.texture if ov.texture is not None else self.texture
            contents = ov.contents if ov.contents is not None else self.contents
            flags = ov.flags if ov.flags is not None else self.flags
            value = ov.value if ov.value is not None else self.value
            p1, p2, p3 = self.face_points(direction)
            u, v = self.texture_axes(direction)
            lines.append(
                f"{_pt(p1)} {_pt(p2)} {_pt(p3)} {tex} "
                f"[ {_fmt(u[0])} {_fmt(u[1])} {_fmt(u[2])} 0 ] "
                f"[ {_fmt(v[0])} {_fmt(v[1])} {_fmt(v[2])} 0 ] "
                f"0 1 1 {contents} {flags} {value}"
            )
        lines.append("}")
        return lines


@dataclass
class Entity:
    """A point or brush entity. Key order is preserved for determinism."""

    classname: str
    keys: list[tuple[str, str]] = field(default_factory=list)
    brushes: list[Box] = field(default_factory=list)

    def emit(self) -> list[str]:
        lines = ["{", f'"classname" "{self.classname}"']
        for key, value in self.keys:
            lines.append(f'"{key}" "{value}"')
        for brush in self.brushes:
            lines.extend(brush.emit())
        lines.append("}")
        return lines


@dataclass
class MapFixture:
    """One authoring fixture: worldspawn plus entities."""

    name: str
    description: str
    worldspawn_keys: list[tuple[str, str]] = field(default_factory=list)
    world_brushes: list[Box] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)

    def emit(self) -> str:
        world = Entity("worldspawn", keys=[("mapversion", "220")] + self.worldspawn_keys)
        world.brushes = self.world_brushes
        lines: list[str] = []
        lines.extend(world.emit())
        for ent in self.entities:
            lines.extend(ent.emit())
        # A trailing newline and Unix endings keep regeneration byte-stable on a
        # tree that mixes CRLF and LF.
        return "\n".join(lines) + "\n"

    def textures(self) -> set[str]:
        names: set[str] = set()
        for box in list(self.world_brushes) + [b for e in self.entities for b in e.brushes]:
            names.add(box.texture)
            for ov in box.overrides.values():
                if ov.texture:
                    names.add(ov.texture)
        return names


def hollow_room(
    inner_mins: tuple[float, float, float],
    inner_maxs: tuple[float, float, float],
    thickness: float = 16.0,
    texture: str = "e1u1/c_met5_2",
    floor_texture: str | None = None,
    ceiling_texture: str | None = None,
    omit: str | None = None,
) -> list[Box]:
    """Six slabs forming a sealed room around the given interior volume.

    `omit` drops one slab by name, which is how the leak fixture is built: the
    same generator produces the sealed and the leaking case, so the difference
    between them is exactly one wall and nothing else.
    """
    x0, y0, z0 = inner_mins
    x1, y1, z1 = inner_maxs
    t = thickness
    slabs = {
        "floor": Box((x0 - t, y0 - t, z0 - t), (x1 + t, y1 + t, z0), texture=floor_texture or texture),
        "ceiling": Box((x0 - t, y0 - t, z1), (x1 + t, y1 + t, z1 + t), texture=ceiling_texture or texture),
        "west": Box((x0 - t, y0 - t, z0), (x0, y1 + t, z1), texture=texture),
        "east": Box((x1, y0 - t, z0), (x1 + t, y1 + t, z1), texture=texture),
        "south": Box((x0, y0 - t, z0), (x1, y0, z1), texture=texture),
        "north": Box((x0, y1, z0), (x1, y1 + t, z1), texture=texture),
    }
    if omit is not None:
        if omit not in slabs:
            raise ValueError(f"unknown slab {omit!r}; expected one of {sorted(slabs)}")
        del slabs[omit]
    # Fixed emission order regardless of the omission, for byte-stable output.
    order = ("floor", "ceiling", "west", "east", "south", "north")
    return [slabs[k] for k in order if k in slabs]


def write_pcx_palette(path, fill: int = 0x20) -> bytes:
    """Write a minimal but structurally valid 8-bit PCX carrying a palette.

    The LIGHT pass needs `<moddir>pics/colormap.pcx` to turn 8-bit texels into
    RGB reflectivity (q2tools-220 `src/patches.c:147-161`) and calls
    `Error()` - a hard exit - when it is missing. So the game palette is a
    TARGET-MANIFEST dependency of the compiler, not just of the game, and the
    job-local mirror must carry it.

    A fixture must not copy the retail `colormap.pcx`: contract section 15
    forbids copying game pixels into fixtures or packages, and depending on the
    PO's installed data would make the fixture unrunnable elsewhere. This
    writes its own.

    Loader constraints honoured (`src/lbmlib.c:378-417`): manufacturer 0x0A,
    version 5, RLE encoding, 8 bits per pixel, xmax < 640, ymax < 480, and the
    palette in the LAST 768 bytes of the file.
    """
    width, height = 64, 64
    header = bytearray(128)
    header[0] = 0x0A          # manufacturer
    header[1] = 5             # version
    header[2] = 1             # encoding: RLE
    header[3] = 8             # bits per pixel
    header[4:6] = (0).to_bytes(2, "little")            # xmin
    header[6:8] = (0).to_bytes(2, "little")            # ymin
    header[8:10] = (width - 1).to_bytes(2, "little")   # xmax
    header[10:12] = (height - 1).to_bytes(2, "little")  # ymax
    header[12:14] = (72).to_bytes(2, "little")         # hres
    header[14:16] = (72).to_bytes(2, "little")         # vres
    header[65] = 1                                     # color planes
    header[66:68] = width.to_bytes(2, "little")        # bytes per line
    header[68:70] = (1).to_bytes(2, "little")          # palette type

    # RLE body: one full-width run per scanline.
    body = bytearray()
    remaining_per_row = width
    row = bytearray()
    left = remaining_per_row
    while left:
        run = min(left, 63)
        row += bytes([0xC0 | run, fill])
        left -= run
    body += row * height

    # 256-entry palette: a deterministic grayscale ramp. Reflectivity derived
    # from it is uniform, which is exactly what a fixture wants - no lighting
    # result should depend on an arbitrary palette choice.
    palette = bytearray()
    for i in range(256):
        v = i
        palette += bytes([v, v, v])

    data = bytes(header) + bytes(body) + b"\x0c" + bytes(palette)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return data


def write_wal(
    path,
    name: str,
    width: int = 16,
    height: int = 16,
    flags: int = 0,
    contents: int = 0,
    value: int = 0,
    animname: str = "",
    fill: int = 0x2F,
) -> bytes:
    """Write a minimal but structurally valid `.wal`.

    Real texture pixels are irrelevant to a compiler fixture - what matters is
    that the file exists, that its header declares the flags/contents the
    compiler will read, and that the four mip offsets are consistent. Contract
    section 15 forbids copying real texture pixels anywhere, so a fixture must
    synthesize its own.
    """
    header = 32 + 4 + 4 + 16 + 32 + 4 + 4 + 4  # 100 bytes
    sizes = [(width >> i) * (height >> i) for i in range(4)]
    offsets = []
    cursor = header
    for size in sizes:
        offsets.append(cursor)
        cursor += size
    blob = bytearray()
    blob += name.encode("ascii", "strict").ljust(32, b"\0")[:32]
    blob += struct.pack("<II", width, height)
    blob += struct.pack("<4I", *offsets)
    blob += animname.encode("ascii", "strict").ljust(32, b"\0")[:32]
    blob += struct.pack("<iii", flags, contents, value)
    assert len(blob) == header, f"header is {len(blob)} bytes, expected {header}"
    for size in sizes:
        blob += bytes([fill]) * size
    data = bytes(blob)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return data
