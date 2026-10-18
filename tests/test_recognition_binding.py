"""Chain binding and the pre-content stratum fingerprint (paper §5, §6.4).

The binding tests exist mainly to pin down what the proposer refuses to do.
Over-eager locus assignment is the failure mode that matters here: it hands a
recognition chain to artifacts that have none, and every locus-indexed figure
downstream inherits the fiction.
"""

import os

import pytest

from owltester.context import GateContext
from owltester.kernel import load_kernel
from recognition import binding as B
from recognition import profile as P

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fixtures", "recognition")


def _catalog():
    try:
        from bfo.catalog import load_catalog
        return load_catalog()
    except Exception:  # noqa: BLE001 - corroboration degrades, tests still run
        return None


def context_for(name):
    return GateContext(os.path.join(FIXTURES, name),
                       kernel=load_kernel(None), catalog=_catalog())


@pytest.fixture(scope="module")
def scientific():
    return B.propose(context_for("scientific.ttl"))


@pytest.fixture(scope="module")
def recognition_only():
    return B.propose(context_for("recognition_only.ttl"))


@pytest.fixture(scope="module")
def act_thick():
    return B.propose(context_for("act_thick.ttl"))


# --- what the proposer must refuse to do --------------------------------------

def test_scientific_ontology_gets_no_chain(scientific):
    """A gene-ontology-shaped artifact has no recognition chain at all.

    Every entity here is a BFO material entity, process, or quality. If BFO
    typing alone could assign a locus, the depolarization process would be a
    candidate recognition act and this artifact would acquire a chain it does
    not have.
    """
    assert scientific.occupied_loci == []
    assert scientific.assignments == {}


def test_process_alone_is_not_a_recognition_act(scientific):
    """BFO process must not, by itself, place anything at the act locus."""
    depolarization = "http://example.org/rec#Depolarization"
    assert depolarization in scientific.unbound
    assert scientific.locus_of(depolarization) is None


def test_ambiguous_label_is_not_resolved_by_picking_the_first():
    """A label naming two loci yields an ambiguity, never a confident guess."""
    binding = B.ChainBinding()
    loci = B._lexical_loci("sign contract obligation")
    assert set(loci) == {"facts", "effect"}, loci
    assert binding.locus_of("anything") is None


def test_cues_are_word_anchored():
    """"signing" must not fire the clinical-sign cue for the facts locus."""
    assert B._lexical_loci("signing event") == []
    assert B._lexical_loci("presenting sign") == ["facts"]


# --- what it should do --------------------------------------------------------

def test_criteria_grounded_through_iao_are_found(recognition_only):
    """IAO:directive information entity anchors the criteria locus.

    GateContext.bfo_parents stops at the BFO namespace, so this only works
    because the proposer walks subClassOf with a wider prefix set.
    """
    criterion = "http://example.org/rec#DiagnosticCriterion"
    assignment = recognition_only.assignments[criterion]
    assert assignment.locus == "criteria"
    assert assignment.confidence == "high"
    assert assignment.basis == "bfo-type+label"


def test_label_disambiguates_act_from_remedy(act_thick):
    """Both ground to BFO process; only the label separates them."""
    assert act_thick.locus_of("http://example.org/rec#CertificationAct") == "act"
    assert act_thick.locus_of("http://example.org/rec#AppealProcess") == "remedy"
    assert act_thick.locus_of("http://example.org/rec#RevocationProcess") == "remedy"


def test_role_splits_into_assessor_and_effect(act_thick):
    """BFO role admits both loci; the label decides which."""
    assert act_thick.locus_of("http://example.org/rec#BoardExaminer") == "assessor"
    assert act_thick.locus_of("http://example.org/rec#PracticeEntitlement") == "effect"


def test_declared_binding_overrides_a_proposal():
    ctx = context_for("scientific.ttl")
    neuron = "http://example.org/rec#Neuron"
    binding = B.propose(ctx, overrides={neuron: "criteria"})
    assert binding.locus_of(neuron) == "criteria"
    assert binding.assignments[neuron].confidence == "declared"
    assert binding.is_declared is True


def test_proposed_binding_is_not_declared(act_thick):
    assert act_thick.is_declared is False


# --- the fingerprint (Table 8) ------------------------------------------------

def test_three_rows_of_table_8(scientific, recognition_only, act_thick):
    assert P.classify(scientific)[0] == "scientific"
    assert P.classify(recognition_only)[0] == "recognition-only"
    assert P.classify(act_thick)[0] == "act-thick"


def test_stratum_d_not_applicable_for_a_scientific_ontology(scientific):
    """An empty Stratum D here is the correct result, not missing data."""
    fp = P.build(scientific)
    assert fp.strata["D"]["status"] == "not-applicable"
    assert "correct result" in fp.strata["D"]["reading"]


def test_stratum_d_not_assessed_when_no_record_is_bound(act_thick):
    """For an act-thick artifact, D can fire -- so silence must read as unknown."""
    fp = P.build(act_thick, available_instruments=("dl", "structural"))
    assert fp.strata["D"]["status"] == "not-assessed"
    assert fp.strata["D"]["findings"] == 0
    assert "not evidence of no failure" in fp.strata["D"]["reading"]


def test_stratum_d_assessed_once_the_world_instruments_run(act_thick):
    fp = P.build(act_thick,
                 available_instruments=("dl", "structural", "world", "process"))
    assert fp.strata["D"]["status"] == "assessed"


def test_unassessed_strata_always_raise_the_sufficiency_warning(act_thick):
    fp = P.build(act_thick)
    assert any("never sufficient" in w for w in fp.warnings)


def test_artifact_object_mismatch_is_reported(scientific):
    """The MF/MDO case: a row-one artifact whose object is a row-two institution."""
    fp = P.build(scientific, declared_object_class="recognition-only")
    assert fp.mismatch is True
    assert any("mismatch of profile" in w for w in fp.warnings)


def test_no_mismatch_when_artifact_and_object_agree(act_thick):
    fp = P.build(act_thick, declared_object_class="act-thick")
    assert fp.mismatch is False


def test_proposed_binding_warns_that_figures_inherit_uncertainty(act_thick):
    fp = P.build(act_thick)
    assert any("proposed from BFO typing" in w for w in fp.warnings)
