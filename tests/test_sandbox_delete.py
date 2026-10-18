"""Owners can delete their sandbox ontologies and the items in them; no one else can."""

import uuid

import pytest


@pytest.fixture()
def env():
    import app as app_module
    from models import (db, User, OntologyFile, SandboxOntology, OntologyClass,
                        OntologyProperty, OntologyIndividual)

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.app_context():
        db.create_all()
        tag = uuid.uuid4().hex[:8]

        def make_user(name):
            user = User(username=f"{name}-{tag}", email=f"{name}-{tag}@example.org")
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()
            return user.id

        alice, bob = make_user("alice"), make_user("bob")
        sb = SandboxOntology(title=f"alice sandbox {tag}", domain="d", subject="s", user_id=alice)
        db.session.add(sb)
        db.session.commit()

        parent = OntologyClass(ontology_id=sb.id, name="Parent")
        db.session.add(parent)
        db.session.commit()
        child = OntologyClass(ontology_id=sb.id, name="Child", parent_id=parent.id)
        other = OntologyClass(ontology_id=sb.id, name="Other")
        db.session.add_all([child, other])
        db.session.commit()
        grandchild = OntologyClass(ontology_id=sb.id, name="Grandchild", parent_id=child.id)
        db.session.add(grandchild)
        db.session.commit()

        prop = OntologyProperty(ontology_id=sb.id, name="relatesTo", property_type="object",
                                domain_class_id=child.id, range_class_id=other.id)
        dprop = OntologyProperty(ontology_id=sb.id, name="hasLabel", property_type="data",
                                 domain_class_id=other.id)
        db.session.add_all([prop, dprop])
        db.session.commit()
        ind_child = OntologyIndividual(ontology_id=sb.id, name="c1", class_id=grandchild.id)
        ind_other = OntologyIndividual(ontology_id=sb.id, name="o1", class_id=other.id,
                                       property_values={str(dprop.id): "x"})
        db.session.add_all([ind_child, ind_other])

        exported = OntologyFile(filename=f"{uuid.uuid4().hex}.owl", original_filename="exp.owl",
                                file_path="/nonexistent/exp.owl", file_size=1,
                                mime_type="application/rdf+xml", user_id=alice,
                                sandbox_ontology_id=sb.id)
        db.session.add(exported)
        db.session.commit()

        data = {
            "app": flask_app, "alice": alice, "bob": bob, "sandbox": sb.id,
            "parent": parent.id, "child": child.id, "grandchild": grandchild.id,
            "other": other.id, "prop": prop.id, "dprop": dprop.id,
            "ind_child": ind_child.id, "ind_other": ind_other.id, "exported": exported.id,
        }
        db.session.remove()
    yield data


def _client_as(env, user_key):
    client = env["app"].test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(env[user_key])
        sess["_fresh"] = True
    return client


def _get(env, model_name, obj_id):
    import models
    with env["app"].app_context():
        obj = models.db.session.get(getattr(models, model_name), obj_id)
        result = None if obj is None else {c.name: getattr(obj, c.name)
                                           for c in obj.__table__.columns}
        models.db.session.remove()
        return result


def test_owner_can_delete_sandbox(env):
    client = _client_as(env, "alice")
    resp = client.post(f"/sandbox/{env['sandbox']}/delete")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/sandbox")

    assert _get(env, "SandboxOntology", env["sandbox"]) is None
    for key in ("parent", "child", "grandchild", "other"):
        assert _get(env, "OntologyClass", env[key]) is None, key
    for key in ("prop", "dprop"):
        assert _get(env, "OntologyProperty", env[key]) is None, key
    for key in ("ind_child", "ind_other"):
        assert _get(env, "OntologyIndividual", env[key]) is None, key

    exported = _get(env, "OntologyFile", env["exported"])
    assert exported is not None
    assert exported["sandbox_ontology_id"] is None
    assert client.get(f"/sandbox/{env['sandbox']}").status_code == 404


def test_non_owner_cannot_delete_sandbox(env):
    client = _client_as(env, "bob")
    assert client.post(f"/sandbox/{env['sandbox']}/delete").status_code == 404
    assert _get(env, "SandboxOntology", env["sandbox"]) is not None
    assert _get(env, "OntologyClass", env["parent"]) is not None
    assert _get(env, "OntologyFile", env["exported"])["sandbox_ontology_id"] == env["sandbox"]

    anon = env["app"].test_client()
    assert anon.post(f"/sandbox/{env['sandbox']}/delete").status_code == 404
    assert _get(env, "SandboxOntology", env["sandbox"]) is not None


def test_owner_deletes_class_with_subclasses(env):
    client = _client_as(env, "alice")
    resp = client.delete(f"/api/sandbox/{env['sandbox']}/classes/{env['child']}")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert sorted(resp.get_json()["deleted_class_ids"]) == sorted([env["child"], env["grandchild"]])

    assert _get(env, "OntologyClass", env["child"]) is None
    assert _get(env, "OntologyClass", env["grandchild"]) is None
    assert _get(env, "OntologyIndividual", env["ind_child"]) is None
    # Unrelated classes and individuals are untouched
    assert _get(env, "OntologyClass", env["parent"]) is not None
    assert _get(env, "OntologyClass", env["other"]) is not None
    assert _get(env, "OntologyIndividual", env["ind_other"]) is not None
    # The property survives with its domain cleared but range intact
    prop = _get(env, "OntologyProperty", env["prop"])
    assert prop["domain_class_id"] is None and prop["range_class_id"] == env["other"]


def test_owner_deletes_class_used_as_range(env):
    client = _client_as(env, "alice")
    resp = client.delete(f"/api/sandbox/{env['sandbox']}/classes/{env['other']}")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert _get(env, "OntologyProperty", env["prop"])["range_class_id"] is None
    assert _get(env, "OntologyProperty", env["dprop"])["domain_class_id"] is None
    assert _get(env, "OntologyIndividual", env["ind_other"]) is None


def test_owner_deletes_property(env):
    client = _client_as(env, "alice")
    resp = client.delete(f"/api/sandbox/{env['sandbox']}/properties/{env['dprop']}")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert _get(env, "OntologyProperty", env["dprop"]) is None
    assert _get(env, "OntologyIndividual", env["ind_other"])["property_values"] == {}


def test_non_owner_cannot_delete_class_or_property(env):
    client = _client_as(env, "bob")
    sid = env["sandbox"]
    assert client.delete(f"/api/sandbox/{sid}/classes/{env['parent']}").status_code == 404
    assert client.delete(f"/api/sandbox/{sid}/properties/{env['prop']}").status_code == 404
    assert _get(env, "OntologyClass", env["parent"]) is not None
    assert _get(env, "OntologyProperty", env["prop"]) is not None

    anon = env["app"].test_client()
    assert anon.delete(f"/api/sandbox/{sid}/classes/{env['parent']}").status_code == 404
    assert anon.delete(f"/api/sandbox/{sid}/properties/{env['prop']}").status_code == 404


def test_delete_button_shown_to_owner(env):
    client = _client_as(env, "alice")
    for url in ("/sandbox", f"/sandbox/{env['sandbox']}"):
        html = client.get(url).get_data(as_text=True)
        assert f"/sandbox/{env['sandbox']}/delete" in html, url
