"""What a power user (owltester/power.py) gets beyond a free account: guided repair,
the release builder, higher rate limits, bigger sandbox caps, the server's AI key."""

import uuid

import pytest


@pytest.fixture()
def env(monkeypatch):
    import app as app_module
    from abuse_limits import limiter
    from models import db, User

    for name in ("ADMIN_USERS", "AUDIT_ALLOWED_USERS", "REPAIR_ALLOWED_USERS",
                 "BUILD_ALLOWED_USERS", "SERVER_AI_KEY_FOR"):
        monkeypatch.delenv(name, raising=False)
    flask_app = app_module.app
    saved = {k: flask_app.config.get(k) for k in ("TESTING", "WTF_CSRF_ENABLED", "RATELIMIT_ENABLED",
                                                  "MAX_SANDBOXES_PER_USER")}
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    ids = {}
    with flask_app.app_context():
        db.create_all()
        for who in ("free", "power"):
            tag = uuid.uuid4().hex[:8]
            u = User(username=f"{who}-{tag}", email=f"{who}-{tag}@example.org")
            u.set_password("password123")
            db.session.add(u)
            db.session.commit()
            ids[who] = u.id
        limiter.reset()
    _grant(flask_app, ids["power"])
    yield {"app": flask_app, **ids}
    flask_app.config.update(saved)
    with flask_app.app_context():
        from models import PowerUser
        PowerUser.query.filter(PowerUser.user_id.in_(list(ids.values()))).delete(synchronize_session=False)
        db.session.commit()
        limiter.reset()


def _grant(flask_app, user_id):
    from models import db, PowerUser
    with flask_app.app_context():
        db.session.add(PowerUser(user_id=user_id, granted_by="test"))
        db.session.commit()


def _revoke(flask_app, user_id):
    from models import db, PowerUser
    with flask_app.app_context():
        PowerUser.query.filter_by(user_id=user_id).delete()
        db.session.commit()


def _client(env, who):
    c = env["app"].test_client()
    with c.session_transaction() as s:
        s["_user_id"] = str(env[who])
        s["_fresh"] = True
    return c


def _as(env, who, fn):
    """Run fn() in a request signed in as ``who``."""
    from flask_login import login_user
    from models import User
    with env["app"].test_request_context("/"):
        login_user(User.query.get(env[who]))
        return fn()


def test_repair_and_builder_follow_power_status(env):
    from owltester.release_repair.access import account_may_repair, may_repair
    from owltester.release_service import may_build
    from models import User
    assert _as(env, "free", may_repair) is False
    assert _as(env, "free", may_build) is False
    assert _as(env, "power", may_repair) is True
    assert _as(env, "power", may_build) is True
    with env["app"].app_context():
        assert account_may_repair(User.query.get(env["power"])) is True     # can be added to a plan
        assert account_may_repair(User.query.get(env["free"])) is False
    assert _client(env, "free").get("/release/new").status_code == 403
    assert _client(env, "power").get("/release/new").status_code == 200
    _revoke(env["app"], env["power"])
    assert _as(env, "power", may_repair) is False
    assert _client(env, "power").get("/release/new").status_code == 403


def test_power_users_get_higher_rate_limits(env):
    env["app"].config["RATELIMIT_ENABLED"] = True
    hit = lambda c: c.post("/api/sandbox/ai/description", json={}).status_code
    free, power = _client(env, "free"), _client(env, "power")
    assert all(hit(free) != 429 for _ in range(20))
    assert hit(free) == 429                                   # free: 20 per hour
    assert all(hit(power) != 429 for _ in range(40))          # power: 100 per hour


def test_scale_limit():
    from abuse_limits import scale_limit
    assert scale_limit("20 per hour;100 per day", 5) == "100 per hour;500 per day"
    assert scale_limit("30/minute", 2) == "60/minute"


def test_power_users_get_bigger_sandbox_caps(env):
    from abuse_limits import cap
    env["app"].config["MAX_SANDBOXES_PER_USER"] = 3
    assert _as(env, "free", lambda: cap("MAX_SANDBOXES_PER_USER")) == 3
    assert _as(env, "power", lambda: cap("MAX_SANDBOXES_PER_USER")) == 12
    assert _as(env, "power", lambda: cap("MAX_SANDBOXES_PER_ANON_SESSION")) == \
        _as(env, "free", lambda: cap("MAX_SANDBOXES_PER_ANON_SESSION"))


def test_server_ai_key_is_for_power_users(env, monkeypatch):
    import api_key_utils as k
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _as(env, "free", k.resolve_ai) == (None, None)
    assert _as(env, "free", k.ai_key_source) == "none"
    assert _as(env, "free", k.server_key_withheld) is True
    assert _as(env, "free", k.resolve_openai_key) is None
    assert _as(env, "power", k.resolve_ai) == ("openai", "sk-server")
    assert _as(env, "power", k.ai_key_source) == "server"

    def own_key():
        from flask import session
        session[k.SESSION_KEY] = "sk-mine"
        return k.resolve_ai()
    assert _as(env, "free", own_key) == ("openai", "sk-mine")        # BYO still works
    assert k.resolve_ai() == (None, None)                             # no request: fails closed
    monkeypatch.setenv("SERVER_AI_KEY_FOR", "all")                    # rollback switch
    assert _as(env, "free", k.resolve_ai) == ("openai", "sk-server")
