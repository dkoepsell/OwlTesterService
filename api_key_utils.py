"""
Resolve AI API keys for AI features (implication generation, suggestions).

Two providers are supported: OpenAI and Anthropic (Claude). Keys are resolved in
this priority order:
  1. An explicit key passed by the caller.
  2. A user-supplied key stored in the Flask session (Bring Your Own Key). This
     lets the app run without a server-side key: each user pastes their own,
     which lives only in their session cookie's server-side store and is never
     written to the database. Each provider has its own session slot, and the
     user's selected provider is recorded so resolution is unambiguous.
  3. The server's OPENAI_API_KEY / ANTHROPIC_API_KEY environment variables.

Keeping this in one place means openai_utils, improved_openai_utils, and the web
layer all make the same decision. Implication generation is provider-aware via
resolve_ai(); the OpenAI-only suggestion features keep using resolve_openai_key().
"""
import os

# Per-provider session slots (Bring Your Own Key) and the user's chosen provider.
SESSION_KEY = "openai_api_key"            # kept as-is for backward compatibility
ANTHROPIC_SESSION_KEY = "anthropic_api_key"
PROVIDER_SESSION_KEY = "ai_provider"      # "openai" | "anthropic"

VALID_PROVIDERS = ("openai", "anthropic")


def _session():
    """The Flask session if we're in a request context, else None."""
    try:
        from flask import session, has_request_context
        if has_request_context():
            return session
    except Exception:
        # Not in a Flask context (e.g. a script or worker).
        pass
    return None


def resolve_openai_key(explicit=None):
    """Return the OpenAI key to use, or None. Used by OpenAI-only features."""
    if explicit:
        return explicit
    s = _session()
    if s and s.get(SESSION_KEY):
        return s.get(SESSION_KEY)
    return os.environ.get("OPENAI_API_KEY")


def resolve_anthropic_key(explicit=None):
    """Return the Anthropic key to use, or None."""
    if explicit:
        return explicit
    s = _session()
    if s and s.get(ANTHROPIC_SESSION_KEY):
        return s.get(ANTHROPIC_SESSION_KEY)
    return os.environ.get("ANTHROPIC_API_KEY")


def resolve_ai(explicit_key=None, explicit_provider=None):
    """Return (provider, key) for AI features, or (None, None) if unconfigured.

    Provider is 'openai' or 'anthropic'. Priority:
      1. An explicit key (+ provider) passed by the caller.
      2. A BYO session key, honoring the provider the user selected; if no
         provider was selected (or its key is missing), whichever session key
         is present.
      3. The server env keys: OPENAI_API_KEY first (to preserve the prior
         default behavior), then ANTHROPIC_API_KEY.
    """
    if explicit_key:
        return (explicit_provider or "openai", explicit_key)
    s = _session()
    if s:
        chosen = s.get(PROVIDER_SESSION_KEY)
        openai_key = s.get(SESSION_KEY)
        anthropic_key = s.get(ANTHROPIC_SESSION_KEY)
        if chosen == "anthropic" and anthropic_key:
            return ("anthropic", anthropic_key)
        if chosen == "openai" and openai_key:
            return ("openai", openai_key)
        if anthropic_key:
            return ("anthropic", anthropic_key)
        if openai_key:
            return ("openai", openai_key)
    if os.environ.get("OPENAI_API_KEY"):
        return ("openai", os.environ["OPENAI_API_KEY"])
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ("anthropic", os.environ["ANTHROPIC_API_KEY"])
    return (None, None)


def has_openai_key():
    """True if any OpenAI key (session or server) is available."""
    return bool(resolve_openai_key())


def key_source():
    """Where the active OpenAI key comes from: 'session', 'server', or 'none'."""
    s = _session()
    if s and s.get(SESSION_KEY):
        return "session"
    return "server" if os.environ.get("OPENAI_API_KEY") else "none"


def has_ai_key():
    """True if any AI key (either provider, session or server) is available."""
    return resolve_ai()[0] is not None


def ai_key_source():
    """Where the active AI key comes from: 'session', 'server', or 'none'."""
    s = _session()
    if s and (s.get(SESSION_KEY) or s.get(ANTHROPIC_SESSION_KEY)):
        return "session"
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
        return "server"
    return "none"


def active_provider():
    """The provider resolve_ai() would use right now, or None if unconfigured."""
    return resolve_ai()[0]
