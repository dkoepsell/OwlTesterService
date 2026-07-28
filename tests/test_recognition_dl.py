"""Retyping reasoner and lint output onto the kernel (paper §6.2, §9.3, §10.1).

Nothing here tests new reasoning. Stage C and bfo_lint already do the detecting;
these tests pin down the three things the recognition layer adds on top, each of
which the paper shows is easy to get wrong:

  * a finding becomes ``K-xx at a locus``, and so a named CT type
  * an inherited flag is marked blanket, not counted as a fresh discovery
  * a defect our own extraction introduced is attributed to the artifact
"""

import os

import pytest

from owltester.context import GateContext
from owltester.kernel import load_kernel
from recognition import binding as B
from recognition import report as R
from recognition.detectors import dl
from recognition.finding import ARTIFACT, BLANKET, PER_ENTITY, UNDETERMINED

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fixtures", "recognition")

EX = "http://example.org/rec#"


@pytest.fixture(scope="module")
def report():
    """Built without the reasoner: every assertion below is graph-derived."""
    return R.build_for_path(os.path.join(FIXTURES, "stratum_abc.ttl"),
                            use_reasoner=False)


def _by_iri(report, local):
    return [f for f in report.findings if f.iri == EX + local]


# --- typing -------------------------------------------------------------------

def test_category_clash_is_typed_k_c1_and_ct_7(report):
    found = _by_iri(report, "HearingCriterion")
    assert len(found) == 1
    assert found[0].kernel == "K-C1"
    assert found[0].classificatory_type["id"] == "CT-7"


def test_subsumption_cycle_is_typed_k_b1_and_ct_2_at_criteria(report):
    cycles = [f for f in report.findings if f.kernel == "K-B1"]
    assert len(cycles) == 1
    assert cycles[0].locus == "criteria"
    assert cycles[0].classificatory_type["id"] == "CT-2"
    assert set(cycles[0].evidence["cycle"]) == {EX + "ResidencyCondition",
                                                EX + "SettlementCondition"}


def test_unborne_dependent_is_typed_k_c3_and_marked_partial(report):
    found = _by_iri(report, "ApplicantStatus")
    assert len(found) == 1
    assert found[0].kernel == "K-C3"
    assert found[0].evidence["partial"] is True


def test_findings_carry_their_stratum(report):
    assert {f.kernel: f.stratum for f in report.findings} == {
        "K-C1": "C", "K-B1": "B", "K-C3": "C"}


# --- blanket versus per-entity (§9.3) -----------------------------------------

def test_inherited_clash_is_marked_blanket(report):
    """The ICD-11 correction in miniature.

    A parent's contestable typing propagated to all 154 traditional-medicine
    patterns and inflated the headline density figure by an order of magnitude.
    A child that clashes only because its parent does is not an independent
    discovery.
    """
    parent = _by_iri(report, "HearingCriterion")[0]
    child = _by_iri(report, "UrgentHearingCriterion")[0]
    assert parent.flag_scope == PER_ENTITY
    assert child.flag_scope == BLANKET


def test_blanket_findings_do_not_count_toward_debt(report):
    child = _by_iri(report, "UrgentHearingCriterion")[0]
    assert child.counts_toward_debt is False


# --- attribution (§10.1) ------------------------------------------------------

def test_reified_realizable_is_attributed_to_the_artifact(report):
    """The extraction defect must not be reported against the source.

    The class is already grounded as a disposition and also hangs a realizable
    on a bearer. That is a standing tendency of LLM ontology extraction, and
    the paper records its own reporting layer once describing exactly this kind
    of translation error as an error in the source text.
    """
    found = _by_iri(report, "FlightRiskDisposition")[0]
    assert found.attribution == ARTIFACT
    assert found.evidence["artifact_rule"] == "reified-realizable-on-bearer"
    assert found.counts_toward_debt is False


def test_ordinary_findings_stay_undetermined(report):
    """Attribution is a discipline, not a guess. Only the named rule fires."""
    assert _by_iri(report, "HearingCriterion")[0].attribution == UNDETERMINED
    assert _by_iri(report, "ApplicantStatus")[0].attribution == UNDETERMINED


# --- coverage bookkeeping (§6.3, §7.5) ----------------------------------------

def test_without_a_reasoner_stratum_a_is_not_reported_clean(report):
    """The failure mode the paper names: scoring an unexamined stratum zero.

    K-A3 is structural and does run here, so Stratum A is partially assessed --
    but the two primitives that need a reasoner must be named as unexamined,
    not left to read as zero.
    """
    stratum_a = report.fingerprint["strata"]["A"]
    assert stratum_a["status"] == "partially-assessed"
    assert "K-A1" in stratum_a["primitives_unassessed"]
    assert "K-A2" in stratum_a["primitives_unassessed"]
    assert "never looked for" in stratum_a["reading"]


def test_graph_walks_still_run_without_a_reasoner(report):
    """Turning off HermiT must not silently switch off K-C1, K-B1, K-C3."""
    assert {"K-C1", "K-B1", "K-C3"} <= report.primitives_attempted


def test_coverage_is_tracked_per_primitive_not_per_instrument(report):
    """K-C1 and K-A2 are both 'the DL instrument'; only one of them ran."""
    assert "K-C1" in report.primitives_attempted
    assert "K-A2" not in report.primitives_attempted


def test_report_lists_what_it_never_looked_for(report):
    """Without a reasoner or an institutional record, exactly five go unchecked."""
    unattempted = report.to_dict()["primitives_not_attempted"]
    assert {"K-A1", "K-A2", "K-D1", "K-D2", "K-D3"} == set(unattempted)


# --- the SCC walk -------------------------------------------------------------

def test_cycle_detection_reports_each_component_once():
    """Two mutually subsuming classes are one cycle, not two."""
    ctx = GateContext(os.path.join(FIXTURES, "stratum_abc.ttl"),
                      kernel=load_kernel(None), catalog=None)
    found = dl.subsumption_cycles(ctx, B.propose(ctx))
    assert len(found) == 1


def test_acyclic_ontology_reports_no_cycles():
    ctx = GateContext(os.path.join(FIXTURES, "act_thick.ttl"),
                      kernel=load_kernel(None), catalog=None)
    assert dl.subsumption_cycles(ctx, B.propose(ctx)) == []
