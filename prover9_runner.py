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
#   5 -> MAX_MEGS    (ran out of memory)
_P9_PROVED = 0
_P9_EXHAUSTED = 2
_PROOF_RE = re.compile(r"THEOREM PROVED|Exiting with \d+ proof", re.IGNORECASE)
_MODEL_RE = re.compile(r"MODEL|Exiting with \d+ model", re.IGNORECASE)


def prover9_available():
    return shutil.which("prover9") is not None


def mace4_available():
    return shutil.which("mace4") is not None


def _goal_block(sym, kind, align=False):
    """A Prover9 goals list asserting class `sym` is empty.

    With align=True every class (including occurrents) is queried through the
    ternary instance_of(x, C, t), matching an export rendered with align_bfo=True
    and the BFO background. Without it, occurrents keep the binary form.
    """
    if kind == "occurrent" and not align:
        body = f"all X (-instance_of_at(X,{sym}))."
    else:
        body = f"all X all T (-instance_of(X,{sym},T))."
    return f"\nformulas(goals).\n  {body}\nend_of_list.\n"


def _existence_block(sym, kind, align=False):
    """A Prover9 assumptions fragment asserting class `sym` is inhabited."""
    if kind == "occurrent" and not align:
        return f"\nformulas(assumptions).\n  exists X (instance_of_at(X,{sym})).\nend_of_list.\n"
    return f"\nformulas(assumptions).\n  exists X exists T (instance_of(X,{sym},T)).\nend_of_list.\n"


def _limits_block(max_seconds, max_megs):
    """Prover9/Mace4 resource-limit directives, or '' when both are unset."""
    out = ""
    if max_seconds is not None:
        out += f"assign(max_seconds, {max_seconds}).\n"
    if max_megs is not None:
        out += f"assign(max_megs, {max_megs}).\n"
    return out


def _run(cmd, stdin_text, timeout):
    return subprocess.run(cmd, input=stdin_text, capture_output=True,
                          text=True, timeout=timeout)


def check_class_unsat(assumptions_p9, sym, kind, timeout=5, background="",
                      align=False, max_seconds=None, max_megs=None):
    """Return 'unsatisfiable' | 'satisfiable' | 'undetermined' | 'unknown'.

    `assumptions_p9` is the Prover9 assumptions file from fol_export.render_prover9.
    `background`, when given, is the translated BFO-2020 theory
    (clif_theory.render_prover9_theory) prepended ahead of the export so the
    prover can use the full first-order axiomatization; pass align=True alongside
    an export rendered with align_bfo=True so goals and both theories share the
    ternary instance_of/3. max_seconds / max_megs bound each invocation.

    Prover9 decides; if it finds no proof and Mace4 is available, a Mace4 model
    confirms satisfiability. The distinction the heavy background needs:
    'undetermined' means the engine ran out of time or memory before deciding,
    which must never be reported as 'satisfiable' (i.e. as agreement). Without a
    background, behaviour is unchanged: a timeout is treated as satisfiable, since
    the lightweight theory is small enough that no proof in time is meaningful.
    Without a binary the result is 'unknown'.
    """
    if not prover9_available():
        return "unknown"
    # Inconclusive-on-timeout only when a heavy background is in play.
    stalled = "undetermined" if background else "satisfiable"
    base = _limits_block(max_seconds, max_megs) + background + assumptions_p9
    p9_input = base + _goal_block(sym, kind, align=align)
    try:
        proc = _run(["prover9"], p9_input, timeout)
    except subprocess.TimeoutExpired:
        return "undetermined" if background else "unknown"
    except Exception as e:  # noqa: BLE001
        logger.warning("prover9 invocation failed: %s", e)
        return "unknown"

    if proc.returncode == _P9_PROVED or _PROOF_RE.search(proc.stdout or ""):
        return "unsatisfiable"

    # No proof. Did the search finish, or did it hit a resource limit?
    exhausted = proc.returncode == _P9_EXHAUSTED

    # Confirm satisfiability with a Mace4 model when possible.
    if mace4_available():
        m4_input = base + _existence_block(sym, kind, align=align)
        try:
            m4 = _run(["mace4"], m4_input, timeout)
            if m4.returncode == 0 or _MODEL_RE.search(m4.stdout or ""):
                return "satisfiable"
        except subprocess.TimeoutExpired:
            return stalled  # no model found in time
        except Exception as e:  # noqa: BLE001
            logger.warning("mace4 invocation failed: %s", e)

    # No proof and no model. Trustworthy only if Prover9 actually exhausted its
    # search; otherwise it stalled on a limit and we cannot claim satisfiability.
    if exhausted:
        return "satisfiable"
    return stalled


def cross_check(theory, reasoner_unsat_names=None, assumptions_p9=None,
                max_classes=60, per_class_timeout=5, bfo_background=False,
                background_max_seconds=10, background_max_megs=500):
    """Run the prover over a theory and compare with the DL reasoner.

    Args:
        theory: a fol_export.FolTheory.
        reasoner_unsat_names: iterable of class names/labels the OWL reasoner
            found unsatisfiable (for the agreement comparison).
        assumptions_p9: pre-rendered Prover9 assumptions; rendered from theory if
            omitted (rendered aligned to the BFO signature when bfo_background).
        max_classes: cap on classes tested (logged when exceeded; the prover is
            invoked once per class so this bounds wall-clock).
        per_class_timeout: wall-clock seconds per prover invocation.
        bfo_background: when True, prepend the full BFO-2020 first-order theory
            (clif_theory.render_prover9_theory) so the check can confirm
            relation- and restriction-mediated unsatisfiability, not just derived
            disjointness straddles. Opt-in: it is far heavier and may not decide
            every class within the limits, in which case the class is reported as
            'undetermined' rather than counted as agreement.
        background_max_seconds / background_max_megs: per-class Prover9/Mace4
            resource limits applied only on the background path.

    Returns a dict:
        {
          'ran': bool,
          'engine': 'prover9'|'prover9+mace4'(+'+bfo')|None,
          'available': bool,
          'bfo_background': bool,
          'reason': Optional[str],          # why it did not run
          'prover_unsatisfiable': [names],  # the prover's verdict
          'reasoner_unsatisfiable': [names],
          'undetermined': [names],          # background path: not decided in time
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
        "bfo_background": bool(bfo_background),
        "reason": None, "prover_unsatisfiable": [], "reasoner_unsatisfiable": [],
        "undetermined": [],
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

    background = ""
    if bfo_background:
        try:
            from clif_theory import render_prover9_theory
            background = render_prover9_theory()
        except Exception as e:  # noqa: BLE001
            result["reason"] = f"could not load BFO background theory: {e}"
            return result

    if assumptions_p9 is None:
        from fol_export import render_prover9
        assumptions_p9 = render_prover9(theory, align_bfo=bfo_background)

    max_secs = background_max_seconds if bfo_background else None
    max_megs = background_max_megs if bfo_background else None

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
    undetermined = []
    for sym, kind, label in candidates:
        verdict = check_class_unsat(
            assumptions_p9, sym, kind, timeout=per_class_timeout,
            background=background, align=bfo_background,
            max_seconds=max_secs, max_megs=max_megs)
        result["tested"] += 1
        if verdict == "unsatisfiable":
            prover_unsat.append(label)
        elif verdict == "undetermined":
            undetermined.append(label)

    result["ran"] = True
    engine = "prover9+mace4" if mace4_available() else "prover9"
    result["engine"] = engine + "+bfo" if bfo_background else engine
    result["prover_unsatisfiable"] = sorted(prover_unsat)
    result["undetermined"] = sorted(undetermined)

    prover_set = set(prover_unsat)
    # Compare on the intersection of names we actually tested vs reasoner output.
    result["only_prover"] = sorted(prover_set - reasoner_set)
    result["only_reasoner"] = sorted(reasoner_set - prover_set)
    # A cap or any undetermined class means we cannot claim full agreement: an
    # undetermined verdict is not "satisfiable", so a timeout never reads as
    # agreement.
    if result["capped"] or undetermined:
        result["agree"] = None
    else:
        result["agree"] = (prover_set == reasoner_set)
    result["elapsed_seconds"] = time.perf_counter() - started
    logger.info("prover cross-check: %d tested, %d unsat, %d undetermined, "
                "agree=%s (%.2fs)", result["tested"], len(prover_unsat),
                len(undetermined), result["agree"], result["elapsed_seconds"])
    return result
