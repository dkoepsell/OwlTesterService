"""Stratum D and contradiction debt (paper §7, §9.3, §10.1).

Two things are being defended here.

Stratum D is the stratum that fires only where there are acts, and no artifact
contains acts. Every test below that touches it is really testing that the app
refuses to invent a verdict it has no evidence for.

Contradiction debt is a typed count, not an inconsistency measure, and the two
corrections it applies -- blanket flags and artifactual defects -- are the ones
the paper had to apply to its own headline numbers.
"""

import os

import pytest

from recognition import measure, report as R
from recognition.detectors import stratum_d
from recognition.finding import ARTIFACT, BLANKET, RecognitionFinding

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fixtures", "recognition")

ACT = "http://example.org/rec#CertificationAct"

FULL_RECORD = {
    "adjudications": [{"category": ACT, "outcome": "contradicted",
                       "source": "Tribunal 2025/114"}],
    "acts": [{"act": ACT,
              "preconditions": ["examiner independent"],
              "effects": ["licence granted", "!examiner independent"]}],
    "modal_pairs": [{"possibility": "appeal within 30 days",
                     "possible_in_structure": True,
                     "possible_in_practice": False}],
}


def _report(record=None):
    return R.build_for_path(os.path.join(FIXTURES, "act_thick.ttl"),
                            use_reasoner=False, record=record)


# --- Stratum D needs a record -------------------------------------------------

def test_no_record_means_unassessed_not_clean():
    """Three of twelve primitives must not be scored zero by default."""
    built = _report()
    assert built.fingerprint["strata"]["D"]["status"] == "not-assessed"
    assert {"K-D1", "K-D2", "K-D3"}.isdisjoint(built.primitives_attempted)
    assert [f for f in built.findings if f.stratum == "D"] == []


def test_a_record_closes_stratum_d():
    built = _report(FULL_RECORD)
    assert built.fingerprint["strata"]["D"]["status"] == "assessed"
    assert {"K-D1", "K-D2", "K-D3"} <= built.primitives_attempted


def test_partial_record_buys_only_the_coverage_it_carries():
    """Adjudications say nothing about whether anyone modelled the acts."""
    built = _report({"adjudications": FULL_RECORD["adjudications"]})
    assert "K-D1" in built.primitives_attempted
    assert "K-D2" not in built.primitives_attempted
    assert "K-D3" not in built.primitives_attempted
    assert built.fingerprint["strata"]["D"]["status"] == "partially-assessed"


# --- the three D primitives ---------------------------------------------------

def test_k_d1_fires_only_on_a_contradicted_adjudication():
    """An adjudication that upheld the classification is not a falsification."""
    upheld = {"adjudications": [{"category": ACT, "outcome": "upheld"}]}
    assert stratum_d.falsifications(upheld) == []
    contradicted = {"adjudications": FULL_RECORD["adjudications"]}
    assert len(stratum_d.falsifications(contradicted)) == 1


def test_k_d2_fires_when_an_effect_negates_a_precondition():
    found = stratum_d.self_defeats({"acts": FULL_RECORD["acts"]})
    assert len(found) == 1
    assert found[0].evidence["defeated_preconditions"] == ["examiner independent"]


def test_k_d2_is_silent_when_effects_leave_preconditions_alone():
    record = {"acts": [{"act": ACT, "preconditions": ["fee paid"],
                        "effects": ["licence granted"]}]}
    assert stratum_d.self_defeats(record) == []


def test_k_d3_needs_structure_permitting_and_practice_forbidding():
    both = {"modal_pairs": [{"possibility": "appeal",
                             "possible_in_structure": True,
                             "possible_in_practice": True}]}
    assert stratum_d.modal_clashes(both) == []
    assert len(stratum_d.modal_clashes(
        {"modal_pairs": FULL_RECORD["modal_pairs"]})) == 1


def test_modal_clash_lands_on_the_remedy_locus_by_default():
    """An appeal that formally exists and practically does not is repair failure."""
    found = stratum_d.modal_clashes({"modal_pairs": FULL_RECORD["modal_pairs"]})
    assert found[0].locus == "remedy"


# --- record validation at the boundary ----------------------------------------

def test_malformed_record_is_rejected_not_silently_ignored():
    with pytest.raises(stratum_d.RecordError):
        stratum_d.validate({"acts": "not a list"})
    with pytest.raises(stratum_d.RecordError):
        stratum_d.validate({"adjudications": [{"outcome": "contradicted"}]})


def test_unknown_keys_warn_rather_than_fail():
    _record, warnings = stratum_d.validate({"provenance": "somewhere"})
    assert any("provenance" in w for w in warnings)


def test_unrecognised_outcome_warns_and_does_not_fire():
    _record, warnings = stratum_d.validate(
        {"adjudications": [{"category": ACT, "outcome": "maybe"}]})
    assert any("maybe" in w for w in warnings)


# --- the measure --------------------------------------------------------------

def _finding(kernel, iri, **kwargs):
    return RecognitionFinding(kernel=kernel, message="", iri=iri, **kwargs)


def test_blanket_flags_are_excluded_from_the_corrected_figure():
    """The ICD-11 correction: 1.123 to 0.129 once the blanket flag came out."""
    findings = [_finding("K-C1", "a"),
                _finding("K-C1", "b", flag_scope=BLANKET),
                _finding("K-C1", "c", flag_scope=BLANKET)]
    result = measure.compute(findings, category_count=3)
    assert result["cd_raw"] == 1.0
    assert result["cd_corrected"] == pytest.approx(1 / 3, abs=1e-4)
    assert result["excluded"]["blanket"] == 2


def test_artifact_attributed_defects_are_excluded():
    """A defect our extraction introduced is not the source's debt."""
    findings = [_finding("K-C1", "a"),
                _finding("K-C1", "b", attribution=ARTIFACT)]
    result = measure.compute(findings, category_count=2)
    assert result["cd_raw"] == 1.0
    assert result["cd_corrected"] == 0.5
    assert result["excluded"]["artifact_attributed"] == 1


def test_both_readings_are_reported():
    """Hiding the raw figure would make the correction unauditable."""
    result = measure.compute([_finding("K-C1", "a", flag_scope=BLANKET)],
                             category_count=1)
    assert "cd_raw" in result and "cd_corrected" in result
    assert result["cd_raw"] == 1.0
    assert result["cd_corrected"] == 0.0


def test_debt_is_normalized_by_category_count():
    """What lets a 3,498-class branch sit beside a 26-class one."""
    findings = [_finding("K-B3", f"c{i}") for i in range(10)]
    assert measure.compute(findings, 100)["cd_corrected"] == 0.1
    assert measure.compute(findings, 10)["cd_corrected"] == 1.0


def test_zero_categories_does_not_divide_by_zero():
    assert measure.compute([], 0)["cd_corrected"] == 0.0


def test_debt_is_indexed_by_chain_locus():
    findings = [_finding("K-B3", "a", locus="criteria"),
                _finding("K-B3", "b", locus="criteria"),
                _finding("K-D3", "c", locus="remedy")]
    by_locus = measure.debt_by_locus(findings)
    assert by_locus["criteria"] == 2.0
    assert by_locus["remedy"] == 1.0
    assert by_locus["authority"] == 0.0


def test_unbound_findings_land_in_their_own_bucket():
    """Defects we could not place must not be silently attributed to a locus."""
    by_locus = measure.debt_by_locus([_finding("K-C2", "a")])
    assert by_locus["unbound"] == 1.0


def test_locus_table_covers_the_whole_chain_in_order():
    rows = measure.locus_table([_finding("K-B3", "a", locus="criteria")])
    assert [r["key"] for r in rows] == [
        "authority", "criteria", "assessor", "facts", "act", "effect",
        "remedy", "unbound"]
    assert next(r for r in rows if r["key"] == "criteria")["findings"] == 1


def test_measure_disclaims_being_an_inconsistency_measure():
    """§7.4. K-B3 and K-C2 fire on consistent artifacts; Monotony fails."""
    result = measure.compute([], 1)
    assert "not an inconsistency measure" in result["not_an_inconsistency_measure"]


def test_report_carries_the_measure():
    built = _report(FULL_RECORD)
    assert built.measure["category_count"] == 9    # named classes in the fixture
    assert built.measure["cd_corrected"] > 0
    assert [r["key"] for r in built.locus_table][-1] == "unbound"
