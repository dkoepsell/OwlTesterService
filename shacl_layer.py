"""HTTP surface for SHACL: the ``/shacl/<filename>`` workbench and its JSON API.

Lets a user build shapes for an uploaded ontology (generate a scaffold from its
OWL axioms, edit, save named versions) and test them: lint the shapes against
SHACL-SHACL and the ontology's vocabulary, then validate instance data -- the
ontology's own individuals, pasted RDF, or both -- with the ontology supplying
the class hierarchy. Logic lives in ``shacl_tools``; kept parallel to
``recognition_layer.py`` (blueprint, filename-keyed, JSON API behind a page).
"""

import logging
import os

from flask import Blueprint, abort, current_app, jsonify, render_template, request

import shacl_tools

logger = logging.getLogger(__name__)

shacl_bp = Blueprint("shacl_layer", __name__)

MAX_NAME = 255


# -- lookup ---------------------------------------------------------------------

def _artifact_path(filename):
    """Resolve an upload filename, refusing anything that escapes the folder."""
    if not filename or os.path.basename(filename) != filename:
        return None
    path = os.path.join(current_app.config.get("UPLOADED_OWLS_DEST", "uploads"), filename)
    return path if os.path.isfile(path) else None


def _ontology_or_404(filename):
    path = _artifact_path(filename)
    if path is None:
        abort(404)
    try:
        return shacl_tools.load_ontology_graph(path)
    except Exception as exc:  # noqa: BLE001 - rdflib cannot read e.g. OFN
        abort(422, description=f"Ontology could not be parsed as RDF: {exc}")


def _file_record(filename):
    try:
        from models import OntologyFile
        return (OntologyFile.query.filter_by(filename=filename)
                .order_by(OntologyFile.id.desc()).first())
    except Exception:  # noqa: BLE001 - no DB
        return None


def _error(message, status=400):
    return jsonify({"error": message}), status


def _json():
    return request.get_json(silent=True) or {}


# -- page -----------------------------------------------------------------------

@shacl_bp.route("/shacl/<path:filename>")
def shacl_page(filename):
    if _artifact_path(filename) is None:
        abort(404)
    record = _file_record(filename)
    return render_template(
        "shacl.html",
        filename=filename,
        display_name=getattr(record, "original_filename", None) or filename,
        inference_modes=shacl_tools.INFERENCE_MODES,
    )


# -- build ----------------------------------------------------------------------

@shacl_bp.route("/api/shacl/<path:filename>/generate", methods=["POST"])
def shacl_generate(filename):
    onto = _ontology_or_404(filename)
    include_dr = bool(_json().get("include_domain_range", True))
    return jsonify(shacl_tools.generate_shapes(onto, include_domain_range=include_dr))


@shacl_bp.route("/api/shacl/<path:filename>/lint", methods=["POST"])
def shacl_lint(filename):
    onto = _ontology_or_404(filename)
    try:
        shapes = shacl_tools.parse_rdf(_json().get("shapes"), "turtle")
    except ValueError as exc:
        return jsonify({"issues": [{"level": "error", "message": str(exc)}]})
    return jsonify({"issues": shacl_tools.lint_shapes(shapes, onto)})


# -- test -----------------------------------------------------------------------

@shacl_bp.route("/api/shacl/<path:filename>/validate", methods=["POST"])
def shacl_validate(filename):
    """Body: {shapes, data?, data_format?, include_ontology_individuals?, inference?}"""
    onto = _ontology_or_404(filename)
    body = _json()
    try:
        shapes = shacl_tools.parse_rdf(body.get("shapes"), "turtle")
    except ValueError as exc:
        return _error(f"Shapes: {exc}")

    import rdflib
    data = rdflib.Graph()
    data_text = body.get("data") or ""
    if data_text.strip():
        try:
            data = shacl_tools.parse_rdf(data_text, body.get("data_format") or None)
        except ValueError as exc:
            return _error(f"Data: {exc}")
    # pySHACL mixes ont_graph into the data graph, so the ontology's own
    # individuals are under test exactly when the full ontology is passed.
    include_abox = bool(body.get("include_ontology_individuals", not data_text.strip()))
    ont = onto if include_abox else shacl_tools.tbox_only(onto)
    if len(data) == 0 and not include_abox:
        return _error("No data to validate: paste instance data or include the ontology's individuals.")

    inference = body.get("inference") or "rdfs"
    try:
        report = shacl_tools.validate(data, shapes, ont_graph=ont, inference=inference)
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001 - pySHACL reports malformed shapes this way
        logger.warning("SHACL validation failed for %s: %s", filename, exc)
        return _error(f"Validation could not run: {str(exc)[:1000]}", 422)
    report["data_triples"] = len(data)
    return jsonify(report)


# -- saved shape sets -------------------------------------------------------------

def _shape_sets():
    from models import ShaclShapeSet, db
    return ShaclShapeSet, db


@shacl_bp.route("/api/shacl/<path:filename>/shapes", methods=["GET", "POST"])
def shacl_shapes(filename):
    if _artifact_path(filename) is None:
        abort(404)
    ShaclShapeSet, db = _shape_sets()
    if request.method == "GET":
        rows = (ShaclShapeSet.query.filter_by(filename=filename)
                .order_by(ShaclShapeSet.updated_at.desc()).all())
        return jsonify({"shape_sets": [r.to_dict() for r in rows]})

    body = _json()
    name = (body.get("name") or "").strip()[:MAX_NAME]
    text = body.get("shapes") or ""
    if not name:
        return _error("A name is required.")
    try:
        shacl_tools.parse_rdf(text, "turtle")
    except ValueError as exc:
        return _error(f"Shapes are not valid RDF: {exc}")
    row = ShaclShapeSet.query.filter_by(filename=filename, name=name).first()
    if row is None:
        row = ShaclShapeSet(filename=filename, name=name, shapes_ttl=text)
        db.session.add(row)
    else:
        row.shapes_ttl = text
    db.session.commit()
    return jsonify(row.to_dict())


@shacl_bp.route("/api/shacl/<path:filename>/shapes/<int:set_id>", methods=["GET", "DELETE"])
def shacl_shape_set(filename, set_id):
    ShaclShapeSet, db = _shape_sets()
    row = ShaclShapeSet.query.filter_by(filename=filename, id=set_id).first()
    if row is None:
        abort(404)
    if request.method == "DELETE":
        db.session.delete(row)
        db.session.commit()
        return jsonify({"deleted": set_id})
    return jsonify(row.to_dict(with_body=True))
