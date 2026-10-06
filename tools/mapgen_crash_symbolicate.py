"""Read a MAPGEN pipeline crash record against the build that crashed.

Ledger row 392 (Fable's brief 3, G2). `pipeline.exe` writes `crash.txt` into its job folder when it faults: the code,
the last PROGRESS line, and the faulting address and the faulting thread's frames as offsets into the executable
(`pipeline.exe+0x...`). This names each offset - the function it falls in and the offset into it - from the
executable's own symbol table (`nm -n`, the build is not stripped) and the object file it came from from the linker
map the build writes beside it (`pipeline.map`). Never a rebuild with symbols: that changes the code under the
addresses ([[q2prox-crash-symbolication-link-map]]).

    python tools/mapgen_crash_symbolicate.py JOB/crash.txt BIN/pipeline.exe [BIN/pipeline.map]
"""
from __future__ import annotations

import bisect
import re
import struct
import subprocess
import sys
from pathlib import Path


def image_base(exe: Path) -> int:
    data = exe.read_bytes()[:4096]
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    magic = struct.unpack_from("<H", data, pe + 24)[0]
    return struct.unpack_from("<Q", data, pe + 24 + 24)[0] if magic == 0x20B else \
        struct.unpack_from("<I", data, pe + 24 + 28)[0]


def text_symbols(exe: Path) -> list[tuple[int, str]]:
    out = subprocess.run(["nm", "-n", str(exe)], capture_output=True, text=True).stdout
    syms = []
    for ln in out.splitlines():
        m = re.match(r"^([0-9a-fA-F]+) ([tT]) (\S+)$", ln)
        if m:
            syms.append((int(m.group(1), 16), m.group(3)))
    return syms


def map_objects(mp: Path) -> list[tuple[int, str]]:
    """(start, object file) of every .text input section the linker map lists."""
    out, pending = [], None
    for ln in mp.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^ \.text(?:\.\S+)?\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S+)", ln)
        if m:
            out.append((int(m.group(1), 16), Path(m.group(3)).name))
            continue
        m = re.match(r"^ \.text(?:\.\S+)?$", ln)
        if m:
            pending = True
            continue
        if pending:
            m = re.match(r"^\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S+)", ln)
            if m:
                out.append((int(m.group(1), 16), Path(m.group(3)).name))
            pending = None
    return sorted(out)


def name(va: int, syms: list, objs: list) -> str:
    i = bisect.bisect_right([s[0] for s in syms], va) - 1
    fn = f"{syms[i][1]}+0x{va - syms[i][0]:x}" if i >= 0 else "?"
    j = bisect.bisect_right([o[0] for o in objs], va) - 1
    # a one-command gcc build links temporaries (`ccXXXXXX.o`) - no source file to name then
    obj = objs[j][1] if j >= 0 else ""
    return fn + (f" ({obj})" if obj and not re.match(r"^cc\w{6}\.o$", obj) and "crt" not in obj else "")


def symbolicate(crash: Path, exe: Path, mp: Path | None = None) -> list[str]:
    base = image_base(exe)
    syms = text_symbols(exe)
    objs = map_objects(mp) if mp and mp.is_file() else []
    said = []
    for ln in crash.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^(at|frame) pipeline\.exe\+0x([0-9a-f]+)$", ln)
        if m:
            said.append(f"{m.group(1)} {name(base + int(m.group(2), 16), syms, objs)}")
        else:
            said.append(ln)
    return said


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    for ln in symbolicate(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else None):
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
