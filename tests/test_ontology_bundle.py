"""Multi-file ontology bundles: local import resolution, merge, provenance,
upload route, and the layer-by-layer check.

The fixture is a three-module stack, each importing the one below:
    thesis.ttl → core.ttl → patterns.ttl → (BFO, not uploaded)
patterns declares A and B disjoint; thesis adds C ⊑ A ⊓ B, so the stack first
breaks at the thesis layer.
"""

import io
import json
import os
import zipfile

import pytest
import rdflib
from rdflib.namespace import OWL, RDF

from tests.conftest import requires_java

EX = "http://example.org/"
PREFIXES = f"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix ex: <{EX}> .
"""

PATTERNS = PREFIXES + f"""
<{EX}patterns> a owl:Ontology ; dcterms:title "Patterns" ;
    owl:imports <http://purl.obolibrary.org/obo/bfo/2020/bfo.owl> .
ex:A a owl:Class . ex:B a owl:Class . ex:A owl:disjointWith ex:B .
"""
CORE = PREFIXES + f"""
<{EX}core> a owl:Ontology ; owl:versionIRI <{EX}core/1.0> ; owl:imports <{EX}patterns> .
ex:D a owl:Class ; rdfs:subClassOf ex:A .
"""
THESIS = PREFIXES + f"""
<{EX}thesis> a owl:Ontology ; owl:imports <{EX}core/1.0> .
ex:C a owl:Class ; rdfs:subClassOf ex:A, ex:B .
"""
STACK = {"patterns.ttl": PATTERNS, "core.ttl": CORE, "thesis.ttl": THESIS}


def _write_stack(d, files=STACK):
    for name, text in files.items():
        (d / name).write_text(text)
    return list(files)


def test_resolves_imports_and_merges_closure(tmp_path):
    from ontology_bundle import build_bundle

    names = _write_stack(tmp_path)
    merged, manifest = build_bundle(str(tmp_path), names)

    assert manifest["root"] == "thesis.ttl"
    assert manifest["order"] == ["patterns.ttl", "core.ttl", "thesis.ttl"]
    layers = {m["name"]: m["layer"] for m in manifest["modules"]}
    assert layers == {"patterns.ttl": 0, "core.ttl": 1, "thesis.ttl": 2}
    assert manifest["unresolved"] == []
    assert manifest["bfo_vendored"] is True  # BFO import maps to the built-in copy

    # Version-IRI import resolved locally.
    thesis = next(m for m in manifest["modules"] if m["name"] == "thesis.ttl")
    assert thesis["imports"] == [{"iri": f"{EX}core/1.0", "module": "core.ttl", "status": "local"}]

    # One ontology header (the root's), no imports left, every module's axioms present.
    assert list(merged.subjects(RDF.type, OWL.Ontology)) == [rdflib.URIRef(f"{EX}thesis")]
    assert not list(merged.triples((None, OWL.imports, None)))
    assert (rdflib.URIRef(f"{EX}A"), OWL.disjointWith, rdflib.URIRef(f"{EX}B")) in merged

    assert manifest["entity_module"][f"{EX}A"] == "patterns.ttl"
    assert manifest["entity_module"][f"{EX}C"] == "thesis.ttl"


def test_catalog_filename_and_unresolved(tmp_path):
    from ontology_bundle import build_bundle

    files = dict(STACK)
    # thesis imports core under an IRI that only the catalog knows about,
    # core imports patterns under an IRI whose last segment is the file name.
    files["thesis.ttl"] = THESIS.replace(f"{EX}core/1.0", "http://elsewhere.org/nao-core") \
        .replace("owl:Ontology ;", "owl:Ontology ; owl:imports <http://nowhere.org/gone> ;")
    files["core.ttl"] = CORE.replace(f"owl:imports <{EX}patterns>",
                                     "owl:imports <http://elsewhere.org/onto/patterns.ttl>")
    names = _write_stack(tmp_path, files)
    (tmp_path / "catalog-v001.xml").write_text(
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">'
        '<uri name="http://elsewhere.org/nao-core" uri="./core.ttl"/></catalog>')

    _, manifest = build_bundle(str(tmp_path), names, "catalog-v001.xml")

    assert manifest["order"] == ["patterns.ttl", "core.ttl", "thesis.ttl"]
    assert manifest["unresolved"] == [{"module": "thesis.ttl", "iri": "http://nowhere.org/gone"}]


def test_root_choice_and_unused(tmp_path):
    from ontology_bundle import build_bundle

    names = _write_stack(tmp_path)
    _, manifest = build_bundle(str(tmp_path), names, root_name="core.ttl")
    assert manifest["order"] == ["patterns.ttl", "core.ttl"]
    assert manifest["unused"] == ["thesis.ttl"]


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    buf.seek(0)
    return buf


@pytest.fixture()
def client(tmp_path):
    import app as app_module

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    flask_app.config["UPLOADED_OWLS_DEST"] = str(tmp_path)
    with flask_app.app_context():
        app_module.db.create_all()
        yield flask_app.test_client()
        app_module.db.session.remove()


def test_zip_upload_creates_merged_record(client, tmp_path):
    from models import OntologyFile
    from ontology_bundle import load_manifest

    files = {f"nao/{k}": v for k, v in STACK.items()}
    files["../../evil.ttl"] = PATTERNS.replace("patterns", "evil")  # zip-slip attempt
    resp = client.post("/upload", data={"file": (_zip(files), "nao.zip")},
                       content_type="multipart/form-data")
    assert resp.status_code == 302 and "/analyze/" in resp.headers["Location"]

    stored = resp.headers["Location"].rsplit("/", 1)[-1]
    record = OntologyFile.query.filter_by(filename=stored).one()
    manifest = load_manifest(record.file_path)
    # The zip-slip member is flattened into the modules dir and becomes a second root.
    assert sorted(manifest["roots"]) == ["evil.ttl", "thesis.ttl"]
    assert record.original_filename.endswith("(+2 imported modules)")
    assert not (tmp_path.parent / "evil.ttl").exists()


def test_multi_file_upload_with_root(client):
    from models import OntologyFile
    from ontology_bundle import load_manifest

    data = {"file": [(io.BytesIO(t.encode()), n) for n, t in STACK.items()],
            "root_module": "thesis.ttl"}
    resp = client.post("/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 302
    stored = resp.headers["Location"].rsplit("/", 1)[-1]
    record = OntologyFile.query.filter_by(filename=stored).one()
    assert load_manifest(record.file_path)["order"] == ["patterns.ttl", "core.ttl", "thesis.ttl"]

    # No layer check has run yet.
    assert client.get(f"/api/bundle/{stored}/layers").get_json()["status"] == "none"


@requires_java
def test_layer_check_finds_breaking_layer(tmp_path):
    from bundle_layers import check_layers
    from ontology_bundle import build_bundle, manifest_path, modules_dir_for

    final = tmp_path / "bundle.owl"
    mod_dir = modules_dir_for(str(final))
    os.makedirs(mod_dir)
    names = _write_stack(__import__("pathlib").Path(mod_dir))
    merged, manifest = build_bundle(mod_dir, names)
    merged.serialize(destination=str(final), format="xml")
    with open(manifest_path(str(final)), "w") as fh:
        json.dump(manifest, fh)

    report = check_layers(str(final))
    by = {l["module"]: l for l in report["layers"]}
    assert by["patterns.ttl"]["status"] == "ok"
    assert by["core.ttl"]["status"] == "ok"
    assert by["thesis.ttl"]["status"] == "incoherent"
    assert report["first_break"] == "thesis.ttl"
    assert [c["module"] for c in by["thesis.ttl"]["introduced_unsatisfiable"]] == ["thesis.ttl"]
