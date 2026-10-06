#!/usr/bin/env python3
"""MAPGEN-1 M0 acceptance suite.

Every case ASSERTS and can fail. Hard Rule #46 section 5: a harness that only
prints is not a test, "N cases captured" is not a result, and each case name is
verified against what the case actually does.

Coverage, mapped to the phase M0 deliverables in the Codex ruling:

  1. the MapCompilerAdapter contract in src/mapgen/mapgen_compiler.h agrees
     with the runner that implements it;
  2. the format-neutral fixtures regenerate byte-identically and are valid;
  3. the independent BSP oracle reads real Quake II maps and rejects malformed
     ones;
  4. the fake process adapter reproduces exit, timeout, crash, bounded logs and
     path behaviour as REAL processes;
  5. a controlled RED - damaged and missing compiler output - fails, and the
     restored good case passes;
  6. a zero exit code without a BSP reread and semantic check CANNOT be
     reported as success.

Run: python tools/check_mapgen_m0_contract.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import mapgen_bsp_oracle as oracle  # noqa: E402
import mapgen_bsp_synth as synth  # noqa: E402
import mapgen_qualification as q  # noqa: E402

# The one rule for what belongs to the fixed corpus; see mapgen_corpus.py.
from mapgen_corpus import is_generated  # noqa: E402

FIXTURES = REPO / "tools" / "mapgen_fixtures"
HEADER = REPO / "src" / "mapgen" / "mapgen_compiler.h"

CASES = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    if condition:
        print(f"  PASS  {name}")
        return True
    print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    FAILED += 1
    return False


def head(text: str) -> None:
    print(f"\n=== {text}")


# ---------------------------------------------------------------------------
# 1. Contract / implementation agreement
# ---------------------------------------------------------------------------
def test_contract_agreement() -> None:
    head("contract: header and runner agree")
    src = HEADER.read_text(encoding="utf-8")
    end = src.index("} mapcompile_result_t;")
    start = src.rindex("typedef enum {", 0, end)
    body = src[start:end]
    header_codes = re.findall(r"^\s*(MAPCOMPILE_(?:OK|ERR_[A-Z_]+))\s*[,=]", body, re.MULTILINE)
    check(
        "header declares a non-empty, duplicate-free result enum",
        len(header_codes) > 5 and len(header_codes) == len(set(header_codes)),
        f"{header_codes}",
    )
    check(
        "header result codes match the runner",
        header_codes == list(q.RESULTS),
        f"header={header_codes}\nrunner={list(q.RESULTS)}",
    )
    check(
        "header states the zero-exit law",
        "A zero exit code is NEVER success." in src,
        "the law must be stated where the contract lives",
    )
    check(
        "header forbids OK without reread and semantics",
        "MAPCOMPILE_OK implies report->reread_performed && report->semantics_checked" in src,
        "post-condition missing from the header",
    )
    check(
        "header is not wired into any build target",
        "mapgen_compiler.h" not in (REPO / "meson.build").read_text(encoding="utf-8"),
        "M0 must not add production build targets",
    )


# ---------------------------------------------------------------------------
# 2. Fixtures
# ---------------------------------------------------------------------------
def test_fixtures() -> None:
    head("fixtures: deterministic and complete")
    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "mapgen_make_fixtures.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    check("fixtures regenerate byte-identically", proc.returncode == 0, proc.stdout + proc.stderr)

    index = json.loads((FIXTURES / "index.json").read_text(encoding="ascii"))
    for name in index["fixtures"]:
        map_path = FIXTURES / "maps" / f"{name}.map"
        exp_path = FIXTURES / "expected" / f"{name}.json"
        check(f"fixture present: {name}", map_path.is_file() and exp_path.is_file(), f"{map_path} / {exp_path}")

    sealed = (FIXTURES / "maps" / "sealed_room.map").read_text(encoding="ascii")
    check("valve 220 selected in worldspawn", '"mapversion" "220"' in sealed, "missing mapversion")
    check(
        "faces carry explicit contents/flags/value",
        re.search(r"\] 0 1 1 1 0 0$", sealed, re.MULTILINE) is not None,
        "faces must state collision semantics in the source text",
    )
    check("no CRLF in generated fixtures", "\r" not in sealed, "fixtures must be LF-only for stable regeneration")

    leaking = (FIXTURES / "maps" / "leaking_room.map").read_text(encoding="ascii")
    check(
        "leak fixture differs from sealed by exactly one brush",
        sealed.count("\n{\n") - leaking.count("\n{\n") == 1,
        f"sealed={sealed.count(chr(10)+'{'+chr(10))} leaking={leaking.count(chr(10)+'{'+chr(10))}",
    )
    leak_exp = json.loads((FIXTURES / "expected" / "leaking_room.json").read_text(encoding="ascii"))
    check(
        "leak expectation names the zero-exit trap",
        leak_exp.get("expected_failure") == "MAPCOMPILE_ERR_LEAKED" and "exit(0)" in leak_exp.get("note", ""),
        f"{leak_exp}",
    )

    for wal in sorted((FIXTURES / "textures").rglob("*.wal")):
        data = wal.read_bytes()
        width, height = int.from_bytes(data[32:36], "little"), int.from_bytes(data[36:40], "little")
        offsets = [int.from_bytes(data[40 + 4 * i : 44 + 4 * i], "little") for i in range(4)]
        expect = 100 + sum((width >> i) * (height >> i) for i in range(4))
        check(
            f"wal is structurally valid: {wal.name}",
            offsets[0] == 100 and len(data) == expect and width == height == 16,
            f"w={width} h={height} offsets={offsets} bytes={len(data)} expected={expect}",
        )


# ---------------------------------------------------------------------------
# 3. Oracle against external ground truth
# ---------------------------------------------------------------------------
def test_oracle_against_real_maps() -> None:
    head("oracle: real Quake II maps and malformed input")
    roots = [
        Path(r"O:\Claude2\q2pro-release\baseq2\maps"),
        Path(r"O:\Claude2\q2pro-release\action\maps"),
    ]
    maps = [p for root in roots if root.is_dir() for p in sorted(root.glob("*.bsp"))
            # The generator publishes into this directory under contract 22's
            # reserved `q2mg_` basename. Those are legal training input but they are
            # not part of the fixed corpus these checks count, and a count that moves
            # every time somebody generates a map is not a count.
            if not is_generated(p.name)]
    if not check("real maps are available as ground truth", len(maps) >= 20, f"found {len(maps)}"):
        return

    parsed = 0
    problems: list[str] = []
    for path in maps:
        try:
            bsp = oracle.load(path)
            bsp.entities()
            bsp.semantic_digest()
            parsed += 1
        except Exception as exc:  # noqa: BLE001 - any failure is a finding
            problems.append(f"{path.name}: {type(exc).__name__}: {exc}")
    check(
        f"oracle parses all {len(maps)} shipped maps",
        parsed == len(maps),
        "; ".join(problems[:5]),
    )

    # Spot-check the tree walk on real geometry: no shipped spawn or item point
    # may be inside solid, and a point far below any map must be solid.
    sample = next((p for p in maps if p.name == "aerowalk.bsp"), maps[0])
    bsp = oracle.load(sample)
    solid_spawns = 0
    checked_points = 0
    for ent in bsp.entities():
        if ent.get("classname", "").startswith(("info_player", "item_", "weapon_", "ammo_")) and "origin" in ent:
            x, y, z = (float(v) for v in ent["origin"].split())
            checked_points += 1
            if bsp.point_contents((x, y, z + 1)) & oracle.CONTENTS["CONTENTS_SOLID"]:
                solid_spawns += 1
    check(
        f"no spawn/item point of {sample.name} is inside solid",
        checked_points >= 10 and solid_spawns == 0,
        f"checked {checked_points}, solid {solid_spawns}",
    )
    check(
        "a point far outside the world is solid",
        bool(bsp.point_contents((0, 0, -100000)) & oracle.CONTENTS["CONTENTS_SOLID"]),
        "the tree walk does not classify the void as solid",
    )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        bad = tmp / "not_a_bsp.bsp"
        bad.write_bytes(b"NOPE" + b"\0" * 512)
        check("oracle rejects a wrong ident", _oracle_rejects(bad), "bad ident accepted")

        good = synth.synth_solid_cube()
        wrong_version = bytearray(good)
        wrong_version[4:8] = (37).to_bytes(4, "little")
        p = tmp / "wrong_version.bsp"
        p.write_bytes(bytes(wrong_version))
        check("oracle rejects a wrong version", _oracle_rejects(p), "version 37 accepted")

        p = tmp / "truncated.bsp"
        p.write_bytes(good[: len(good) // 2])
        check("oracle rejects a truncated file", _oracle_rejects(p), "truncated file accepted")

        p = tmp / "tiny.bsp"
        p.write_bytes(b"IBSP")
        check("oracle rejects a file smaller than its header", _oracle_rejects(p), "4-byte file accepted")

        # Each of the following isolates ONE oracle guard: the file is valid in
        # every other respect, so only the guard under test can reject it. A
        # case that several guards catch cannot prove any of them.
        wrong_ident = bytearray(good)
        wrong_ident[0:4] = b"XBSP"
        p = tmp / "wrong_ident_only.bsp"
        p.write_bytes(bytes(wrong_ident))
        check(
            "oracle rejects a wrong ident on an otherwise valid file",
            _oracle_rejects(p),
            "only the ident is wrong and it was accepted",
        )

        oob = bytearray(good)
        # Lump 7 is LIGHTING; claim it extends far past the end of the file.
        struct_off = 8 + oracle.LUMP_LIGHTING * 8 + 4
        oob[struct_off : struct_off + 4] = (len(good) * 4).to_bytes(4, "little")
        p = tmp / "lump_out_of_bounds.bsp"
        p.write_bytes(bytes(oob))
        check(
            "oracle rejects a lump that runs past the end of the file",
            _oracle_rejects(p),
            "an out-of-bounds lump length was accepted",
        )

        broken_ents = synth.synth_solid_cube(
            entities=[{"classname": "worldspawn", "message": "unterminated"}]
        )
        # Mangle INSIDE the entity lump. Searching the whole file for the last
        # "}\n" can land in binary lump data, which leaves the entity string
        # valid and makes this case pass for the wrong reason - it did exactly
        # that until the controlled RED refused to go red on it.
        mangled = bytearray(broken_ents)
        ent_hdr = 8 + oracle.LUMP_ENTITIES * 8
        ent_off = int.from_bytes(mangled[ent_hdr : ent_hdr + 4], "little")
        ent_len = int.from_bytes(mangled[ent_hdr + 4 : ent_hdr + 8], "little")
        idx = ent_off + bytes(mangled[ent_off : ent_off + ent_len]).rindex(b"}")
        mangled[idx : idx + 1] = b" "
        # Each case gets its OWN variable. Reusing one `p` between the write and
        # the assertion silently pointed this check at a different file, so it
        # passed under a mutation that removed the guard it claims to test.
        unterminated_path = tmp / "unterminated_entity.bsp"
        unterminated_path.write_bytes(bytes(mangled))
        check(
            "oracle rejects an unterminated entity block",
            _oracle_rejects(unterminated_path),
            "a truncated entity string was accepted",
        )

        overflow = bytearray(synth.synth_solid_cube())
        # Claim leafbrushes the lump does not contain.
        lb_off = 8 + oracle.LUMP_LEAFBRUSHES * 8
        overflow[lb_off + 4 : lb_off + 8] = (0).to_bytes(4, "little")
        overflow_path = tmp / "leafbrush_overflow.bsp"
        overflow_path.write_bytes(bytes(overflow))
        check(
            "oracle rejects an out-of-range leafbrush reference",
            _oracle_rejects(overflow_path),
            "a leaf referencing leafbrushes that do not exist was accepted, "
            "or the reader crashed instead of rejecting",
        )

    head("oracle: synthesized fixtures round-trip")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for extended in (False, True):
            name = "QBSP" if extended else "IBSP"
            p = tmp / f"synth_{name}.bsp"
            p.write_bytes(synth.synth_solid_cube(extended=extended))
            b = oracle.load(p)
            check(f"synth {name}: format detected", ("QBSP" if b.extended else "IBSP") == name, "")
            check(
                f"synth {name}: inside the cube is solid",
                bool(b.point_contents((0, 0, 0)) & oracle.CONTENTS["CONTENTS_SOLID"]),
                "",
            )
            check(
                f"synth {name}: outside the cube is open",
                not (b.point_contents((0, 0, 512)) & oracle.CONTENTS["CONTENTS_SOLID"]),
                "",
            )
            check(
                f"synth {name}: entities survive the round trip",
                [e.get("classname") for e in b.entities()] == ["worldspawn", "info_player_start"],
                "",
            )


def _oracle_rejects(path: Path) -> bool:
    try:
        bsp = oracle.load(path)
        bsp.entities()
        bsp.semantic_digest()
    except oracle.BspError:
        return True
    except Exception:
        # Any other exception means the oracle crashed instead of rejecting.
        return False
    return False


# ---------------------------------------------------------------------------
# 4-6. The qualification runner against the fake process adapter
# ---------------------------------------------------------------------------
SUCCESS_EXPECTATIONS = {
    "entity_classnames": {"worldspawn": 1, "info_player_start": 1},
    "solid_points": [[0, 0, 0]],
    "interior_points_empty": [[0, 0, 512]],
    "min_models": 1,
}


def _request(job: Path, expectations=None, **kw) -> q.CompileRequest:
    return q.CompileRequest(
        job_dir=job,
        map_name="sealed_room",
        profile=kw.pop("profile", q.PROFILE_DRAFT),
        threads=kw.pop("threads", 1),
        moddir=kw.pop("moddir", job),
        basedir=kw.pop("basedir", job),
        timeout_s=kw.pop("timeout_s", 60.0),
        max_log_bytes=kw.pop("max_log_bytes", 64 * 1024),
        disk_budget_bytes=kw.pop("disk_budget_bytes", 32 * 1024 * 1024),
        expect_format=kw.pop("expect_format", "IBSP"),
        expectations=SUCCESS_EXPECTATIONS if expectations is None else expectations,
    )


def test_runner(sandbox: Path) -> None:
    head("runner: the fake process adapter drives every failure mode")
    src_map = FIXTURES / "maps" / "sealed_room.map"

    expectations = [
        ("success", "MAPCOMPILE_OK", {}),
        ("zero_exit_no_output", "MAPCOMPILE_ERR_NO_OUTPUT", {}),
        ("zero_exit_leak", "MAPCOMPILE_ERR_LEAKED", {}),
        ("zero_exit_missing_texture", "MAPCOMPILE_ERR_MISSING_ASSET", {}),
        ("zero_exit_wrong_semantics", "MAPCOMPILE_ERR_SEMANTICS", {}),
        ("nonzero_exit", "MAPCOMPILE_ERR_NONZERO_EXIT", {}),
        ("crash", "MAPCOMPILE_ERR_CRASH", {}),
        ("hang", "MAPCOMPILE_ERR_TIMEOUT", {"timeout_s": 4.0}),
        ("damaged_output", "MAPCOMPILE_ERR_OUTPUT_UNREADABLE", {}),
        ("stale_output", "MAPCOMPILE_ERR_NO_OUTPUT", {}),
        ("escape_path", "MAPCOMPILE_ERR_ESCAPED_JOB_ROOT", {}),
        ("log_flood", "MAPCOMPILE_OK", {"max_log_bytes": 8 * 1024}),
        # Isolated leak detection: each of these is caught by exactly one guard.
        ("zero_exit_leak_marker_only", "MAPCOMPILE_ERR_LEAKED", {}),
        ("zero_exit_leak_pts_only", "MAPCOMPILE_ERR_LEAKED", {}),
        # A later pass that leaves the map byte-identical did not run.
        ("vis_noop", "MAPCOMPILE_ERR_STALE_OUTPUT", {}),
        # A readable BSP with no world in it is not a map.
        ("degenerate_output", "MAPCOMPILE_ERR_SEMANTICS", {}),
    ]

    reports: dict[str, q.CompileReport] = {}
    for behavior, want, kw in expectations:
        job = q.prepare_job_dir(sandbox, f"job_{behavior}", src_map)
        report = q.run_profile(q.fake_adapter(behavior), _request(job, **kw), sandbox_root=sandbox)
        reports[behavior] = report
        check(
            f"behavior {behavior} -> {want}",
            report.result == want,
            f"got {report.result}; failures={report.failures[:3]}",
        )

    head("runner: the evidence each case must carry")
    ok = reports["success"]
    check("success reread the produced BSP", ok.reread_performed, "")
    check("success checked semantics", ok.semantics_checked, "")
    check("success recorded a BSP sha256", bool(ok.bsp_sha256 and len(ok.bsp_sha256) == 64), f"{ok.bsp_sha256}")
    check("success recorded a semantic digest", bool(ok.semantic_digest), "")
    check("success ran both draft stages", [s.stage for s in ok.stages] == ["bsp", "vis-fast"], f"{[s.stage for s in ok.stages]}")

    leak = reports["zero_exit_leak"]
    check("leak case really exited zero", leak.stages[0].exit_code == 0, f"{leak.stages[0].exit_code}")
    check("leak case never reread anything", not leak.reread_performed, "")

    missing = reports["zero_exit_missing_texture"]
    check("missing-asset case really exited zero", missing.stages[0].exit_code == 0, f"{missing.stages[0].exit_code}")
    check(
        "missing-asset failure names the texture",
        any("q2mgfx/absent" in f for f in missing.failures),
        f"{missing.failures}",
    )

    degenerate = reports["degenerate_output"]
    check(
        "the degenerate-output failure names what is missing",
        any("no brushes" in f or "no faces" in f or "no nodes" in f for f in degenerate.failures),
        f"{degenerate.failures}",
    )

    wrong = reports["zero_exit_wrong_semantics"]
    check("wrong-semantics case exited zero and parsed", wrong.reread_performed and wrong.stages[0].exit_code == 0, "")
    check(
        "wrong-semantics failure names the missing entity",
        any("info_player_start" in f for f in wrong.failures),
        f"{wrong.failures}",
    )

    flood = reports["log_flood"]
    check("flood produced far more output than was retained", flood.stages[0].stdout_total_bytes > 1_000_000, f"{flood.stages[0].stdout_total_bytes}")
    check("flood capture is marked truncated", flood.stages[0].stdout_truncated, "")
    check(
        "flood kept a rolling hash of the WHOLE stream",
        len(flood.stages[0].stdout_rolling_sha256) == 64,
        "",
    )
    check("flood stayed inside the retained-log budget", len(flood.stages[0].stdout_captured) <= 8 * 1024, f"{len(flood.stages[0].stdout_captured)}")

    hang = reports["hang"]
    check("timeout is recorded on the stage", hang.stages[0].timed_out, "")
    check("timeout left no exit code", hang.stages[0].exit_code is None, f"{hang.stages[0].exit_code}")

    escape = reports["escape_path"]
    check(
        "escape case names the file it wrote outside the job root",
        any("escaped_from_the_job_root" in p for p in escape.escaped_paths),
        f"{escape.escaped_paths}",
    )

    head("runner: profiles and formats")
    job = q.prepare_job_dir(sandbox, "job_final", src_map)
    final = q.run_profile(q.fake_adapter("success"), _request(job, profile=q.PROFILE_FINAL), sandbox_root=sandbox)
    check("final profile succeeds on a lit, vised output", final.result == "MAPCOMPILE_OK", f"{final.failures}")
    check("final profile ran three stages", [s.stage for s in final.stages] == ["bsp", "vis", "rad"], f"{[s.stage for s in final.stages]}")

    job = q.prepare_job_dir(sandbox, "job_final_nolight", src_map)
    nolight = q.run_profile(
        q.fake_adapter("final_no_light"), _request(job, profile=q.PROFILE_FINAL), sandbox_root=sandbox
    )
    check("final profile refuses output with no lighting", nolight.result == "MAPCOMPILE_ERR_SEMANTICS", f"{nolight.result}")
    check(
        "the no-lighting failure says so",
        any("lighting" in f for f in nolight.failures),
        f"{nolight.failures}",
    )

    job = q.prepare_job_dir(sandbox, "job_final_novis", src_map)
    novis = q.run_profile(
        q.fake_adapter("final_no_vis"), _request(job, profile=q.PROFILE_FINAL), sandbox_root=sandbox
    )
    check("final profile refuses output with no visibility", novis.result == "MAPCOMPILE_ERR_SEMANTICS", f"{novis.result}")
    check(
        "the no-visibility failure says so",
        any("visibility" in f for f in novis.failures),
        f"{novis.failures}",
    )

    job = q.prepare_job_dir(sandbox, "job_draft_nolight", src_map)
    draft_nolight = q.run_profile(
        q.fake_adapter("final_no_light"), _request(job, profile=q.PROFILE_DRAFT), sandbox_root=sandbox
    )
    check(
        "the DRAFT profile does not require lighting",
        draft_nolight.result == "MAPCOMPILE_OK",
        f"{draft_nolight.result}: {draft_nolight.failures}",
    )

    job = q.prepare_job_dir(sandbox, "job_qbsp", src_map)
    qbsp_ok = q.run_profile(q.fake_adapter("success"), _request(job, expect_format="QBSP"), sandbox_root=sandbox)
    check("an honoured QBSP request succeeds", qbsp_ok.result == "MAPCOMPILE_OK", f"{qbsp_ok.failures}")
    check(
        "the QBSP request really produced QBSP",
        (qbsp_ok.oracle_summary or {}).get("format") == "QBSP",
        f"{(qbsp_ok.oracle_summary or {}).get('format')}",
    )

    job = q.prepare_job_dir(sandbox, "job_format", src_map)
    wrong_fmt = q.run_profile(
        q.fake_adapter("wrong_format"), _request(job, expect_format="QBSP"), sandbox_root=sandbox
    )
    check("a format mismatch is a failure", wrong_fmt.result == "MAPCOMPILE_ERR_WRONG_FORMAT", f"{wrong_fmt.result}")

    head("runner: the job directory must be fresh")
    job = q.prepare_job_dir(sandbox, "job_dirty", src_map)
    (job / "sealed_room.bsp").write_bytes(synth.synth_solid_cube())
    dirty = q.run_profile(q.fake_adapter("success"), _request(job), sandbox_root=sandbox)
    check("a pre-existing BSP is refused before the run", dirty.result == "MAPCOMPILE_ERR_DIRTY_JOB_DIR", f"{dirty.result}")
    check("the dirty case never launched the compiler", not dirty.stages, f"{len(dirty.stages)} stages ran")

    head("runner: explicit thread policy")
    job = q.prepare_job_dir(sandbox, "job_threads", src_map)
    argv = q.fake_adapter("success").build_argv(_request(job, threads=3), "bsp")
    check("-threads is always passed explicitly", "-threads" in argv and argv[argv.index("-threads") + 1] == "3", f"{argv}")
    check("-moddir and -basedir are always passed", "-moddir" in argv and "-basedir" in argv, f"{argv}")

    head("runner: OK cannot be forged")

    # Each half is tested with the OTHER half already satisfied, so a case can
    # only pass because the guard under test fired. Testing both at once let a
    # mutation that deleted the reread guard hide behind the semantics guard.
    only_semantics = q.CompileReport(request=_request(sandbox / "job_success"))
    only_semantics.semantics_checked = True
    raised = False
    try:
        only_semantics.finish_ok()
    except q.QualificationError as exc:
        raised = "reread" in str(exc)
    check("finish_ok refuses without a reread", raised, "a report with no reread returned OK")

    only_reread = q.CompileReport(request=_request(sandbox / "job_success"))
    only_reread.reread_performed = True
    raised = False
    try:
        only_reread.finish_ok()
    except q.QualificationError as exc:
        raised = "semantic" in str(exc)
    check("finish_ok refuses without a semantic check", raised, "a report with no semantic check returned OK")

    forged = q.CompileReport(request=_request(sandbox / "job_success"))
    forged.reread_performed = True
    forged.semantics_checked = True
    check("finish_ok accepts a fully evidenced report", forged.finish_ok() == "MAPCOMPILE_OK", "")

    head("runner: determinism of the semantic digest")
    digests = set()
    for i in range(3):
        job = q.prepare_job_dir(sandbox, f"job_det_{i}", src_map)
        r = q.run_profile(q.fake_adapter("success"), _request(job), sandbox_root=sandbox)
        digests.add(r.semantic_digest)
    check("the same output digests identically across runs", len(digests) == 1, f"{digests}")

    head("runner: no orphan processes")
    check("no fake compiler survived the matrix", _no_orphans(), "a mapgen_fake_compiler process is still running")


def _no_orphans() -> bool:
    """Did anything THIS guard started outlive it?

    Not "is any fake compiler running anywhere": the suite runs guards four at
    a time and the pipeline guard has one of its own, doing exactly what it is
    supposed to be doing. A check whose answer depends on what else is running
    is not a check, and this one reported a failure that a second run of the
    same guard could not reproduce.
    """
    if os.name != "nt":
        return True
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Select-Object ProcessId,"
         " ParentProcessId, CommandLine | ConvertTo-Json -Compress"],
        capture_output=True, text=True,
    )
    try:
        rows = json.loads(proc.stdout)
    except (ValueError, TypeError):
        return True
    if isinstance(rows, dict):
        rows = [rows]

    parent = {}
    suspects = []
    for row in rows:
        pid = row.get("ProcessId")
        if pid is None:
            continue
        parent[pid] = row.get("ParentProcessId")
        command = row.get("CommandLine") or ""
        if "mapgen_fake_compiler" in command:
            suspects.append(pid)

    mine = os.getpid()
    for pid in suspects:
        seen = set()
        walk = pid
        while walk is not None and walk not in seen:
            if walk == mine:
                return False
            seen.add(walk)
            walk = parent.get(walk)
    return True


def main() -> int:
    print("=== MAPGEN-1 M0 contract acceptance")
    test_contract_agreement()
    test_fixtures()
    test_oracle_against_real_maps()
    sandbox = Path(tempfile.mkdtemp(prefix="mapgen_m0_"))
    try:
        test_runner(sandbox)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
