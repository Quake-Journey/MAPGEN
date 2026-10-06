#!/usr/bin/env python3
"""R1 — controlled-RED mutations never touch the shared worktree.

Every MAPGEN RED matrix used to mutate the real file in `O:\\Claude2\\q2pro`
and restore it in a `finally:` block. That is correct only while the process
survives to run the `finally`. It twice did not: a full sweep run under a shell
timeout was killed mid-mutation and left `{ "item_quad", NULL }` in
`mapgen_entities.c`, and later a flipped bridge condition in
`mapgen_features.c`. Both were caught by the next guard sweep, and both were
luck rather than design - a mutation left in a shared tree is a defect
introduced by the tooling that exists to find defects.

Codex, 2026-09-01, directive R1: mutation cases run only in isolated disposable
copies under the owned temp root, and shared-repository pre/post hash identity
is proven on normal failure, on timeout AND on forced termination. Explicitly:
a longer timeout is not a fix, because restoration must not depend on the
mutator process surviving at all.

So a matrix copies what it needs into a disposable tree, mutates THERE, runs
the suite THERE, and never opens a shared file for writing. If the process is
killed at the worst possible moment, the shared tree is untouched by
construction and the only casualty is a directory nobody depends on.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

# The task's own root. S0 owns it; nothing here writes outside it.
OWNED_TEMP = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\red")

# What a mapgen suite actually reads. Deliberately not `tools` wholesale: that
# directory carries 36 MB of assets and data no guard opens, and copying it per
# matrix would make the safe path the slow path, which is how safe paths get
# switched off.
# src/common/pmove is here because MAPGEN now runs the engine's own player
# movement rather than modelling it: a contract that reads or compiles that
# code cannot run in a sandbox that does not contain it, and the RED matrix
# then reports "baseline is not GREEN" - which says nothing about the
# contract and is not a failure of it.
COPY_TREES = ("inc", "src/mapgen", "src/mapgen_worker", "src/common/pmove",
              "tools/mapgen_fixtures")
COPY_GLOBS = ("tools/*.py", "tools/*.c", "tools/*.ps1", "tools/*.json",
              "src/windows/mapgen_*.c", "src/shared/shared.c",
              # The walk asks how many performance-class CPUs there are, so
              # every guard that links it needs this in the sandbox too.
              "src/common/q2prox_cpu_topology.c",
              "src/common/msg.c", "src/common/sizebuf.c", "src/common/math.c",
              # Read, not compiled: several contracts assert that MAPGEN agrees
              # with the engine by comparing against the engine's own source.
              "src/common/bsp.c", "src/game/g_main.c",
              "src/client/demo_offline_decoder.c", "meson.build")


class Sandbox:
    """A disposable copy of the parts of the repo a RED matrix needs."""

    @staticmethod
    def sweep_abandoned() -> int:
        """Remove the sandboxes of processes that are no longer alive.

        Disposal on the way out depends on the mutator surviving, and a sweep
        run under a shell timeout does not. One session left eight hundred and
        forty-six behind - nine point four gigabytes on a volume with
        twenty-six free - which is how a task runs out of disk without writing
        anything large.

        A sandbox is named for the process that made it, so a live one is left
        alone by construction and this is safe to run while a suite works.
        """
        if not OWNED_TEMP.is_dir():
            return 0
        try:
            listing = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Process | Select-Object -ExpandProperty Id"],
                capture_output=True, text=True, timeout=60)
            alive = {int(x) for x in listing.stdout.split() if x.isdigit()}
        except Exception:
            return 0
        if not alive:
            return 0

        removed = 0
        for entry in sorted(OWNED_TEMP.iterdir()):
            if not entry.is_dir():
                continue
            name = entry.name
            if name.endswith("-pristine"):
                name = name[:-len("-pristine")]
            _, _, tail = name.rpartition("-")
            if not tail.isdigit() or int(tail) in alive:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
        return removed

    def __init__(self, repo: Path, label: str) -> None:
        Sandbox.sweep_abandoned()
        self.repo = repo
        self.root = OWNED_TEMP / f"{label}-{os.getpid()}"
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)

        for tree in COPY_TREES:
            src = repo / tree
            if src.is_dir():
                shutil.copytree(src, self.root / tree, dirs_exist_ok=True)
        for pattern in COPY_GLOBS:
            for src in repo.glob(pattern):
                if src.is_file():
                    dest = self.root / src.relative_to(repo)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)

        # A pristine second copy, so a case restores from something the run
        # cannot have damaged rather than from the file it just mutated.
        self.pristine = self.root.with_name(self.root.name + "-pristine")
        if self.pristine.exists():
            shutil.rmtree(self.pristine, ignore_errors=True)
        shutil.copytree(self.root, self.pristine)

    def path(self, relative: str) -> Path:
        """The sandbox's copy of a repo-relative path."""
        return self.root / relative

    def restore(self, relative: str) -> None:
        """Put one file back from the pristine copy."""
        shutil.copy2(self.pristine / relative, self.root / relative)

    def relative(self, path: Path) -> str:
        return str(path.relative_to(self.root)).replace("\\", "/")

    def dispose(self) -> None:
        """Only ever the sandbox. Never a shared path, and never on failure."""
        for tree in (self.root, self.pristine):
            shutil.rmtree(tree, ignore_errors=True)


def hash_tree(repo: Path) -> dict[str, str]:
    """Every source file a matrix could conceivably mutate, by content.

    The proof obligation is about the SHARED tree, so this reads the shared
    tree and nothing else.
    """
    digests: dict[str, str] = {}
    for tree in ("inc", "src/mapgen", "src/mapgen_worker", "src/windows"):
        base = repo / tree
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                digests[str(path.relative_to(repo)).replace("\\", "/")] = \
                    hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted((repo / "tools").glob("*.py")):
        digests[str(path.relative_to(repo)).replace("\\", "/")] = \
            hashlib.sha256(path.read_bytes()).hexdigest()
    return digests
