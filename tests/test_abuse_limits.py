"""Abuse controls: rate limits (429), ProxyFix client-IP keying, hard caps."""

import uuid

import pytest


@pytest.fixture()
def env():
    import app as app_module
    from abuse_limits import limiter
    from models import db, User

    flask_app = app_module.app
    saved = {k: flask_app.config.get(k) for k in (
        "TESTING", "WTF_CSRF_ENABLED", "RATELIMIT_ENABLED",
        "MAX_SANDBOXES_PER_ANON_SESSION", "MAX_SANDBOXES_PER_USER",
        "MAX_CLASSES_PER_SANDBOX", "MAX_PROPERTIES_PER_SANDBOX")}
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with flask_app.app_context():
        db.create_all()
        user = User(username=f"lim-{uuid.uuid4().hex[:8]}",
                    email=f"lim-{uuid.uuid4().hex[:8]}@example.org")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        limiter.reset()
    yield {"app": flask_app, "user_id": user_id}
    flask_app.config.update(saved)
    with flask_app.app_context():
        limiter.reset()


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


# -- rate limiting ------------------------------------------------------------------

def test_limiting_is_off_for_the_suite(env):
    client = env["app"].test_client()
    for _ in range(25):
        assert client.post("/api/sandbox/ai/description", json={}).status_code != 429


def test_ai_endpoint_returns_json_429_after_limit(env):
    env["app"].config["RATELIMIT_ENABLED"] = True
    client = env["app"].test_client()
    hdr = {"X-Forwarded-For": "203.0.113.7"}
    # AI_LIMIT is 20 per hour; empty bodies are rejected cheaply (no OpenAI call).
    for _ in range(20):
        assert client.post("/api/sandbox/ai/description", json={}, headers=hdr).status_code != 429
    resp = client.post("/api/sandbox/ai/description", json={}, headers=hdr)
    assert resp.status_code == 429
    assert "Rate limit exceeded" in resp.get_json()["error"]


def test_login_limit_is_keyed_on_forwarded_client_ip(env):
    env["app"].config["RATELIMIT_ENABLED"] = True
    client = env["app"].test_client()
    attacker = {"X-Forwarded-For": "198.51.100.1"}
    bystander = {"X-Forwarded-For": "198.51.100.2"}
    form = {"username": "nobody", "password": "wrong"}
    for _ in range(10):  # LOGIN_LIMIT: 10 per minute
        assert client.post("/login", data=form, headers=attacker).status_code != 429
    assert client.post("/login", data=form, headers=attacker).status_code == 429
    # A different real client behind the same proxy is unaffected.
    assert client.post("/login", data=form, headers=bystander).status_code != 429
    # GET is not limited.
    assert client.get("/login", headers=attacker).status_code == 200


def test_proxyfix_sets_remote_addr_from_forwarded_for(env):
    from werkzeug.middleware.proxy_fix import ProxyFix
    from werkzeug.test import EnvironBuilder
    proxy = env["app"].wsgi_app
    assert isinstance(proxy, ProxyFix)
    assert (proxy.x_for, proxy.x_proto, proxy.x_host) == (1, 1, 1)

    seen = {}

    def capture(environ, start_response):
        seen["addr"] = environ["REMOTE_ADDR"]
        seen["scheme"] = environ["wsgi.url_scheme"]
        start_response("200 OK", [])
        return [b""]

    environ = EnvironBuilder(path="/", headers={
        "X-Forwarded-For": "10.9.9.9, 192.0.2.44", "X-Forwarded-Proto": "https"},
        environ_base={"REMOTE_ADDR": "172.18.0.1"}).get_environ()
    proxy.app, original = capture, proxy.app
    try:
        proxy(environ, lambda *a: None)
    finally:
        proxy.app = original
    # Only the last hop (set by the trusted host nginx) is believed.
    assert seen == {"addr": "192.0.2.44", "scheme": "https"}


def test_sandbox_creation_shares_one_limit(env):
    env["app"].config.update(RATELIMIT_ENABLED=True, MAX_SANDBOXES_PER_USER=1000)
    client = env["app"].test_client()
    _login(client, env["user_id"])
    form = {"title": "Limited", "domain": "Test", "subject": "Test", "description": ""}
    for _ in range(10):  # SANDBOX_CREATE_LIMIT: 10 per hour
        assert client.post("/sandbox/new", data=form).status_code == 302
    assert client.post("/sandbox/new", data=form).status_code == 429
    # import_to_sandbox draws on the same budget.
    assert client.post("/import_to_sandbox/999999").status_code == 429


# -- hard caps ----------------------------------------------------------------------

def test_anonymous_sandbox_count_cap(env):
    from models import SandboxOntology
    env["app"].config["MAX_SANDBOXES_PER_ANON_SESSION"] = 2
    client = env["app"].test_client()
    form = {"title": "Anon box", "domain": "Test", "subject": "Test", "description": ""}
    for _ in range(3):
        client.post("/sandbox/new", data=form)
    with client.session_transaction() as sess:
        ids = sess.get("anon_sandbox_ids", [])
    assert len(ids) == 2
    resp = client.post("/sandbox/new", data=form, follow_redirects=True)
    assert b"at most 2 sandbox ontologies" in resp.data
    with env["app"].app_context():
        assert SandboxOntology.query.filter(SandboxOntology.id.in_(ids)).count() == 2


def test_user_sandbox_count_cap(env):
    from models import db, SandboxOntology
    env["app"].config["MAX_SANDBOXES_PER_USER"] = 1
    client = env["app"].test_client()
    _login(client, env["user_id"])
    form = {"title": "User box", "domain": "Test", "subject": "Test", "description": ""}
    client.post("/sandbox/new", data=form)
    client.post("/sandbox/new", data=form)
    with env["app"].app_context():
        assert SandboxOntology.query.filter_by(user_id=env["user_id"]).count() == 1


def _user_sandbox(env):
    from models import db, SandboxOntology
    with env["app"].app_context():
        box = SandboxOntology(title="Capped", domain="d", subject="s", user_id=env["user_id"])
        db.session.add(box)
        db.session.commit()
        return box.id


def test_class_and_property_caps(env):
    env["app"].config.update(MAX_CLASSES_PER_SANDBOX=2, MAX_PROPERTIES_PER_SANDBOX=1)
    box_id = _user_sandbox(env)
    client = env["app"].test_client()
    _login(client, env["user_id"])
    for i in range(2):
        assert client.post(f"/api/sandbox/{box_id}/classes", json={"name": f"C{i}"}).status_code == 200
    resp = client.post(f"/api/sandbox/{box_id}/classes", json={"name": "C3"})
    assert resp.status_code == 409
    assert "at most 2 classes" in resp.get_json()["error"]

    prop = {"name": "p", "property_type": "object"}
    assert client.post(f"/api/sandbox/{box_id}/properties", json=prop).status_code == 200
    resp = client.post(f"/api/sandbox/{box_id}/properties", json=prop)
    assert resp.status_code == 409
    assert "at most 1 properties" in resp.get_json()["error"]


def _anon_file_with_classes(env, client, class_names):
    from models import db, OntologyFile, OntologyAnalysis
    from tests.conftest import grant_anon_files
    with env["app"].app_context():
        f = OntologyFile(filename=f"{uuid.uuid4().hex}.owl", original_filename="big.owl",
                         file_path="/nonexistent/big.owl", file_size=1)
        db.session.add(f)
        db.session.flush()
        db.session.add(OntologyAnalysis(ontology_file_id=f.id, ontology_name="Big",
                                        class_list=class_names))
        db.session.commit()
        file_id = f.id
    grant_anon_files(client, file_id)
    return file_id


def test_import_rejects_oversized_ontology(env):
    env["app"].config["MAX_CLASSES_PER_SANDBOX"] = 3
    client = env["app"].test_client()
    file_id = _anon_file_with_classes(env, client, [f"C{i}" for i in range(5)])
    resp = client.post(f"/import_to_sandbox/{file_id}", follow_redirects=True)
    assert b"at most 3 classes" in resp.data
    with client.session_transaction() as sess:
        assert not sess.get("anon_sandbox_ids")


def test_import_creates_a_single_sandbox(env):
    from models import SandboxOntology, OntologyClass
    client = env["app"].test_client()
    file_id = _anon_file_with_classes(env, client, ["A", "B"])
    client.post(f"/import_to_sandbox/{file_id}")
    with client.session_transaction() as sess:
        ids = sess.get("anon_sandbox_ids", [])
    with env["app"].app_context():
        boxes = SandboxOntology.query.filter(SandboxOntology.id.in_(ids)).all()
        assert len(boxes) == 1
        assert OntologyClass.query.filter_by(ontology_id=boxes[0].id).count() == 2
