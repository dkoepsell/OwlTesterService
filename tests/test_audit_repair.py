"""Guided release repair (SPEC-audit-repair.md, section 9).

Access tests need no reasoner. Remedy tests run the full audit twice (before
and after), so they need Java, like the audit tests they mirror.
"""

import hashlib
import json
import os
import shutil
import time
import zipfile

import pytest

from owltester.audit import jobs
from owltester.audit.runner import run_audit
from owltester.release_repair import ops as O
from owltester.release_repair import storage
from owltester.release_repair.apply import ApplyError, apply_plan
from owltester.release_repair.model import Plan, Remedy, RemedyOption
from owltester.release_repair.planner import DecisionError, build_plan, decide
from owltester.release_repair.templates import render_text
from owltester.release_repair.turtle_splice import splice

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "fixtures", "audit")
MINI = os.path.join(FIX, "mini")
LOMO = os.path.join(FIX, "lomo-1.0.0-trimmed")
ME = {"user_id": 1, "name": "owner"}


def materialize_case(case, dest):
    shutil.copytree(os.path.join(MINI, "clean"), dest)
    if case != "clean":
        shutil.copytree(os.path.join(MINI, case), dest, dirs_exist_ok=True)
    return dest


def above_info(findings):
    return sorted(f["code"] for f in findings if f["severity"] != "info" and not f.get("expected"))


def tree_bytes(root):
    out = {}
    for rel in O.Tree(root).files():
        with open(os.path.join(root, *rel.split("/")), "rb") as fh:
            out[rel] = hashlib.sha256(fh.read()).hexdigest()
    return out


# -- templates, splicing and op guards (no reasoner) ------------------------------------------

def test_ci_step_is_added_to_the_existing_workflow():
    current = open(os.path.join(MINI, "ci-no-shacl", ".github", "workflows", "ci.yml")).read()
    text = render_text("ci_github_steps", {"kind": "shacl", "shapes": ["shapes/mini-shapes.ttl"],
                                           "ontology": ["ontology/mini.ttl"], "data": ["data/main/*.ttl"]},
                       current)
    assert text.startswith(current)
    assert "      - run: for f in data/main/*.ttl; do pyshacl -s shapes/mini-shapes.ttl" in text


def test_templates_reject_free_text_in_path_slots():
    with pytest.raises(O.OpError):
        render_text("ci_github_workflow", {"kind": "shacl", "shapes": ["x.ttl; rm -rf /"],
                                           "data": ["d.ttl"]}, None)


def test_audit_yaml_expected_round_trip():
    from owltester.audit.config import parse_simple_yaml
    base = "profile: general\nexpected:\n  - finding: E_SHACL\n    reason: \"designed\"\nignore:\n  - x/**\n"
    text = render_text("audit_yaml_expected", {"entries": [{"code": "W_RANGE", "file": "data/*.ttl",
                                                            "reason": "examples"}]}, base)
    cfg = parse_simple_yaml(text)
    assert [e["finding"] for e in cfg["expected"]] == ["E_SHACL", "W_RANGE"]
    assert cfg["ignore"] == ["x/**"]
    dropped = parse_simple_yaml(render_text("audit_yaml_drop_expected", {"entries": [{"code": "E_SHACL"}]}, text))
    assert [e["finding"] for e in dropped["expected"]] == ["W_RANGE"]
    with pytest.raises(O.OpError):
        render_text("audit_yaml_expected", {"entries": [{"code": "W_RANGE", "reason": ""}]}, base)


def test_splice_keeps_untouched_statements_byte_for_byte():
    import rdflib
    text = open(os.path.join(MINI, "clean", "ontology", "mini.ttl")).read()
    g = O.canonical_graph(rdflib.Graph().parse(data=text, format="turtle"))
    dt = rdflib.URIRef("https://w3id.org/audit-mini/onto#title")
    g.remove((dt, rdflib.RDFS.range, rdflib.XSD.string))
    out = splice(text, g)
    assert out is not None
    assert O._same(O.canonical_graph(rdflib.Graph().parse(data=out, format="turtle")), g)
    removed = [line for line in text.splitlines() if line not in out.splitlines()]
    assert removed == ["    rdfs:label \"title\"@en ;", "    rdfs:range xsd:string ."]


def test_rewrite_stops_when_the_preview_counts_no_longer_match(tmp_path):
    rel = materialize_case("ns-mismatch", str(tmp_path / "r"))
    tree = O.Tree(rel)
    with pytest.raises(O.OpError, match="preview counted"):
        O.run(tree, {"op": "rewrite_iri", "args": {
            "from": "https://w3id.org/audit-mini/modality#", "to": "https://w3id.org/audit-mini/modality/",
            "mode": "namespace", "files": ["data/main/rules.ttl"], "expect": {"data/main/rules.ttl": 7}}})


def test_ops_cannot_leave_the_release(tmp_path):
    rel = materialize_case("clean", str(tmp_path / "r"))
    with pytest.raises(O.OpError):
        O.run(O.Tree(rel), {"op": "write_text", "args": {"path": "../escape.yml",
                                                         "template": "changelog_entry",
                                                         "slots": {"items": ["x"]}}})


def _plan_with(rel, remedies):
    return Plan(plan_id="a" * 32, job_id="b" * 32, artifact="mini", profile="general",
                created_at="2026-10-31T00:00:00", created_by=ME, remedies=remedies,
                audit_before={"findings": []})


def _accepted(rid, ops, finding="R5-1", code="E_UNDECLARED_TERM"):
    r = Remedy(id=rid, finding_id=finding, code=code, kind="choice", title=rid, rationale="",
               options=[RemedyOption(id="a", label="x", consequence="", ops=ops)])
    r.status, r.decision = "accepted", {"option": "a", "ops": ops, "by": ME, "at": "t"}
    return r


def test_a_plan_over_the_removal_bound_fails_and_writes_nothing(tmp_path):
    rel = materialize_case("clean", str(tmp_path / "r"))
    onto = "<https://w3id.org/audit-mini/onto#"
    rows = [[onto + c + ">", "<http://www.w3.org/2000/01/rdf-schema#label>", lab]
            for c, lab in (("Rule", '"rule"@en'), ("Action", '"action"@en'),
                           ("Obligation", '"obligation"@en'), ("Permission", '"permission"@en'))]
    plan = _plan_with(rel, [_accepted("M-1", [{"op": "remove_triples",
                                              "args": {"file": "ontology/mini.ttl", "triples": rows}}])])
    out = str(tmp_path / "plan")
    with pytest.raises(ApplyError) as e:
        apply_plan(plan, rel, out, reaudit=False)
    assert e.value.code == "E_OVER_RELAXED"
    assert not os.path.exists(os.path.join(out, "out"))


def test_apply_is_deterministic_and_an_empty_plan_reproduces_the_release(tmp_path):
    rel = materialize_case("ns-mismatch", str(tmp_path / "r"))
    ops = [{"op": "rewrite_iri", "args": {"from": "https://w3id.org/audit-mini/modality#",
                                          "to": "https://w3id.org/audit-mini/modality/",
                                          "mode": "namespace", "files": ["data/main/rules.ttl"]}}]
    zips = []
    for n in (1, 2):
        plan = _plan_with(rel, [_accepted("M-1", ops)])
        out = str(tmp_path / f"p{n}")
        apply_plan(plan, rel, out, reaudit=False)
        with open(os.path.join(out, "out", "mini-repaired.zip"), "rb") as fh:
            zips.append(fh.read())
    assert zips[0] == zips[1]
    patch = open(os.path.join(tmp_path, "p1", "out", "repair.patch")).read()
    assert patch.count("\n-    onto:hasModality") == 1 and patch.count("\n+    onto:hasModality") == 1

    # revert everything: the work tree is the original, byte for byte
    plan = _plan_with(rel, [])
    apply_plan(plan, rel, str(tmp_path / "p3"), reaudit=False)
    assert tree_bytes(os.path.join(tmp_path, "p3", "work")) == tree_bytes(rel)
    assert open(os.path.join(tmp_path, "p3", "out", "repair.patch")).read() == ""


def test_declare_needs_a_reason_and_inputs_are_validated():
    r = Remedy(id="M-1", finding_id="R8-1", code="W_PLACEHOLDER_IRI", kind="choice", title="t",
               rationale="", options=[RemedyOption(
                   id="a", label="map", consequence="",
                   ops=[{"op": "rewrite_iri", "args": {"from": "http://example.org/", "to": "{{value}}",
                                                      "mode": "namespace", "files": ["d.ttl"]}}],
                   input={"kind": "iri", "label": "Base"})])
    plan = _plan_with(".", [r])
    with pytest.raises(DecisionError, match="reason"):
        decide(plan, "M-1", "declare", note="", user=ME)
    with pytest.raises(DecisionError):
        decide(plan, "M-1", "accept", option="a", content="not an iri", user=ME)
    with pytest.raises(DecisionError, match="ends in"):
        decide(plan, "M-1", "accept", option="a", content="https://data.example.net/id", user=ME)
    decide(plan, "M-1", "accept", option="a", content="https://data.example.net/id/", user=ME)
    assert r.decision["ops"][0]["args"]["to"] == "https://data.example.net/id/"
    assert plan.log[-1]["action"] == "accept"


# -- remedies on the mini fixtures (Java: two full audits each) --------------------------------

EXAMPLE = ('ex:rule1 a :Obligation ;\n    :requires ex:act1 ;\n    :hasModality mod:Must ;\n'
           '    :title "File a tax return" .\nex:act1 a :Action .')


@pytest.mark.java
@pytest.mark.parametrize("case, code, option, content", [
    ("ns-mismatch", "E_NS_MISMATCH", "a", None),
    ("datatype", "E_DATATYPE_PROFILE", "a", None),
    ("inconsistent", "E_ABOX_INCONSISTENT", "b", None),
    ("layer-conflict", "E_LAYER_CONFLICT", "a", None),
    ("self-example", "E_SELF_EXAMPLE", "a", EXAMPLE),
    ("ci-no-shacl", "W_CI_NO_SHACL", "a", None),
])
def test_each_remedy_closes_its_finding_and_adds_nothing(tmp_path, case, code, option, content):
    rel = materialize_case(case, str(tmp_path / "r"))
    before = run_audit(rel, budget=300).to_dict()
    plan = build_plan(before, rel, job_id="c" * 32, user=ME)
    r = next(r for r in plan.remedies if r.code == code)
    decide(plan, r.id, "accept", option=option, content=content, user=ME, release=rel)
    result = apply_plan(plan, rel, str(tmp_path / "plan"), audit_options={"budget": 300})
    assert code in [f["code"] for f in result["closed"]]
    assert result["new"] == [] and result["flagged"] == []
    after = json.load(open(os.path.join(tmp_path, "plan", "out", "audit-after.json")))
    assert above_info(after["findings"]) == []
    assert result["fixed"] is True
    if case == "ns-mismatch":       # the linked SHACL violation closes with its cause
        assert "E_SHACL" in [f["code"] for f in result["closed"]]
        assert r.id in next(x for x in plan.remedies if x.code == "E_SHACL").depends_on
    log = json.load(open(os.path.join(tmp_path, "plan", "out", "FIXLOG.json")))["entries"]
    assert log and all(e["finding_id"] == r.finding_id and e["by"] == ME for e in log)


@pytest.mark.java
def test_declared_outcome_is_written_and_counts_as_expected(tmp_path):
    rel = materialize_case("inconsistent", str(tmp_path / "r"))
    before = run_audit(rel, budget=300).to_dict()
    plan = build_plan(before, rel, job_id="c" * 32, user=ME)
    r = next(r for r in plan.remedies if r.code == "E_ABOX_INCONSISTENT")
    decide(plan, r.id, "declare", note="r3 tests the disjointness on purpose", user=ME)
    result = apply_plan(plan, rel, str(tmp_path / "plan"), audit_options={"budget": 300})
    assert [f["code"] for f in result["declared"]] == ["E_ABOX_INCONSISTENT"]
    out = os.path.join(tmp_path, "plan", "out")
    with zipfile.ZipFile(os.path.join(out, result["outputs"]["zip"])) as zf:
        assert "r3 tests the disjointness" in zf.read("r/audit.yaml").decode()


@pytest.mark.java
def test_lomo_namespace_rewrite_and_legacy_remedies(tmp_path):
    before = run_audit(LOMO, budget=900).to_dict()
    plan = build_plan(before, LOMO, job_id="c" * 32, user=ME)
    ns = [r for r in plan.remedies if r.code == "E_NS_MISMATCH"]
    assert len(ns) == 4
    for r in ns:
        decide(plan, r.id, "accept", option="a", user=ME)
    for r in [r for r in plan.remedies if r.code == "E_ABOX_INCONSISTENT"]:
        decide(plan, r.id, "declare", note="legacy data, kept for history", user=ME)
    result = apply_plan(plan, LOMO, str(tmp_path / "plan"), audit_options={"budget": 900})
    closed = [f["code"] for f in result["closed"]]
    assert closed.count("E_NS_MISMATCH") == 4
    assert [f["code"] for f in result["declared"]].count("E_ABOX_INCONSISTENT") == 2
    after = json.load(open(os.path.join(tmp_path, "plan", "out", "audit-after.json")))
    codes = {f["id"]: f["code"] for f in after["findings"]}
    assert not any(f["code"] == "E_NS_MISMATCH" for f in after["findings"])
    linked = [f for f in after["findings"] if f["code"] == "E_SHACL"
              and any(codes.get(r) == "E_NS_MISMATCH" for r in f.get("related") or [])]
    assert linked == []


@pytest.mark.java
@pytest.mark.skipif(not os.environ.get("LOF_RELEASE"), reason="set LOF_RELEASE to the LOF ODPs zip")
def test_lof_bundle_ci_and_subclass_tables(tmp_path):
    src = os.environ["LOF_RELEASE"]
    before = run_audit(src, budget=900).to_dict()
    plan = build_plan(before, src, job_id="c" * 32, user=ME)
    ci = next(r for r in plan.remedies if r.code == "W_CI_NO_SHACL")
    decide(plan, ci.id, "accept", option="a", user=ME)
    for r in [r for r in plan.remedies if r.code == "W_SUBCLASS_COLLAPSE"]:
        opt = r.options[0]
        first = opt.input["choices"][0]["iri"]
        decide(plan, r.id, "accept", option="a", content={"values": {str(i): first for i in
                                                                    range(len(opt.input["rows"]))}}, user=ME)
    result = apply_plan(plan, src, str(tmp_path / "plan"), audit_options={"budget": 900})
    closed = [f["code"] for f in result["closed"]]
    assert "W_CI_NO_SHACL" in closed
    assert closed.count("W_SUBCLASS_COLLAPSE") == len([r for r in plan.remedies if r.code == "W_SUBCLASS_COLLAPSE"])


# -- access (spec 1.1 and 1.2; no reasoner) ----------------------------------------------------

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
    return c, uid


def _done_job(flask_app, owner_id, tmp_path):
    up = flask_app.config["UPLOADED_OWLS_DEST"]
    job_id, d = jobs.create(up, {"user_id": owner_id}, "mini", "general")
    rel = materialize_case("ci-no-shacl", os.path.join(d, "release", "mini"))
    from owltester.audit.artifact import load_artifact
    from owltester.model import AuditReport
    art = load_artifact(rel)
    report = AuditReport(artifact="mini", audited_at="t", tool_version="x", profile="general",
                         manifest=art.manifest()).to_dict()
    art.cleanup()
    jobs.update(up, job_id, status="done", report=report, release_files=["mini"])
    plan = Plan(plan_id="d" * 32, job_id=job_id, artifact="mini", profile="general", created_at="t",
                created_by={"user_id": owner_id, "name": "owner"}, audit_before=report)
    storage.save(up, plan)
    return job_id, plan.plan_id, rel


ROUTES = [("get", "/audit/{j}/repair"), ("post", "/audit/{j}/repair"), ("get", "/audit/{j}/repair/{p}"),
          ("get", "/owltester/audit/{j}/repair/{p}"), ("post", "/owltester/audit/{j}/repair/{p}/apply"),
          ("post", "/owltester/audit/{j}/repair/{p}/remedy/M-x"),
          ("get", "/owltester/audit/{j}/repair/{p}/issues.zip")]


def test_repair_is_closed_when_the_allowlist_is_empty(flask_app, monkeypatch, tmp_path):
    monkeypatch.delenv("REPAIR_ALLOWED_USERS", raising=False)
    monkeypatch.setenv("AUDIT_ALLOWED_USERS", "owner@example.test")
    c, uid = _client(flask_app, "owner")
    j, p, _ = _done_job(flask_app, uid, tmp_path)
    for method, url in ROUTES:
        res = getattr(c, method)(url.format(j=j, p=p), json={})
        assert res.status_code in (403, 404), (method, url, res.status_code)
    assert b"Fix this release" not in c.get(f"/audit/{j}").data


def test_anonymous_is_refused(flask_app, monkeypatch, tmp_path):
    monkeypatch.setenv("REPAIR_ALLOWED_USERS", "owner")
    _, uid = _client(flask_app, "owner")
    j, p, _ = _done_job(flask_app, uid, tmp_path)
    anon = flask_app.test_client()
    for method, url in ROUTES:
        res = getattr(anon, method)(url.format(j=j, p=p), json={})
        assert res.status_code in (403, 404), (method, url, res.status_code)
    assert anon.post(f"/audit/{j}/repair").status_code == 403


def test_allowed_account_cannot_reach_someone_elses_job(flask_app, monkeypatch, tmp_path):
    monkeypatch.setenv("REPAIR_ALLOWED_USERS", "owner,other")
    _, owner_id = _client(flask_app, "owner")
    other, _ = _client(flask_app, "other")
    j, p, _ = _done_job(flask_app, owner_id, tmp_path)
    assert other.get(f"/audit/{j}/repair/{p}").status_code == 404
    assert other.get(f"/owltester/audit/{j}/repair/{p}").status_code == 404
    assert other.post(f"/audit/{j}/repair").status_code == 403


def test_owner_sees_the_button_and_the_plan(flask_app, monkeypatch, tmp_path):
    monkeypatch.setenv("REPAIR_ALLOWED_USERS", "OWNER@example.test")
    c, uid = _client(flask_app, "owner")
    j, p, _ = _done_job(flask_app, uid, tmp_path)
    assert b"Fix this release" in c.get(f"/audit/{j}").data
    assert c.get(f"/audit/{j}/repair/{p}").status_code == 200
    assert c.get(f"/owltester/audit/{j}/repair/{p}").get_json()["role"] == "owner"


def test_sharing_roles_and_revocation(flask_app, monkeypatch, tmp_path):
    monkeypatch.setenv("REPAIR_ALLOWED_USERS", "owner,dwayne,stranger")
    owner, uid = _client(flask_app, "owner")
    dwayne, dwayne_id = _client(flask_app, "dwayne")
    _client(flask_app, "outsider")
    j, p, _ = _done_job(flask_app, uid, tmp_path)
    up = flask_app.config["UPLOADED_OWLS_DEST"]
    plan = storage.load(up, j, p)
    plan.remedies = [Remedy(id="M-R1-1", finding_id="R1-1", code="W_CI_NO_SHACL", kind="mechanical",
                            title="t", rationale="", options=[RemedyOption(id="a", label="x", consequence="",
                                                                           ops=[{"op": "exclude_file", "args": {"path": "x"}}])])]
    storage.save(up, plan)
    base = f"/owltester/audit/{j}/repair/{p}"
    assert dwayne.get(base).status_code == 404                     # not a member yet
    assert owner.post(base + "/members", json={"account": "outsider", "role": "reviewer"}).status_code == 400
    assert owner.post(base + "/members", json={"account": "dwayne", "role": "reviewer"}).status_code == 200
    assert dwayne.get(base).get_json()["role"] == "reviewer"
    assert dwayne.post(base + "/remedy/M-R1-1/comment", json={"text": "looks right", "propose_option": "a"}).status_code == 200
    assert dwayne.post(base + "/remedy/M-R1-1", json={"action": "skip"}).status_code == 403
    assert dwayne.post(base + "/apply").status_code == 403
    assert dwayne.get(base + "/issues.zip").status_code == 403
    assert dwayne.post(base + "/members", json={"account": "owner", "role": "approver"}).status_code == 403
    assert owner.delete(base + f"/members/{dwayne_id}").status_code == 200
    assert dwayne.get(base).status_code == 404                     # revoked at once
    assert storage.load(up, j, p).remedies[0].comments[0]["propose_option"] == "a"


@pytest.mark.java
def test_web_flow_builds_decides_and_applies(flask_app, monkeypatch, tmp_path):
    monkeypatch.setenv("REPAIR_ALLOWED_USERS", "owner")
    c, uid = _client(flask_app, "owner")
    up = flask_app.config["UPLOADED_OWLS_DEST"]
    job_id, d = jobs.create(up, {"user_id": uid}, "mini", "general")
    rel = materialize_case("ci-no-shacl", os.path.join(d, "release", "mini"))
    report = run_audit(rel, budget=300, artifact_name="mini").to_dict()
    jobs.update(up, job_id, status="done", report=report, release_files=["mini"])
    res = c.post(f"/audit/{job_id}/repair", headers={"Accept": "application/json"})
    assert res.status_code == 202
    pid = res.get_json()["plan_id"]
    base = f"/owltester/audit/{job_id}/repair/{pid}"
    for _ in range(120):
        plan = c.get(base).get_json()
        if plan["status"] != "building":
            break
        time.sleep(0.5)
    assert plan["status"] == "ready", plan.get("error")
    rid = next(r["id"] for r in plan["remedies"] if r["code"] == "W_CI_NO_SHACL")
    assert c.post(f"{base}/remedy/{rid}", json={"action": "accept", "option": "a"}).status_code == 200
    assert c.post(f"{base}/apply").status_code == 202
    for _ in range(600):
        state = c.get(f"{base}/apply").get_json()
        if state["status"] != "running":
            break
        time.sleep(0.5)
    assert state["status"] == "done", state
    assert state["result"]["fixed"] is True
    assert c.get(f"{base}/out/zip").status_code == 200
    assert b"pyshacl" in c.get(f"{base}/out/patch").data
    assert c.get(f"{base}").get_json()["remedies"][0]["status"] in ("applied", "open")


# -- pull requests (spec 6) --------------------------------------------------------------------

def test_github_token_is_stored_encrypted(tmp_path, monkeypatch):
    from owltester.release_repair import github
    monkeypatch.setenv("SESSION_SECRET", "s3cret")
    token = "ghp_" + "a" * 36
    github.store_token(str(tmp_path), 7, token)
    raw = open(tmp_path / "secrets" / "github-7.token", "rb").read()
    assert token.encode() not in raw
    assert oct(os.stat(tmp_path / "secrets" / "github-7.token").st_mode & 0o777) == "0o600"
    assert github.load_token(str(tmp_path), 7) == token
    monkeypatch.setenv("SESSION_SECRET", "another")
    assert github.load_token(str(tmp_path), 7) is None          # wrong key: unreadable
    assert github.delete_token(str(tmp_path), 7) is True


def test_pull_request_calls_only_the_git_data_api(tmp_path):
    from owltester.release_repair import github
    calls = []

    def fake(method, path, payload=None):
        calls.append((method, path, payload))
        return {"object": {"sha": "h"}, "tree": {"sha": "t"}, "sha": "n", "html_url": "https://x/pr/1",
                "number": 1}
    res = github.open_pull_request("tok", "dkoepsell/lof", "main", "release", [("a.ttl", "x\n"), ("b.ttl", None)],
                                   "title", "body", "owltester-repair-abc", call=fake)
    assert res["url"] == "https://x/pr/1"
    assert [c[0] + " " + c[1] for c in calls] == [
        "GET /repos/dkoepsell/lof/git/ref/heads/main", "GET /repos/dkoepsell/lof/git/commits/h",
        "POST /repos/dkoepsell/lof/git/trees", "POST /repos/dkoepsell/lof/git/commits",
        "POST /repos/dkoepsell/lof/git/refs", "POST /repos/dkoepsell/lof/pulls"]
    tree = calls[2][2]["tree"]
    assert tree[0] == {"path": "release/a.ttl", "mode": "100644", "type": "blob", "content": "x\n"}
    assert tree[1]["sha"] is None
    for bad in (("x", "main", ""), ("a/b", "main", "../up"), ("a/b", "bad..branch", "")):
        with pytest.raises(github.GitHubError):
            github.open_pull_request("tok", *bad, [("a", "x")], "t", "b", "br", call=fake)


def test_only_the_owner_may_open_a_pull_request(flask_app, monkeypatch, tmp_path):
    monkeypatch.setenv("REPAIR_ALLOWED_USERS", "owner,dwayne")
    owner, uid = _client(flask_app, "owner")
    dwayne, _ = _client(flask_app, "dwayne")
    j, p, _ = _done_job(flask_app, uid, tmp_path)
    base = f"/owltester/audit/{j}/repair/{p}"
    owner.post(base + "/members", json={"account": "dwayne", "role": "approver"})
    assert dwayne.post(base + "/pull-request", json={}).status_code == 403
    assert dwayne.post(base + "/github-token", json={"token": "x" * 40}).status_code == 403
    assert owner.post(base + "/pull-request", json={"repo": "a/b"}).status_code == 409   # not applied yet


def test_plan_build_reports_progress_and_goes_stale(flask_app, monkeypatch, tmp_path):
    from owltester import repair_service
    from owltester.release_repair.model import Plan
    monkeypatch.setenv("REPAIR_ALLOWED_USERS", "owner")
    c, uid = _client(flask_app, "owner")
    j, p, _ = _done_job(flask_app, uid, tmp_path)
    up = flask_app.config["UPLOADED_OWLS_DEST"]
    stub = Plan(plan_id="b" * 32, job_id=j, artifact="mini", profile="general",
                created_at="2026-01-01T00:00:00", created_by={"user_id": uid}, status="building",
                build={"stage": "Proposing fixes (W_HEADER)", "done": 3, "total": 9,
                       "updated_at": "2026-01-01T00:00:00"})
    storage.save(up, stub)
    assert c.get(f"/owltester/audit/{j}/repair/{stub.plan_id}").get_json()["build"]["status"] == "stale"
    assert b"stopped building" in c.get(f"/audit/{j}/repair/{stub.plan_id}").data
    stub.build["updated_at"] = repair_service.now()
    storage.save(up, stub)
    b = c.get(f"/owltester/audit/{j}/repair/{stub.plan_id}").get_json()["build"]
    assert (b["status"], b["done"], b["total"]) == ("building", 3, 9)
    page = c.get(f"/audit/{j}/repair/{stub.plan_id}").data
    assert b"Proposing fixes (W_HEADER)" in page and b"3 of 9 findings" in page
