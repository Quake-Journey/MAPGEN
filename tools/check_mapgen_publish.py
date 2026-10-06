"""Publishing a Project: all of it, or none of it, and never over the top.

Codex's ruling of 2026-09-03, section 11, made this a blocking correction. The
old publication copied the map, tried the sidecars, ignored whether they
arrived, returned success, and called `remove()` on the destination first - so
a second job with the same name silently replaced the first. Nothing recorded
that a set of files belonged together, so the client decided what was playable
from filename prefixes, and about twenty-five driver artifacts in the Release
tree were being offered to the player as generated maps.

    python tools/check_mapgen_publish.py [--work DIR]

GREEN here, and the controlled REDs section 11 names in
check_mapgen_publish_red.py: destination collision, failure before each member
and before the commit point, a missing or corrupt certificate, a missing or
corrupt recipe, a declared hash that does not match, a stale staging file, a
job identity reused across sessions, a loose prefixed BSP, and tampering after
publication.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260903\publish")

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + (f"  -- {detail}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILED += 1
    return ok


def build(work: Path) -> Path:
    exe = work / "pub.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
         "-I" + str(REPO / "inc"),
         str(REPO / "tools/mapgen_publish_driver.c"),
         str(REPO / "src/mapgen/mapgen_publish.c"),
         str(REPO / "src/mapgen/mapgen_digest.c"),
         "-o", str(exe)], capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the publish driver")
    return exe


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def run_driver(exe: Path, *args: str) -> dict:
    run = subprocess.run([str(exe), *args], capture_output=True, text=True,
                         timeout=300)
    out = {"result": "?", "detail": "", "members": [], "projects": [],
           "code": run.returncode, "manifest": "", "name": ""}
    for line in run.stdout.splitlines():
        if line.startswith("result "):
            out["result"] = line.split()[1]
        elif line.startswith("detail "):
            out["detail"] = line[7:]
        elif line.startswith("member "):
            out["members"].append(line.split()[1:])
        elif line.startswith("project "):
            out["projects"].append(line.split()[1])
        elif line.startswith("manifest "):
            out["manifest"] = line.split()[1] if len(line.split()) > 1 else ""
        elif line.startswith("name "):
            out["name"] = line.split()[1] if len(line.split()) > 1 else ""
    return out


def make_source(work: Path, name: str, text: str) -> Path:
    path = work / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin1"))
    return path


def certificate_text(map_hash: str, count: int = 1) -> str:
    """Certificates in the shape MapGenCertificate_Render writes them.

    A file that merely says the word "certificate" is not evidence: publication
    insists every record names the candidate it certifies and carries a physics
    identity, so the fixtures have to be real records.
    """
    out = []
    for i in range(count):
        out.append(f"certificate {i}\n"
                   "  kind rocket-jump\n"
                   f"  candidate {map_hash}\n"
                   f"  donor {'d' * 64}\n"
                   f"  physics {'p' * 64}\n"
                   "  entity 12 item_quad\n"
                   "  at 0.0 0.0 0.0\n")
    return "".join(out)


def receipt_text(map_hash: str, certificates: int = 1,
                 recipe: str = "job.q2mgrec") -> str:
    """What the worker's verdict says, in the shape the strict parser reads."""
    return ("result OK\n"
            "map job.map\n"
            "bsp job.bsp\n"
            f"bspsha {map_hash}\n"
            "places 100\n"
            "spawns 8\n"
            "divergence 0\n"
            "target 0\n"
            "inband 1\n"
            f"certificates {certificates}\n"
            f"recipe {recipe}\n"
            "publishable 1\n")


def members(work: Path, declared_map_hash: str | None = None) -> list[str]:
    bsp = make_source(work, "job.bsp", "IBSP" + "x" * 512)
    certs = make_source(work, "job.certificates.txt",
                        certificate_text(sha256(bsp)))
    recipe = make_source(work, "job.q2mgrec", "Q2MGREC" + "y" * 64)
    declared = declared_map_hash if declared_map_hash is not None else sha256(bsp)
    receipt = make_source(work, "receipt.txt", receipt_text(sha256(bsp)))
    return [
        f"map:.bsp:{bsp}:required:{declared}",
        f"certificates:.certificates.txt:{certs}:required",
        f"recipe:.q2mgrec:{recipe}:required",
        f"receipt:.q2mgreceipt:{receipt}:required",
    ]


def commit(exe: Path, maps: Path, name: str, work: Path, job: str = "j1",
           declared: str | None = None) -> dict:
    args = ["commit", "--maps", str(maps), "--name", name, "--job", job,
            "--jobdir", str(work / "src")]
    for m in members(work, declared):
        args += ["--member", m]
    return run_driver(exe, *args)


def loader_binding(exe: Path, maps: Path, work: Path) -> None:
    """A Project is only playable as the map its manifest records.

    `verify` opens the files and hashes them, which answers about a path. The
    engine then opens that path AGAIN, and nothing about the first answer says
    the second read saw the same thing. `bind` is handed the bytes a loader is
    holding, so what was checked and what is used are one thing.

    The case that separates them is a Project that verifies perfectly while the
    bytes offered are something else - which is what a load in the window
    between the two would be.
    """
    print("\nthe loader is bound to the bytes it is holding, not to a path")

    published = maps / "q2mg_0001.bsp"
    ok = run_driver(exe, "verify", "--maps", str(maps), "--name", "q2mg_0001")
    if not check("the Project this rests on still verifies",
                 ok["result"] == "OK", ok["result"]):
        return

    out = run_driver(exe, "bind", "--maps", str(maps), "--name", "q2mg_0001",
                     "--bytes", str(published))
    check("its own map binds", out["result"] == "OK", str(out))

    #
    # The controlled RED, and the one that matters: the files on disk are
    # untouched, so `verify` still says OK - and the bytes in hand are not the
    # map, so the load must be refused. A check made before the read cannot
    # tell these two runs apart.
    #
    other = work / "not_the_map.bsp"
    original = published.read_bytes()
    other.write_bytes(original[:-1] + bytes([original[-1] ^ 0x01]))
    out = run_driver(exe, "bind", "--maps", str(maps), "--name", "q2mg_0001",
                     "--bytes", str(other))
    check("one bit different is refused", out["result"] == "ERR_NOT_THESE_BYTES",
          str(out))
    still = run_driver(exe, "verify", "--maps", str(maps), "--name", "q2mg_0001")
    check("and the path still verifies, which is why the path is not enough",
          still["result"] == "OK", str(still))

    empty = work / "nothing.bsp"
    empty.write_bytes(b"")
    out = run_driver(exe, "bind", "--maps", str(maps), "--name", "q2mg_0001",
                     "--bytes", str(empty))
    check("no bytes at all are refused",
          out["result"] == "ERR_NOT_THESE_BYTES", str(out))

    out = run_driver(exe, "bind", "--maps", str(maps), "--name", "q2mg_9999",
                     "--bytes", str(published))
    check("a name with no manifest is refused as not a Project",
          out["result"] == "ERR_NOT_A_PROJECT", str(out))

    #
    # And the call site, statically. A binding the loader does not ask is a
    # binding that does not happen - Hard Rule #51: a seam proves the
    # algorithm, never the call.
    #
    bsp_c = (REPO / "src" / "common" / "bsp.c").read_text(encoding="utf-8",
                                                          errors="replace")
    check("the loader asks it", "BSP_BindProject(name, buf, filelen)" in bsp_c)
    if "BSP_BindProject(name, buf, filelen)" in bsp_c:
        asked = bsp_c.index("BSP_BindProject(name, buf, filelen)")
        parsed = bsp_c.index("header = (dheader_t *)buf;")
        check("before it parses a single byte of the file", asked < parsed,
              f"asked at {asked}, parses at {parsed}")
    check("and a map that is not a Project is left alone",
          "MapGenPublish_IsProjectName(base)" in bsp_c)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    args = ap.parse_args()
    if args.work.exists():
        shutil.rmtree(args.work, ignore_errors=True)
    args.work.mkdir(parents=True, exist_ok=True)

    exe = build(args.work)
    maps = args.work / "maps"
    maps.mkdir(parents=True, exist_ok=True)

    print("a Project is published, and it is all there")
    out = commit(exe, maps, "q2mg_0001", args.work)
    check("the commit succeeds", out["result"] == "OK", out["detail"])
    check("every member is recorded with its hash", len(out["members"]) == 4,
          f"{len(out['members'])} members")
    for role, file, digest in out["members"]:
        on_disk = maps / file
        check(f"the {role} is on the disk", on_disk.is_file())
        if on_disk.is_file():
            check(f"the {role} hashes to what the manifest says",
                  sha256(on_disk) == digest,
                  f"{sha256(on_disk)[:16]} vs {digest[:16]}")

    print("\nand nothing is left behind")
    stage = [p for p in maps.iterdir() if p.name.startswith(".q2mgstage")]
    check("the staging directory is gone", not stage, str(stage))
    parts = list(maps.glob("*.part"))
    check("no half-written file remains", not parts, str(parts))

    print("\nverification")
    out = run_driver(exe, "verify", "--maps", str(maps), "--name", "q2mg_0001")
    check("the Project verifies", out["result"] == "OK", out["detail"])
    out = run_driver(exe, "verify", "--maps", str(maps), "--name", "not_here")
    check("something that was never published is not a Project",
          out["result"] == "ERR_NOT_A_PROJECT", out["result"])

    loader_binding(exe, maps, args.work)

    print("\nlisting")
    commit(exe, maps, "q2mg_0002", args.work, job="j2")
    out = run_driver(exe, "list", "--maps", str(maps))
    check("both Projects are listed", sorted(out["projects"])
          == ["q2mg_0001", "q2mg_0002"], str(out["projects"]))

    (maps / "q2mg_loose.bsp").write_bytes(b"IBSP not a project")
    out = run_driver(exe, "list", "--maps", str(maps))
    check("a loose BSP with the right-looking name is not listed",
          "q2mg_loose" not in out["projects"], str(out["projects"]))
    out = run_driver(exe, "verify", "--maps", str(maps), "--name",
                     "q2mg_loose")
    check("and it does not verify",
          out["result"] == "ERR_NOT_A_PROJECT", out["result"])

    print("\nthe manifest is the only thing that makes a Project")
    manifest = maps / "q2mg_0002.q2mgproj"
    kept = manifest.read_bytes()
    manifest.unlink()
    out = run_driver(exe, "list", "--maps", str(maps))
    check("with the manifest gone the files are not a Project",
          "q2mg_0002" not in out["projects"], str(out["projects"]))
    manifest.write_bytes(kept)
    out = run_driver(exe, "list", "--maps", str(maps))
    check("and putting it back makes it one again",
          "q2mg_0002" in out["projects"], str(out["projects"]))

    print(f"\n{CASES} cases, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
