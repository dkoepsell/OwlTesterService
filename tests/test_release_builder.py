"""Audited releases, Part B: the release builder (SPEC-release.md, section 14).

Builds need ROBOT: ``robot`` on PATH, or ROBOT_JAR naming robot.jar (a wrapper is
put on PATH for the audit). The LOF test runs when LOF_RELEASE points at the
LOF bundle zip.
"""

import json
import os
import shutil
import subprocess
import time
import zipfile

import pytest
from rdflib import Graph, RDFS, URIRef
from rdflib.compare import isomorphic

from owltester.release import answers as A
from owltester.release import builder, docs, publish, robot, tools
from owltester.release_repair.github import GitHubError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = os.path.join(ROOT, "fixtures", "release", "bfo-agent")
LOF = os.environ.get("LOF_RELEASE", "")
needs_lof = pytest.mark.skipif(not os.path.isfile(LOF), reason="set LOF_RELEASE to the LOF bundle zip")


@pytest.fixture
def with_robot(tmp_path_factory, monkeypatch):
    if tools.robot_command() is None or shutil.which("java") is None:
        pytest.skip("needs Java and ROBOT (robot on PATH or ROBOT_JAR)")
    if shutil.which("robot") is None:
        bindir = tmp_path_factory.mktemp("bin")
        with open(bindir / "robot", "w") as fh:
            fh.write(f'#!/bin/sh\nexec java -jar {os.environ["ROBOT_JAR"]} "$@"\n')
        os.chmod(bindir / "robot", 0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")


def agent_answers(**over):
    a = A.load(os.path.join(AGENT, "build.yaml"))
    a.update(over)
    return A.validate(a)


# -- no ROBOT needed --------------------------------------------------------------------

def test_answers_are_validated():
    with pytest.raises(A.AnswersError) as e:
        A.validate({"name": "Bad Name", "version": "1.0", "ontology_iri": "ftp://x", "license": "GPL",
                    "creators": [{"name": "A", "orcid": "1234"}], "repository": "https://gitlab.com/a/b",
                    "formats": ["rdfxml"], "expected": [{"finding": "x"}]})
    text = " ".join(e.value.problems)
    for word in ("name", "version", "ontology_iri", "license", "ORCID", "repository", "formats", "expected",
                 "title is required"):
        assert word in text, word
    a = agent_answers()
    assert a["base"] == "https://w3id.org/clinic-demo" and a["w3id_project"] == "clinic-demo"
    assert A.version_iri(a) == "https://w3id.org/clinic-demo/releases/0.1.0/clinic-demo.owl"
    assert a["creators"][0]["orcid"] == "0000-0002-1825-0097"
    lof = A.validate({"name": "lof-odp-001", "title": "t", "description": "d", "version": "0.1.0",
                      "ontology_iri": "https://w3id.org/lof/odp-001.owl", "creators": ["D"]})
    assert A.version_iri(lof) == "https://w3id.org/lof/odp-001/releases/0.1.0/lof-odp-001.owl"
    assert A.base_iri(lof) == "https://w3id.org/lof/odp-001/lof-odp-001-base.owl"


def test_templates_are_strict():
    with pytest.raises(docs.TemplateError):
        docs.render("NOTICE", title="t")                         # missing slots
    with pytest.raises(docs.TemplateError):
        docs.render("gitignore", extra="x")                     # unknown slot
    with pytest.raises(docs.TemplateError):
        docs.render("cq.sparql", n="1", question="{{name}}")    # a placeholder smuggled in a value


def test_version_suggestion():
    base = """@prefix : <https://w3id.org/x/X_> . @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    :1 a owl:Class ; rdfs:label "one" . :2 a owl:Class ; rdfs:subClassOf :1 ; rdfs:label "two" ."""
    old = Graph().parse(data=base, format="turtle")
    own = lambda iri: iri.startswith("https://w3id.org/x/")
    same = Graph().parse(data=base.replace('"two"', '"second"'), format="turtle")
    assert robot.suggest_version(old, same, "1.2.3", own)[0] == "1.2.4"
    added = Graph().parse(data=base + ' :3 a owl:Class .', format="turtle")
    assert robot.suggest_version(old, added, "1.2.3", own)[0] == "1.3.0"
    removed = Graph().parse(data=base.split(":2 a")[0], format="turtle")
    assert robot.suggest_version(old, removed, "1.2.3", own)[0] == "2.0.0"
    moved = Graph().parse(data=base.replace("rdfs:subClassOf :1 ;", ""), format="turtle")
    assert robot.suggest_version(old, moved, "1.2.3", own)[0] == "2.0.0"


def test_publish_sequence_with_a_fake_github(tmp_path):
    z = tmp_path / "x-1.0.0.zip"
    z.write_bytes(b"PK")
    calls = []

    def call(method, path, payload=None):
        calls.append((method, path))
        if path == "/user":
            return {"login": "owner"}
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "h"}}
        if "/git/ref/tags/" in path:
            raise GitHubError("GitHub answered 404")
        if "/git/commits/h" in path:
            return {"tree": {"sha": "t"}}
        if path.endswith("/releases"):
            return {"id": 7, "html_url": "https://github.com/owner/x/releases/tag/v1.0.0"}
        return {"sha": "s"}

    uploads = []
    files = [("README.md", b"# x\n", False), ("scripts/stage-release.sh", b"#!/bin/sh\n", True)]
    p = publish.plan("owner/x", "1.0.0", files, z.name, create=True)
    assert p["branch"] == "main" and p["tag"] == "v1.0.0" and len(p["steps"]) == 4
    res = publish.publish("tok", "owner/x", "1.0.0", files, str(z), "body", create=True, call=call,
                          upload=lambda rid, name, data: uploads.append((rid, name)) or {"browser_download_url": "u"})
    assert res["tag"] == "v1.0.0" and uploads == [(7, "x-1.0.0.zip")]
    assert ("POST", "/user/repos") in calls and ("PATCH", "/repos/owner/x/git/refs/heads/main") in calls
    with pytest.raises(GitHubError):
        publish.publish("tok", "someone-else/x", "1.0.0", files, str(z), "b", create=True, call=call,
                        upload=lambda *a: {})
    with pytest.raises(GitHubError):
        publish.plan("not a repo", "1.0.0", files, "z.zip")


# -- builds -----------------------------------------------------------------------------

def _build(out, **over):
    return builder.build(os.path.join(AGENT, "clinic-agent.owl"), agent_answers(**over), str(out))


@pytest.mark.java
def test_build_from_a_bfo_agent_output(tmp_path, with_robot):
    rep = _build(tmp_path / "a")
    assert rep["status"] == "done", rep.get("audit")
    assert rep["audit"]["verdict"] in ("pass", "warn")
    z = tmp_path / "a" / rep["outputs"]["zip"]
    with zipfile.ZipFile(z) as zf:
        names = {n.split("/", 1)[1] for n in zf.namelist()}
    for part in ("clinic-demo.owl", "clinic-demo-base.owl", "clinic-demo.ttl", "clinic-demo.ofn",
                 "clinic-demo.jsonld", "README.md", "docs/terms.md", "docs/diagram.svg", "CHANGELOG.md",
                 "NOTICE", "LICENSE", "CITATION.cff", "audit.yaml", "MANIFEST.json", "VERIFICATION.json",
                 "VERIFICATION.md", "audit/report.json", "audit/report.md",
                 "sparql/missing-label-violation.sparql", "sparql/no-bfo-ancestor-violation.sparql",
                 "sparql/cq/cq-001.sparql"):
        assert part in names, part
    rel = tmp_path / "a" / rep["outputs"]["release_dir"]
    built = Graph().parse(rel / "clinic-demo.ttl")
    # missing labels and definitions are listed, never invented
    no_label = "https://w3id.org/clinic-demo/CLINIC_0000003"
    assert rep["gaps"]["label"] == [no_label]
    assert sorted(rep["gaps"]["definition"]) == ["https://w3id.org/clinic-demo/CLINIC_0000002",
                                                  "https://w3id.org/clinic-demo/CLINIC_0000004"]
    assert built.value(URIRef(no_label), RDFS.label) is None
    assert f"no label: `{no_label}`" in (rel / "docs" / "terms.md").read_text()
    assert rep["qc"]["missing-label-violation.sparql"] == 1
    # the BFO module holds the terms used; the header carries the answers
    assert "BFO_0000015" in (rel / "clinic-demo.owl").read_text()
    assert isomorphic(built, Graph().parse(rel / "clinic-demo.jsonld", format="json-ld"))
    rec = json.loads((rel / "VERIFICATION.json").read_text())
    assert rec["release"]["version_iri"] == "https://w3id.org/clinic-demo/releases/0.1.0/clinic-demo.owl"
    assert rec["attestation"] is None and "not signed" in (rel / "VERIFICATION.md").read_text()
    cff = (rel / "CITATION.cff").read_text()
    assert "orcid: \"https://orcid.org/0000-0002-1825-0097\"" in cff and "family-names: \"Example\"" in cff
    w3 = (tmp_path / "a" / "w3id" / ".htaccess").read_text()
    assert "RewriteRule ^releases/([0-9][^/]*)/(.+)$ https://raw.githubusercontent.com/example/clinic-demo/v$1/$2" in w3
    assert "RewriteRule ^clinic\\.owl$" in w3
    from owltester.release import record
    assert record.verify(str(z))["ok"]
    # determinism: the same inputs and answers give byte-identical zips
    again = _build(tmp_path / "b")
    assert again["outputs"]["zip_sha256"] == rep["outputs"]["zip_sha256"]
    assert again["outputs"]["repo_zip_sha256"] == rep["outputs"]["repo_zip_sha256"]
    # with the first build as the previous release, adding a term suggests a minor version
    extra = tmp_path / "next.owl"
    extra.write_text((open(os.path.join(AGENT, "clinic-agent.owl")).read()).replace(
        "</rdf:RDF>", '<owl:Class rdf:about="https://w3id.org/clinic-demo/CLINIC_0000005">'
        '<rdfs:label xml:lang="en">walk-in visit</rdfs:label>'
        '<rdfs:subClassOf rdf:resource="https://w3id.org/clinic-demo/CLINIC_0000001"/></owl:Class></rdf:RDF>'))
    nxt = builder.build(str(extra), agent_answers(version="0.2.0"), str(tmp_path / "c"), previous=str(z))
    assert nxt["version_suggestion"]["suggested"] == "0.2.0"
    log = (tmp_path / "c" / nxt["outputs"]["release_dir"] / "CHANGELOG.md").read_text()
    assert "## 0.2.0" in log and "CLINIC_0000005" in log and "## 0.1.0" in log


def _workflow_ok(path):
    from tests.test_release_gate import workflow_problems
    if shutil.which("actionlint"):
        res = subprocess.run(["actionlint", path], capture_output=True, text=True)
        assert res.returncode == 0, res.stdout
    assert workflow_problems(path) == [], path


@pytest.mark.java
@needs_lof
def test_build_reproduces_lof_odp_001(tmp_path, with_robot):
    with zipfile.ZipFile(LOF) as zf:
        zf.extractall(tmp_path / "lof")
    (top,) = os.listdir(tmp_path / "lof")
    pat = tmp_path / "lof" / top / "patterns" / "lof-odp-001"
    a = A.validate({"name": "lof-odp-001", "title": "LOF-ODP-001: Legal Act and Legal Document",
                    "description": "Ontology design pattern distinguishing three entities that legal information "
                                   "systems routinely conflate: the legal act (a process), the legal content it "
                                   "establishes (a generically dependent continuant), and the legal documents that "
                                   "carry that content (material entities). DRAFT for review by the LOF founding "
                                   "coordinators.",
                    "ontology_iri": "https://w3id.org/lof/odp-001.owl", "version": "0.1.0",
                    "license": "CC-BY-4.0", "creators": ["David R. Koepsell"], "bfo": "module",
                    "profile": "bfo", "release_date": "2026-10-31",
                    "repository": "https://github.com/legal-ontologies-foundry/lof-odp-001"})
    rep = builder.build(str(pat / "src" / "ontology" / "lof-odp-001-edit.owl"), a, str(tmp_path / "out"),
                        supplied_imports=[str(pat / "src" / "ontology" / "imports" / "bfo_import.owl")])
    assert rep["status"] == "done", rep["audit"]
    built = tmp_path / "out" / rep["outputs"]["release_dir"] / "lof-odp-001.owl"
    diff = robot.diff(str(pat / "lof-odp-001.owl"), str(built), str(tmp_path / "diff.md"), robot.Budget(120), [])
    lines = [ln for ln in diff.splitlines() if ln.strip().startswith(("-", "+"))]
    assert all("Ontology" in ln or "versionInfo" in ln or "versionIRI" in ln for ln in lines), lines[:10]
    # the repository scaffold runs `make test`, and its workflows lint
    with zipfile.ZipFile(tmp_path / "out" / rep["outputs"]["repo_zip"]) as zf:
        zf.extractall(tmp_path / "repo")
    repo = tmp_path / "repo" / "lof-odp-001"
    jar = os.environ.get("ROBOT_JAR")
    if jar is None:
        pytest.skip("make test needs ROBOT_JAR (the Makefile runs java -jar)")
    res = subprocess.run(["make", "-C", str(repo / "src" / "ontology"), "test", f"ROBOT_JAR={jar}"],
                         capture_output=True, text=True, timeout=600)
    assert res.returncode == 0, res.stdout[-2000:] + res.stderr[-2000:]
    for wf in ("audit.yml", "release.yml"):
        _workflow_ok(str(repo / ".github" / "workflows" / wf))
    assert "fail-on: major" in (repo / ".github" / "workflows" / "release.yml").read_text()
    with zipfile.ZipFile(tmp_path / "out" / rep["outputs"]["repo_zip"]) as zf:
        mode = zf.getinfo("lof-odp-001/scripts/stage-release.sh").external_attr >> 16
    assert mode & 0o111


# -- web access and flow ------------------------------------------------------------------

@pytest.fixture
def flask_app(monkeypatch, tmp_path):
    from app import app
    monkeypatch.setitem(app.config, "UPLOADED_OWLS_DEST", str(tmp_path / "uploads"))
    os.makedirs(app.config["UPLOADED_OWLS_DEST"], exist_ok=True)
    app.config["TESTING"] = True
    return app


def _client(flask_app, username):
    from models import User, db
    with flask_app.app_context():
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(username=username, email=f"{username}@example.test", password_hash="x")
            db.session.add(user)
            db.session.commit()
        uid = user.id
    c = flask_app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
    return c


def _upload(c):
    with open(os.path.join(AGENT, "clinic-agent.owl"), "rb") as fh:
        return c.post("/release/new", data={"ontology": (fh, "clinic-agent.owl")},
                      content_type="multipart/form-data")


def test_builder_is_closed_by_default(flask_app, monkeypatch):
    monkeypatch.delenv("BUILD_ALLOWED_USERS", raising=False)
    owner = _client(flask_app, "builder")
    assert owner.get("/release/new").status_code == 403
    assert _upload(owner).status_code == 403
    assert b"Build a Release" not in owner.get("/").data
    monkeypatch.setenv("BUILD_ALLOWED_USERS", "builder")
    assert flask_app.test_client().get("/release/new").status_code == 403      # never anonymous
    assert owner.get("/release/new").status_code == 200


def test_builds_belong_to_their_owner(flask_app, monkeypatch):
    monkeypatch.setenv("BUILD_ALLOWED_USERS", "builder,other")
    owner, other = _client(flask_app, "builder"), _client(flask_app, "other")
    res = _upload(owner)
    assert res.status_code == 302
    build_id = res.headers["Location"].split("/release/")[1].split("/")[0]
    page = owner.get(f"/release/{build_id}/step/identity")
    assert page.status_code == 200 and b"https://w3id.org/clinic-demo/clinic.owl" in page.data
    for url in (f"/release/{build_id}", f"/release/{build_id}/step/identity", f"/release/{build_id}/status"):
        assert other.get(url).status_code == 404
    assert other.post(f"/release/{build_id}/publish", json={"repo": "other/x"}).status_code == 404
    assert flask_app.test_client().get(f"/release/{build_id}").status_code == 404
    monkeypatch.setenv("BUILD_ALLOWED_USERS", "other")                           # revoked
    assert owner.get(f"/release/{build_id}").status_code == 404
    # review lists what is missing before a build can start
    monkeypatch.setenv("BUILD_ALLOWED_USERS", "builder")
    res = owner.post(f"/release/{build_id}/step/review", data={})
    assert res.status_code == 400 and b"title is required" in res.data


@pytest.mark.java
def test_web_flow_builds_and_publishes_a_dry_run(flask_app, monkeypatch, with_robot):
    monkeypatch.setenv("BUILD_ALLOWED_USERS", "builder")
    c = _client(flask_app, "builder")
    build_id = _upload(c).headers["Location"].split("/release/")[1].split("/")[0]
    form = {"name": "clinic-demo", "title": "Clinic demo ontology", "description": "A demo.",
            "ontology_iri": "https://w3id.org/clinic-demo/clinic.owl", "version": "0.1.0",
            "license": "CC-BY-4.0", "creators": "Ada Example, 0000-0002-1825-0097", "contributors": "",
            "release_date": "2026-11-01", "repository": "https://github.com/builder/clinic-demo"}
    assert c.post(f"/release/{build_id}/step/identity", data=form).status_code == 302
    assert c.post(f"/release/{build_id}/step/imports", data={"bfo": "module"}).status_code == 302
    assert c.post(f"/release/{build_id}/step/build", data={"fail_on": "major"}).status_code == 302
    assert c.post(f"/release/{build_id}/step/quality", data={"shapes_scaffold": "draft"}).status_code == 302
    assert c.post(f"/release/{build_id}/step/review", data={}).status_code == 302
    for _ in range(600):
        s = c.get(f"/release/{build_id}/status").get_json()
        if s["status"] != "running":
            break
        time.sleep(0.5)
    assert s["status"] == "done", s
    page = c.get(f"/release/{build_id}")
    assert b"Audit: " in page.data and b"clinic-demo-0.1.0.zip" in page.data
    z = c.get(f"/release/{build_id}/out/zip")
    assert z.status_code == 200 and z.data[:2] == b"PK"
    assert c.get(f"/release/{build_id}/out/htaccess").status_code == 200
    dry = c.post(f"/release/{build_id}/publish", json={"repo": "builder/clinic-demo"}).get_json()
    assert dry["dry_run"] and dry["tag"] == "v0.1.0" and "README.md" in dry["files"]
    res = c.post(f"/release/{build_id}/publish", json={"repo": "builder/clinic-demo", "confirm": True})
    assert res.status_code == 400 and "token" in res.get_json()["error"]          # nothing pushed


@pytest.mark.java
def test_rejected_build_goes_to_guided_repair_and_back(flask_app, monkeypatch, tmp_path, with_robot):
    """Section 9.6: a release the gate rejects is handed to guided repair; the repaired
    release is audited and recorded again."""
    from owltester.release import record
    monkeypatch.setenv("BUILD_ALLOWED_USERS", "builder")
    monkeypatch.setenv("REPAIR_ALLOWED_USERS", "builder")
    c = _client(flask_app, "builder")
    build_id = _upload(c).headers["Location"].split("/release/")[1].split("/")[0]
    d = os.path.join(flask_app.config["UPLOADED_OWLS_DEST"], "releases", build_id)
    with open(os.path.join(d, "build.json")) as fh:
        data = json.load(fh)
    data["answers"] = dict(agent_answers(fail_on="minor", formats=[]))          # minor: rejected
    rep = builder.build(os.path.join(AGENT, "clinic-agent.owl"), data["answers"], os.path.join(d, "out"))
    assert rep["status"] == "rejected"
    data["status"] = "rejected"
    with open(os.path.join(d, "build.json"), "w") as fh:
        json.dump(data, fh)
    assert b"Open guided repair" in c.get(f"/release/{build_id}").data
    res = c.post(f"/release/{build_id}/repair")
    assert res.status_code == 302 and "/repair" in res.headers["Location"]
    job_id = res.headers["Location"].split("/audit/")[1].split("/")[0]
    assert c.get(f"/audit/{job_id}/repair?new=1").status_code == 200
    # the repaired release (here: unchanged) is audited and recorded anew
    out = builder.repackage(os.path.join(d, "out"), os.path.join(d, "out", rep["outputs"]["zip"]), data["answers"])
    assert out["repaired"] and out["audit"]["gate"] == "rejected"
    assert record.verify(os.path.join(d, "out", out["outputs"]["zip"]))["ok"]
