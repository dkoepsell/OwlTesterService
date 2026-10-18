"""
Coverage Coherence Checker — the live demo blueprint (SPEC-coverage-coherence-demo.md).

Serves /coverage, a single self-contained demo page, plus the JSON API that runs
the coherence check for a fixture. Fixtures live in fixtures/coverage/ as JSON:
policy clauses, clause-labeled Prover9 axioms, a mock baseline score, and a
precomputed verdict cache used whenever the live prover path is unavailable or
slow (the demo must not die on stage).

Verdict logic per fixture, over the carveback-restored class R:
  Prover9 proves "R is empty"  -> INCOHERENT; the proof's used assumption labels
                                  map back to clause ids = the contradiction core.
  Prover9 exhausts, Mace4 model -> COHERENT; the fixture's witness sentence renders
                                  the "a claim scenario exists" side.
Anything else falls back to the checked-in verdict cache (itself prover-produced).

No DB, no login, no OpenAI. The page never shows the mechanism (axioms, prover
names) except under ?debug=1, which is presenter-only.
"""
import json
import logging
import re
import time
from pathlib import Path

from flask import Blueprint, abort, jsonify, render_template, request

from prover9_runner import find_model, prove_goal, prover9_available

logger = logging.getLogger(__name__)

coverage_bp = Blueprint("coverage_demo", __name__)

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "coverage"
_FIXTURE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PROVER_TIMEOUT = 3  # seconds per engine; theories are ~4 axioms

# The taxonomy strip (panel 3). Names are the product; one line each, no method.
FAILURE_PATTERNS = [
    {"key": "illusory-carveback",
     "name": "Illusory carveback",
     "line": "cyber",
     "shown_live": True,
     "blurb": "The carveback's condition contradicts the exclusion it modifies; "
              "it restores nothing.",
     "example": "An endorsement gives back coverage only for claims the exclusion "
                "never touched in the first place."},
    {"key": "definitional-gutting",
     "name": "Definitional gutting",
     "line": "crime",
     "shown_live": True,
     "blurb": "A defined term is narrowed until the grant that uses it can no "
              "longer pay the scenarios it advertises.",
     "example": "“Computer Fraud” defined so tightly that the social-"
                "engineering scenarios the insuring clause names fall outside it."},
    {"key": "same-term-two-meanings",
     "name": "Same term, two meanings",
     "line": "management liability",
     "shown_live": False,
     "blurb": "One term used with incompatible senses in two clauses; which sense "
              "applies decides the claim.",
     "example": "“Claim” includes regulatory investigations in the grant "
                "but not in the notice condition that preserves coverage."},
    {"key": "follow-form-contradiction",
     "name": "Follow-form contradiction",
     "line": "excess",
     "shown_live": False,
     "blurb": "An excess or follow-form layer incorporates underlying terms that "
              "contradict its own endorsements.",
     "example": "The excess layer follows form to an underlying exclusion its own "
                "endorsement purports to delete."},
]


# -- fixtures ------------------------------------------------------------------

def _fixture_path(fixture_id):
    if not _FIXTURE_ID_RE.match(fixture_id or ""):
        return None
    path = _FIXTURES_DIR / f"{fixture_id}.json"
    return path if path.is_file() else None

def load_fixture(fixture_id):
    path = _fixture_path(fixture_id)
    if path is None:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def list_fixtures():
    out = []
    for path in sorted(_FIXTURES_DIR.glob("*.json")):
        if path.name.endswith(".verdict.json") or path.stem == "portfolio_mock":
            continue
        try:
            fix = json.loads(path.read_text(encoding="utf-8"))
            out.append({"id": fix["id"], "title": fix["title"],
                        "line_of_business": fix.get("line_of_business")})
        except Exception as e:  # noqa: BLE001
            logger.warning("skipping unreadable fixture %s: %s", path.name, e)
    return out


# -- the coherence pipeline ----------------------------------------------------

def build_assumptions(fixture):
    """The fixture's clause-labeled theory as a Prover9 assumptions block."""
    lines = ["set(prolog_style_variables).", "", "formulas(assumptions)."]
    for ax in fixture["axioms"]:
        lines.append(f"  {ax['formula']} # label({ax['label']}).")
    lines.append("end_of_list.")
    return "\n".join(lines) + "\n"

def _labels_to_clauses(fixture, labels):
    by_label = {ax["label"]: ax["clause_id"] for ax in fixture["axioms"]}
    clause_order = [c["id"] for c in fixture["clauses"]]
    ids = {by_label[l] for l in labels if l in by_label}
    return [c for c in clause_order if c in ids]

def run_check(fixture, timeout=_PROVER_TIMEOUT):
    """Live prover verdict for one fixture, or None if the engines can't decide.

    Prover9 first (terminates either way on these tiny theories); Mace4 only on
    the no-proof side, because Mace4 does not terminate on unsatisfiable input.
    """
    if not prover9_available():
        return None
    assumptions = build_assumptions(fixture)
    position = fixture["check"]["position"]

    started = time.monotonic()
    proof = prove_goal(assumptions, f"all X (-{position}(X)).", timeout=timeout)
    if proof["status"] == "proved":
        clauses = _labels_to_clauses(fixture, proof["used_labels"])
        n = len(clauses)
        debug = {"engine": "prover9", "elapsed_ms": int((time.monotonic() - started) * 1000),
                 "used_labels": proof["used_labels"], "proof_text": proof["proof_text"]}
        return {
            "fixture_id": fixture["id"],
            "coherent": False,
            "headline": f"No possible claim can satisfy these {n} clauses at once."
                        if n != 3 else
                        "No possible claim can satisfy these three clauses at once.",
            "checked_positions": [{
                "position": position,
                "label": fixture["check"]["question"],
                "result": "empty",
                "contradicting_clauses": clauses,
            }],
            "plain_english_why": fixture["plain_english_why"],
            "scenario": None,
            "computed_live": True,
            "debug": debug,
        }

    if proof["status"] == "no_proof":
        existence = (assumptions +
                     f"\nformulas(assumptions).\n  exists X {position}(X)."
                     f"\nend_of_list.\n")
        model = find_model(existence, timeout=timeout)
        if model["found"]:
            return {
                "fixture_id": fixture["id"],
                "coherent": True,
                "headline": "A claim scenario exists in which this coverage pays.",
                "checked_positions": [{
                    "position": position,
                    "label": fixture["check"]["question"],
                    "result": "inhabited",
                    "contradicting_clauses": [],
                }],
                "plain_english_why": fixture["plain_english_why"],
                "scenario": fixture.get("witness_scenario"),
                "computed_live": True,
                "debug": {"engine": "prover9+mace4",
                          "elapsed_ms": int((time.monotonic() - started) * 1000)},
            }
    return None

def _load_cache(fixture):
    cache_name = fixture.get("verdict_cache") or f"{fixture['id']}.verdict.json"
    path = _FIXTURES_DIR / cache_name
    if not path.is_file():
        return None
    verdict = json.loads(path.read_text(encoding="utf-8"))
    verdict["computed_live"] = False
    return verdict

def check_with_fallback(fixture):
    try:
        verdict = run_check(fixture)
    except Exception as e:  # noqa: BLE001
        logger.warning("live coherence check failed for %s: %s", fixture["id"], e)
        verdict = None
    return verdict or _load_cache(fixture)


# -- routes ----------------------------------------------------------------------

def _load_portfolio():
    path = _FIXTURES_DIR / "portfolio_mock.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

def _public_view(fixture):
    """The fixture minus the mechanism (axioms, check target, canned verdicts).

    Everything embedded in the page is visible in view-source; the page must
    show clauses and scores only, so formalization details never ship with it.
    """
    keys = ("id", "title", "line_of_business", "baseline_score", "clauses", "edges")
    return {k: fixture[k] for k in keys if k in fixture}

# The two same-score snippets render first — they are the demo's opening beat.
_CENTERPIECE = ["cyber-sound", "cyber-illusory-carveback"]

@coverage_bp.route("/coverage")
def coverage_page():
    ids = _CENTERPIECE + sorted(f["id"] for f in list_fixtures()
                                if f["id"] not in _CENTERPIECE)
    fixtures = [_public_view(f) for f in (load_fixture(i) for i in ids) if f]
    return render_template(
        "coverage_demo.html",
        fixtures=fixtures,
        patterns=FAILURE_PATTERNS,
        portfolio=_load_portfolio(),
        debug=request.args.get("debug") == "1",
    )

@coverage_bp.route("/api/coverage/fixtures")
def coverage_fixtures():
    return jsonify({"fixtures": list_fixtures()})

@coverage_bp.route("/api/coverage/check/<fixture_id>", methods=["POST"])
def coverage_check(fixture_id):
    fixture = load_fixture(fixture_id)
    if fixture is None:
        abort(404)
    verdict = check_with_fallback(fixture)
    if verdict is None:
        return jsonify({"error": "coherence check unavailable"}), 503
    if request.args.get("debug") != "1":
        verdict = {k: v for k, v in verdict.items() if k != "debug"}
        verdict["checked_positions"] = [
            {k: v for k, v in cp.items() if k != "position"}
            for cp in verdict["checked_positions"]]
    return jsonify(verdict)


# -- verdict-cache precompute (fixture-authoring time, not runtime) ---------------

def precompute_caches():
    """Run the live pipeline for every fixture and write its verdict cache.

    The caches ARE prover-produced — they are the stage fallback, and serving
    them is still serving a reasoner verdict.
    """
    for entry in list_fixtures():
        fixture = load_fixture(entry["id"])
        verdict = run_check(fixture, timeout=10)
        if verdict is None:
            raise SystemExit(f"FAIL {entry['id']}: engines could not decide; "
                             "no cache written")
        cache_name = fixture.get("verdict_cache") or f"{fixture['id']}.verdict.json"
        cached = dict(verdict)
        cached.pop("computed_live", None)
        cached.pop("debug", None)
        (_FIXTURES_DIR / cache_name).write_text(
            json.dumps(cached, indent=2) + "\n", encoding="utf-8")
        core = verdict["checked_positions"][0]["contradicting_clauses"]
        print(f"OK {entry['id']}: coherent={verdict['coherent']}"
              f"{' core=' + ','.join(core) if core else ''} -> {cache_name}")


if __name__ == "__main__":
    precompute_caches()
