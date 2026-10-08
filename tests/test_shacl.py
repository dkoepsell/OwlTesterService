"""Readable axioms (labels + restrictions) and the SHACL workbench.

Uses an inline ontology with opaque OBO-style IRIs, so every assertion about
readability fails if the engine falls back to IRI local names.
"""

import os
import shutil
import tempfile

import pytest

import shacl_tools

ONTOLOGY = """
@prefix : <http://ex.org/x#> . @prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<http://ex.org/x> a owl:Ontology .
:EX_1 a owl:Class ; rdfs:label "Fahrzeug"@de , "Vehicle"@en .
:EX_2 a owl:Class ; rdfs:label "Wheel" .
:EX_5 a owl:Class ; rdfs:label "Round" .
:EX_3 a owl:ObjectProperty ; rdfs:label "has part" ;
    rdfs:domain [ a owl:Class ; owl:unionOf (:EX_1 :EX_2) ] .
:EX_6 a owl:DatatypeProperty , owl:FunctionalProperty ; rdfs:label "wheel count" ;
    rdfs:range xsd:integer .
:EX_4 a owl:Class ; rdfs:label "Car" ;
  rdfs:subClassOf :EX_1 ,
    [ a owl:Restriction ; owl:onProperty :EX_3 ;
      owl:someValuesFrom [ a owl:Class ; owl:intersectionOf (:EX_2 :EX_5) ] ] ,
    [ a owl:Restriction ; owl:onProperty :EX_3 ;
      owl:minQualifiedCardinality "4"^^xsd:nonNegativeInteger ; owl:onClass :EX_2 ] ,
    [ a owl:Restriction ; owl:onProperty [ owl:inverseOf :EX_3 ] ;
      owl:allValuesFrom [ owl:complementOf :EX_2 ] ] .
:EX_7 a owl:Class ; rdfs:label "Bike" ;
  owl:equivalentClass [ owl:intersectionOf ( :EX_1
    [ a owl:Restriction ; owl:onProperty :EX_3 ;
      owl:qualifiedCardinality "2"^^xsd:nonNegativeInteger ; owl:onClass :EX_2 ] ) ] .
:car1 a owl:NamedIndividual , :EX_4 ; rdfs:label "my car" ; :EX_6 4 .
"""

DATA = """
@prefix : <http://ex.org/x#> . @prefix d: <http://ex.org/data#> .
d:good a :EX_4 ; :EX_6 4 ;
    :EX_3 d:w1 , d:w2 , d:w3 , d:w4 .
d:w1 a :EX_2 , :EX_5 . d:w2 a :EX_2 . d:w3 a :EX_2 . d:w4 a :EX_2 .
d:bad a :EX_4 ; :EX_6 3 , 5 .
"""


@pytest.fixture(scope="module")
def onto_path():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "opaque.ttl")
    with open(path, "w") as fh:
        fh.write(ONTOLOGY)
    yield path
    shutil.rmtree(d)


@pytest.fixture(scope="module")
def onto(onto_path):
    return shacl_tools.load_ontology_graph(onto_path)


# --- readable axioms -------------------------------------------------------------

def test_asserted_axioms_use_labels_and_render_restrictions(onto_path):
    from owl_tester import OwlTester
    rdf = OwlTester()._extract_with_rdflib(onto_path)
    tester = OwlTester()
    tester._apply_labels(rdf["axioms"], rdf["entity_labels"])
    descs = {a["description"] for a in rdf["axioms"]}

    assert "Car ⊑ Vehicle" in descs  # English label preferred over German
    assert "Car ⊑ has part some (Wheel and Round)" in descs
    assert "Car ⊑ has part min 4 Wheel" in descs
    assert "Car ⊑ inverse has part only (not Wheel)" in descs
    assert "Bike ≡ Vehicle and (has part exactly 2 Wheel)" in descs
    assert "has part domain ⇒ Vehicle or Wheel" in descs
    # IDs are kept for traceability.
    assert any(a.get("description_ids") == "EX_4 ⊑ EX_1" for a in rdf["axioms"])


def test_entity_labels_map_covers_classes_and_properties(onto_path):
    from owl_tester import OwlTester
    labels = OwlTester()._extract_with_rdflib(onto_path)["entity_labels"]
    assert labels["EX_4"] == "Car"
    assert labels["EX_3"] == "has part"
    assert labels["car1"] == "my car"


# --- SHACL -----------------------------------------------------------------------

def test_generated_shapes_are_valid_and_reference_only_declared_terms(onto):
    gen = shacl_tools.generate_shapes(onto)
    assert gen["node_shapes"] >= 2
    assert gen["property_shapes"] >= 5
    shapes = shacl_tools.parse_rdf(gen["turtle"], "turtle")
    assert shacl_tools.lint_shapes(shapes, onto) == []


def test_validation_flags_only_the_bad_instance(onto):
    shapes = shacl_tools.parse_rdf(shacl_tools.generate_shapes(onto)["turtle"], "turtle")
    data = shacl_tools.parse_rdf(DATA)
    report = shacl_tools.validate(data, shapes, shacl_tools.tbox_only(onto), "rdfs")
    assert not report["conforms"]
    focus = {r["focus_label"] for r in report["results"]}
    assert "bad" in focus and "good" not in focus
    constraints = {r["constraint"] for r in report["results"] if r["focus_label"] == "bad"}
    assert "MaxCount" in constraints          # functional data property
    assert "QualifiedMinCount" in constraints  # 'some' and 'min 4'
    assert all(r["path_label"] in ("has part", "wheel count") for r in report["results"])


def test_tbox_only_drops_individuals(onto):
    from rdflib import URIRef
    tbox = shacl_tools.tbox_only(onto)
    car1 = URIRef("http://ex.org/x#car1")
    assert (car1, None, None) not in tbox
    assert (URIRef("http://ex.org/x#EX_4"), None, None) in tbox


def test_lint_reports_undeclared_terms_and_untargeted_shapes(onto):
    shapes = shacl_tools.parse_rdf("""
        @prefix sh: <http://www.w3.org/ns/shacl#> . @prefix : <http://ex.org/x#> .
        :S1 a sh:NodeShape ; sh:targetClass :EX_404 .
        :S2 a sh:NodeShape ; sh:property [ sh:path :EX_3 ; sh:minCount 1 ] .
    """)
    messages = " | ".join(i["message"] for i in shacl_tools.lint_shapes(shapes, onto))
    assert "EX_404" in messages
    assert "S2 has no target" in messages


def test_parse_rdf_rejects_garbage():
    with pytest.raises(ValueError):
        shacl_tools.parse_rdf("this is not rdf {{{")


# --- HTTP ------------------------------------------------------------------------

ARTIFACT = "test_shacl_opaque.ttl"


@pytest.fixture(scope="module")
def client(onto_path):
    os.environ.setdefault("SESSION_SECRET", "test")
    from app import app

    upload_dir = app.config.get("UPLOADED_OWLS_DEST", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    target = os.path.join(upload_dir, ARTIFACT)
    shutil.copy(onto_path, target)
    app.config["TESTING"] = True
    yield app.test_client()
    if os.path.exists(target):
        os.remove(target)


def test_workbench_round_trip(client):
    assert client.get(f"/shacl/{ARTIFACT}").status_code == 200
    assert client.get("/shacl/../app.py").status_code == 404

    gen = client.post(f"/api/shacl/{ARTIFACT}/generate", json={}).get_json()
    lint = client.post(f"/api/shacl/{ARTIFACT}/lint", json={"shapes": gen["turtle"]}).get_json()
    assert lint["issues"] == []

    # Pasted data only: the ontology's own car1 (missing wheels) is not under test.
    only_data = client.post(f"/api/shacl/{ARTIFACT}/validate", json={
        "shapes": gen["turtle"], "data": DATA, "include_ontology_individuals": False,
    }).get_json()
    assert {r["focus_label"] for r in only_data["results"]} == {"bad"}

    # Ontology individuals included: car1 now fails too, reported by its label.
    with_abox = client.post(f"/api/shacl/{ARTIFACT}/validate", json={
        "shapes": gen["turtle"], "include_ontology_individuals": True,
    }).get_json()
    assert "my car" in {r["focus_label"] for r in with_abox["results"]}

    bad = client.post(f"/api/shacl/{ARTIFACT}/validate", json={"shapes": "nonsense {"})
    assert bad.status_code == 400


def test_saved_shape_sets(client):
    saved = client.post(f"/api/shacl/{ARTIFACT}/shapes",
                        json={"name": "t", "shapes": "@prefix sh: <http://www.w3.org/ns/shacl#> ."})
    if saved.status_code >= 500:
        pytest.skip("no database available")
    set_id = saved.get_json()["id"]
    listed = client.get(f"/api/shacl/{ARTIFACT}/shapes").get_json()["shape_sets"]
    assert any(s["id"] == set_id for s in listed)
    assert client.get(f"/api/shacl/{ARTIFACT}/shapes/{set_id}").get_json()["name"] == "t"
    assert client.delete(f"/api/shacl/{ARTIFACT}/shapes/{set_id}").status_code == 200
