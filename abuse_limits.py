"""Abuse controls: real client IP, rate limits, and hard sandbox size caps.

Production sits behind a host-level nginx that proxies to the container, so
without ProxyFix every request's remote_addr is the docker gateway and an
IP-keyed limit would throttle all visitors as one. ``init_abuse_controls``
wires ProxyFix (trusting exactly one proxy hop) and Flask-Limiter onto the app.

Rate-limit storage comes from RATELIMIT_STORAGE_URI (default ``memory://``).
Memory storage is per gunicorn worker process, so with N workers the effective
limit is up to N times the configured one, and counters reset whenever a worker
recycles (max_requests). Point RATELIMIT_STORAGE_URI at redis:// or
memcached:// for exact, shared counting.

Set RATELIMIT_ENABLED=0 to turn limiting off (the test suite does). The flag is
read per request, so a test can flip ``app.config['RATELIMIT_ENABLED']``.

Power users (owltester/power.py) get POWER_FACTOR times the upload, analysis and
AI limits, and POWER_CAP_FACTOR times the per-account sandbox caps. Override with
POWER_UPLOAD_LIMIT / POWER_ANALYSIS_LIMIT / POWER_AI_LIMIT (limit strings) and
POWER_<cap name> (integers), in the app config or the environment.
"""

import os
import re

from flask import current_app, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix

# -- rate limits (per key: signed-in user id, else client IP) -----------------
SANDBOX_CREATE_LIMIT = "10 per hour;30 per day"     # /sandbox/new, import_to_sandbox
SANDBOX_WRITE_LIMIT = "120 per minute"              # class / property create
UPLOAD_LIMIT_FREE = "30 per hour"                   # /upload, gate check/repair, export
ANALYSIS_LIMIT_FREE = "60 per hour"                 # reanalyze, fix-and-reanalyze, prover
AI_LIMIT_FREE = "20 per hour;100 per day"           # anything that calls OpenAI/Anthropic
FOL_TEST_LIMIT = "30 per minute"                    # /api/test-expression
LOGIN_LIMIT = "10 per minute;50 per hour"           # POST /login
REGISTER_LIMIT = "5 per hour"                       # POST /register

# -- hard caps, independent of rate (overridable via env) ---------------------
DEFAULT_CAPS = {
    "MAX_SANDBOXES_PER_USER": 50,
    "MAX_SANDBOXES_PER_ANON_SESSION": 5,
    "MAX_CLASSES_PER_SANDBOX": 2000,
    "MAX_PROPERTIES_PER_SANDBOX": 1000,
}
POWER_FACTOR = 5          # rate limits
POWER_CAP_FACTOR = 4      # per-account sandbox caps
POWER_CAPS = ("MAX_SANDBOXES_PER_USER", "MAX_CLASSES_PER_SANDBOX", "MAX_PROPERTIES_PER_SANDBOX")


def _is_power_user():
    """Fails closed: any error (no request, no table) means not a power user."""
    try:
        from owltester.power import is_power_user
        return bool(is_power_user())
    except Exception:  # noqa: BLE001
        return False


def scale_limit(limit, factor):
    """"20 per hour;100 per day" * 5 -> "100 per hour;500 per day"."""
    return ";".join(re.sub(r"^\s*(\d+)", lambda m: str(int(m.group(1)) * factor), part)
                    for part in limit.split(";"))


def tiered(free, power_name):
    """A limit flask-limiter evaluates per request: ``free`` for most accounts, the
    power value (``power_name`` in config/env, else ``free`` * POWER_FACTOR) for
    power users. Counters are kept separately per limit value."""
    def limit():
        if not _is_power_user():
            return free
        try:
            override = current_app.config.get(power_name)
        except RuntimeError:  # no app context
            override = None
        return override or os.environ.get(power_name) or scale_limit(free, POWER_FACTOR)
    limit.free = free
    return limit


UPLOAD_LIMIT = tiered(UPLOAD_LIMIT_FREE, "POWER_UPLOAD_LIMIT")
ANALYSIS_LIMIT = tiered(ANALYSIS_LIMIT_FREE, "POWER_ANALYSIS_LIMIT")
AI_LIMIT = tiered(AI_LIMIT_FREE, "POWER_AI_LIMIT")


def _env_flag(name, default=True):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off", "")


def rate_limit_key():
    """Signed-in users are limited per account; everyone else per client IP."""
    try:
        if current_user.is_authenticated:
            return f"user:{current_user.get_id()}"
    except Exception:  # noqa: BLE001 - no login manager / no request user
        pass
    return f"ip:{get_remote_address()}"


limiter = Limiter(key_func=rate_limit_key, headers_enabled=True)


@limiter.request_filter
def _limiting_disabled():
    return not current_app.config.get("RATELIMIT_ENABLED", True)


def _wants_json():
    if request.path.startswith("/api/") or request.is_json:
        return True
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json"


def _too_many_requests(e):
    limit = getattr(e, "description", "") or "too many requests"
    message = (f"Rate limit exceeded ({limit}). Please wait a while before "
               "trying again.")
    if _wants_json():
        return jsonify({"error": message}), 429
    return render_template("index.html", error=message), 429


class SandboxCapError(ValueError):
    """A sandbox hard cap (count or size) would be exceeded."""


def cap(name):
    base = int(current_app.config.get(name, DEFAULT_CAPS[name]))
    if name in POWER_CAPS and _is_power_user():
        return int(current_app.config.get("POWER_" + name) or base * POWER_CAP_FACTOR)
    return base


def check_sandbox_count_cap():
    """Raise SandboxCapError if the visitor may not create another sandbox.

    Signed-in users are capped per account. Anonymous visitors are capped per
    browser session (the ids ownership.py records in the session cookie); a
    client that drops cookies gets a fresh session each time, so for scripts
    the per-IP rate limit is the real backstop.
    """
    from ownership import owned_sandboxes_query
    count = owned_sandboxes_query().count()
    if current_user.is_authenticated:
        limit = cap("MAX_SANDBOXES_PER_USER")
        if count >= limit:
            raise SandboxCapError(
                f"You already have {count} sandbox ontologies (limit {limit}). "
                "Delete some before creating more.")
    else:
        limit = cap("MAX_SANDBOXES_PER_ANON_SESSION")
        if count >= limit:
            raise SandboxCapError(
                f"Anonymous visitors can keep at most {limit} sandbox ontologies. "
                "Log in or register to create more, or delete one first.")


def check_sandbox_size_cap(ontology_id, add_classes=0, add_properties=0):
    """Raise SandboxCapError if adding items would exceed the per-sandbox caps."""
    from models import OntologyClass, OntologyProperty
    if add_classes:
        limit = cap("MAX_CLASSES_PER_SANDBOX")
        have = OntologyClass.query.filter_by(ontology_id=ontology_id).count() if ontology_id else 0
        if have + add_classes > limit:
            raise SandboxCapError(
                f"A sandbox ontology can hold at most {limit} classes "
                f"(it has {have}; this would add {add_classes}).")
    if add_properties:
        limit = cap("MAX_PROPERTIES_PER_SANDBOX")
        have = OntologyProperty.query.filter_by(ontology_id=ontology_id).count() if ontology_id else 0
        if have + add_properties > limit:
            raise SandboxCapError(
                f"A sandbox ontology can hold at most {limit} properties "
                f"(it has {have}; this would add {add_properties}).")


def init_abuse_controls(app):
    """Install ProxyFix, Flask-Limiter, the 429 handler and the cap config."""
    if not getattr(app.wsgi_app, "_owltester_proxyfix", False):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.wsgi_app._owltester_proxyfix = True

    app.config.setdefault("RATELIMIT_STORAGE_URI",
                          os.environ.get("RATELIMIT_STORAGE_URI", "memory://"))
    app.config.setdefault("RATELIMIT_HEADERS_ENABLED", True)
    # If the shared store (redis) is unreachable, fail open to per-process
    # memory counters rather than erroring every limited request.
    app.config.setdefault("RATELIMIT_SWALLOW_ERRORS", True)
    app.config.setdefault("RATELIMIT_IN_MEMORY_FALLBACK_ENABLED", True)
    # Initialise the limiter enabled, then apply the env switch through the
    # per-request filter above, so tests can re-enable it at runtime.
    app.config["RATELIMIT_ENABLED"] = True
    limiter.init_app(app)
    app.config["RATELIMIT_ENABLED"] = _env_flag("RATELIMIT_ENABLED", True)

    for name, default in DEFAULT_CAPS.items():
        app.config.setdefault(name, int(os.environ.get(name, default)))
    for name in POWER_CAPS:
        if os.environ.get("POWER_" + name):
            app.config.setdefault("POWER_" + name, int(os.environ["POWER_" + name]))

    app.register_error_handler(429, _too_many_requests)


def limit_endpoint(app, endpoint, limit_value, **kwargs):
    """Apply a limit to an already-registered view (e.g. a blueprint's)."""
    view = app.view_functions.get(endpoint)
    if view is not None:
        app.view_functions[endpoint] = limiter.limit(limit_value, **kwargs)(view)
