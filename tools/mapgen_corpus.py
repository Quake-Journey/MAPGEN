"""Which maps in the PO's Release tree are the fixed corpus, and which are ours.

Ten guards count the shipped maps and assert numbers about them - 132 of them
load, the corpus has 47 links that go nowhere, every source is recorded. Their
own comment says why the set has to be fixed: "a count that moves every time
somebody generates a map is not a count."

Each of them wrote the same rule by hand, and the rule was the publish prefix
alone. That was not enough. `q2mg_` is reserved for published Projects and the
loader REFUSES any `q2mg_` map that is not a verified Project, so a map handed
to the PO for testing cannot use it - the last three were named `q2mg_lit*` and
the engine turned all three away with ERR_NOT_A_PROJECT. Renamed to something
the loader accepts, they landed in the counted corpus instead, and four guards
went red on numbers that had nothing to do with what they were guarding.

So the rule lives here, once, and covers both: what the generator publishes and
what it hands over to be tested.
"""
from __future__ import annotations

from pathlib import Path

#
# Maps the generator made, by the two names it is allowed to use.
#
#   q2mg_    contract 22's reserved basename for a published Project. The
#            loader demands a manifest for these and refuses them without one.
#   mgtest_  a build handed to the PO to look at. It has to be loadable, so it
#            cannot carry the reserved prefix, and it has to be recognisable,
#            so it carries this one.
#
GENERATED_PREFIXES = ("q2mg_", "mgtest_")


def is_generated(name: str) -> bool:
    """Did MAPGEN make this map? Legal training input, not part of the corpus."""
    return name.startswith(GENERATED_PREFIXES)


def shipped(roots) -> list[Path]:
    """Every map that came with the game, in a fixed order."""
    return [p for root in roots if Path(root).is_dir()
            for p in sorted(Path(root).glob("*.bsp"))
            if not is_generated(p.name)]
