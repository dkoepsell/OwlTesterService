"""Tests for parsing ROBOT/ELK unsatisfiable-class output (large-ontology coherence).

The ROBOT integration itself needs the robot CLI (present in the Docker image,
not in dev), so here we test the output parsing against captured real ROBOT logs.
"""

from external_reasoner import extract_unsatisfiable

# Real ROBOT 1.9.6 output captured from `robot merge ... reason --reasoner ELK`
ROBOT_OUTPUT_TWO = """\
2026-06-24 19:45:13,405 ERROR org.obolibrary.robot.ReasonerHelper - There are 2 unsatisfiable classes in the ontology.
2026-06-24 19:45:13,410 ERROR org.obolibrary.robot.ReasonerHelper -     unsatisfiable: http://example.org/x#Drag
2026-06-24 19:45:13,410 ERROR org.obolibrary.robot.ReasonerHelper -     unsatisfiable: http://example.org/x#Force
"""


def test_extracts_all_unsatisfiable_iris():
    found = extract_unsatisfiable(ROBOT_OUTPUT_TWO)
    iris = {f["iri"] for f in found}
    assert iris == {"http://example.org/x#Drag", "http://example.org/x#Force"}
    names = {f["name"] for f in found}
    assert names == {"Drag", "Force"}


def test_no_unsatisfiable_returns_empty():
    assert extract_unsatisfiable("Reasoning completed. Ontology is coherent.") == []
    assert extract_unsatisfiable("") == []


def test_dedupes_and_skips_nothing():
    text = (
        "unsatisfiable: http://x#A\n"
        "unsatisfiable: http://x#A\n"
        "unsatisfiable: http://www.w3.org/2002/07/owl#Nothing\n"
    )
    found = extract_unsatisfiable(text)
    assert [f["iri"] for f in found] == ["http://x#A"]
