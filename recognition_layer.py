"""HTTP surface for the recognition layer.

Serves ``/recognition/<filename>``, the report that answers what kind of
institutional object an uploaded ontology is and where along its recognition
chain it breaks, plus the JSON API behind it and the two endpoints that accept
the inputs an artifact cannot supply: a declared chain binding and an
institutional record.

Deliberately kept parallel to ``coverage_demo.py`` -- blueprint, fixture-free
JSON API, page that renders whatever the API returns.
"""

import logging
import os

from flask import (Blueprint, abort, current_app, jsonify, render_template,
                   request)

from recognition import measure as measure_mod
from recognition import report as report_mod
from recognition.detectors.stratum_d import RecordError, validate as validate_record
from recognition.kernel import CHAIN_LOCI, CLASSIFICATORY_TYPES, KERNEL, STRATA
from recognition.profile import system_class_options

logger = logging.getLogger(__name__)

recognition_bp = Blueprint("recognition_layer", __name__)

MAX_RECORD_BYTES = 512 * 1024


# -- artifact lookup -----------------------------------------------------------

def _upload_dir():
    return current_app.config.get("UPLOADED_OWLS_DEST", "uploads")


def _artifact_path(filename):
    """Resolve an upload filename, refusing anything that escapes the folder."""
    if not filename or os.path.basename(filename) != filename:
        return None
    path = os.path.join(_upload_dir(), filename)
    return path if os.path.isfile(path) else None


def _analysis_for(filename):
    """The most recent OntologyAnalysis row for ``filename``, or None.

    Persistence is best-effort: the report works without a database, it just
    cannot remember a declared binding between requests.
    """
    try:
        from models import OntologyAnalysis, OntologyFile
        record = (OntologyFile.query
                  .filter_by(filename=filename)
                  .order_by(OntologyFile.id.desc())
                  .first())
        if record is None:
            return None
        return (OntologyAnalysis.query
                .filter_by(file_id=record.id)
                .order_by(OntologyAnalysis.id.desc())
                .first())
    except Exception as exc:  # noqa: BLE001 - no DB, or schema not migrated
        logger.debug("no analysis row for %s: %s", filename, exc)
        return None


def _stored(analysis, attribute, default=None):
    return getattr(analysis, attribute, None) or default if analysis else default


# -- building ------------------------------------------------------------------

def build_report(filename, use_reasoner=True):
    """The recognition report for an uploaded artifact, or None if absent."""
    path = _artifact_path(filename)
    if path is None:
        return None
    analysis = _analysis_for(filename)
    return report_mod.build_for_path(
        path,
        overrides=_stored(analysis, "recognition_binding", {}),
        record=_stored(analysis, "institutional_record"),
        declared_object_class=_stored(analysis, "declared_object_class", ""),
        use_reasoner=use_reasoner)


# -- routes --------------------------------------------------------------------

@recognition_bp.route("/recognition/<path:filename>")
def recognition_page(filename):
    report = build_report(filename,
                          use_reasoner=request.args.get("fast") != "1")
    if report is None:
        abort(404)
    return render_template(
        "recognition_report.html",
        filename=filename,
        report=report.to_dict(),
        chain_loci=CHAIN_LOCI,
        strata=STRATA,
        kernel=KERNEL,
        classificatory_types=CLASSIFICATORY_TYPES,
        system_classes=system_class_options(),
        debug=request.args.get("debug") == "1")


@recognition_bp.route("/api/recognition/<path:filename>")
def recognition_json(filename):
    report = build_report(filename,
                          use_reasoner=request.args.get("fast") != "1")
    if report is None:
        abort(404)
    return jsonify(report.to_dict())


@recognition_bp.route("/api/recognition/<path:filename>/bind", methods=["POST"])
def recognition_bind(filename):
    """Declare chain loci for entities the proposer could not place.

    A declared binding outranks every proposal, which is the point: the
    proposer is built to refuse ambiguous cases, and this is how a human
    resolves them.
    """
    if _artifact_path(filename) is None:
        abort(404)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "expected a JSON object of iri -> locus"}), 400

    valid_loci = {locus["key"] for locus in CHAIN_LOCI}
    cleaned, rejected = {}, []
    for iri, locus in payload.items():
        if isinstance(locus, str) and locus in valid_loci:
            cleaned[str(iri)] = locus
        else:
            rejected.append(iri)

    saved = _persist(filename, recognition_binding=cleaned)
    return jsonify({"saved": saved, "bound": len(cleaned),
                    "rejected": rejected,
                    "valid_loci": sorted(valid_loci)})


@recognition_bp.route("/api/recognition/<path:filename>/record", methods=["POST"])
def recognition_record(filename):
    """Attach the institutional record Stratum D needs.

    Without one, K-D1 through K-D3 are reported unassessed rather than clean --
    so this endpoint is the only route by which an artifact can be evaluated on
    all twelve kernel primitives.
    """
    if _artifact_path(filename) is None:
        abort(404)

    # Size-check via content_length, not get_data(): reading the stream
    # uncached consumes it, and every later get_json() then returns None -- so
    # the validation below would silently pass on any payload at all.
    if (request.content_length or 0) > MAX_RECORD_BYTES:
        return jsonify({"error": "institutional record too large"}), 413

    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "expected a JSON institutional record"}), 400
    try:
        record, warnings = validate_record(payload)
    except RecordError as exc:
        return jsonify({"error": str(exc)}), 400

    saved = _persist(filename, institutional_record=record)
    return jsonify({"saved": saved, "warnings": warnings})


@recognition_bp.route("/api/recognition/<path:filename>/object-class",
                      methods=["POST"])
def recognition_object_class(filename):
    """Declare which system class the ontology's *object* occupies.

    The artifact's own row can be read off its chain occupancy; what the
    artifact is *about* cannot. Declaring it is what lets the report detect the
    mismatch of stratum profile that no amount of content inspection would
    reveal.
    """
    if _artifact_path(filename) is None:
        abort(404)

    payload = request.get_json(silent=True) or {}
    declared = payload.get("object_class", "")
    valid = {option["key"] for option in system_class_options()}
    if declared and declared not in valid:
        return jsonify({"error": "unknown system class",
                        "valid": sorted(valid)}), 400

    saved = _persist(filename, declared_object_class=declared)
    return jsonify({"saved": saved, "object_class": declared})


@recognition_bp.route("/api/recognition/kernel")
def recognition_kernel():
    """The vocabulary itself, for a UI that needs to render the tables."""
    return jsonify({
        "kernel": KERNEL,
        "strata": STRATA,
        "chain_loci": CHAIN_LOCI,
        "classificatory_types": CLASSIFICATORY_TYPES,
        "system_classes": system_class_options(),
        "weighting": measure_mod.DEFAULT_WEIGHTS,
    })


# -- persistence ---------------------------------------------------------------

def _persist(filename, **fields):
    """Store recognition inputs on the latest analysis row.

    Returns False rather than raising when there is no database or the
    migration has not been run: the report still works from the request's own
    inputs, it simply will not remember them.
    """
    analysis = _analysis_for(filename)
    if analysis is None:
        return False
    try:
        from models import db
        for name, value in fields.items():
            setattr(analysis, name, value)
        db.session.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not persist recognition input for %s: %s",
                       filename, exc)
        try:
            from models import db
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False
