"""Who may repair (spec section 1). Closed by default; never anonymous.

``REPAIR_ALLOWED_USERS`` lists usernames or emails, matched case-insensitively.
Empty or unset means nobody, as with AUDIT_ALLOWED_USERS. A plan is open to the owner of the audit job
it came from and to the accounts that owner adds to it, each with a role.
"""

import os

ROLES = ("owner", "approver", "reviewer")
CAN = {
    "view": {"owner", "approver", "reviewer"},
    "comment": {"owner", "approver", "reviewer"},
    "decide": {"owner", "approver"},
    "apply": {"owner", "approver"},
    "export": {"owner", "approver"},
    "share": {"owner"},
    "pull_request": {"owner"},
}


def allowed_users():
    raw = os.environ.get("REPAIR_ALLOWED_USERS", "")
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def current():
    """(user_id, username, email) of the signed-in account, or (None, '', '')."""
    try:
        from flask_login import current_user
        if current_user.is_authenticated:
            return (current_user.id, str(getattr(current_user, "username", "") or ""),
                    str(getattr(current_user, "email", "") or ""))
    except Exception:  # noqa: BLE001 - served without flask-login
        pass
    return None, "", ""


def matches(allow, username, email):
    """Is the account named in ``allow``? An entry with "@" names an email and matches only
    the account's email; any other entry matches only the username. So nobody can register
    a username that equals someone's allowlisted email. Case-insensitive; registration
    refuses case-variants of an existing username or email."""
    username, email = (username or "").strip().lower(), (email or "").strip().lower()
    for entry in allow:
        if "@" in entry:
            if email and entry == email:
                return True
        elif username and entry == username:
            return True
    return False


def is_allowed(username, email):
    return matches(allowed_users(), username, email)


def may_repair():
    """Signed in, and named in REPAIR_ALLOWED_USERS. Fails closed."""
    uid, username, email = current()
    return uid is not None and is_allowed(username, email)


def role(plan, job, user_id):
    """The account's role on this plan, or None."""
    if user_id is None:
        return None
    if (job.get("owner") or {}).get("user_id") == user_id:
        return "owner"
    for m in plan.members if plan is not None else ():
        if m.get("user_id") == user_id and m.get("role") in ROLES:
            return m["role"]
    return None


def can(role_name, what):
    return role_name in CAN.get(what, set())


def describe():
    """One line for the startup log: who may audit and who may repair."""
    audit_allow = os.environ.get("AUDIT_ALLOWED_USERS", "").strip()
    repair = sorted(allowed_users())
    return (f"full audits: {('only ' + audit_allow) if audit_allow else 'no one named (AUDIT_ALLOWED_USERS is empty)'}"
            " plus power users; "
            f"guided repair: {'only ' + ', '.join(repair) if repair else 'nobody (REPAIR_ALLOWED_USERS is empty)'}")
