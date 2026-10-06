"""Do the maps we are about to hand over actually LOAD? Asked of a HEADLESS
dedicated server.

The batch of 2026-09-04 was refused by the engine with ERR_NOT_A_PROJECT and
nobody found out until the PO tried it, because every check in this tree looks
at the .bsp and none of them asks the game. This asks the game.

    python tools/mapgen_verify_map_loads.py mgtest_f100 mgtest_f075 ...

One launch per map, each one bounded and each one INVISIBLE. It used to start
the client; on 2026-09-10 the PO was at his machine while a batch of those ran
and our window covered his screen - «не нужно мне экраны эти открывать». The
client cannot be hidden (`src/windows/client.c:215`), so this runs a dedicated
server with a hidden console, on a UDP port asked of the OS (his own game
holds 27910, and a server that cannot bind its port is a FATAL error with a
dialog), with `sys_exitonerror 1` so nothing can open a MessageBox, and the
run is watched from Python: if any visible window of that process ever
appears, it is killed and the case fails.

Per the standing rule for agent launches it runs with
`q2prox_config_readonly 1` so it cannot touch the PO's config, and
`net_clientport -1` so it cannot take the client port out from under his own
game.

A map counts as loaded when the server's own log says it spawned that map and
no error line follows.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_mapgen_glass_alive as alive          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as load_guard          # noqa: E402

RELEASE = Path(r"O:\Claude2\q2pro-release")
EXE = RELEASE / "Q2PRO-X.exe"
DUMPS = RELEASE / "baseq2" / "condumps"

ERROR = re.compile(r"^(ERR_|ERROR:|\*\*\*\*|Couldn't load|Error:)", re.M)


LOGNAME = "mgloadcheck"


def verify(name: str, seconds: int) -> tuple[bool, str]:
    log = RELEASE / "baseq2" / "logs" / f"{LOGNAME}.log"
    if log.exists():
        log.unlink()
    argv = [
        str(EXE),
        "+set", "dedicated", "1",
        "+set", "q2prox_config_readonly", "1",
        "+set", "net_clientport", "-1",
        "+set", "net_port", str(alive.free_port()),
        "+set", "sys_exitonerror", "1",
        "+set", "logfile_name", LOGNAME,
        "+set", "logfile", "2",
        "+map", name,
        "+wait", "10",
        "+quit",
    ]
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0                     # SW_HIDE
    began = time.time()
    seen = []
    proc = load_guard.popen(argv, cwd=str(RELEASE), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, startupinfo=startup,
                            creationflags=subprocess.CREATE_NEW_CONSOLE)
    while proc.poll() is None:
        if time.time() - began > seconds:
            proc.kill()
            return False, f"did not exit within {seconds}s"
        now = alive.visible_windows(proc.pid)
        if now:
            proc.kill()
            seen = now
            break
        time.sleep(0.1)
    took = time.time() - began
    if seen:
        return False, "it put a window on the screen: " + "; ".join(seen)

    if not log.is_file():
        return False, f"no server log after {took:.0f}s - it never started"
    text = log.read_text(encoding="utf-8", errors="replace")
    bad = ERROR.search(text)
    if bad:
        line = text[bad.start():text.find("\n", bad.start())]
        return False, line.strip()
    if f"SpawnServer: {name}" not in text:
        return False, "the server log does not say it spawned the map"
    return True, f"{took:.0f}s"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("maps", nargs="+")
    ap.add_argument("--seconds", type=int, default=120)
    a = ap.parse_args()

    if not EXE.is_file():
        print(f"no client at {EXE}")
        return 2
    DUMPS.mkdir(parents=True, exist_ok=True)

    failures = 0
    for name in a.maps:
        ok, why = verify(name, a.seconds)
        print(f"  {'LOADS ' if ok else 'FAILED'}  {name}  -- {why}")
        failures += 0 if ok else 1
    print(f"{len(a.maps)} maps, {failures} that do not load")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
