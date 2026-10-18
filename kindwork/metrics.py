"""P1 measurement log (module spec section 9): one row per session, counts only.

No term text is ever stored. To tell "confirmed unchanged" from "confirmed after
a change", proposals are remembered as {hash: {question id: y/n}}, where the
hash is HMAC-SHA256 of the lower-cased term name under a random per-session
salt that lives only in the visitor's signed session cookie. Without that
cookie the hashes cannot be linked back to any word. Rows older than 12
months are deleted.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import secrets
import uuid

from flask import session
from sqlalchemy.orm.attributes import flag_modified

from models import db

logger = logging.getLogger(__name__)

RETENTION_DAYS = 365
SESSION_KEY = "kindwork_p1"
SOURCE_TYPES = {"csv", "tsv", "xlsx", "json", "sql", "txt", "md"}
BLOCKING = {"partition", "within"}


class KindworkSession(db.Model):
    __tablename__ = "kindwork_session"

    id = db.Column(db.String(36), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    mode = db.Column(db.String(16))
    # {"source": "paste"|"task"|<file type>, "terms_in": n, "terms_proposed": n,
    #  "confirmed_unchanged": n, "confirmed_changed": n, "confirmed_by_hand": n,
    #  "changed_questions": {qid: n}, "held_back": n,
    #  "cards_raised": {type: n}, "cards_resolved": {type: {how: n}},
    #  "downloads": {kind: n}, "triage_clicked": bool,
    #  "calls": {op: n}}
    counts = db.Column(db.JSON, default=dict)
    # Hash-keyed working state; never term text. See module docstring.
    state = db.Column(db.JSON, default=dict)


def _salt():
    data = session.get(SESSION_KEY) or {}
    if "salt" not in data:
        data = {"id": str(uuid.uuid4()), "salt": secrets.token_hex(16)}
        session[SESSION_KEY] = data
        session.permanent = True
    return data


def _h(salt, name):
    return hmac.new(bytes.fromhex(salt), str(name).strip().lower().encode("utf-8"),
                    hashlib.sha256).hexdigest()[:24]


def _row(mode):
    data = _salt()
    row = db.session.get(KindworkSession, data["id"])
    if row is None:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=RETENTION_DAYS)
        KindworkSession.query.filter(KindworkSession.created_at < cutoff).delete()
        row = KindworkSession(id=data["id"], mode=mode, counts={}, state={})
        db.session.add(row)
    return row, data["salt"]


def _save(row):
    row.updated_at = datetime.datetime.utcnow()
    flag_modified(row, "counts")
    flag_modified(row, "state")
    db.session.commit()


def _bump(d, key, by=1):
    d[key] = d.get(key, 0) + by


def _safely(fn):
    """Measurement must never break a reply."""
    def wrapper(*args, **kwargs):
        try:
            fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            logger.warning("kindwork metrics skipped: %s", e)
    wrapper.__name__ = fn.__name__
    return wrapper


@_safely
def record_ingest(mode, filename, n_terms):
    row, _ = _row(mode)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    row.counts["source"] = ext if ext in SOURCE_TYPES else "file"
    row.counts["terms_in"] = n_terms
    _bump(row.counts.setdefault("calls", {}), "ingest")
    _save(row)


@_safely
def record_propose(mode, request_body, reply):
    row, salt = _row(mode)
    c = row.counts
    if request_body.get("kind") == "task":
        c["source"] = "task"
    else:
        c.setdefault("source", "paste")
        if c["source"] == "task":
            c["source"] = "paste"
        c["terms_in"] = max(c.get("terms_in", 0), len(request_body.get("terms") or []))
    proposals = row.state.setdefault("proposed", {})
    for t in (reply.get("result") or {}).get("terms") or []:
        if isinstance(t, dict) and t.get("name"):
            answers = {k: v for k, v in (t.get("answers") or {}).items() if v in ("y", "n")}
            proposals[_h(salt, t["name"])] = answers
    c["terms_proposed"] = len(proposals)
    _bump(c.setdefault("calls", {}), "propose")
    _save(row)


@_safely
def record_check(mode, manifest, findings_doc):
    """Derive confirmations, hold-backs and card resolutions from a /check."""
    row, salt = _row(mode)
    c, st = row.counts, row.state
    proposals = st.get("proposed", {})
    terms = [t for t in (manifest or {}).get("terms") or [] if isinstance(t, dict) and t.get("name")]
    by_id = {t.get("id"): t for t in terms}

    failed_iris = {i for f in (findings_doc or {}).get("findings") or []
                   if f.get("verdict") == "fail" and f.get("check") in ("coherence", "consistency")
                   for i in f.get("classes") or []}
    blocked_ids = {k.get("term") for k in (manifest or {}).get("conflicts") or []
                   if k.get("severity") in BLOCKING}

    unchanged = changed = by_hand = held = 0
    changed_q = {}
    keywords = {}
    for t in terms:
        h = _h(salt, t["name"])
        keywords[h] = t.get("keyword")
        if t.get("state") != "confirmed":
            continue
        if t.get("id") in blocked_ids or t.get("iri") in failed_iris:
            held += 1
        if h not in proposals:
            by_hand += 1
            continue
        now = {k: v for k, v in (t.get("answers") or {}).items() if v in ("y", "n")}
        diff = sorted(q for q in set(now) | set(proposals[h]) if now.get(q) != proposals[h].get(q))
        if diff:
            changed += 1
            for q in diff:
                _bump(changed_q, q)
        else:
            unchanged += 1
    c.update(confirmed_unchanged=unchanged, confirmed_changed=changed,
             confirmed_by_hand=by_hand, changed_questions=changed_q, held_back=held)

    open_now = {}
    for k in (manifest or {}).get("conflicts") or []:
        t = by_id.get(k.get("term"))
        if t and k.get("type"):
            open_now[f"{_h(salt, t['name'])}:{k['type']}"] = k["type"]
    was_open = st.get("open_cards", {})
    raised = c.setdefault("cards_raised", {})
    for key, typ in open_now.items():
        if key not in st.setdefault("seen_cards", []):
            st["seen_cards"].append(key)
            _bump(raised, typ)
    resolved = c.setdefault("cards_resolved", {})
    prev_kw = st.get("keywords", {})
    for key, typ in was_open.items():
        if key in open_now:
            continue
        h = key.split(":", 1)[0]
        how = ("term removed" if h not in keywords
               else "kind changed" if keywords.get(h) != prev_kw.get(h) else "answers changed")
        _bump(resolved.setdefault(typ, {}), how)
    st["open_cards"] = open_now
    st["keywords"] = keywords
    _bump(c.setdefault("calls", {}), "check")
    _save(row)


EVENTS = {"save-csv", "save-ttl", "save-other", "triage"}


@_safely
def record_event(mode, event):
    if event not in EVENTS:
        return
    row, _ = _row(mode)
    if event == "triage":
        row.counts["triage_clicked"] = True
    else:
        _bump(row.counts.setdefault("downloads", {}), event[5:])
    _save(row)
