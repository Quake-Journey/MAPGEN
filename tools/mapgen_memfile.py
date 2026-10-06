r"""Memory files for the pinned compiler's P13, from Python (ledger row 411, Fable's brief 8).

A `mem:KEY` path given to the compiler names a named shared-memory section `Local\q2mem_KEY` (backslashes made
slashes) that its CALLER made: 32 header bytes - b"Q2MEM1\0\0", the room, the size, present (little-endian u64 each)
- then the bytes. The section lives while a handle to it is open, so the caller holds a `Section` for as long as any
stage of the compile and its own reading need it.

    with Section("mapgen_x/q2mg.map", 64 << 20) as m:
        m.put(text_bytes)          # the compiler reads it
        ...                        # run q2tool on "mem:mapgen_x/q2mg.map"
        data = Section.read("mapgen_x/q2mg.bsp")   # what it wrote (None if never written or emptied)

`Sections(key_dir, names, room)` makes the set a compile uses (map, bsp, prt, pts) in one go.
"""
from __future__ import annotations

import mmap
import os
import struct

MAGIC = b"Q2MEM1\0\0"
HEAD = 32


def tag(key: str) -> str:
    return "Local\\q2mem_" + key.replace("\\", "/")


class Section:
    """One named section of `room` bytes, held open while this object is."""

    def __init__(self, key: str, room: int):
        self.key = key.replace("\\", "/")
        self.room = room
        self.map = mmap.mmap(-1, HEAD + room, tagname=tag(self.key))
        if self.map[:8] != MAGIC:
            self.map[:HEAD] = MAGIC + struct.pack("<QQQ", room, 0, 0)

    @property
    def path(self) -> str:
        return "mem:" + self.key

    def put(self, data: bytes) -> None:
        if len(data) > self.room:
            raise ValueError(f"memory file {self.key}: {len(data)} bytes, its room is {self.room}")
        self.map[24:32] = struct.pack("<Q", 0)
        self.map[HEAD:HEAD + len(data)] = data
        self.map[16:24] = struct.pack("<Q", len(data))
        self.map[24:32] = struct.pack("<Q", 1)

    def get(self) -> bytes | None:
        size, present = struct.unpack_from("<QQ", self.map, 16)
        return bytes(self.map[HEAD:HEAD + size]) if present else None

    def empty(self) -> None:
        self.map[16:32] = struct.pack("<QQ", 0, 0)

    def close(self) -> None:
        self.map.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Sections:
    """The set one compile uses: `<key_dir>/<name>.<ext>` for each extension, `room` bytes each."""

    EXTS = ("map", "bsp", "prt", "pts")

    def __init__(self, key_dir: str, name: str, room: int):
        self.key_dir = key_dir.replace("\\", "/").rstrip("/")
        self.name = name
        self.parts = {e: Section(f"{self.key_dir}/{name}.{e}", room) for e in self.EXTS}

    def path(self, ext: str) -> str:
        return self.parts[ext].path

    def __getitem__(self, ext: str) -> Section:
        return self.parts[ext]

    def close(self) -> None:
        for s in self.parts.values():
            s.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def unique_dir(label: str) -> str:
    """A key directory no other run of this machine is using: the label, this process, a counter."""
    unique_dir.n = getattr(unique_dir, "n", 0) + 1
    return f"{label}_{os.getpid()}_{unique_dir.n}"


def compiler_has_memory_files(exe) -> bool:
    """Does this compiler carry P13 - its own code names the sections' magic? A compiler without it reads files."""
    try:
        with open(exe, "rb") as f:
            return MAGIC[:6] in f.read()
    except OSError:
        return False


def compile_bsp_in_memory(compiler, stages: list[list[str]], bsp: bytes, prt: bytes | None = None,
                          timeout: int = 7200, label: str = "py"):
    """The stages a Python step runs on a compiled map (-vis, -rad ...: each the compiler's words before the map's
    name) through memory - the map in, the result out, nothing of it a file. Returns (the stages' results, the .bsp
    they left; None when the compiler has no memory files - the caller then works in files, as before).

    The room: the map four times over and 16 MB (the light lump may grow to the 8 MB `-maxdata` allows)."""
    if not compiler_has_memory_files(compiler):
        return None, None
    import mapgen_load_guard as guard
    room = max(64 << 20, 4 * len(bsp) + (16 << 20))
    results = []
    with Sections(unique_dir(label), "q2mg", room) as mem:
        mem["bsp"].put(bsp)
        if prt:
            mem["prt"].put(prt)
        for words in stages:
            r = guard.run([str(compiler), *words, mem.path("map")], capture_output=True, text=True, errors="replace",
                          timeout=timeout)
            results.append(r)
            if r.returncode:
                break
        return results, mem["bsp"].get()
