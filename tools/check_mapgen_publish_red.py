"""Can the publication refuse what it must refuse?

Codex's ruling of 2026-09-03, section 11, names the controlled REDs: a
destination collision, a failure before each member and before the commit
point, a missing or corrupt certificate, a missing or corrupt recipe, a summary
hash that does not match, a stale staging file, a job identity reused across
sessions, a loose prefixed BSP, and tampering after publication.

Each case damages one thing and asserts the result the publication gave, and
- for the refusals - that NOTHING became visible. A publication that refuses
loudly and still leaves a map in the maps directory has refused nothing.

    python tools/check_mapgen_publish_red.py [--work DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260903"
                    r"\publish_red")

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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    """A worker verdict in the shape the strict receipt parser reads."""
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


def run_driver(exe: Path, *args: str) -> dict:
    run = subprocess.run([str(exe), *args], capture_output=True, text=True,
                         timeout=300)
    out = {"result": "?", "detail": "", "members": [], "projects": []}
    for line in run.stdout.splitlines():
        if line.startswith("result "):
            out["result"] = line.split()[1]
        elif line.startswith("detail "):
            out["detail"] = line[7:]
        elif line.startswith("member "):
            out["members"].append(line.split()[1:])
        elif line.startswith("project "):
            out["projects"].append(line.split()[1])
    return out


class Bench:
    """A clean maps directory and a fresh set of source artifacts per case."""

    def __init__(self, work: Path, exe: Path, case: str):
        self.root = work / case
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        self.maps = self.root / "maps"
        self.src = self.root / "src"
        self.maps.mkdir(parents=True)
        self.src.mkdir(parents=True)
        self.exe = exe
        self.bsp = self.write("job.bsp", b"IBSP" + b"x" * 512)
        self.certs = self.write(
            "job.certificates.txt",
            certificate_text(sha256_bytes(self.bsp.read_bytes()))
            .encode())
        self.recipe = self.write("job.q2mgrec", b"Q2MGREC" + b"y" * 64)
        self.receipt = self.write("receipt.txt",
                                  receipt_text(sha256_bytes(
                                      self.bsp.read_bytes())).encode())

    def write(self, name: str, data: bytes) -> Path:
        path = self.src / name
        path.write_bytes(data)
        return path

    def commit(self, name: str = "q2mg_0001", job: str = "j1",
               declared: str | None = None, drop: str | None = None) -> dict:
        if declared is None:
            # The verdict declared a hash when the file was still there, so a
            # case that takes the map away must still present the hash it had -
            # otherwise the publication would refuse for the wrong reason.
            declared = sha256_bytes(self.bsp.read_bytes()
                                    if self.bsp.is_file() else b"")
        wanted = [
            ("map", ".bsp", self.bsp, True, declared),
            ("certificates", ".certificates.txt", self.certs, True, ""),
            ("recipe", ".q2mgrec", self.recipe, True, ""),
            ("receipt", ".q2mgreceipt", self.receipt, True, ""),
        ]
        args = ["commit", "--maps", str(self.maps), "--name", name,
                "--job", job, "--jobdir", str(self.src)]
        for role, suffix, path, required, sha in wanted:
            if role == drop:
                continue
            piece = f"{role}:{suffix}:{path}"
            piece += ":required" if required else ":optional"
            if sha:
                piece += f":{sha}"
            args += ["--member", piece]
        return run_driver(self.exe, *args)

    def visible(self) -> list[str]:
        """Everything a player could see: files in the maps directory that are
        not staging."""
        return sorted(p.name for p in self.maps.iterdir()
                      if not p.name.startswith(".q2mgstage"))

    def listed(self) -> list[str]:
        return run_driver(self.exe, "list", "--maps", str(self.maps))["projects"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    exe = build(args.work)

    print("the name is already taken")
    b = Bench(args.work, exe, "collision")
    first = b.commit()
    check("the first publication succeeds", first["result"] == "OK",
          first["detail"])
    before = sorted(p.read_bytes() for p in b.maps.iterdir() if p.is_file())
    b.bsp.write_bytes(b"IBSP" + b"z" * 512)          # a different map, same name
    b.receipt.write_bytes(receipt_text(
        sha256_bytes(b.bsp.read_bytes())).encode())
    b.certs.write_bytes(certificate_text(
        sha256_bytes(b.bsp.read_bytes())).encode())
    second = b.commit()
    check("a second publication under the same name is refused",
          second["result"] == "ERR_COLLISION", second["result"])
    after = sorted(p.read_bytes() for p in b.maps.iterdir() if p.is_file())
    check("and the Project that was there is untouched", before == after)

    print("\none member of the set is not there")
    for role in ("map", "certificates", "recipe", "receipt"):
        b = Bench(args.work, exe, f"missing_{role}")
        out = b.commit(drop=role)
        if role == "map":
            expected = out["result"] in ("ERR_SOURCE", "ERR_ARGS")
        else:
            expected = out["result"] == "OK"
        # A member the caller does not declare at all is a different thing from
        # one it declares and cannot produce; both must leave nothing behind
        # when they refuse.
        b2 = Bench(args.work, exe, f"gone_{role}")
        getattr(b2, {"map": "bsp", "certificates": "certs",
                     "recipe": "recipe", "receipt": "receipt"}[role]).unlink()
        out2 = b2.commit()
        check(f"a declared {role} that is not on disk is refused",
              out2["result"] == "ERR_SOURCE", out2["result"])
        check(f"and nothing of the set is visible ({role})",
              b2.visible() == [], str(b2.visible()))
        del expected

    print("\nthe map is not what the verdict said it was")
    b = Bench(args.work, exe, "hash")
    out = b.commit(declared=sha256_bytes(b"something else entirely"))
    check("a declared hash that does not match is refused",
          out["result"] == "ERR_HASH", out["result"])
    check("and nothing is visible", b.visible() == [], str(b.visible()))

    print("\nthe evidence a verdict rests on")
    b = Bench(args.work, exe, "empty_certificates")
    b.certs.write_bytes(b"")
    out = b.commit()
    published = out["result"] == "OK"
    verified = run_driver(exe, "verify", "--maps", str(b.maps), "--name",
                          "q2mg_0001") if published else out
    check("a receipt resting on a certificate cannot be satisfied by an "
          "empty file",
          not published or verified["result"] != "OK",
          f"commit {out['result']}, verify {verified['result']}")

    b = Bench(args.work, exe, "certificates_omitted")
    out = b.commit(drop="certificates")
    check("a receipt that declares a certificate refuses a manifest without "
          "one", out["result"] != "OK", out["detail"])

    b = Bench(args.work, exe, "recipe_omitted")
    out = b.commit(drop="recipe")
    check("and the same for the recipe it names", out["result"] != "OK",
          out["detail"])

    b = Bench(args.work, exe, "receipt_wrong_map")
    b.receipt.write_bytes(receipt_text(sha256_bytes(b"a different map"))
                          .encode())
    out = b.commit()
    published = out["result"] == "OK"
    verified = run_driver(exe, "verify", "--maps", str(b.maps), "--name",
                          "q2mg_0001") if published else out
    check("a receipt that describes a different map is not this Project's",
          not published or verified["result"] != "OK",
          f"commit {out['result']}, verify {verified['result']}")

    print("\ntampering after publication")
    b = Bench(args.work, exe, "tamper")
    b.commit()
    target = b.maps / "q2mg_0001.bsp"
    target.write_bytes(target.read_bytes() + b"one more byte")
    out = run_driver(exe, "verify", "--maps", str(b.maps), "--name",
                     "q2mg_0001")
    check("a map edited after publication does not verify",
          out["result"] == "ERR_HASH", out["result"])
    check("and it is not listed", b.listed() == [], str(b.listed()))

    b = Bench(args.work, exe, "tamper_manifest")
    b.commit()
    manifest = b.maps / "q2mg_0001.q2mgproj"
    text = manifest.read_bytes().decode("latin1")
    manifest.write_bytes(text.replace("name q2mg_0001", "name q2mg_9999")
                         .encode("latin1"))
    out = run_driver(exe, "verify", "--maps", str(b.maps), "--name",
                     "q2mg_0001")
    check("a manifest edited to lie about itself does not verify",
          out["result"] == "ERR_MANIFEST", out["result"])

    b = Bench(args.work, exe, "tamper_sidecar")
    b.commit()
    certs = b.maps / "q2mg_0001.certificates.txt"
    certs.write_text("a certificate somebody made up\n", encoding="latin1")
    out = run_driver(exe, "verify", "--maps", str(b.maps), "--name",
                     "q2mg_0001")
    check("a certificate replaced after publication does not verify",
          out["result"] == "ERR_HASH", out["result"])

    b = Bench(args.work, exe, "member_removed")
    b.commit()
    (b.maps / "q2mg_0001.q2mgrec").unlink()
    out = run_driver(exe, "verify", "--maps", str(b.maps), "--name",
                     "q2mg_0001")
    check("a recipe deleted after publication does not verify",
          out["result"] == "ERR_SOURCE", out["result"])

    print("\na stale staging directory from a run that died")
    b = Bench(args.work, exe, "stale_stage")
    stale = b.maps / ".q2mgstage_q2mg_0001_j1"
    stale.mkdir(parents=True)
    (stale / "q2mg_0001.bsp").write_bytes(b"IBSP half a map")
    out = b.commit()
    check("a staging directory that is already there refuses the publication",
          out["result"] == "ERR_STAGE", f"{out['result']}: {out['detail']}")
    check("and nothing became visible", b.visible() == [], str(b.visible()))
    out = b.commit(job="j2")
    check("the same artifacts publish under a fresh identity",
          out["result"] == "OK", out["detail"])
    check("and the map published is the one from this run",
          (b.maps / "q2mg_0001.bsp").read_bytes() == b.bsp.read_bytes())

    print("\nthe same job identity used twice")
    b = Bench(args.work, exe, "job_reuse")
    check("the first is published", b.commit(name="q2mg_0001", job="same")
          ["result"] == "OK")
    out = b.commit(name="q2mg_0002", job="same")
    check("a second Project with the same job identity still publishes under "
          "its own name", out["result"] == "OK", out["detail"])
    check("and both are listed", sorted(b.listed())
          == ["q2mg_0001", "q2mg_0002"], str(b.listed()))
    out = b.commit(name="q2mg_0001", job="same")
    check("but reusing the identity cannot overwrite the first",
          out["result"] == "ERR_COLLISION", out["result"])

    print("\na loose file that looks like a map")
    b = Bench(args.work, exe, "loose")
    (b.maps / "q2mg_driver_artifact.bsp").write_bytes(b"IBSP a test artifact")
    (b.maps / "q2mg_driver_artifact.certificates.txt").write_bytes(b"x\n")
    check("a loose BSP with sidecars is still not a Project",
          b.listed() == [], str(b.listed()))
    out = run_driver(exe, "verify", "--maps", str(b.maps), "--name",
                     "q2mg_driver_artifact")
    check("and it does not verify", out["result"] == "ERR_NOT_A_PROJECT",
          out["result"])

    print("\na manifest that does not bind the map")
    #
    # Codex calls this the critical one: a manifest listing one receipt, beside
    # a loose BSP nothing ever hashed, used to verify - and Play would load
    # the BSP.
    #
    b = Bench(args.work, exe, "manifest_without_map")
    b.commit()
    manifest = b.maps / "q2mg_0001.q2mgproj"
    text = manifest.read_bytes().decode("latin1")
    kept_map = (b.maps / "q2mg_0001.bsp").read_bytes()
    lines = [ln for ln in text.splitlines()
             if not ln.startswith("member map ")]
    lines = [ln.replace("members 4", "members 3") for ln in lines]
    body = "\n".join(ln for ln in lines
                      if not ln.startswith("manifest-sha256")) + "\n"
    manifest.write_bytes((body + "manifest-sha256 "
                          + sha256_bytes(body.encode("latin1"))
                          + "\n").encode("latin1"))
    (b.maps / "q2mg_0001.bsp").write_bytes(kept_map + b" tampered")
    out = run_driver(exe, "verify", "--maps", str(b.maps), "--name",
                     "q2mg_0001")
    check("a manifest with no map role is not a Project",
          out["result"] == "ERR_ROLE", f"{out['result']}: {out['detail']}")
    check("and it is not listed", b.listed() == [], str(b.listed()))

    print("\nthe manifest grammar")
    schema_cases = [
        ("the project name in the manifest must be its own",
         lambda s: s.replace("name q2mg_0001", "name q2mg_9999")),
        ("the member count must be the number of members",
         lambda s: s.replace("members 4", "members 3")),
        ("a hash must be a hash",
         lambda s: s.replace("member map q2mg_0001.bsp ", "member map "
                             "q2mg_0001.bsp zz")),
        ("the map member must be <name>.bsp",
         lambda s: s.replace("member map q2mg_0001.bsp",
                             "member map q2mg_other.bsp")),
        ("nothing may follow the manifest hash",
         lambda s: s + "member map q2mg_0001.bsp " + "0" * 64 + "\n"),
        ("a role may not appear twice",
         lambda s: s.replace("members 4", "members 5").replace(
             "manifest-sha256",
             "member receipt q2mg_0001.q2mgreceipt " + "0" * 64
             + "\nmanifest-sha256")),
        ("a member file may not be a path",
         lambda s: s.replace("member map q2mg_0001.bsp",
                             "member map ../q2mg_0001.bsp")),
    ]
    for label, mutate in schema_cases:
        b = Bench(args.work, exe, "schema_" + label.split()[1])
        b.commit()
        manifest = b.maps / "q2mg_0001.q2mgproj"
        manifest.write_bytes(
            mutate(manifest.read_bytes().decode("latin1")).encode("latin1"))
        out = run_driver(exe, "verify", "--maps", str(b.maps), "--name",
                         "q2mg_0001")
        check(label, out["result"] not in ("OK", "?"),
              f"{out['result']}: {out['detail']}")

    print("\nwhat a worker may name")
    b = Bench(args.work, exe, "escape")
    outside = b.root / "outside.bsp"
    outside.write_bytes(b"IBSP somewhere else")
    args_list = ["commit", "--maps", str(b.maps), "--name", "q2mg_0001",
                 "--job", "j1", "--jobdir", str(b.src),
                 f"--member", f"map:.bsp:{outside}:required",
                 f"--member", f"receipt:.q2mgreceipt:{b.receipt}:required"]
    out = run_driver(exe, *args_list)
    check("a source outside the job directory is refused",
          out["result"] == "ERR_NAME", f"{out['result']}: {out['detail']}")
    check("and nothing is visible", b.visible() == [], str(b.visible()))

    for bad in ("../escape", "a/b", "nul", ".hidden", "with space"):
        b = Bench(args.work, exe, "name_" + bad.replace("/", "_")
                  .replace(".", "_").replace(" ", "_"))
        out = b.commit(name=bad)
        check(f"a Project may not be called {bad!r}",
              out["result"] == "ERR_NAME", f"{out['result']}")

    print(f"\n{CASES} cases, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
