"""ONE place that starts a heavy process, so the PO's machine keeps most of
itself.

His order, 2026-09-11, in anger and after his desktop had gone down more than once
under our load: «Требую перестать юзать проц на 100%, задавайте не более 70% - а то
уже который раз комп не выдерживает!» And on 2026-09-30, so that a map build can run
while another session works on the Release3 bots: «так ты просто модифицируй план
сборок так чтобы использовать не более 30% CPU ресурса» (ledger row 329). And on
2026-10-01: «с 9 утра до 23 вечера по моему местному времени можешь использовать до 60%
cpu чтобы компилилось быстрей» (row 347) - the share follows the machine's local clock.

Every heavy launch this project makes - the map compiler, the mapgen drivers and
the pipeline, the hidden dedicated server the alive and load checks use, the probes
- goes through `run()` or `popen()` here and nowhere else. Both of them:

  * start the process at BELOW_NORMAL priority, so anything the PO is doing wins
    every scheduling contest against us;
  * pin it to the LOW `ALLOWED` logical CPUs of the machine and leave the top ones
    free, so a compiler that asks for every core gets 60 per cent of them by day and
    30 at night and the rest of the box stays responsive;
  * follow the clock: once a minute the parent re-pins itself and every live child
    it started to the share of that hour, so a build running across 23:00 drops to
    the night share within a minute (and one running across 09:00 rises);
  * keep whatever creation flags the caller needs (the hidden-window server adds
    `STARTF_USESHOWWINDOW` + `SW_HIDE` + `CREATE_NEW_CONSOLE`, and that still
    works - these flags are OR-ed in, not replaced).

`-threads 1` on the compiler is a separate and unchanged rule: the pin bounds how
many cores a process MAY use, the thread policy bounds how many it asks for, and the
pinned compiler's own qualification rests on the second.

`tools/check_mapgen_load_discipline.py` asserts that nothing under `tools/` starts
one of these binaries any other way, and has a controlled RED.
"""
from __future__ import annotations

import ctypes
import math
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

# What fraction of the machine we may occupy, and his numbers: 30 at night (row 329,
# was 70), 60 from 09:00 to 23:00 his local time (row 347).
SHARE = 0.30
DAY_SHARE = 0.60
DAY_HOURS = (9, 23)

# The binaries this rule is about. A launch of any of them outside this module is
# what the static guard refuses.
HEAVY = (
    "q2tool.exe",
    "pipeline.exe",
    "recut_driver.exe",
    "dig_probe.exe",
    "reach.exe",
    "traversal.exe",
    "Q2PRO-X.exe",
    "transaction_driver.exe",
    "txn_driver.exe",
    "worth.exe",
)


def logical_cpus() -> int:
    return os.cpu_count() or 1


def share_now(now: datetime | None = None) -> float:
    """The share of this hour on the machine's local clock: DAY_SHARE in DAY_HOURS, else SHARE."""
    h = (now or datetime.now()).hour
    return DAY_SHARE if DAY_HOURS[0] <= h < DAY_HOURS[1] else SHARE


def allowed_cpus(now: datetime | None = None) -> int:
    """How many logical CPUs a heavy process may use now. At least one."""
    return max(1, int(math.floor(share_now(now) * logical_cpus())))


def performance_cpus() -> list[int]:
    """The logical CPUs (group 0) of the machine's highest efficiency class, ascending; [] when unknown.

    Row 404, the PO (2026-10-03): «у меня в моем процессоре есть P-ядра, а есть E-ядра ... для моего проца нужны
    только P-ядра». His P-core threads are 0-15 and the day's share of 32 is 19, so the low bits brought three
    E-cores into every daytime run.
    """
    if sys.platform != "win32":
        return []
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        need = ctypes.c_ulong(0)
        k32.GetSystemCpuSetInformation(None, 0, ctypes.byref(need), None, 0)
        if not need.value:
            return []
        buf = ctypes.create_string_buffer(need.value)
        got = ctypes.c_ulong(0)
        if not k32.GetSystemCpuSetInformation(buf, need, ctypes.byref(got), None, 0):
            return []
        raw = buf.raw[:got.value]
        cpus, at = [], 0
        while at + 19 <= len(raw):
            size = int.from_bytes(raw[at:at + 4], "little")
            if not size:
                break
            if int.from_bytes(raw[at + 4:at + 8], "little") == 0 and int.from_bytes(raw[at + 12:at + 14], "little") == 0:
                cpus.append((raw[at + 14], raw[at + 18]))       # LogicalProcessorIndex, EfficiencyClass
            at += size
        if not cpus:
            return []
        top = max(c for _, c in cpus)
        return sorted(i for i, c in cpus if c == top and i < 64)
    except (OSError, AttributeError):
        return []


FAULTY_DAYS = 30


def faulty_cpus() -> set:
    """The logical CPUs of the cores the machine itself reported for hardware errors: WHEA-Logger's machine checks in
    the System log (events 17, 18, 19) of the last FAULTY_DAYS, by their «APIC ID», read once a day (a small cache in
    LOCALAPPDATA). Brief 12, 07.10: three generator crashes in a row (0xC0000005, the CPU executing at its own branch
    target with bit 31 and a low bit set - an address no instruction of ours computes) while the System log held 80
    corrected «internal parity error» machine checks of the core at APIC ID 0 in 30 days, three of them during those
    runs - and that core was the first the share took. Both threads of a reported core are left out. On Intel's hybrid
    parts (12th..14th) a P-core's APIC IDs are 8 apart and its two threads the logical CPUs 2k and 2k+1; elsewhere the
    APIC ID is taken for the logical index."""
    if sys.platform != "win32":
        return set()
    import json
    import re
    import tempfile
    cache = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "mapgen_faulty_cpus.json")
    try:
        if time.time() - os.path.getmtime(cache) < 86400:
            with open(cache, encoding="utf-8") as f:
                return set(json.load(f)["cpus"])
    except (OSError, ValueError, KeyError):
        pass
    apics: set = set()
    try:
        ps = ("Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'; "
              f"StartTime=(Get-Date).AddDays(-{FAULTY_DAYS})}} -ErrorAction SilentlyContinue | "
              "ForEach-Object { $_.Message }")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                             text=True, errors="replace", timeout=60).stdout
        apics = {int(m) for m in re.findall(r"APIC[^:\n]*:\s*(\d+)", out)}
    except (OSError, subprocess.SubprocessError):
        return set()
    fast = performance_cpus()
    hybrid = bool(fast) and len(fast) < logical_cpus()
    cpus = set()
    for a in apics:
        if hybrid and a < 64:
            cpus |= {2 * (a // 8), 2 * (a // 8) + 1}
        else:
            cpus.add(a)
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"cpus": sorted(cpus), "apic": sorted(apics), "days": FAULTY_DAYS}, f)
    except OSError:
        pass
    return cpus


def affinity_mask(now: datetime | None = None) -> int:
    """`allowed_cpus()` of the performance cores, lowest first (the top cores are left to the PO), never an E-core;
    the low bits on a machine with one class of core."""
    fast = performance_cpus()
    if not fast:
        return (1 << allowed_cpus(now)) - 1
    # row 410, the PO (2026-10-04): «опять у меня vs code вешается когда ты генератор запускаешь» - the share was of all
    # 32 logical CPUs (19 by day) taken from 16 P-cores, so every P-core went to the run; the share is of the P-cores
    # themselves now - 9 of 16 by day, 4 at night - and the fast cores he works on are never all taken
    take = max(1, int(math.floor(share_now(now) * len(fast))))
    # brief 12: never a core the machine reported for hardware errors (`faulty_cpus`) - the next ones instead
    bad = faulty_cpus()
    usable = [i for i in fast if i not in bad] or fast
    mask = 0
    for i in usable[:take]:
        mask |= 1 << i
    return mask


BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)

# Row 376: and the disk. The PO, 2026-10-02: «Каждый раз когда работает генератор то моя VS Code как бы висит ...
# Это явно не нагрузка на CPU виновата». A compile or a walk writing gigabytes at normal I/O priority stalls an
# editor that reads the same disk; LOW lets anything the PO does go first.
IO_PRIORITY_LOW = 1          # IoPriorityVeryLow 0, Low 1, Normal 2, High 3
PROCESS_IO_PRIORITY = 33     # PROCESSINFOCLASS ProcessIoPriority


def _lower_io(pid: int) -> bool:
    """Set a live process's I/O priority to LOW. False when it could not be done."""
    if sys.platform != "win32":
        return False
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(0x0200 | 0x0400, False, int(pid))
    if not handle:
        return False
    try:
        prio = ctypes.c_ulong(IO_PRIORITY_LOW)
        status = ctypes.windll.ntdll.NtSetInformationProcess(
            ctypes.c_void_p(handle), PROCESS_IO_PRIORITY, ctypes.byref(prio), ctypes.sizeof(prio))
        return status == 0
    finally:
        k32.CloseHandle(handle)


def io_priority(pid: int) -> int | None:
    """A live process's I/O priority, or None when it cannot be read."""
    if sys.platform != "win32":
        return None
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(0x0400, False, int(pid))
    if not handle:
        return None
    try:
        prio = ctypes.c_ulong(0)
        status = ctypes.windll.ntdll.NtQueryInformationProcess(
            ctypes.c_void_p(handle), PROCESS_IO_PRIORITY, ctypes.byref(prio), ctypes.sizeof(prio), None)
        return prio.value if status == 0 else None
    finally:
        k32.CloseHandle(handle)


def _pin(handle_or_pid, is_handle: bool, mask: int | None = None) -> bool:
    """Pin a live process to `mask` (this hour's `affinity_mask()`). False when it could not be done."""
    mask = affinity_mask() if mask is None else mask
    if sys.platform != "win32":
        try:
            os.sched_setaffinity(handle_or_pid, [i for i in range(logical_cpus()) if mask >> i & 1])
            return True
        except Exception:                                   # noqa: BLE001
            return False
    k32 = ctypes.windll.kernel32
    handle = handle_or_pid
    opened = False
    if not is_handle:
        PROCESS_SET_INFORMATION = 0x0200
        PROCESS_QUERY_INFORMATION = 0x0400
        handle = k32.OpenProcess(PROCESS_SET_INFORMATION
                                 | PROCESS_QUERY_INFORMATION, False,
                                 int(handle_or_pid))
        opened = True
        if not handle:
            return False
    try:
        ok = k32.SetProcessAffinityMask(ctypes.c_void_p(int(handle)),
                                       ctypes.c_size_t(mask))
        return bool(ok)
    finally:
        if opened:
            k32.CloseHandle(handle)


_SELF_PINNED = None
_CHILDREN: list = []
_FOLLOWING = None


def _follow_clock() -> None:
    """Row 347: once a minute, the share of the hour for this process and every live child it started."""
    applied = affinity_mask()
    while True:
        time.sleep(60)
        mask = affinity_mask()
        if mask == applied:
            continue
        _pin(os.getpid(), is_handle=False, mask=mask)
        for p in list(_CHILDREN):
            if p.poll() is None:
                _pin(p.pid, is_handle=False, mask=mask)
            else:
                _CHILDREN.remove(p)
        applied = mask
        print(f"load guard: the hour's share is now {describe()}", file=sys.stderr, flush=True)


def pin_self() -> bool:
    """Pin THIS process, so every child inherits the bound before it runs.

    Why this exists: `popen` pinned the child AFTER `CreateProcess` returned, so
    a compiler that started threads immediately could run unbounded for a moment
    - and Codex's review of 2026-09-13 said so: «the unchanged load wrapper
    still pins after launch and ignores pin failure; its presence alone does not
    substantiate a strict 70% bound». Windows gives a child its parent's
    affinity, so setting it here bounds the child from its first instruction.
    The post-start pin stays as a second line of defence for a child that
    changed its own mask.
    """
    global _SELF_PINNED, _FOLLOWING
    if _FOLLOWING is None:
        _FOLLOWING = threading.Thread(target=_follow_clock, name="load-guard-clock", daemon=True)
        _FOLLOWING.start()
    if _SELF_PINNED is None:
        _lower_io(os.getpid())       # row 376: and the disk
        _SELF_PINNED = _pin(os.getpid(), is_handle=False)
        if not _SELF_PINNED:
            print(f"load guard: COULD NOT pin this process to {describe()};"
                  " children are not bounded before they start",
                  file=sys.stderr, flush=True)
    return _SELF_PINNED


def popen(argv, *, creationflags: int = 0, **kw) -> subprocess.Popen:
    """`subprocess.Popen`, below normal, pinned, with the caller's own flags kept."""
    before = pin_self()
    flags = creationflags | BELOW_NORMAL
    p = subprocess.Popen([str(a) for a in argv], creationflags=flags, **kw)
    after = _pin(p.pid, is_handle=False)
    _lower_io(p.pid)                 # row 376: and the disk
    _CHILDREN.append(p)
    if not before and not after:
        # Neither bound took. Say it; a silent failure is how an unbounded run
        # gets reported as a bounded one.
        print(f"load guard: {argv[0]} is NOT pinned - neither the parent nor the"
              f" child could be set to {describe()}", file=sys.stderr,
              flush=True)
    return p


def run(argv, *, timeout=None, capture_output=False, text=False,
        creationflags: int = 0, **kw) -> subprocess.CompletedProcess:
    """`subprocess.run` for a heavy binary: below normal, pinned, same result.

    Deliberately the same shape as `subprocess.run` so a call site changes by its
    name alone and nothing else about it moves.
    """
    if capture_output:
        kw.setdefault("stdout", subprocess.PIPE)
        kw.setdefault("stderr", subprocess.PIPE)
    p = popen(argv, creationflags=creationflags,
              **({"text": text} if text else {}), **kw)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        raise
    return subprocess.CompletedProcess([str(a) for a in argv], p.returncode,
                                       out, err)


def describe() -> str:
    mask = affinity_mask()
    return (f"{bin(mask).count('1')} of {logical_cpus()} logical CPUs, performance cores only"
            f" (mask {mask:#x}), BELOW_NORMAL priority, LOW I/O priority")


if __name__ == "__main__":
    print(describe())
