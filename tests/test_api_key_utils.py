"""Tests for Bring-Your-Own-Key resolution (api_key_utils)."""

import api_key_utils


def test_explicit_key_wins(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert api_key_utils.resolve_openai_key("sk-explicit") == "sk-explicit"


def test_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("SERVER_AI_KEY_FOR", "all")
    assert api_key_utils.resolve_openai_key() == "sk-env"


def test_server_key_withheld_outside_a_power_user_request(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.delenv("SERVER_AI_KEY_FOR", raising=False)
    assert api_key_utils.resolve_openai_key() is None


def test_none_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert api_key_utils.resolve_openai_key() is None
    assert api_key_utils.has_openai_key() is False
    assert api_key_utils.key_source() == "none"


def test_session_key_preferred_over_env(monkeypatch):
    """Inside a Flask request context, a session key beats the server env key."""
    from flask import Flask
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    app = Flask(__name__)
    app.secret_key = "t"
    with app.test_request_context("/"):
        from flask import session
        session[api_key_utils.SESSION_KEY] = "sk-session"
        assert api_key_utils.resolve_openai_key() == "sk-session"
        assert api_key_utils.key_source() == "session"
