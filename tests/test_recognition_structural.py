"""The half of the kernel description logic cannot see (paper §6.3, Table 7).

Every defect in the ``structural.ttl`` fixture leaves the artifact consistent.
A reasoner asked about any of them has nothing to report, because nothing is
wrong with the theory as a theory. If these detectors regress, the pipeline
goes back to reporting Stratum A plus part of C and scoring the rest zero --
which is the specific failure the paper is written against.

The discipline in §6.2 requires each type be distinguishable from every other
in *both* directions, so the central test here is the cross-negative matrix:
each defect class fires its own primitive and no other class's.
"""

import os

import pytest

from recognition import report as R
from recognition.detectors import structural

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fixtures", "recognition")

EX = "http://example.org/rec#"


@pytest.fixture(scope="module")
def report():
    return R.build_for_path(os.path.join(FIXTURES, "structural.ttl"),
                            use_reasoner=False)


def _kernels_on(report, local):
    return {f.kernel for f in report.findings if f.iri == EX + local}


# --- the cross-negative matrix (§6.2) -----------------------------------------
#
# Each class carries exactly one defect and must fire exactly one primitive.

CASES = [
    ("OtherAnxietyCriterion", "K-B3", "CT-5"),
    ("UnspecifiedMoodCondition", "K-B3", "CT-5"),
    ("QualifyingDisabilityCriterion", "K-B2", "CT-4"),
    ("DependencyCriterion", "K-B1", "CT-2"),
    ("PolytheticSyndromeCriterion", "K-A3", "CT-3"),
    ("SeverityRating", "K-C2", None),
]


@pytest.mark.parametrize("local,kernel,ct", CASES)
def test_each_defect_fires_exactly_its_own_primitive(report, local, kernel, ct):
    assert _kernels_on(report, local) == {kernel}


@pytest.mark.parametrize("local,kernel,ct", CASES)
def test_each_defect_carries_its_classificatory_type(report, local, kernel, ct):
    finding = next(f for f in report.findings if f.iri == EX + local)
    actual = finding.classificatory_type
    assert (actual["id"] if actual else None) == ct


def test_clean_classes_fire_nothing(report):
    """Classes present only as scenery must stay silent."""
    for local in ("PanicCriterion", "PhobiaCriterion", "Impairment",
                  "FeatureInsomnia", "FeatureFatigue"):
        assert _kernels_on(report, local) == set(), local


# --- K-B3: residual definition ------------------------------------------------

def test_residual_definition_found_by_axiom(report):
    """Genus plus subtracted siblings, with no positive differentia."""
    finding = next(f for f in report.findings
                   if f.iri == EX + "OtherAnxietyCriterion")
    assert "axiomatic" in finding.evidence["routes"]


def test_residual_definition_found_by_label(report):
    """The "not otherwise specified" family: the same defect without an axiom."""
    finding = next(f for f in report.findings
                   if f.iri == EX + "UnspecifiedMoodCondition")
    assert "lexical" in finding.evidence["routes"]


def test_naming_a_genus_does_not_defeat_the_residual_check(report):
    """"No positive differentia" is not "no positive terms".

    The canonical residual category names its genus and subtracts its siblings.
    A check requiring zero positive terms would miss every real instance.
    """
    finding = next(f for f in report.findings
                   if f.iri == EX + "OtherAnxietyCriterion")
    assert finding.kernel == "K-B3"


# --- K-B2: equivocation -------------------------------------------------------

def test_equivocation_names_the_double_duty_term(report):
    """The term required as an inclusion filler and excluded outright."""
    finding = next(f for f in report.findings
                   if f.iri == EX + "QualifyingDisabilityCriterion")
    assert finding.evidence["terms"] == [EX + "LongTermImpairment"]


def test_polarity_is_tracked_per_visit_not_per_node():
    """Regression: a node-keyed visited set silently disables K-B2 entirely.

    The equivocation signature is one term appearing in both polarities. A
    visited set keyed on the node alone treats the second appearance as a
    repeat and drops it, and the detector then never fires on anything.
    """
    from recognition.detectors import _expr
    from owltester.context import GateContext
    from owltester.kernel import load_kernel

    ctx = GateContext(os.path.join(FIXTURES, "structural.ttl"),
                      kernel=load_kernel(None), catalog=None)
    node = _expr.equivalence_nodes(
        ctx.graph, EX + "QualifyingDisabilityCriterion")[0]
    positive, negative, _props = _expr.expression_terms(ctx.graph, node)
    assert EX + "LongTermImpairment" in positive
    assert EX + "LongTermImpairment" in negative


# --- K-B1: definitional cycles ------------------------------------------------

def test_definitional_cycle_is_distinct_from_a_subsumption_cycle(report):
    """This artifact has no subsumption cycle; the defect is in the definitions."""
    finding = next(f for f in report.findings if f.kernel == "K-B1")
    assert "definitional" in finding.evidence["kinds"]
    assert set(finding.evidence["cycle"]) == {EX + "DependencyCriterion",
                                              EX + "ToleranceCriterion"}


# --- K-A3: polythetic families ------------------------------------------------

def test_polythetic_family_lists_its_alternatives(report):
    finding = next(f for f in report.findings if f.kernel == "K-A3")
    assert len(finding.evidence["alternatives"]) == 4


def test_union_with_a_shared_essence_is_not_polythetic(tmp_path):
    """An ordinary disjunction over a common genus is not underconstrained."""
    path = tmp_path / "shared.ttl"
    path.write_text("""
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://example.org/rec#> .
<http://example.org/rec/shared> a owl:Ontology .
ex:Mood a owl:Class .
ex:A a owl:Class ; rdfs:subClassOf ex:Mood .
ex:B a owl:Class ; rdfs:subClassOf ex:Mood .
ex:C a owl:Class ; rdfs:subClassOf ex:Mood .
ex:AnyMood a owl:Class ; owl:equivalentClass [ owl:unionOf ( ex:A ex:B ex:C ) ] .
""", encoding="utf-8")
    built = R.build_for_path(str(path), use_reasoner=False)
    assert [f for f in built.findings if f.kernel == "K-A3"] == []


# --- CT-1: latent overlap -----------------------------------------------------

def test_latent_overlap_is_reported_per_parent_not_per_pair(report):
    """One row per parent. Per-pair reporting does not survive a real corpus."""
    latent = [f for f in report.findings
              if f.kernel == "K-A1" and f.evidence.get("latent")]
    assert len(latent) == 1
    assert latent[0].iri == EX + "DiagnosticCriterion"
    assert latent[0].classificatory_type["id"] == "CT-1"


def test_latent_overlap_does_not_mark_k_a1_assessed(report):
    """A missing axiom is silent about whether the theory admits a model.

    Counting CT-1 as coverage of K-A1 would report Stratum A as examined on the
    strength of a check that cannot answer the question K-A1 asks.
    """
    assert "K-A1" not in report.primitives_attempted
    assert "K-A1" in report.fingerprint["strata"]["A"]["primitives_unassessed"]


def test_asserted_disjointness_suppresses_the_latent_flag(tmp_path):
    path = tmp_path / "disjoint.ttl"
    path.write_text("""
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://example.org/rec#> .
<http://example.org/rec/disjoint> a owl:Ontology .
ex:Parent a owl:Class .
ex:A a owl:Class ; rdfs:subClassOf ex:Parent ; owl:disjointWith ex:B .
ex:B a owl:Class ; rdfs:subClassOf ex:Parent .
""", encoding="utf-8")
    built = R.build_for_path(str(path), use_reasoner=False)
    assert [f for f in built.findings if f.kernel == "K-A1"] == []


def test_truncation_is_reported_rather_than_silent(monkeypatch, tmp_path):
    """A capped report must say what it dropped, or it reads as complete."""
    monkeypatch.setattr(structural, "MAX_LATENT_OVERLAPS", 1)
    lines = ["@prefix owl: <http://www.w3.org/2002/07/owl#> .",
             "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
             "@prefix ex: <http://example.org/rec#> .",
             "<http://example.org/rec/many> a owl:Ontology ."]
    for parent in range(3):
        lines.append(f"ex:P{parent} a owl:Class .")
        for child in range(2):
            lines.append(f"ex:C{parent}_{child} a owl:Class ; "
                         f"rdfs:subClassOf ex:P{parent} .")
    path = tmp_path / "many.ttl"
    path.write_text("\n".join(lines), encoding="utf-8")

    built = R.build_for_path(str(path), use_reasoner=False)
    truncation = [f for f in built.findings
                  if f.evidence.get("truncated")]
    assert len(truncation) == 1
    assert truncation[0].evidence["truncated"] == 2


# --- coverage -----------------------------------------------------------------

def test_structural_detector_closes_strata_b_and_c(report):
    assert report.fingerprint["strata"]["B"]["status"] == "assessed"
    assert report.fingerprint["strata"]["C"]["status"] == "assessed"


def test_stratum_d_stays_unassessed_without_a_record(report):
    assert report.fingerprint["strata"]["D"]["status"] == "not-assessed"


# --- model witnesses (§6.2, CT-1) ---------------------------------------------

def test_latent_overlap_is_promoted_to_a_witnessed_model(report):
    """A syntactic shape is a suspicion; an admitted model is a demonstration.

    Skipped where Mace4 is absent -- the structural finding stands either way,
    it just keeps the weaker evidence it already had.
    """
    try:
        from prover9_runner import prover9_available
    except Exception:  # noqa: BLE001
        pytest.skip("prover9_runner unavailable")
    if not prover9_available():
        pytest.skip("Mace4 not installed")

    latent = next(f for f in report.findings if f.evidence.get("latent"))
    assert latent.evidence["unintended_model"]["witnessed"] is True


def test_prover_probe_adds_no_primitive(report):
    """Evidence promotion must not change which strata read as assessed."""
    assert "K-A1" not in report.primitives_attempted


def test_report_survives_without_a_prover():
    """A missing model finder degrades evidence, never the report."""
    built = R.build_for_path(os.path.join(FIXTURES, "structural.ttl"),
                             use_reasoner=False, use_prover=False)
    latent = next(f for f in built.findings if f.evidence.get("latent"))
    assert "unintended_model" not in latent.evidence
    assert latent.kernel == "K-A1"
