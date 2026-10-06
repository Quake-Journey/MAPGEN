"""Nothing starts a heavy binary except through `mapgen_load_guard`.

The PO, 2026-09-11, in anger and after his desktop had gone down under our load more
than once: «Требую перестать юзать проц на 100%, задавайте не более 70% - а то уже
который раз комп не выдерживает!»

`mapgen_load_guard.run` / `.popen` start a process at BELOW_NORMAL priority pinned to
the low 30 per cent of the machine's logical CPUs - his 70 until 2026-09-30, when a map
build was to run beside the bot work of another session: «модифицируй план сборок так
чтобы использовать не более 30% CPU ресурса» (ledger row 329); and since 2026-10-01 the low 60 per cent from
09:00 to 23:00 his local time: «с 9 утра до 23 вечера по моему местному времени можешь использовать до 60%
cpu» (row 347). A single call site that bypasses
them is a compiler at full priority on every core, which is exactly the thing he is
describing - so the rule is only as good as the sites it cannot be skipped at, and
this is the check that says so.

    python tools/check_mapgen_load_discipline.py [--red]

What it reads: every `.py` under `tools/` and the scratch drivers named on the
command line, with comments and docstrings stripped, because a rule that fires on a
COMMENT is the defect this project already paid for once
(`feedback_never_corrupt_po_preset_and_config_data`, the `latin-1` exclusion that
matched a comment and let a mutant through).

`--red` is the controlled RED: it writes a throwaway file with a raw
`subprocess.run([q2tool, ...])` in it and asserts that this check refuses it; and it
puts the old share of 0.70 into the wrapper and asserts that the share questions
refuse it.
"""
from __future__ import annotations

import argparse
import ast
import io
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"

sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as load_guard              # noqa: E402

#
# A launch is heavy when the text of the call names one of the BINARIES.
#
# Names only. The first version also matched the words «compiler» and «pinned()»,
# and then flagged `build_pinned_compiler.py` - a cmake build belonging to another
# task - along with three release packagers. A rule that fires on a word rather
# than on a launch is a rule nobody can keep.
#
HEAVY_HINTS = tuple(x.lower() for x in load_guard.HEAVY) + ("q2tool",)
# These files are allowed to call subprocess directly: the wrapper itself.
#
# And this file, whose RED fixture TEXT is a string literal rather than a
# call - the only launch it makes is the one it writes to disk and reads
# back, which is the RED proving the reader works.
#
EXEMPT = {"mapgen_load_guard.py", "check_mapgen_load_discipline.py"}
#
# WHAT IS IN SCOPE. This round owns the mapgen launch sites; the release packagers
# and `build_pinned_compiler.py` start heavy work of their own and are NOT
# retrofitted here, which is recorded rather than hidden.
#
SCOPE = ("check_mapgen_*.py", "mapgen_*.py", "run_mapgen_*.py")

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


def code_only(text: str) -> str:
    """The file with every comment and docstring removed.

    A check that counts a mention inside a comment is a check that can be fooled by
    writing about the rule instead of following it - and the mirror of that mistake
    let a mutant through a guard on 2026-08-17.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    drop = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                drop.append((body[0].lineno, body[0].end_lineno))
    lines = text.splitlines()
    keep = []
    for i, line in enumerate(lines, 1):
        if any(a <= i <= b for a, b in drop):
            continue
        # strip a trailing comment, naively but only outside quotes
        out, q = [], None
        for ch in line:
            if q:
                out.append(ch)
                if ch == q:
                    q = None
                continue
            if ch in "'\"":
                q = ch
                out.append(ch)
                continue
            if ch == "#":
                break
            out.append(ch)
        keep.append("".join(out))
    return "\n".join(keep)


def offenders(path: Path) -> list[str]:
    if path.name in EXEMPT:
        return []
    text = code_only(io.open(path, encoding="utf-8", errors="replace").read())
    bad = []
    for m in re.finditer(r"subprocess\.(run|Popen|check_output|call)\s*\(",
                         text):
        # the call's own text, to the matching close paren or 600 chars
        tail = text[m.start():m.start() + 600].lower()
        if any(h in tail for h in HEAVY_HINTS):
            line = text[:m.start()].count("\n") + 1
            bad.append(f"{path.name}:{line} {text[m.start():m.start() + 70]!r}")
    return bad


def share_ok() -> bool:
    """Rows 329 and 347: at every hour of the day the wrapper's CPUs are at most his share of that hour - 60 per
    cent from 09:00 to 23:00, 30 otherwise."""
    from datetime import datetime
    n = load_guard.logical_cpus()
    for h in range(24):
        for m in (0, 59):
            at = datetime(2026, 10, 1, h, m)
            cap = 0.60 if 9 <= h < 23 else 0.30
            if load_guard.allowed_cpus(at) > cap * n or load_guard.share_now(at) > cap + 1e-9:
                return False
    return True


def follows_clock() -> bool:
    """Row 347: the day share at 09:00 and 22:59, the night share at 08:59 and 23:00."""
    from datetime import datetime
    s = load_guard.share_now
    return (s(datetime(2026, 10, 1, 9, 0)) == load_guard.DAY_SHARE
            and s(datetime(2026, 10, 1, 22, 59)) == load_guard.DAY_SHARE
            and s(datetime(2026, 10, 1, 8, 59)) == load_guard.SHARE
            and s(datetime(2026, 10, 1, 23, 0)) == load_guard.SHARE)


IO_PROBE = r"""
import subprocess, sys, time
sys.path.insert(0, sys.argv[1])
import mapgen_load_guard as g
if sys.argv[2] == "red":
    g._lower_io = lambda pid: False
p = g.popen([sys.executable, "-c", "import time; time.sleep(4)"])
time.sleep(0.5)
print(g.io_priority(p.pid))
p.kill()
"""


def child_io_priority(red: bool) -> int | None:
    """Row 376: the I/O priority of a child the wrapper starts, read back from the live process - run in a fresh
    interpreter, so nothing this check did to its own priority is inherited."""
    import subprocess
    out = subprocess.run([sys.executable, "-c", IO_PROBE, str(TOOLS), "red" if red else "green"],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    try:
        return int(out.splitlines()[-1])
    except (ValueError, IndexError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--red", action="store_true")
    ap.add_argument("extra", nargs="*", type=Path)
    a = ap.parse_args()

    print(f"the wrapper: {load_guard.describe()}")
    check("the share is the PO's - 60 per cent from 09:00 to 23:00, 30 otherwise - not more, at every hour, and so"
          " are the CPUs it allows", share_ok(), f"SHARE={load_guard.SHARE}, DAY_SHARE={load_guard.DAY_SHARE},"
          f" now {load_guard.allowed_cpus()} of {load_guard.logical_cpus()}")
    check("the share follows the clock: day from 09:00 to 22:59, night from 23:00 to 08:59", follows_clock(),
          f"DAY_HOURS={load_guard.DAY_HOURS}")
    check("and it leaves at least one core free",
          load_guard.allowed_cpus() < load_guard.logical_cpus(),
          f"{load_guard.allowed_cpus()} of {load_guard.logical_cpus()}")
    # row 404: the LOW allowed cores of the performance class - the PO's P-cores, never an E-core («для моего проца
    # нужны только P-ядра»); the plain low bits on a machine with one class of core
    fast = load_guard.performance_cpus()
    # row 410 (the PO: «опять у меня vs code вешается»): the share is of the performance cores themselves, and some of
    # them always stay his - 19 of 32 taken from 16 P-cores had taken all 16
    take = max(1, int(load_guard.share_now() * len(fast))) if fast else 0
    want = sum(1 << i for i in fast[:take]) if fast else (1 << load_guard.allowed_cpus()) - 1
    check("the mask is the hour's share OF the performance cores, the lowest, so the top ones stay the PO's and no"
          " E-core is in it",
          load_guard.affinity_mask() == want and (not fast or not load_guard.affinity_mask() & ~sum(1 << i for i in fast))
          and (not fast or bin(load_guard.affinity_mask()).count("1") < len(fast)),
          f"{load_guard.affinity_mask():#x}, performance cores {fast}")

    io = child_io_priority(red=False)
    check("a child the wrapper starts runs at LOW I/O priority, read back from the live process",
          io == load_guard.IO_PRIORITY_LOW, f"I/O priority {io}")

    files = sorted({f for pat in SCOPE for f in TOOLS.glob(pat)})
    files += list(a.extra)
    bad = []
    for f in files:
        bad += offenders(f)
    check(f"no heavy launch bypasses the wrapper ({len(files)} files read)",
          not bad, "; ".join(bad[:4]))

    if a.red:
        red = TOOLS / "_load_discipline_red_fixture.py"
        red.write_text(
            "import subprocess\n"
            "subprocess.run([r'O:/q2tool.exe', '-bsp', 'x.map'])\n",
            encoding="utf-8")
        try:
            found = offenders(red)
            check("RED: a raw subprocess.run of the compiler is refused",
                  bool(found), found[0] if found else "it was not seen")
        finally:
            red.unlink(missing_ok=True)
        kept = load_guard.SHARE
        load_guard.SHARE = 0.70
        try:
            said = f"{load_guard.allowed_cpus()} of {load_guard.logical_cpus()}"
            check("RED: the old share of 0.70 is refused by the share questions",
                  not share_ok(), said)
        finally:
            load_guard.SHARE = kept
        io_red = child_io_priority(red=True)
        check("RED: with the I/O lowering taken out, the child runs at NORMAL I/O priority",
              io_red == 2, f"I/O priority {io_red}")
        kept_hours = load_guard.DAY_HOURS
        load_guard.DAY_HOURS = (9, 24)
        try:
            check("RED: the day share running to midnight is refused by the share questions",
                  not share_ok() and not follows_clock(), f"DAY_HOURS={load_guard.DAY_HOURS}")
        finally:
            load_guard.DAY_HOURS = kept_hours

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
