"""Full artifact audit (SPEC-audit.md): R0 ingest, one test per mini fixture,
the LOMO golden test, CLI exit codes, budgets, outputs, HTTP and lenses.

Tests that start a reasoner are marked ``java`` and skip cleanly without one.
"""

import contextlib
import io
import json
import os
import shutil
import time
import zipfile

import pytest

from owltester.audit import jobs, lenses
from owltester.audit.artifact import load_artifact
from owltester.audit.config import parse_simple_yaml
from owltester.audit.context import AuditContext
from owltester.audit.profiles import get_profile
from owltester.audit.render import issues_zip, to_html, to_markdown
from owltester.audit.runner import run_audit
from owltester.model import AuditFinding, AuditReport

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "fixtures", "audit")
LOMO = os.path.join(FIX, "lomo-1.0.0-trimmed")
MINI = os.path.join(FIX, "mini")
LOMO_NS = "http://data.europa.eu/leg/"


def materialize(case, dest):
    """clean/ with the case's overlay on top."""
    target = os.path.join(str(dest), case)
    shutil.copytree(os.path.join(MINI, "clean"), target)
    if case != "clean":
        shutil.copytree(os.path.join(MINI, case), target, dirs_exist_ok=True)
    return target


def audit(path, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return run_audit(path, **kw)


def above_info(report):
    return sorted({f.code for f in report.findings if f.severity != "info"})


def zip_dir(src, zpath, top="release-1.0.0"):
    with zipfile.ZipFile(zpath, "w") as zf:
        for dirpath, _, files in os.walk(src):
            for fn in files:
                ab = os.path.join(dirpath, fn)
                zf.write(ab, os.path.join(top, os.path.relpath(ab, src)))
    return zpath


# -- R0: ingest and roles (no reasoner) ----------------------------------------------

def test_lomo_roles_data_sets_and_owned_namespaces():
    art = load_artifact(LOMO)
    roles = art.manifest()["roles"]
    assert roles["ontology"] == ["ontologies/lomo-ontology.ttl"]
    assert len(roles["vocabulary"]) == 4
    assert roles["shapes"] == ["shapes/lomo-shapes.ttl"]
    assert roles["shapes (external)"] == ["shapes/iopa-shapes.ttl"]
    assert roles["vocabulary (external)"] == ["iopa/interop-assessment-codes.ttl"]
    assert sorted(art.data_sets) == ["data/examples", "data/lfds/ttl", "data/other"]
    assert art.data_sets["data/other"]["legacy"] and not art.data_sets["data/examples"]["legacy"]
    assert sorted(art.owned_namespaces) == [
        LOMO_NS + "deontic-modality/", LOMO_NS + "digital-dimensions/", LOMO_NS + "lomo#",
        LOMO_NS + "result-category/", LOMO_NS + "temporal-function/"]
    assert {i["iri"] for i in art.imports["unresolved"]} >= {"http://www.w3.org/ns/dcat"}


def test_zip_keeps_paths_and_sanitises_members(tmp_path):
    src = materialize("clean", tmp_path)
    z = zip_dir(src, str(tmp_path / "r.zip"))
    with zipfile.ZipFile(z, "a") as zf:
        zf.writestr("release-1.0.0/../../evil.ttl", "<urn:a> <urn:b> <urn:c> .")
    art = load_artifact(z)
    try:
        assert art.name == "release-1.0.0"
        assert "data/main" in art.data_sets
        assert any(f.path == "evil.ttl" for f in art.files)
        assert all(os.path.realpath(f.abspath).startswith(os.path.realpath(art.root)) for f in art.files)
    finally:
        art.cleanup()


def test_audit_yaml_overrides(tmp_path):
    src = materialize("clean", tmp_path)
    os.makedirs(os.path.join(src, "data", "scratch"))
    shutil.copy(os.path.join(src, "data", "main", "rules.ttl"), os.path.join(src, "data", "scratch", "x.ttl"))
    with open(os.path.join(src, "audit.yaml"), "w") as fh:
        fh.write("# overrides\ndata_sets:\n  published: [data/main/*.ttl]\n"
                 "ignore:\n  - data/scratch/**\nlegacy: [published]\nbogus: 1\n")
    art = load_artifact(src)
    assert list(art.data_sets) == ["published"]
    assert art.data_sets["published"]["legacy"] is True
    assert not any(f.path.startswith("data/scratch") for f in art.files)
    assert art.config["_unknown_keys"] == ["bogus"]


def test_simple_yaml_reader():
    cfg = parse_simple_yaml("ontology: [a.ttl]\nvocabularies:\n  - v1.ttl\n  - 'v2.ttl'\n"
                            "data_sets:\n  ex: [d/*.ttl, e/*.ttl]\n  lf: x.ttl\nprofile: general # c\n")
    assert cfg == {"ontology": ["a.ttl"], "vocabularies": ["v1.ttl", "v2.ttl"],
                   "data_sets": {"ex": ["d/*.ttl", "e/*.ttl"], "lf": "x.ttl"}, "profile": "general"}


LOF_STYLE = """profile: bfo
ontology:
  - patterns/p4/p4.owl
data_sets:
  examples:
    - a.ttl
  tests:
    - b.ttl
expected:
  - file: b.ttl
    finding: E_ABOX_INCONSISTENT
    reason: by design
  - finding: W_PLACEHOLDER_IRI
    reason: examples
shacl:
  inference: reasoned   # comment
ignore:
  - x/**
"""


def test_simple_yaml_reader_lists_of_mappings():
    cfg = parse_simple_yaml(LOF_STYLE)
    assert cfg["expected"] == [
        {"file": "b.ttl", "finding": "E_ABOX_INCONSISTENT", "reason": "by design"},
        {"finding": "W_PLACEHOLDER_IRI", "reason": "examples"}]
    assert cfg["shacl"] == {"inference": "reasoned"}
    yaml = pytest.importorskip("yaml")
    assert cfg == yaml.safe_load(LOF_STYLE)


def _without_pyyaml(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "yaml", None)   # import yaml -> ImportError


def test_lof_style_config_loads_without_pyyaml(tmp_path, monkeypatch):
    _without_pyyaml(monkeypatch)
    src = materialize("clean", tmp_path)
    with open(os.path.join(src, "audit.yaml"), "w") as fh:
        fh.write(LOF_STYLE)
    art = load_artifact(src)
    try:
        assert "_config_error" not in art.config
        assert [e["code"] for e in art.config["expected"]] == ["E_ABOX_INCONSISTENT", "W_PLACEHOLDER_IRI"]
        assert "shacl" in art.config["_unknown_keys"]
    finally:
        art.cleanup()


def test_broken_config_is_reported_not_fatal(tmp_path, monkeypatch):
    _without_pyyaml(monkeypatch)
    src = materialize("clean", tmp_path)
    with open(os.path.join(src, "audit.yaml"), "w") as fh:
        fh.write("ontology:\n  - a.ttl\n    nested: oops\n")
    art = load_artifact(src)
    try:
        assert art.config["_config_error"].startswith("audit.yaml")
        assert art.data_sets            # roles still detected from content
    finally:
        art.cleanup()


@pytest.mark.java
def test_expected_outcome_does_not_count(tmp_path):
    src = materialize("inconsistent", tmp_path)
    plain = audit(src, budget=300)
    assert "E_ABOX_INCONSISTENT" in above_info(plain) and plain.verdict == "fail"
    with open(os.path.join(src, "audit.yaml"), "w") as fh:
        fh.write("expected:\n  - finding: E_ABOX_INCONSISTENT\n    file: data/**\n"
                 "    reason: a designed test case.\n  - finding: E_NEVER_HAPPENS\n")
    report = audit(src, budget=300)
    hit = [f for f in report.findings if f.code == "E_ABOX_INCONSISTENT"]
    assert hit and all(f.expected == "a designed test case." for f in hit)
    assert report.severity_counts()["expected"] == len(hit)
    assert any(f.code == "W_CONFIG" and f.evidence.get("unmatched") for f in report.findings)
    rest = {f.severity for f in report.findings if not f.expected}
    assert report.verdict == ("fail" if "critical" in rest else "warn" if "major" in rest else "pass")
    assert "expected by the release" in to_markdown(report)
    assert "expected" in to_html(report)


OFN_SAMPLE = """Prefix(:=<https://w3id.org/audit-mini/ofn#>)
Prefix(owl:=<http://www.w3.org/2002/07/owl#>)
Prefix(rdfs:=<http://www.w3.org/2000/01/rdf-schema#>)
Ontology(<https://w3id.org/audit-mini/ofn>
Import(<https://w3id.org/audit-mini/onto>)
Declaration(Class(:Thing2))
AnnotationAssertion(rdfs:label :Thing2 "thing two"@en)
)
"""


def test_owl_functional_syntax_without_robot_is_listed_not_failed(tmp_path, monkeypatch):
    import external_reasoner
    from owltester.audit.files import _parse
    monkeypatch.setattr(external_reasoner, "robot_available", lambda: False)
    path = tmp_path / "edit.owl"
    path.write_text(OFN_SAMPLE)
    graph, err = _parse(str(path), "owl")
    assert graph is None and err.startswith("not parsed: OWL Functional Syntax needs ROBOT")


@pytest.mark.skipif(shutil.which("robot") is None, reason="ROBOT not installed")
def test_owl_functional_syntax_is_read_through_robot(tmp_path):
    from rdflib import OWL, URIRef
    from owltester.audit.files import _parse
    path = tmp_path / "edit.owl"
    path.write_text(OFN_SAMPLE)
    graph, err = _parse(str(path), "owl")
    assert err == "" and (URIRef("https://w3id.org/audit-mini/ofn#Thing2"), None, None) in graph
    assert list(graph.objects(None, OWL.imports)) == [URIRef("https://w3id.org/audit-mini/onto")]


def test_ci_credit_follows_the_make_targets_ci_runs(tmp_path):
    from owltester.audit.hygiene import _ci
    src = materialize("clean", tmp_path)
    os.remove(os.path.join(src, ".github", "workflows", "ci.yml"))
    os.makedirs(os.path.join(src, "pat", ".github", "workflows"))
    os.makedirs(os.path.join(src, "pat", "src", "ontology"))
    with open(os.path.join(src, "pat", ".github", "workflows", "qc.yml"), "w") as fh:
        fh.write("jobs:\n  qc:\n    steps:\n      - name: QC\n"
                 "        working-directory: src/ontology\n        run: make test\n")
    with open(os.path.join(src, "pat", "src", "ontology", "Makefile"), "w") as fh:
        fh.write("ROBOT := java -jar ../../bin/robot.jar\nTMP := tmp\n.PHONY: test shacl\n"
                 "test: verify\n\n$(TMP)/r.owl: in.owl\n\t$(ROBOT) reason --input $< --output $@\n\n"
                 "verify: $(TMP)/r.owl\n\t$(ROBOT) verify --input $<\n\n"
                 "shacl:\n\tpyshacl -s shapes.ttl data.ttl\n")
    art = load_artifact(src)
    try:
        configs, kinds, sources = _ci(art)
        assert "reasoning" in kinds
        assert "shacl" not in kinds          # the target exists, but CI never runs it
        assert any("targets run by CI" in w for w in sources["reasoning"])
    finally:
        art.cleanup()


@pytest.mark.java
def test_data_set_inconsistent_only_when_combined(tmp_path):
    src = materialize("clean", tmp_path)
    with open(os.path.join(src, "data", "main", "extra.ttl"), "w") as fh:
        fh.write("@prefix d: <https://data.audit-mini.test/id/> .\n"
                 "@prefix onto: <https://w3id.org/audit-mini/onto#> .\n"
                 "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
                 "d:r1 a onto:Action ; rdfs:label \"the rule, typed as an action\"@en .\n")
    report = audit(src, budget=300)
    hits = [f for f in report.findings if f.code == "E_ABOX_INCONSISTENT"]
    assert len(hits) == 1 and hits[0].evidence.get("combined") is True
    assert set(hits[0].files) == {"data/main/rules.ttl", "data/main/extra.ttl"}
    assert "only when combined" in report.stages["R3"]["summary"]


@pytest.mark.java
def test_bfo_profile_without_kernel_and_alignment_lint(tmp_path):
    src = materialize("clean", tmp_path)
    with open(os.path.join(src, "ontology", "mini.ttl"), "a") as fh:
        fh.write("\n@prefix obo: <http://purl.obolibrary.org/obo/> .\n"
                 ":about a owl:ObjectProperty ; rdfs:range obo:BFO_0000001 .\n"
                 "obo:BFO_0000050 a owl:ObjectProperty ; rdfs:domain obo:BFO_0000001 .\n"
                 "dcterms:subject rdfs:domain :Rule .\n")
    report = audit(src, budget=300, profile="bfo")
    assert report.stages["R9"]["status"] != "error"
    lint = [f for f in report.findings if f.code == "W_LINT_FOREIGN_AXIOM"]
    assert len(lint) == 1
    flagged = {a["property"] for a in lint[0].evidence["axioms"]}
    assert flagged == {"dcterms:subject"}


def test_qname_is_independent_of_which_file_bound_a_prefix_first():
    import rdflib
    from owltester.audit.schema_checks import qname
    for order in (("odp1", "lof"), ("lof", "odp1")):
        g = rdflib.Graph()
        for prefix in order:
            g.bind(prefix, {"odp1": "https://w3id.org/lof/ODP001_", "lof": "https://w3id.org/lof/"}[prefix])
        assert qname(g, "https://w3id.org/lof/ODP001_0001000") == "lof:ODP001_0001000"
    g = rdflib.Graph()
    g.bind("ex", "http://example.org/")
    g.bind("onto", "http://example.org/onto#")
    assert qname(g, "http://example.org/onto#Rule") == "onto:Rule"   # no "ex:onto#Rule"


def test_make_targets_named_without_file_paths():
    from owltester.audit.hygiene import _make_reachable
    mk = ("ROBOT := java -jar ../../bin/robot.jar\nTMP := tmp\n.PHONY: test verify\n"
          "test: verify\n\n$(TMP):\n\tmkdir -p $(TMP)\n\n"
          "$(TMP)/r.owl: in.owl | ../../bin/robot.jar $(TMP)\n\t$(ROBOT) reason --input $< --output $@\n\n"
          "verify: $(TMP)/r.owl\n\t$(ROBOT) verify --input $<\n")
    recipes, named = _make_reachable(mk, ["test"])
    assert named == ["test", "verify"]
    assert "reason" in recipes                     # file targets are still followed
    _, named = _make_reachable("all: out/x.ttl build\nbuild:\n\techo\nout/x.ttl:\n\ttouch $@\n", [])
    assert named == ["all", "build"]               # no .PHONY: file paths left out


def test_tool_version_without_git_or_env(monkeypatch):
    import subprocess as sp
    from owltester.audit import runner
    monkeypatch.setenv("OWLTESTER_VERSION", "")
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 128, "", "no git"))
    v = runner.tool_version()
    assert v.startswith("src-") and len(v) == 14 and v == runner.source_hash()
    monkeypatch.setenv("OWLTESTER_VERSION", "abc1234")
    assert runner.tool_version() == "abc1234"


# -- one test per mini fixture --------------------------------------------------------

@pytest.mark.java
def test_clean_artifact_has_nothing_above_info(tmp_path):
    report = audit(materialize("clean", tmp_path), budget=300)
    assert above_info(report) == []
    assert report.verdict == "pass"
    assert report.stages["R3"]["status"] == "pass"


@pytest.mark.java
@pytest.mark.parametrize("case, expected, verdict", [
    ("ns-mismatch", ["E_NS_MISMATCH", "E_SHACL"], "fail"),
    ("datatype", ["E_DATATYPE_PROFILE"], "fail"),
    ("inconsistent", ["E_ABOX_INCONSISTENT"], "fail"),
    ("layer-conflict", ["E_LAYER_CONFLICT"], "warn"),
    ("self-example", ["E_SELF_EXAMPLE"], "warn"),
    ("ci-no-shacl", ["W_CI_NO_SHACL"], "warn"),
])
def test_mini_case_triggers_exactly_its_finding(tmp_path, case, expected, verdict):
    report = audit(materialize(case, tmp_path), budget=300)
    assert above_info(report) == sorted(expected)
    assert report.verdict == verdict


@pytest.mark.java
def test_shacl_violation_is_linked_to_the_namespace_mismatch(tmp_path):
    report = audit(materialize("ns-mismatch", tmp_path), budget=300)
    by_code = {f.code: f for f in report.findings}
    assert by_code["E_SHACL"].related == [by_code["E_NS_MISMATCH"].id]
    assert by_code["E_SHACL"].message.startswith("All 1 violations are caused by finding R5-")
    assert by_code["E_NS_MISMATCH"].fix.startswith("Replace 'https://w3id.org/audit-mini/modality#'")


@pytest.mark.java
def test_reasoner_input_loads_whatever_triple_comes_first():
    """owlready2 sniffs only 1,000 bytes; a long first triple once broke R3 at random."""
    import rdflib
    from owltester.audit.reasoning import _check
    g = rdflib.Graph()
    s = rdflib.URIRef("urn:x:a")
    g.add((s, rdflib.RDF.type, rdflib.OWL.Class))
    g.add((s, rdflib.RDFS.comment, rdflib.Literal("x" * 5000)))
    ctx = AuditContext(load_artifact(LOMO), get_profile("general"))
    for _ in range(3):
        with contextlib.redirect_stdout(io.StringIO()):
            assert _check(ctx, g)["status"] == "ok"


@pytest.mark.java
def test_inconsistency_is_explained_by_a_minimal_set(tmp_path):
    report = audit(materialize("inconsistent", tmp_path), budget=300)
    f = next(f for f in report.findings if f.code == "E_ABOX_INCONSISTENT")
    assert f.evidence["minimal"] is True
    assert f.evidence["triple_count"] == 2
    assert "declared disjoint" in f.message


# -- golden: LOMO 1.0.0 (trimmed) --------------------------------------------------------

@pytest.fixture(scope="module")
def lomo_report():
    if shutil.which("java") is None:
        pytest.skip("needs a Java runtime for the reasoner")
    return audit(LOMO, budget=900)


@pytest.fixture(scope="module")
def expected():
    with open(os.path.join(FIX, "expected-lomo.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _find(report, code, contains=""):
    return [f for f in report.findings if f.code == code and contains in f.title]


@pytest.mark.java
def test_lomo_golden_codes_and_counts(lomo_report, expected):
    for item in expected["findings"]:
        hits = _find(lomo_report, item["code"], item.get("title_contains", ""))
        assert len(hits) == item.get("findings", 1), item
        if "count" in item:
            assert hits[0].count == item["count"], item
        if "severity" in item:
            assert hits[0].severity == item["severity"], item
        for key, value in item.get("evidence", {}).items():
            assert hits[0].evidence.get(key) == value, (item, key)
    assert lomo_report.verdict == expected["verdict"]


@pytest.mark.java
def test_lomo_l2_datatypes_named(lomo_report, expected):
    f = _find(lomo_report, "E_DATATYPE_PROFILE")[0]
    for name in expected["datatype_profile_names"]:
        assert name in f.title
    assert any("datatype patch" in p["name"] for p in lomo_report.patches)


@pytest.mark.java
def test_lomo_l4_l5_reasoning(lomo_report, expected):
    assert lomo_report.stages["R3"]["notes"]["tbox"] == "ok"
    assert not _find(lomo_report, "E_UNSAT")
    inconsistent = {f.files[0]: f for f in _find(lomo_report, "E_ABOX_INCONSISTENT")}
    assert sorted(inconsistent) == sorted(expected["inconsistent_files"])
    for path, want in expected["minimal_causes"].items():
        f = inconsistent[path]
        assert f.evidence["minimal"] is True
        for fragment in want["turtle_contains"]:
            assert fragment in f.evidence["minimal_triples"]
        assert want["cause_contains"] in f.message


@pytest.mark.java
def test_lomo_l6_shacl_counts(lomo_report, expected):
    got = lomo_report.stages["R4"]["notes"]["data_sets"]
    for name, want in expected["shacl"].items():
        assert got[name] == want, name


@pytest.mark.java
def test_lomo_l3_l7_l9_l12(lomo_report):
    assert _find(lomo_report, "W_CI_NO_SHACL") and _find(lomo_report, "W_CI_NO_REASONER")
    conflict = _find(lomo_report, "E_LAYER_CONFLICT", ":PrescriptiveRule / :hasDeonticModality")[0]
    assert any("TODO" in t for t in conflict.evidence["todo"])
    assert _find(lomo_report, "E_SELF_EXAMPLE", ":PrescriptiveRule")
    assert "produces" in _find(lomo_report, "E_SELF_EXAMPLE", ":PrescriptiveRule")[0].message
    assert _find(lomo_report, "W_LINT_NO_CHARACTERISTICS") or _find(lomo_report, "W_LINT_INVERSE")
    assert "1 disjointness axiom" in _find(lomo_report, "W_LINT_DISJOINT")[0].title


@pytest.mark.java
def test_lomo_report_is_folded(lomo_report):
    assert 20 <= len(lomo_report.findings) <= 150


# -- CLI, budgets ---------------------------------------------------------------------------

@pytest.mark.java
def test_cli_exit_codes(tmp_path):
    from owltester.cli import main
    out = str(tmp_path / "r.json")
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        assert main(["audit", materialize("ci-no-shacl", tmp_path), "--json", out, "--quiet",
                     "--no-explain"]) == 0          # warn
        assert main(["audit", materialize("datatype", tmp_path), "--md", str(tmp_path / "r.md"),
                     "--quiet", "--no-explain"]) == 1   # fail
    assert json.load(open(out))["verdict"] == "warn"
    assert "# Audit report" in open(tmp_path / "r.md").read()


def test_budget_overrun_is_reported_not_raised(tmp_path):
    report = audit(materialize("clean", tmp_path), budget=0.001)
    assert report.limits_hit
    assert all(lim["limit"] == "total" for lim in report.limits_hit)
    assert report.stages["R3"]["status"] == "skipped"


# -- outputs ------------------------------------------------------------------------------

def _toy_report():
    f1 = AuditFinding(code="E_NS_MISMATCH", message="m", stage="R5", severity="critical",
                      title="A | B <script>alert(1)</script>", files=["d.ttl"], count=3, id="R5-1",
                      fix="Replace it.", evidence={"wrong_namespace": "x#"})
    f2 = AuditFinding(code="W_RANGE", message="r", stage="R5", severity="minor", title="range",
                      id="R5-2")
    f3 = AuditFinding(code="I_FEATURE_USE", message="i", stage="R8", severity="info", title="use",
                      id="R8-1")
    return AuditReport(artifact="toy", audited_at="2026-10-31T00:00:00+00:00", tool_version="t",
                       profile="general", stages={"R5": {"title": "Reference integrity",
                                                         "status": "fail", "summary": "s"}},
                       findings=[f2, f3, f1], manifest={"roles": {}, "data_sets": {}})


def test_report_model_verdict_and_roundtrip():
    r = _toy_report()
    assert r.verdict == "fail"
    assert [f.id for f in r.sorted_findings()] == ["R5-1", "R5-2", "R8-1"]
    again = AuditReport.from_dict(json.loads(json.dumps(r.to_dict())))
    assert again.to_dict() == r.to_dict()


def test_markdown_and_issue_zip():
    r = _toy_report()
    md = to_markdown(r)
    assert "| R5 | Reference integrity | fail |" in md
    assert "&lt;script&gt;" in md and "<script>" not in md
    z = zipfile.ZipFile(io.BytesIO(issues_zip(r)))
    names = z.namelist()
    assert "README.md" in names and len(names) == 3      # critical + minor, not info
    assert "\u2014" not in md


def test_html_escapes_archive_text():
    html = to_html(_toy_report())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# -- lenses ----------------------------------------------------------------------------------

def test_lens_rows_are_proposed_until_reviewed():
    art = load_artifact(LOMO)
    ctx = AuditContext(art, get_profile("general"))
    tables = lenses.run_lenses(ctx)
    law = tables[0]
    assert law["lens"] == "law" and law["rows"]
    norm = next(r for r in law["rows"] if r["id"] == "norm")
    assert norm["status"] == "proposed"
    assert any(c["term"] == ":LegalRule" for c in norm["candidates"])
    assert lenses.confirmed_rows(tables) == []
    lenses.review(tables, "law", "norm", "confirmed", "ok")
    assert [r["id"] for _, r in lenses.confirmed_rows(tables)] == ["norm"]
    with pytest.raises(ValueError):
        lenses.review(tables, "law", "norm", "approved")


# -- jobs and HTTP ----------------------------------------------------------------------------

def test_stale_job_marker(tmp_path):
    job_id, d = jobs.create(str(tmp_path), {"user_id": None}, "x", "general")
    assert jobs.read(str(tmp_path), job_id)["status"] == "queued"
    jobs.update(str(tmp_path), job_id, started_at="2000-01-01T00:00:00")
    assert jobs.read(str(tmp_path), job_id)["status"] == "stale"
    assert jobs.read(str(tmp_path), "../../etc") is None


@pytest.fixture
def flask_app(monkeypatch, tmp_path):
    from app import app
    monkeypatch.setitem(app.config, "UPLOADED_OWLS_DEST", str(tmp_path / "uploads"))
    os.makedirs(app.config["UPLOADED_OWLS_DEST"], exist_ok=True)
    app.config["TESTING"] = True
    return app


def test_audit_needs_sign_in_by_default(flask_app, monkeypatch, tmp_path):
    monkeypatch.delenv("AUDIT_MODE", raising=False)
    z = zip_dir(materialize("clean", tmp_path), str(tmp_path / "r.zip"))
    with open(z, "rb") as fh:
        res = flask_app.test_client().post("/owltester/audit", data={"files": (fh, "r.zip")},
                                           headers={"Accept": "application/json"})
    assert res.status_code == 401


def _signed_in_client(flask_app, username):
    from models import User, db
    with flask_app.app_context():
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(username=username, email=f"{username}@example.test", password_hash="x")
            db.session.add(user)
            db.session.commit()
        uid = user.id
    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
    return client


def test_allowlist_limits_who_may_start_an_audit(flask_app, monkeypatch, tmp_path):
    monkeypatch.delenv("AUDIT_MODE", raising=False)
    monkeypatch.setenv("AUDIT_ALLOWED_USERS", "owner@example.test")
    other = _signed_in_client(flask_app, "someone")
    res = other.post("/owltester/audit", data={}, headers={"Accept": "application/json"})
    assert res.status_code == 403
    assert b"Full audits are not open" in other.get("/upload").data
    owner = _signed_in_client(flask_app, "owner")
    res = owner.post("/owltester/audit", data={}, headers={"Accept": "application/json"})
    assert res.status_code == 400          # allowed through; rejected only for the empty upload
    assert b"Start the audit" in owner.get("/upload").data


def test_audits_are_never_public(flask_app, monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_MODE", "public")          # ignored: there is no public mode
    monkeypatch.setenv("AUDIT_ALLOWED_USERS", "owner@example.test")
    res = flask_app.test_client().post("/owltester/audit", data={},
                                       headers={"Accept": "application/json"})
    assert res.status_code == 401
    monkeypatch.delenv("AUDIT_ALLOWED_USERS")           # empty allowlist: nobody
    res = _signed_in_client(flask_app, "owner").post("/owltester/audit", data={},
                                                     headers={"Accept": "application/json"})
    assert res.status_code == 403
    # a job with no owning account (an old anonymous one) is visible to nobody
    job_id, _ = jobs.create(flask_app.config["UPLOADED_OWLS_DEST"], {"user_id": None}, "x", "general")
    with flask_app.test_client() as anon:
        with anon.session_transaction() as sess:
            sess["audit_job_ids"] = [job_id]
        assert anon.get(f"/owltester/audit/{job_id}").status_code == 404


@pytest.mark.java
def test_audit_http_flow(flask_app, monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_ALLOWED_USERS", "owner@example.test")
    client = _signed_in_client(flask_app, "owner")
    z = zip_dir(materialize("ci-no-shacl", tmp_path), str(tmp_path / "r.zip"))
    with open(z, "rb") as fh:
        res = client.post("/owltester/audit", data={"files": (fh, "r.zip"), "profile": "general"},
                          headers={"Accept": "application/json"})
    assert res.status_code == 202
    job_id = res.get_json()["job_id"]
    deadline = time.time() + 300
    while time.time() < deadline:
        body = client.get(f"/owltester/audit/{job_id}").get_json()
        if body["status"] in ("done", "error"):
            break
        time.sleep(1)
    assert body["status"] == "done", body
    assert body["report"]["verdict"] == "warn"
    assert client.get(f"/owltester/audit/{job_id}/report.md").data.startswith(b"# Audit report")
    assert client.get(f"/owltester/audit/{job_id}/report.html").status_code == 200
    assert client.get(f"/audit/{job_id}").status_code == 200
    assert client.get(f"/owltester/audit/{job_id}/issues.zip").mimetype == "application/zip"
    res = client.post(f"/owltester/audit/{job_id}/lens",
                      json={"lens": "law", "row": "norm", "status": "rejected"})
    assert res.status_code == 200 and res.get_json()["status"] == "rejected"
    # another visitor cannot see the job
    assert flask_app.test_client().get(f"/owltester/audit/{job_id}").status_code == 404
