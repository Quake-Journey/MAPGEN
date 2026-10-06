#!/usr/bin/env python3
"""Shared plumbing for the MAPGEN-1 controlled-RED drivers.

One rule lives here, because getting it wrong silently disarms a whole matrix:

    A mutation anchor must match whatever line endings the file happens to use,
    and the file must come back byte-identical.

This tree mixes CRLF and LF, sometimes inside one file, and any helper script
that rewrites a file with the platform's default newline translation converts
it wholesale. That is not hypothetical - it happened here, and the M0 RED
driver failed with "anchor occurs 0 times" until this was fixed. Entry packet
section 6.1 is the standing rule; this is its implementation.

An anchor that cannot be found FAILS the matrix. It is never a SKIP: six silent
SKIPs in the perf-HUD RED matrix are why that is written down.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def resolve_anchor(data: bytes, anchor: bytes, replacement: bytes) -> tuple[bytes, bytes, int]:
    """Return (anchor, replacement, occurrences) in the file's own convention.

    The replacement is normalized to the same convention as the matched anchor,
    so a mutated file keeps the line endings it had and its restoration is
    byte-exact.
    """
    if b"\n" not in anchor:
        return anchor, replacement, data.count(anchor)

    lf_anchor = anchor.replace(b"\r\n", b"\n")
    lf_count = data.count(lf_anchor)
    if lf_count:
        return lf_anchor, replacement.replace(b"\r\n", b"\n"), lf_count

    crlf_anchor = lf_anchor.replace(b"\n", b"\r\n")
    crlf_count = data.count(crlf_anchor)
    if crlf_count:
        return crlf_anchor, replacement.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"), crlf_count

    return lf_anchor, replacement, 0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
