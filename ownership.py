"""Per-user visibility of uploaded ontologies, analyses, sandboxes and FOL tests.

An ontology in a user's history is visible to that user and no one else:

* A signed-in user sees only rows whose ``user_id`` is their own id.
* An anonymous visitor sees only rows created *in their own browser session*.
  Their ids are remembered in the signed Flask session cookie at insert time
  (see ``_remember_anonymous_insert``) and claimed by the account on login.
  Anonymous rows created elsewhere -- including legacy rows with no owner --
  are visible to nobody.

Anything not visible is reported as 404, never 403, so the existence of
another user's file is not leaked.
"""

from flask import abort, has_request_context, session
from flask_login import current_user
from sqlalchemy import event

from models import db, FOLExpression, OntologyAnalysis, OntologyFile, SandboxOntology

# Session keys holding the ids an anonymous visitor created, per model.
_ANON_KEYS = {
    OntologyFile: "anon_file_ids",
    SandboxOntology: "anon_sandbox_ids",
    FOLExpression: "anon_expression_ids",
}
# Keep the cookie bounded; the oldest anonymous ids drop off first.
MAX_ANON_IDS = 200


def _signed_in():
    return has_request_context() and current_user.is_authenticated


def _anon_ids(model):
    if not has_request_context():
        return []
    try:
        return [int(i) for i in session.get(_ANON_KEYS[model], [])]
    except (TypeError, ValueError):
        return []


def _owner_filter(model):
    """SQL criterion restricting ``model`` rows to the current visitor."""
    if _signed_in():
        return model.user_id == current_user.id
    return db.and_(model.user_id.is_(None), model.id.in_(_anon_ids(model)))


def _owns(model, record):
    if record is None:
        return False
    if _signed_in():
        return record.user_id == current_user.id
    return record.user_id is None and record.id in _anon_ids(model)


# -- ontology files and analyses ------------------------------------------------

def owned_files_query():
    """``OntologyFile.query`` restricted to the current visitor's files."""
    return OntologyFile.query.filter(_owner_filter(OntologyFile))


def owns_file(file_record):
    return _owns(OntologyFile, file_record)


def owns_filename(filename):
    """True if an upload with this stored filename belongs to the visitor."""
    if not filename:
        return False
    return owned_files_query().filter(OntologyFile.filename == filename).first() is not None


def owned_file_or_404(filename=None, file_id=None):
    """The visitor's OntologyFile by stored filename or id, else 404."""
    query = owned_files_query()
    if file_id is not None:
        query = query.filter(OntologyFile.id == file_id)
    elif filename:
        query = query.filter(OntologyFile.filename == filename)
    else:
        abort(404)
    record = query.order_by(OntologyFile.id.desc()).first()
    if record is None:
        abort(404)
    return record


def owned_analysis_or_404(analysis_id):
    """``(analysis, file_record)`` for an analysis of the visitor's file, else 404."""
    try:
        analysis_id = int(analysis_id)
    except (TypeError, ValueError):
        abort(404)
    analysis = db.session.get(OntologyAnalysis, analysis_id)
    if analysis is None:
        abort(404)
    file_record = db.session.get(OntologyFile, analysis.ontology_file_id)
    if not owns_file(file_record):
        abort(404)
    return analysis, file_record


def owned_analyses_query():
    """``OntologyAnalysis.query`` restricted to the visitor's files."""
    return (OntologyAnalysis.query.join(OntologyFile,
                                        OntologyAnalysis.ontology_file_id == OntologyFile.id)
            .filter(_owner_filter(OntologyFile)))


# -- sandbox ontologies and FOL expressions ----------------------------------------

def owned_sandboxes_query():
    return SandboxOntology.query.filter(_owner_filter(SandboxOntology))


def owned_sandbox_or_404(ontology_id):
    ontology = db.session.get(SandboxOntology, ontology_id)
    if not _owns(SandboxOntology, ontology):
        abort(404)
    return ontology


def owned_expressions_query():
    return FOLExpression.query.filter(_owner_filter(FOLExpression))


# -- recording and claiming anonymous ownership -------------------------------------

def _remember_anonymous_insert(mapper, connection, target):
    """Record an anonymous visitor's new row in their session cookie.

    Hooked on insert so every creation site (upload, bundle upload, auto-fix,
    sandbox export/import, FOL tests) is covered without touching each one.
    """
    if not has_request_context() or current_user.is_authenticated:
        return
    if target.user_id is not None or target.id is None:
        return
    key = _ANON_KEYS[type(target)]
    ids = [i for i in session.get(key, []) if i != target.id]
    ids.append(target.id)
    session[key] = ids[-MAX_ANON_IDS:]


for _model in _ANON_KEYS:
    event.listen(_model, "after_insert", _remember_anonymous_insert)


def claim_anonymous_records(user):
    """Give ``user`` the rows they created anonymously in this session."""
    claimed = False
    for model, key in _ANON_KEYS.items():
        ids = _anon_ids(model)
        if ids:
            model.query.filter(model.id.in_(ids), model.user_id.is_(None)) \
                .update({model.user_id: user.id}, synchronize_session=False)
            claimed = True
        session.pop(key, None)
    if claimed:
        db.session.commit()
