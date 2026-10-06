#!/usr/bin/env python3
"""Independent build of the target/targetname graph.

What is independent here, and what deliberately is not:

  * the ALGORITHM is written from the description - resolve every link key
    against every targetname, one-to-many; keep the ones that resolve to
    nothing; group teams; find the entities on a cycle - and not from the C;

  * the role TABLE is not duplicated. It is read out of
    `src/mapgen/mapgen_wiring.c` and `inc/common/mapgen_wiring.h`, because a
    table of 60 classname-to-role rows is data, not an algorithm: transcribing
    it into a second file would only create a second place to get it wrong,
    and it would not test anything. What the table SAYS is checked against the
    corpus separately, by the guard.

That split is the point. Cross-implementation agreement is evidence about
logic; for data, single-sourcing is worth more than a second copy.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_bsp_oracle as oracle  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "src" / "mapgen" / "mapgen_wiring.c"
HEADER = REPO / "inc" / "common" / "mapgen_wiring.h"

LINK_KINDS = ("target", "killtarget", "pathtarget")


def _role_bits() -> dict[str, int]:
    bits = {}
    for m in re.finditer(r"^#define (MAPGEN_ENTROLE_\w+)\s+(0x[0-9A-Fa-f]+)u",
                         HEADER.read_text(encoding="utf-8"), re.MULTILINE):
        bits[m.group(1)] = int(m.group(2), 16)
    return bits


def _table(src: str, name: str, bits: dict[str, int]) -> list[tuple[str, int]]:
    m = re.search(rf"{name}\[\] = \{{(.*?)\n\}};", src, re.DOTALL)
    if not m:
        return []
    rows = []
    for entry in re.finditer(r'\{\s*"([^"]*)",\s*([^}]+?)\s*\}', m.group(1)):
        expr = entry.group(2)
        value = 0
        for token in re.findall(r"MAPGEN_ENTROLE_\w+", expr):
            value |= bits.get(token, 0)
        rows.append((entry.group(1), value))
    return rows


_BITS = _role_bits()
_SRC = SOURCE.read_text(encoding="utf-8")
EXACT = dict(_table(_SRC, "EXACT_ROLES", _BITS))
PREFIX = _table(_SRC, "PREFIX_ROLES", _BITS)
ROLE_NAMES = [
    (_BITS[m.group(1)], m.group(2))
    for m in re.finditer(r"\{\s*(MAPGEN_ENTROLE_\w+),\s*\"([^\"]+)\"\s*\}", _SRC)
    if m.group(1) in _BITS
]


def roles_for_classname(classname: str) -> int:
    if not classname:
        return 0
    if classname in EXACT:
        return EXACT[classname]
    for prefix, value in PREFIX:
        if classname.startswith(prefix):
            return value
    return 0


def parse_submodel(model: str | None) -> int:
    """Strict on purpose: `*12` is a submodel, `*12a` and `*` are not."""
    if not model or not model.startswith("*") or len(model) < 2:
        return -1
    body = model[1:]
    if not body.isdigit() or not body.isascii():
        return -1
    v = int(body)
    return v if v <= 0x7FFFFFFF else -1


@dataclass
class Entity:
    roles: int = 0
    submodel: int = -1
    out_links: int = 0
    in_links: int = 0
    team: int = -1
    on_cycle: bool = False


@dataclass
class Wiring:
    entities: list[Entity] = field(default_factory=list)
    links: list[tuple[int, int, int]] = field(default_factory=list)
    dangling: list[tuple[int, int, str]] = field(default_factory=list)
    teams: int = 0
    shared_names: int = 0
    on_cycle: int = 0
    bad_submodels: int = 0


def _mark_cycles(w: Wiring) -> None:
    """Every entity that lies on a cycle, meaning: in a strongly connected
    component of more than one entity, or targeting itself.

    Tarjan, iteratively. The cheaper "unwind the DFS stack on a back edge"
    answer is a different question with a different answer, which is how the C
    and this file first came to disagree on four shipped maps.
    """
    out: dict[int, list[int]] = {}
    for frm, to, _kind in w.links:
        out.setdefault(frm, []).append(to)

    n = len(w.entities)
    index: list[int | None] = [None] * n
    lowlink = [0] * n
    component: list[int] = []
    on_component = [False] * n
    counter = 0

    for root in range(n):
        if index[root] is not None:
            continue
        index[root] = lowlink[root] = counter
        counter += 1
        component.append(root)
        on_component[root] = True
        frames = [[root, 0]]

        while frames:
            v, cursor = frames[-1]
            edges = out.get(v, ())
            if cursor < len(edges):
                frames[-1][1] += 1
                nxt = edges[cursor]
                if index[nxt] is None:
                    index[nxt] = lowlink[nxt] = counter
                    counter += 1
                    component.append(nxt)
                    on_component[nxt] = True
                    frames.append([nxt, 0])
                elif on_component[nxt]:
                    lowlink[v] = min(lowlink[v], index[nxt])
                continue

            frames.pop()
            if lowlink[v] == index[v]:
                members = []
                while True:
                    member = component.pop()
                    on_component[member] = False
                    members.append(member)
                    if member == v:
                        break
                cyclic = len(members) > 1 or v in out.get(v, ())
                if cyclic:
                    for member in members:
                        if not w.entities[member].on_cycle:
                            w.entities[member].on_cycle = True
                            w.on_cycle += 1
            if frames:
                parent = frames[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[v])


def build(ents: list[dict[str, str]], num_models: int | None = None) -> Wiring:
    w = Wiring(entities=[Entity() for _ in ents])

    for i, ent in enumerate(ents):
        e = w.entities[i]
        e.roles = roles_for_classname(ent.get("classname", ""))
        e.submodel = parse_submodel(ent.get("model"))
        if e.submodel >= 0 and num_models is not None and e.submodel >= num_models:
            w.bad_submodels += 1
            e.submodel = -1

    # Teams, in first-appearance order.
    for i, ent in enumerate(ents):
        team = ent.get("team")
        if not team or w.entities[i].team != -1:
            continue
        ident = w.teams
        w.teams += 1
        for j in range(i, len(ents)):
            if ents[j].get("team") == team:
                w.entities[j].team = ident

    # Links: one-to-many, in entity order then key order then target order,
    # which is what makes the result comparable at all.
    for i, ent in enumerate(ents):
        for kind, key in enumerate(LINK_KINDS):
            want = ent.get(key)
            if not want:
                continue
            matched = 0
            for j, other in enumerate(ents):
                if other.get("targetname") == want:
                    w.links.append((i, j, kind))
                    w.entities[i].out_links += 1
                    w.entities[j].in_links += 1
                    matched += 1
            if not matched:
                w.dangling.append((i, kind, want[:63]))

    seen: set[str] = set()
    for ent in ents:
        name = ent.get("targetname")
        if not name or name in seen:
            continue
        seen.add(name)
        if sum(1 for other in ents if other.get("targetname") == name) > 1:
            w.shared_names += 1

    _mark_cycles(w)
    return w


def canonical_text(w: Wiring) -> str:
    out = [f"entities={len(w.entities)}"]
    for e in w.entities:
        out.append("w=%d,%d,%d,%d,%d,%d" % (
            e.roles, e.submodel, e.out_links, e.in_links, e.team,
            1 if e.on_cycle else 0))
    out.append(f"links={len(w.links)}")
    for frm, to, kind in w.links:
        out.append(f"l={frm},{to},{LINK_KINDS[kind]}")
    out.append(f"dangling={len(w.dangling)}")
    for frm, kind, name in w.dangling:
        out.append(f"d={frm},{LINK_KINDS[kind]},{name}")
    out.append(f"teams={w.teams}")
    out.append(f"shared_names={w.shared_names}")
    out.append(f"on_cycle={w.on_cycle}")
    out.append(f"bad_submodels={w.bad_submodels}")
    for bit, name in ROLE_NAMES:
        out.append(f"role={name},{sum(1 for e in w.entities if e.roles & bit == bit)}")
    return "\n".join(out) + "\n"


def canonical_digest(w: Wiring) -> int:
    h = 1469598103934665603
    for byte in canonical_text(w).encode("ascii", "replace"):
        h ^= byte
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def from_map(path: Path) -> Wiring:
    bsp = oracle.load(path)
    return build(list(bsp.entities()), len(bsp.models))
