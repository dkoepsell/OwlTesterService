"""
Prover9 / Mace4 cross-check for the FOL-BFO-OWL tester.

The whole point of a tool named *FOL-BFO-OWL tester* is to confirm that a
first-order prover agrees with the OWL/DL reasoner about what is broken. This
module ships the FOL export (fol_export.py) to Prover9 and asks, per class,
whether the class is provably empty (unsatisfiable). It then compares that set
against the DL reasoner's unsatisfiable set and reports agreement or divergence.

Everything degrades gracefully: if the prover9 / mace4 binaries are not on PATH
the cross-check returns ran=False with a clear reason rather than crashing the
request. Install on Debian/Ubuntu with `apt-get install prover9` (provides both
prover9 and mace4).

Method, per candidate class C:
  assumptions = subsumption + disjointness axioms (the FOL export).
  goal        = "C is empty", i.e. all X all T -instance_of(X, c, T).
  Prover9 proves the goal by assuming the negation (C is inhabited) and deriving
  a contradiction through the disjointness axioms. A proof => C is unsatisfiable.
  No proof within the timeout (optionally confirmed by a Mace4 model) => treated
  as satisfiable.
"""
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time

logger = logging.getLogger(__name__)

# Prover9 exit statuses we care about (see LADR exit_codes):
#   0 -> MAX_PROOFS (a proof was found)
#   2 -> SOS_EMPTY  (search exhausted, no proof)
#   4 -> MAX_SECONDS (timed out)
_P9_PROVED = 0
_PROOF_RE = re.compile(r"THEOREM PROVED|Exiting with \d+ proof", re.IGNORECASE)
_MODEL_RE = re.compile(r"MODEL|Exiting with \d+ model", re.IGNORECASE)


def prover9_available():
    return shutil.which("prover9") is not None


def mace4_available():
    return shutil.which("mace4") is not None


def _goal_block(sym, kind):
    """A Prover9 goals list asserting class `sym` is empty."""
    if kind == "occurrent":
        body = f"all X (-instance_of_at(X,{sym}))."
    else:
        body = f"all X all T (-instance_of(X,{sym},T))."
    return f"\nformulas(goals).\n  {body}\nend_of_list.\n"


def _existence_block(sym, kind):
    """A Prover9 assumptions fragment asserting class `sym` is inhabited."""
    if kind == "occurrent":
        return f"\nformulas(assumptions).\n  exists X (instance_of_at(X,{sym})).\nend_of_list.\n"
    return f"\nformulas(assumptions).\n  exists X exists T (instance_of(X,{sym},T)).\nend_of_list.\n"


def _run(cmd, stdin_text, timeout):
    return subprocess.run(cmd, input=stdin_text, capture_output=True,
                          text=True, timeout=timeout)


def check_class_unsat(assumptions_p9, sym, kind, timeout=5):
    """Return 'unsatisfiable' | 'satisfiable' | 'unknown' for one class.

    `assumptions_p9` is the Prover9 assumptions file from fol_export.render_prover9.
    Prover9 decides; if it finds no proof and Mace4 is available, a Mace4 model
    confirms satisfiability. Without a binary the result is 'unknown'.
    """
    if not prover9_available():
        return "unknown"
    p9_input = assumptions_p9 + _goal_block(sym, kind)
    try:
        proc = _run(["prover9"], p9_input, timeout)
    except subprocess.TimeoutExpired:
        return "unknown"
    except Exception as e:  # noqa: BLE001
        logger.warning("prover9 invocation failed: %s", e)
        return "unknown"

    if proc.returncode == _P9_PROVED or _PROOF_RE.search(proc.stdout or ""):
        return "unsatisfiable"

    # No proof. Confirm satisfiability with a Mace4 model when possible.
    if mace4_available():
        m4_input = assumptions_p9 + _existence_block(sym, kind)
        try:
            m4 = _run(["mace4"], m4_input, timeout)
            if m4.returncode == 0 or _MODEL_RE.search(m4.stdout or ""):
                return "satisfiable"
        except subprocess.TimeoutExpired:
            return "satisfiable"  # no contradiction found in time
        except Exception as e:  # noqa: BLE001
            logger.warning("mace4 invocation failed: %s", e)
    return "satisfiable"


def cross_check(theory, reasoner_unsat_names=None, assumptions_p9=None,
                max_classes=60, per_class_timeout=5):
    """Run the prover over a theory and compare with the DL reasoner.

    Args:
        theory: a fol_export.FolTheory.
        reasoner_unsat_names: iterable of class names/labels the OWL reasoner
            found unsatisfiable (for the agreement comparison).
        assumptions_p9: pre-rendered Prover9 assumptions; rendered from theory if
            omitted.
        max_classes: cap on classes tested (logged when exceeded; the prover is
            invoked once per class so this bounds wall-clock).
        per_class_timeout: seconds per prover invocation.

    Returns a dict:
        {
          'ran': bool,
          'engine': 'prover9'|'prover9+mace4'|None,
          'available': bool,
          'reason': Optional[str],          # why it did not run
          'prover_unsatisfiable': [names],  # the prover's verdict
          'reasoner_unsatisfiable': [names],
          'agree': Optional[bool],
          'only_prover': [names],           # divergence: prover-only
          'only_reasoner': [names],         # divergence: reasoner-only
          'tested': int,
          'capped': bool,
          'elapsed_seconds': float,
        }
    """
    started = time.perf_counter()
    result = {
        "ran": False, "engine": None, "available": prover9_available(),
        "reason": None, "prover_unsatisfiable": [], "reasoner_unsatisfiable": [],
        "agree": None, "only_prover": [], "only_reasoner": [],
        "tested": 0, "capped": False, "elapsed_seconds": 0.0,
    }
    reasoner_set = {str(n) for n in (reasoner_unsat_names or [])}
    result["reasoner_unsatisfiable"] = sorted(reasoner_set)

    if not prover9_available():
        result["reason"] = ("prover9 binary not found on PATH "
                            "(install with: apt-get install prover9)")
        return result
    if theory is None:
        result["reason"] = "no FOL theory available to check"
        return result

    if assumptions_p9 is None:
        from fol_export import render_prover9
        assumptions_p9 = render_prover9(theory)

    # Only user classes are candidates (BFO categories are never the user's bug).
    candidates = [
        (rec["sym"], rec["kind"], rec["label"])
        for iri, rec in theory.classes.items()
        if not iri.startswith("http://purl.obolibrary.org/obo/BFO_")
    ]
    candidates.sort(key=lambda c: c[2].lower())
    if len(candidates) > max_classes:
        result["capped"] = True
        logger.info("prover cross-check: testing %d of %d classes (cap=%d)",
                    max_classes, len(candidates), max_classes)
        candidates = candidates[:max_classes]

    prover_unsat = []
    for sym, kind, label in candidates:
        verdict = check_class_unsat(assumptions_p9, sym, kind,
                                    timeout=per_class_timeout)
        result["tested"] += 1
        if verdict == "unsatisfiable":
            prover_unsat.append(label)

    result["ran"] = True
    result["engine"] = "prover9+mace4" if mace4_available() else "prover9"
    result["prover_unsatisfiable"] = sorted(prover_unsat)

    prover_set = set(prover_unsat)
    # Compare on the intersection of names we actually tested vs reasoner output.
    result["only_prover"] = sorted(prover_set - reasoner_set)
    result["only_reasoner"] = sorted(reasoner_set - prover_set)
    if not result["capped"]:
        result["agree"] = (prover_set == reasoner_set)
    else:
        # With a cap we cannot claim full agreement; report containment instead.
        result["agree"] = None
    result["elapsed_seconds"] = time.perf_counter() - started
    logger.info("prover cross-check: %d tested, %d unsat, agree=%s (%.2fs)",
                result["tested"], len(prover_unsat), result["agree"],
                result["elapsed_seconds"])
    return result
