"""
Resolve the OpenAI API key for AI features (implication generation, suggestions).

Priority order:
  1. An explicit key passed by the caller.
  2. A user-supplied key stored in the Flask session (Bring Your Own Key). This
     lets the app run without a server-side key: each user pastes their own,
     which lives only in their session cookie's server-side store and is never
     written to the database.
  3. The server's OPENAI_API_KEY environment variable.

Keeping this in one place means both openai_utils and improved_openai_utils make
the same decision, and the web layer only has to set session['openai_api_key'].
"""
import os

SESSION_KEY = "openai_api_key"


def resolve_openai_key(explicit=None):
    """Return the API key to use, or None if none is configured anywhere."""
    if explicit:
        return explicit
    try:
        from flask import session, has_request_context
        if has_request_context():
            user_key = session.get(SESSION_KEY)
            if user_key:
                return user_key
    except Exception:
        # Not in a Flask context (e.g. a script or worker) -- fall through to env.
        pass
    return os.environ.get("OPENAI_API_KEY")


def has_openai_key():
    """True if any key (session or server) is available in the current context."""
    return bool(resolve_openai_key())


def key_source():
    """Where the active key comes from: 'session', 'server', or 'none'."""
    try:
        from flask import session, has_request_context
        if has_request_context() and session.get(SESSION_KEY):
            return "session"
    except Exception:
        pass
    return "server" if os.environ.get("OPENAI_API_KEY") else "none"
