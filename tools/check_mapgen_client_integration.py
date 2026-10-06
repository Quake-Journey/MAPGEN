#!/usr/bin/env python3
"""MAPGEN-1: the seam between the generator and the game the player uses.

Everything below the client had a gate. The client itself - the commands, the
cvars, the menu page that calls them - had none, and it showed: `mapgen_maps`
was registered as a command while a cvar of that name already existed, so the
console answered with the cvar and the command could not be called at all. It
printed nothing, failed nothing, and looked exactly like a command that had run
and found no maps.

So this asserts what makes the seam usable rather than merely present:

  * no command shares a name with a cvar - the console has one namespace, and
    the cvar wins;
  * every mapgen command the menu invokes is actually registered, and every
    cvar it binds actually exists;
  * every mapgen cvar the menu edits is one the config-ownership rule covers,
    so an archived setting cannot escape into a global config;
  * every row on the page carries both languages (Hard Rule #26: a page with a
    stale or missing Russian side is rejected on sight);
  * the page speaks in the product's terms, not in the implementation's.

Run:  python tools/check_mapgen_client_integration.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLIENT = REPO / "src" / "client" / "mapgen_client.c"
MENU = REPO / "src" / "client" / "ui" / "q2pro-x.menu2"
OWNERSHIP = REPO / "src" / "common" / "q2prox_config_ownership.c"

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    if ok:
        print(f"  PASS  {name}")
        return True
    FAILED += 1
    print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    return False


def head(title: str) -> None:
    print(f"\n=== {title}")


def main() -> int:
    print("=== MAPGEN-1 client integration")

    for path in (CLIENT, MENU, OWNERSHIP):
        if not path.exists():
            print(f"  FAIL  missing {path}")
            return 1

    client = CLIENT.read_text(encoding="utf-8", errors="replace")
    menu_c = (REPO / "src" / "client" / "ui" / "menu.c").read_text(
        encoding="utf-8", errors="replace")
    notice = (REPO / "src" / "client" / "ui" / "mapgen_notice.c").read_text(
        encoding="utf-8", errors="replace")
    menu = MENU.read_text(encoding="utf-8", errors="replace")
    ownership = OWNERSHIP.read_text(encoding="utf-8", errors="replace")

    commands = set(re.findall(r'Cmd_AddCommand\("([^"]+)"', client))
    cvars = set(re.findall(r'Cvar_Get\("([^"]+)"', client))

    head("one namespace")
    check("the client registers commands at all", bool(commands), "")
    check("the client registers cvars at all", bool(cvars), "")
    clash = sorted(commands & cvars)
    check(
        "no command shares a name with a cvar",
        not clash,
        f"{clash} - the console answers with the cvar, so the command cannot "
        "be called",
    )

    head("the page calls what exists")
    # The generator's own page. Everything it invokes has to be real.
    page = ""
    m = re.search(r"^begin q2prox_mapgen$(.*?)^end$", menu, re.S | re.M)
    if check("the generator page is in the menu", m is not None, ""):
        assert m is not None
        page = m.group(1)

    # An action's trailing token is the command it runs; a widget's is the cvar
    # it edits. They are different namespaces and the page uses both.
    invoked, bound = set(), set()
    for line in page.splitlines():
        tokens = line.strip().split()
        if not tokens:
            continue
        kind = tokens[0]
        named = [t for t in tokens if t.startswith("mapgen_")]
        if not named:
            continue
        if kind == "action":
            invoked.add(named[-1])
        elif kind in ("field", "toggle", "pairs", "values", "range", "bind"):
            bound.add(named[0])

    missing_cmds = sorted(c for c in invoked if c not in commands)
    check(
        "every command the page invokes is registered",
        not missing_cmds,
        f"{missing_cmds}",
    )
    missing_cvars = sorted(c for c in bound if c not in cvars)
    check(
        "every cvar the page edits is registered",
        not missing_cvars,
        f"{missing_cvars}",
    )
    check("the page actually invokes commands", bool(invoked), "")
    check("the page actually edits cvars", bool(bound), "")

    head("archived settings cannot escape")
    archived = set(re.findall(r'Cvar_Get\("(mapgen_[a-z_]+)"[^;]*CVAR_ARCHIVE',
                              client))
    check(
        "the generator has archived settings",
        bool(archived),
        "the donor, the fidelity and the seed are remembered between sessions",
    )
    check(
        "config ownership claims the mapgen prefix",
        '"mapgen_"' in ownership,
        "an archived setting with no ownership rule lands in a global config",
    )

    head("both languages, on every row")
    rows = [ln.strip() for ln in page.splitlines() if ln.strip()]
    speaking = [
        ln for ln in rows
        if ln.split()[0] in ("action", "field", "toggle", "pairs", "values",
                             "range", "blank", "section")
    ]
    check("the page has rows", bool(speaking), "")
    no_ru = [ln[:60] for ln in speaking if "--name-ru" not in ln
             and not ln.startswith("blank")]
    check(
        "every named row has a Russian name",
        not no_ru,
        f"{no_ru}",
    )
    said = [ln for ln in speaking if "--status " in ln]
    no_status_ru = [ln[:60] for ln in said if "--status-ru" not in ln]
    check(
        "every row with a hint has a Russian hint",
        not no_status_ru,
        f"{no_status_ru}",
    )
    blanks = [ln for ln in rows if ln.startswith("blank ")]
    no_blank_ru = [ln[:60] for ln in blanks if "--name-ru" not in ln]
    check(
        "every line of explanation is in both languages",
        not no_blank_ru,
        f"{no_blank_ru}",
    )

    head("what the page promises")
    check(
        "a button acts on what the page shows",
        "if (item->type == MTYPE_ACTION)\n"
        "        Menu_CommitEditedFields(s, item);" in menu_c
        and "strcmp(f->field.text, f->cvar->string) != 0" in menu_c,
        "a field commits on ENTER and on leaving the page; a button press was "
        "neither, so typing a name and pressing Build acted on the old value",
    )
    check(
        "the donor box takes a list",
        "static int donor_list(const char *text" in client
        and "*end != ';'" in client,
        "several maps is what an analysis learns from; one is the shortest "
        "list",
    )
    check(
        "every named map is checked before a job is submitted",
        "donors_are_installed(names, count)" in client
        and "if (!donors_are_installed(names, count))\n        return;" in client,
        "finding a bad name after a compile has run on the others is finding "
        "it out too late",
    )
    check(
        "a missing map is reported by name, and nothing starts",
        "not in this installation: %s" in client
        and "UI_MapGen_Notice(" in client,
        "",
    )
    check(
        "a notice has one button and a question has two",
        'MGN_DrawButton(&l.ok, MGN_Ru() ? "ОК" : "OK", true);' in notice
        and "if (s_rows) {" in notice
        and "} else if (s_confirm) {" in notice
        and "MGN_DrawButton(&l.cancel," in notice,
        "a notice reports something already settled, so a second button would "
        "be asking about a decision that has been made; a question and a list "
        "both need a way out that is not yes",
    )
    check(
        "a name is the same map with or without .bsp",
        "donor_file_name(" in client and '".bsp"' in client,
        "one spelling is what a person types",
    )
    check(
        "the donor has a default that works",
        'Cvar_Get("mapgen_donor", "q2dm1"' in client,
        "a page that refuses until something is typed is a page that looks "
        "broken the first time it is opened",
    )

    head("a build a player can watch")
    check(
        "starting a build opens the panel",
        "mapgen_show_progress();" in client
        and client.count("mapgen_show_progress();") >= 3,
        "a button that appears to do nothing for ten minutes is a button "
        "nobody trusts",
    )
    check(
        "the panel is live, not a sentence that was true once",
        "UI_MapGen_LiveNotice(" in client
        and "s_live(scratch, size, MGN_Ru());" in notice,
        "a build takes minutes; a body composed at open time would be wrong "
        "for almost all of them",
    )
    check(
        "it answers for a finished job too",
        "if (o.view.terminal) {" in client
        and "won ? (ru ?" in client,
        "the window somebody left open has to stop freezing on the last stage "
        "it saw",
    )
    check(
        "the end announces itself, once, naming the map",
        "if (!mapgen_announced) {" in client
        and "mapgen_announced = true;" in client
        and "mapgen_announced = false;" in client,
        "a panel that reopened every frame could never be closed",
    )

    head("the page speaks in the product's terms")
    forbidden = re.findall(
        r"\b(TODO|reserved|placeholder|not implemented|coming soon|phase \d)\b",
        page, re.IGNORECASE)
    check(
        "no unfinished vocabulary on the page",
        not forbidden,
        f"{sorted(set(forbidden))}",
    )

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
