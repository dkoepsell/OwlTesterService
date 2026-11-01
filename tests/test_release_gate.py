"""Audited releases, Part A: the audit as a release gate (SPEC-release.md, section 14).

The LOF tests run when LOF_RELEASE points at lof-odps-2026-10-31.zip (not in the repo).
"""

import json
import os
import shutil
import zipfile

import pytest
import yaml

from owltester import cli
from owltester.release import action, gate, record
from owltester.release.docs import render

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINI = os.path.join(ROOT, "fixtures", "audit", "mini")
GATE_REPO = os.path.join(ROOT, "fixtures", "release", "gate-repo")
ACTION = os.path.join(ROOT, "action")
LOF = os.environ.get("LOF_RELEASE", "")
needs_java = pytest.mark.skipif(shutil.which("java") is None, reason="needs Java")
needs_lof = pytest.mark.skipif(not os.path.isfile(LOF), reason="set LOF_RELEASE to the LOF bundle zip")


def fake(findings):
    return {"verdict": "warn", "artifact": "x", "profile": "general", "tool_version": "t",
            "audited_at": "2026-11-01T00:00:00+00:00", "scorecard": [],
            "severity_counts": {"critical": 0, "major": 1, "minor": 1, "info": 0},
            "findings": findings}


def test_fail_on_thresholds():
    rep = fake([{"code": "W_A", "severity": "major", "title": "a", "files": []},
                {"code": "W_B", "severity": "minor", "title": "b", "files": []},
                {"code": "E_C", "severity": "critical", "title": "c", "files": [], "expected": "by design"}])
    assert not gate.rejected(rep, "critical")       # the expected critical does not count
    assert [f["code"] for f in gate.blocking(rep, "major")] == ["W_A"]
    assert len(gate.blocking(rep, "minor")) == 2
    with pytest.raises(ValueError):
        gate.blocking(rep, "info")
    md = gate.summary_md(rep, "major")
    assert "rejected" in md and "`W_A`" in md and "E_C" not in md
    assert gate.badge(rep) == {"schemaVersion": 1, "label": "OwlTester", "message": "warn", "color": "yellow"}


def test_exit_code_2_for_tool_errors(tmp_path, monkeypatch, capsys):
    assert cli.main(["verify", str(tmp_path / "nope.zip")]) == 2
    assert cli.main(["audit", str(tmp_path / "nope")]) == 2
    from owltester.release import tools
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    assert cli.main(["audit", MINI]) == 2
    assert "Java" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["audit", MINI, "--fail-on", "info"])
    assert e.value.code == 2


def _audit(path, tmp_path, *extra):
    out = str(tmp_path / f"audit-{len(os.listdir(tmp_path))}.json")
    code = cli.main(["audit", path, "--json", out, "--quiet", *extra])
    with open(out, encoding="utf-8") as fh:
        return code, json.load(fh), out


def _copy_clean(tmp_path, case="clean"):
    dest = str(tmp_path / f"rel-{case}")
    shutil.copytree(os.path.join(MINI, "clean"), dest)
    if case != "clean":
        shutil.copytree(os.path.join(MINI, case), dest, dirs_exist_ok=True)
    return dest


@needs_java
def test_record_then_verify_and_tampering(tmp_path, capsys):
    rel = _copy_clean(tmp_path)
    code, rep, path = _audit(rel, tmp_path, "--fail-on", "major")
    assert code == 0
    assert cli.main(["record", rel, "--report", path, "--tag", "v1.0.0", "--commit", "a" * 40,
                     "--fail-on", "major"]) == 0
    rec = record.load_record(rel)
    assert rec["release"]["tag"] == "v1.0.0" and rec["release"]["version"] == "1.0.0"
    assert rec["audit"]["gate"] == "passed" and rec["attestation"] is None
    assert {f["path"] for f in rec["files"]} >= {"audit/report.json", "audit/report.md", "ontology/mini.ttl"}
    assert not {record.RECORD_JSON, record.RECORD_MD} & {f["path"] for f in rec["files"]}
    with open(os.path.join(rel, record.RECORD_MD), encoding="utf-8") as fh:
        first = fh.readline()
    assert first.startswith("Audited by OwlTester `") and ": pass (0 critical, 0 major" in first
    assert cli.main(["verify", rel]) == 0

    # the same, as a zip with a top folder
    z = str(tmp_path / "rel.zip")
    with zipfile.ZipFile(z, "w") as zf:
        for relpath, ab in record.list_files(rel):
            zf.write(ab, "my-release-1.0.0/" + relpath)
    assert record.verify(z)["ok"]

    # one byte of a listed file
    target = os.path.join(rel, "ontology", "mini.ttl")
    with open(target, "rb") as fh:
        data = fh.read()
    with open(target, "wb") as fh:
        fh.write(data[:-1] + (b" " if data[-1:] != b" " else b"\n"))
    res = record.verify(rel)
    assert not res["ok"] and "altered: ontology/mini.ttl" in res["problems"]
    with open(target, "wb") as fh:
        fh.write(data)
    # an unlisted file
    with open(os.path.join(rel, "extra.ttl"), "w") as fh:
        fh.write("# not audited\n")
    assert record.verify(rel)["problems"] == ["not in the record: extra.ttl"]
    assert record.verify(rel, allow=["extra.*"])["ok"]
    os.remove(os.path.join(rel, "extra.ttl"))
    # editing the record
    rec_path = os.path.join(rel, record.RECORD_JSON)
    edited = dict(rec, audit=dict(rec["audit"], verdict="pass", gate="passed",
                                  severity_counts=dict(rec["audit"]["severity_counts"], info=0)))
    with open(rec_path, "w") as fh:
        json.dump(edited, fh)
    assert any("was edited" in p for p in record.verify(rel)["problems"])
    capsys.readouterr()
    assert cli.main(["verify", rel]) == 1
    assert "VERIFICATION.json was edited" in capsys.readouterr().err


@needs_java
def test_verify_reaudit_reproduces_the_record(tmp_path):
    rel = _copy_clean(tmp_path, "ci-no-shacl")
    code, rep, path = _audit(rel, tmp_path, "--fail-on", "major")
    assert code == 1 and any(f["code"] == "W_CI_NO_SHACL" for f in rep["findings"])
    record.write_record(rel, record.make_record(rel, rep, fail_on="major"))
    res = record.verify(rel, reaudit=True)
    assert res["ok"], res["problems"]
    assert res["reaudit"]["verdict"] == rep["verdict"]
    assert "W_CI_NO_SHACL" in res["reaudit"]["codes"]


@needs_java
def test_r10_credits_the_action_and_the_record(tmp_path):
    rel = str(tmp_path / "gate")
    shutil.copytree(GATE_REPO, rel)
    _, rep, path = _audit(rel, tmp_path)
    codes = {f["code"] for f in rep["findings"]}
    assert not codes & {"W_CI_NO_SHACL", "W_CI_NO_REASONER"}
    assert {"shacl", "reasoning"} <= set(rep["stages"]["R10"]["notes"]["ci_checks"])
    record.write_record(rel, record.make_record(rel, rep))
    _, again, _ = _audit(rel, tmp_path)
    assert "I_VERIFIED" in {f["code"] for f in again["findings"]}
    assert {f["code"] for f in again["findings"]} - {"I_VERIFIED"} == codes   # the record is not audited
    with open(os.path.join(rel, "ontology", "mini.ttl"), "a") as fh:
        fh.write("\n# changed after the record\n")
    _, broken, _ = _audit(rel, tmp_path)
    mism = [f for f in broken["findings"] if f["code"] == "W_RECORD_MISMATCH"]
    assert mism and "altered: ontology/mini.ttl" in mism[0]["evidence"]["problems"]


@needs_java
def test_action_entry_point(tmp_path, monkeypatch):
    dist = str(tmp_path / "dist")
    shutil.copytree(GATE_REPO, dist)
    out = str(tmp_path / "out")
    env = {"INPUT_PATH": dist, "INPUT_FAIL_ON": "major", "INPUT_RECORD": "true",
           "INPUT_BADGE": str(tmp_path / "badges" / "audit.json"), "OWLTESTER_OUT": out,
           "GITHUB_SHA": "b" * 40, "GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": "v1.0.0",
           "GITHUB_REPOSITORY": "example/gate-repo", "GITHUB_SERVER_URL": "https://github.com"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert action.run() == 0
    outputs = dict(line.split("=", 1) for line in open(os.path.join(out, "outputs.env")).read().splitlines())
    assert outputs["verdict"] == "pass" and outputs["record"].endswith("VERIFICATION.json")
    assert json.loads(outputs["counts"])["major"] == 0
    rec = record.load_record(dist)
    assert rec["release"]["tag"] == "v1.0.0" and rec["release"]["commit"] == "b" * 40
    assert rec["release"]["repository"] == "https://github.com/example/gate-repo"
    assert json.load(open(tmp_path / "badges" / "audit.json"))["message"] == "pass"
    assert open(os.path.join(out, "summary.md")).read().startswith("## OwlTester audit: pass")
    assert record.verify(dist)["ok"]
    # a release with a major finding fails the step
    bad = _copy_clean(tmp_path, "ci-no-shacl")
    monkeypatch.setenv("INPUT_PATH", bad)
    monkeypatch.setenv("INPUT_RECORD", "false")
    assert action.run() == 1
    monkeypatch.setenv("INPUT_PATH", str(tmp_path / "missing"))
    assert action.run() == 2


def test_action_templates_match_the_scaffold_templates():
    with open(os.path.join(ACTION, "templates", "audit.yml")) as fh:
        assert fh.read() == render("workflow-audit.yml", profile="bfo")
    with open(os.path.join(ACTION, "templates", "release.yml")) as fh:
        assert fh.read() == render("workflow-release.yml", profile="bfo", fail_on="major")


def workflow_problems(path):
    """A structural check when actionlint is not installed."""
    with open(path) as fh:
        wf = yaml.safe_load(fh)
    problems = []
    on = wf.get(True, wf.get("on"))           # YAML 1.1 reads the key `on` as True
    if not on:
        problems.append("no trigger")
    for name, job in (wf.get("jobs") or {}).items():
        if "runs-on" not in job or not job.get("steps"):
            problems.append(f"{name}: needs runs-on and steps")
        for step in job.get("steps", []):
            if not ("uses" in step) ^ ("run" in step):
                problems.append(f"{name}: a step needs exactly one of uses / run")
    return problems


def test_workflows_lint():
    paths = [os.path.join(ACTION, "templates", f) for f in ("audit.yml", "release.yml", "badge.yml")]
    paths += [os.path.join(ROOT, ".github", "workflows", f) for f in os.listdir(os.path.join(ROOT, ".github", "workflows"))]
    if shutil.which("actionlint"):
        import subprocess
        res = subprocess.run(["actionlint", *paths], capture_output=True, text=True)
        assert res.returncode == 0, res.stdout
    for p in paths:
        assert workflow_problems(p) == [], p
    with open(os.path.join(ACTION, "action.yml")) as fh:
        act = yaml.safe_load(fh)
    assert act["runs"]["using"] == "composite"
    assert set(act["outputs"]) == {"verdict", "report-json", "report-md", "record", "counts"}
    assert {"path", "profile", "config", "fail-on", "budget", "record", "comment"} <= set(act["inputs"])


@needs_java
@needs_lof
def test_lof_gate_record_and_verify(tmp_path):
    root = str(tmp_path / "lof")
    with zipfile.ZipFile(LOF) as zf:
        zf.extractall(root)
    (top,) = os.listdir(root)
    rel = os.path.join(root, top)
    code, rep, path = _audit(rel, tmp_path, "--fail-on", "major")
    assert code == 1
    assert [f["code"] for f in gate.blocking(rep, "major")] == ["W_CI_NO_SHACL"]
    wf = os.path.join(rel, "patterns", "lof-odp-004", ".github", "workflows", "audit.yml")
    with open(os.path.join(ACTION, "templates", "audit.yml")) as fh:
        text = fh.read()
    os.makedirs(os.path.dirname(wf), exist_ok=True)
    with open(wf, "w") as fh:
        fh.write(text)
    code, rep, path = _audit(rel, tmp_path, "--fail-on", "major")
    assert code == 0, gate.blocking(rep, "major")
    assert "W_CI_NO_SHACL" not in {f["code"] for f in rep["findings"]}
    record.write_record(rel, record.make_record(rel, rep, fail_on="major"))
    assert record.verify(rel)["ok"]
    victim = os.path.join(rel, "patterns", "lof-odp-001", "lof-odp-001.owl")
    with open(victim, "ab") as fh:
        fh.write(b" ")
    assert "altered: patterns/lof-odp-001/lof-odp-001.owl" in record.verify(rel)["problems"]
