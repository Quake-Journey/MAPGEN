r"""What a crash record's minidump holds about the fault (ledger row 411: the walk's 0xC0000005).

    python tools/mapgen_dump_read.py CRASH.dmp PIPELINE.exe

The faulting thread's registers and the words around its stack pointer, each named against PIPELINE.exe's own symbol
table when it falls inside it (the same executable, never a rebuild); then every other thread: its instruction
pointer and stack pointer, named the same way - so a word written into one thread's stack can be matched to whoever
holds that address. Needs `pip install minidump`.
"""
from __future__ import annotations

import bisect
import subprocess
import sys

from minidump.minidumpfile import MinidumpFile


def symbols(exe: str):
    out = subprocess.run(["nm", "-n", exe], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 3 and p[1] in "tT":
            rows.append((int(p[0], 16) - 0x140000000, p[2]))
    rows.sort()
    return rows


def main() -> int:
    dump, exe = sys.argv[1], sys.argv[2]
    syms = symbols(exe)
    keys = [s[0] for s in syms]
    mf = MinidumpFile.parse(dump)
    reader = mf.get_reader()
    base = next(m.baseaddress for m in mf.modules.modules if m.name.lower().endswith("pipeline.exe"))
    size = next(m.size for m in mf.modules.modules if m.name.lower().endswith("pipeline.exe"))

    def name(v: int) -> str:
        if base <= v < base + size:
            i = bisect.bisect_right(keys, v - base) - 1
            return f"{syms[i][1]}+{v - base - syms[i][0]:#x}" if i >= 0 else f"pipeline.exe+{v - base:#x}"
        return ""

    exc = mf.exception.exception_records[0]
    tid = exc.ThreadId
    rec = exc.ExceptionRecord
    print(f"exception {int(getattr(rec.ExceptionCode, 'value', rec.ExceptionCode)):#x} at {rec.ExceptionAddress:#x} {name(rec.ExceptionAddress)} thread {tid}")
    print("params", [hex(x) for x in rec.ExceptionInformation[:rec.NumberParameters]])
    stacks = {}
    for t in mf.threads.threads:
        ctx = t.ContextObject
        rip, rsp = (ctx.Rip, ctx.Rsp) if ctx else (0, 0)
        lo = t.Stack.StartOfMemoryRange
        hi = lo + t.Stack.MemoryLocation.DataSize
        stacks[t.ThreadId] = (lo, hi)
        mark = "  <-- the fault" if t.ThreadId == tid else ""
        print(f"thread {t.ThreadId}: rip {rip:#x} {name(rip)} rsp {rsp:#x} stack {lo:#x}..{hi:#x}{mark}")
    ctx = mf.exception.exception_records[0].ThreadContext
    t = next(t for t in mf.threads.threads if t.ThreadId == tid)
    c = t.ContextObject
    print("registers:", {r: hex(getattr(c, r)) for r in ("Rax", "Rbx", "Rcx", "Rdx", "Rsi", "Rdi", "Rbp", "Rsp",
                                                        "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15")})
    rsp = c.Rsp
    for k in range(-8, 24):
        a = rsp + 8 * k
        try:
            v = int.from_bytes(reader.read(a, 8), "little")
        except Exception:
            continue
        owner = next((f"thread {i} stack" for i, (lo, hi) in stacks.items() if lo <= v < hi), "")
        print(f"  [rsp{8 * k:+#05x}] {a:#x}: {v:#018x} {name(v)} {owner}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
