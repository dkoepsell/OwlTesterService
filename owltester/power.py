"""Site admins and power users.

Admins are the accounts named in ADMIN_USERS (comma-separated; an entry with "@"
is an email, any other a username; empty means no admins). They grant and revoke
power users at /admin/power-users. A power user gets ``PERKS``; every power-user
feature checks ``is_power_user()`` (signed-in account) or ``is_power_account(user)``.

Everything fails closed: not signed in, or any error reading the table, means no.
"""

import datetime
import logging
import os
import secrets

from flask import Blueprint, abort, render_template, request, redirect, session, url_for

from .release_repair.access import current, matches

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__)
TOKEN_KEY = "admin_form_token"


def admin_users():
    raw = os.environ.get("ADMIN_USERS", "")
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def is_admin():
    uid, username, email = current()
    return uid is not None and matches(admin_users(), username, email)


def is_power_user(user_id=None):
    """Granted by an admin (admins count as power users too)."""
    if user_id is None:
        uid, username, email = current()
        if uid is None:
            return False
        if matches(admin_users(), username, email):
            return True
        user_id = uid
    try:
        from models import PowerUser
        return PowerUser.query.filter_by(user_id=user_id).first() is not None
    except Exception as e:  # noqa: BLE001 - fail closed
        logger.warning("power-user lookup failed: %s", e)
        return False


def is_power_account(user):
    """Same rule for a given account (not the signed-in one): an admin, or granted."""
    if user is None or getattr(user, "id", None) is None:
        return False
    if matches(admin_users(), str(getattr(user, "username", "") or ""),
               str(getattr(user, "email", "") or "")):
        return True
    return is_power_user(user.id)


PERKS = (
    "full artifact audits",
    "guided repair of their own audited releases",
    "the release builder, and publishing to GitHub with their own token",
    "5x the hourly limits on uploads, analysis and AI calls",
    "4x the sandbox caps (sandboxes, classes and properties per sandbox)",
    "the server's AI key (other users must bring their own)",
)


def describe():
    admins = sorted(admin_users())
    try:
        from models import PowerUser
        n = PowerUser.query.count()
    except Exception:  # noqa: BLE001 - before the table exists
        n = "?"
    return f"admins: {', '.join(admins) if admins else 'none (ADMIN_USERS is empty)'}; power users: {n}"


def _token():
    if TOKEN_KEY not in session:
        session[TOKEN_KEY] = secrets.token_urlsafe(32)
    return session[TOKEN_KEY]


def _check_token():
    sent = request.form.get("token", "")
    if not sent or not secrets.compare_digest(sent, session.get(TOKEN_KEY, "")):
        abort(400, description="The form expired; reload the page and try again.")


@admin_bp.route("/admin/power-users", methods=["GET"])
def power_users():
    if not is_admin():
        abort(404)
    from models import PowerUser
    rows = PowerUser.query.order_by(PowerUser.granted_at).all()
    return render_template("admin/power_users.html", rows=rows, token=_token(), perks=PERKS,
                           message=request.args.get("m"), error=request.args.get("e"))


@admin_bp.route("/admin/power-users", methods=["POST"])
def power_users_change():
    if not is_admin():
        abort(404)
    _check_token()
    from sqlalchemy import func
    from models import PowerUser, User, db
    action = request.form.get("action")
    back = lambda **kw: redirect(url_for("admin.power_users", **kw))
    if action == "add":
        who = (request.form.get("account") or "").strip()
        if not who:
            return back(e="Give a username or email.")
        col = User.email if "@" in who else User.username
        user = User.query.filter(func.lower(col) == who.lower()).first()
        if user is None:
            return back(e=f"No account {who}. They must register first.")
        if PowerUser.query.filter_by(user_id=user.id).first() is not None:
            return back(m=f"{user.username} is already a power user.")
        db.session.add(PowerUser(user_id=user.id, granted_by=current()[0],
                                 granted_at=datetime.datetime.utcnow(),
                                 note=(request.form.get("note") or "").strip()[:200]))
        db.session.commit()
        logger.warning("admin %s granted power user to %s (id %s)", current()[1], user.username, user.id)
        return back(m=f"{user.username} is now a power user.")
    if action == "remove":
        try:
            uid = int(request.form.get("user_id", ""))
        except ValueError:
            abort(400)
        row = PowerUser.query.filter_by(user_id=uid).first()
        if row is not None:
            name = row.user.username if row.user else uid
            db.session.delete(row)
            db.session.commit()
            logger.warning("admin %s revoked power user from %s (id %s)", current()[1], name, uid)
            return back(m=f"{name} is no longer a power user.")
        return back()
    abort(400)
