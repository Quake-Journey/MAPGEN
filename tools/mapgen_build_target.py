"""Which build target a MAPGEN module is allowed to be in.

The rule every M2-M4 module guard carries says "the module is in no build
target", and what it protects is the PO's binary: contract 5.3 keeps the
generator out of the client - no client Z_*, no UI, no renderer state, no
command buffer - and the surest way to keep that true is for the client's
source lists never to name it.

What changed is that the generator now HAS a build target of its own. The
packaged helper `q2pro-x-mapgen` is a separate process by the same contract,
and the whole point of it is to run this code. A module the pipeline calls has
to be linked somewhere, and the check that said "nowhere" would have to be
answered by not shipping the feature.

So the rule is stated as what it always meant: a MAPGEN module may appear in
`mapgen_src` and nowhere else. The client and the dedicated server are built
from lists that must not name it, and this reads meson.build to say so rather
than trusting the arrangement.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _list_body(text: str, name: str) -> str:
    """The bracketed body of `name = [...]`, or an empty string."""
    m = re.search(rf"^{re.escape(name)}\s*=\s*\[", text, re.M)
    if not m:
        return ""
    depth = 0
    start = m.end() - 1
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    return ""


# The Seam: what OWNS a worker rather than what builds a map. The client links
# these because the client is what asks for a map; contract 5.3 is about the
# generator, and none of these generates anything.
SEAM = {
    "mapgen_controller.c",
    "mapgen_job.c",
    "mapgen_ipc.c",
    "mapgen_process.c",
    # A document the client reads to rebuild a map from the record that
    # travelled with it rather than from whatever the menu currently says.
    "mapgen_recipe.c",
}

# COMMON: what the LOADER itself has to be able to ask.
#
# `BSP_Load` refuses a Project that is not the map its manifest records. That
# question belongs in the loader and nowhere else - a check made before it
# answers about a path the engine then opens a second time, and a check in the
# menu is no check for a map named at the console, reached from a demo, or
# asked for by a server. The loader is common, and `q2proded` loads maps too:
# a rule that let the dedicated server play an unverified Project while the
# client refused it would not be much of a rule.
#
# Neither of these generates anything. They read a document and hash bytes,
# which is the line contract 5.3 draws. They may be in `common_src` and in
# `mapgen_src`, and nowhere else.
COMMON = {
    "mapgen_publish.c",
    "mapgen_digest.c",
}


def seam_matches_build() -> tuple[bool, str]:
    """The Seam declared above and `mapgen_seam_src` name the same modules.

    A rule that can be widened by editing one of two lists is not a rule. This
    is what stops the Seam growing quietly: a module added to the build and not
    to `SEAM` fails here, and so does one removed from the build and left here.

    `mapgen_client.c` is the client's own file rather than a MAPGEN module, and
    `mapgen_process.c` is added by a platform subdirectory, so neither is
    expected to appear in this list.
    """
    text = (REPO / "meson.build").read_text(encoding="utf-8", errors="replace")
    body = _list_body(text, "mapgen_seam_src")
    if not body:
        return False, "meson.build declares no mapgen_seam_src"
    named = re.findall(r"'src/[^']*/([A-Za-z0-9_]+\.c)'", body)
    seen = set(named)
    duplicates = sorted({n for n in named if named.count(n) > 1})
    if duplicates:
        return False, f"mapgen_seam_src names {duplicates} more than once"
    expected = (SEAM - {"mapgen_process.c"}) | {"mapgen_client.c"}
    if seen != expected:
        extra = sorted(seen - expected)
        missing = sorted(expected - seen)
        return False, (f"mapgen_seam_src has {extra} that SEAM does not, "
                       f"and SEAM has {missing} that it does not")

    # And the common list, by the same rule: neither of the two can be widened
    # by editing one side of it.
    common_body = _list_body(text, "mapgen_common_src")
    if not common_body:
        return False, "meson.build declares no mapgen_common_src"
    common_named = re.findall(r"'src/[^']*/([A-Za-z0-9_]+\.c)'", common_body)
    if sorted(common_named) != sorted(set(common_named)):
        return False, "mapgen_common_src names a module more than once"
    if set(common_named) != COMMON:
        extra = sorted(set(common_named) - COMMON)
        missing = sorted(COMMON - set(common_named))
        return False, (f"mapgen_common_src has {extra} that COMMON does not, "
                       f"and COMMON has {missing} that it does not")
    return True, "the Seam, the common list and the build agree"


def only_in_helper(module: str) -> tuple[bool, str]:
    """True when `module` is named by mapgen_src alone.

    Returns the reason as well, because a guard that says only "False" sends
    somebody to read meson.build with no idea what they are looking for.
    """
    text = (REPO / "meson.build").read_text(encoding="utf-8", errors="replace")
    if module not in text:
        # Not built at all is still within the rule: a module nothing links
        # cannot reach the client.
        return True, "not in any build target"

    if module in COMMON:
        #
        # The loader's own question, so it is in common and in the helper. It
        # may NOT be listed again in the client's own sources: it arrives there
        # through common_src, and a second listing would be a second copy.
        #
        common = _list_body(text, "mapgen_common_src")
        helper = _list_body(text, "mapgen_src")
        for other in ("client_src", "refresh_src", "server_src", "ui_src",
                      "mapgen_seam_src"):
            body = _list_body(text, other)
            if body and module in body:
                return False, (f"{module} is in {other} as well as in common:"
                               " it reaches every target through common_src")
        if module in common and module in helper:
            return True, "common, because the loader itself must ask it"
        return False, (f"{module} is COMMON but is not in both"
                       " mapgen_common_src and mapgen_src")

    if module in SEAM:
        #
        # The Seam may be in the client's own list and in the helper's, and
        # nowhere else: it is the interface between the two and belongs to
        # both ends of it.
        #
        # `mapgen_process.c` is platform work and is added inside
        # src/windows/meson.build rather than in a list here, so a Seam module
        # that appears in neither list is accepted only when nothing else
        # claims it.
        #
        seam = _list_body(text, "mapgen_seam_src")
        helper = _list_body(text, "mapgen_src")
        for other in ("common_src", "refresh_src", "server_src", "ui_src"):
            body = _list_body(text, other)
            if body and module in body:
                return False, (f"{module} is in {other}: the Seam belongs to"
                               " the client and the helper, not to everything")
        if module in seam or module in helper:
            return True, "the Seam, which the client is allowed to own"
        return True, "the Seam, added by a platform subdirectory"

    helper = _list_body(text, "mapgen_src")
    if module not in helper:
        return False, f"{module} is in meson.build but not in mapgen_src"

    for other in ("common_src", "client_src", "refresh_src", "server_src",
                  "ui_src"):
        body = _list_body(text, other)
        if body and module in body:
            return False, f"{module} is in {other}: the PO's binary must not link it"

    # And nowhere else in the file: an executable() that names it directly
    # would be a target this cannot see.
    outside = text.replace(helper, "")
    if module in outside:
        return False, f"{module} is named outside mapgen_src"
    return True, "mapgen_src only"
