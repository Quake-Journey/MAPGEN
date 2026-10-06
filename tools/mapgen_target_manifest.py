#!/usr/bin/env python3
"""MAPGEN-1 - what a texture name actually resolves to in a game directory.

Contract section 15 forbids emitting a material the target does not have, and
contract 17 records that a missing texture is only a WARNING inside the
compiler - so "it compiled" is not evidence that a map is textured. The set of
names that really resolve has to be known BEFORE a map is written, not
discovered from a warning afterwards.

This is the Python half of that. It reads the same two places the compiler
does - loose files under the game directory, and `pakN.pak` beside them - and
answers which `textures/<name>.wal` exist. The C adapter will ask the engine's
own VFS the same question; two implementations of one question is the pattern
the rest of MAPGEN already follows.

Usage:
    python tools/mapgen_target_manifest.py <gamedir> [--prefix e1u1]
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

PAK_ENTRY_BYTES = 64


def pak_entries(pak: Path) -> list[str]:
    """Every filename in one .pak, lower-cased with forward slashes."""
    data = pak.read_bytes()
    if len(data) < 12 or data[:4] != b"PACK":
        return []
    dir_offset, dir_size = struct.unpack_from("<II", data, 4)
    if dir_offset + dir_size > len(data):
        return []
    names = []
    for at in range(dir_offset, dir_offset + dir_size, PAK_ENTRY_BYTES):
        raw = data[at:at + 56]
        name = raw.split(b"\0", 1)[0].decode("latin-1")
        names.append(name.replace("\\", "/").lower())
    return names


def resolvable_textures(gamedir: Path) -> set[str]:
    """`<dir>/<name>` for every texture the compiler could load from here."""
    found: set[str] = set()

    root = gamedir / "textures"
    if root.is_dir():
        for wal in root.rglob("*.wal"):
            rel = wal.relative_to(root).with_suffix("")
            found.add(str(rel).replace("\\", "/").lower())

    # The compiler looks for pak0.pak, pak1.pak, ... beside the game directory
    # and stops at the first one missing, so the search follows that order.
    for index in range(100):
        pak = None
        for candidate in (gamedir / f"pak{index}.pak", gamedir / f"PAK{index}.PAK"):
            if candidate.is_file():
                pak = candidate
                break
        if pak is None:
            break
        for name in pak_entries(pak):
            if name.startswith("textures/") and name.endswith(".wal"):
                found.add(name[len("textures/"):-len(".wal")])

    return found


def has_colormap(gamedir: Path) -> bool:
    """The LIGHT pass calls Error() without pics/colormap.pcx."""
    if (gamedir / "pics" / "colormap.pcx").is_file():
        return True
    for index in range(100):
        pak = None
        for candidate in (gamedir / f"pak{index}.pak", gamedir / f"PAK{index}.PAK"):
            if candidate.is_file():
                pak = candidate
                break
        if pak is None:
            break
        if "pics/colormap.pcx" in pak_entries(pak):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gamedir")
    parser.add_argument("--prefix", default=None,
                        help="only names under this directory")
    parser.add_argument("--count", action="store_true",
                        help="print totals rather than names")
    args = parser.parse_args()

    gamedir = Path(args.gamedir)
    if not gamedir.is_dir():
        print(f"not a directory: {gamedir}")
        return 2

    textures = resolvable_textures(gamedir)
    if args.prefix:
        textures = {t for t in textures if t.startswith(args.prefix.lower() + "/")}

    if args.count:
        prefixes: dict[str, int] = {}
        for name in textures:
            head = name.split("/", 1)[0] if "/" in name else ""
            prefixes[head] = prefixes.get(head, 0) + 1
        print(f"textures that resolve: {len(textures)}")
        print(f"pics/colormap.pcx: {'yes' if has_colormap(gamedir) else 'NO'}")
        for head in sorted(prefixes, key=lambda h: -prefixes[h])[:20]:
            print(f"  {head or '(root)'}: {prefixes[head]}")
    else:
        for name in sorted(textures):
            print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
