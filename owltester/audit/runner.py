"""Run a full artifact audit: R0, then R1..R10, then cross-stage links."""

import datetime
import logging
import os
import subprocess
import traceback

from .. import errors
from ..model import AuditReport
from . import (alignment, data_profile, docs, hygiene, layers, lenses, reasoning, references,
               schema_checks, shacl_check)
from .artifact import load_artifact
from .context import AuditContext, Budget
from .profiles import get_profile

logger = logging.getLogger(__name__)

STAGES = (
    ("R1", "Parse and inventory", schema_checks.run_r1),
    ("R2", "OWL 2 profile", schema_checks.run_r2),
    ("R2b", "Design lint", schema_checks.run_r2b),
    ("R3", "Reasoning", reasoning.run_r3),
    ("R4", "SHACL with the artifact's own shapes", shacl_check.run_r4),
    ("R5", "Reference integrity", references.run_r5),
    ("R6", "Constraint layers: OWL, SHACL, documentation", layers.run_r6),
    ("R7", "Documentation integrity and self-examples", docs.run_r7),
    ("R8", "Data profile", data_profile.run_r8),
    ("R9", "BFO alignment", alignment.run_r9),
    ("R10", "Release hygiene", hygiene.run_r10),
)


def tool_version():
    v = os.environ.get("OWLTESTER_VERSION")
    if v:
        return v
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=here,
                             capture_output=True, text=True, timeout=5, check=False)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def run_r0(ctx):
    art = ctx.artifact
    for f in art.rdf_files():
        if f.error:
            ctx.add("R0", errors.E_PARSE, "info" if f.error.startswith("not parsed") else "major",
                    f"{f.path} could not be parsed", f.error, files=[f.path],
                    fix="Fix the syntax error; the rest of the audit skipped this file.")
    if art.imports["unresolved"]:
        iris = sorted({i["iri"] for i in art.imports["unresolved"]})
        ctx.add("R0", errors.W_IMPORT, "info",
                f"{len(iris)} import(s) not available locally were removed before reasoning",
                "The audit never uses the network, so anything these imports add is not checked.",
                files=sorted({i["from"] for i in art.imports["unresolved"]}), count=len(iris),
                evidence={"imports": iris},
                fix="Ship the imported ontologies with the release, or list them in a catalog.")
    for lim in art.limits:
        ctx.limits_hit.append(lim)
    unknown = art.config.get("_unknown_keys") or []
    m = art.manifest()
    ctx.finish("R0", "Ingest and role detection", status="pass",
               summary=(f"{m['files_total']} files ({m['rdf_files']} RDF, {m['triples']:,} triples); "
                        + ", ".join(f"{len(v)} {k}" for k, v in sorted(m["roles"].items()))
                        + f"; {len(art.data_sets)} data sets"
                        + (f"; audit.yaml keys not understood: {', '.join(unknown)}" if unknown else "")),
               notes={})


def run_audit(source, profile="general", config_path=None, budget=None, max_explanations=None,
              explain=True, progress=None, lenses_enabled=True, artifact_name=None):
    """Audit ``source`` (zip, directory or list of files) and return an AuditReport."""
    prof = get_profile(profile)
    art = load_artifact(source, config_path=config_path, profile=prof)
    if art.config.get("profile") and profile == "general" and art.config["profile"] != "general":
        prof = get_profile(art.config["profile"])
    if artifact_name:
        art.name = artifact_name
    env_budget = os.environ.get("AUDIT_BUDGET")
    b = Budget(total=budget or art.config.get("budget") or (float(env_budget) if env_budget else None),
               max_explanations=max_explanations if max_explanations is not None
               else art.config.get("max_explanations"))
    ctx = AuditContext(art, prof, b, options={"explain": explain}, progress=progress)
    try:
        ctx.progress("R0")
        run_r0(ctx)
        # The report lists stages R0..R10; they run cheap first, so a budget that
        # runs out can only cut short the expensive stages (reasoning and SHACL),
        # never the quick ones. R3 needs R2's datatype patch, and R4 is linked to
        # R5 afterwards, so this order changes no result.
        expensive = ("R3", "R4")
        ordered = [s for s in STAGES if s[0] not in expensive] + \
            [s for s in STAGES if s[0] in expensive]
        for code, title, fn in ordered:
            if code not in prof["stages"]:
                ctx.skip(code, title, f"Not part of the '{prof['name']}' profile.")
                continue
            if ctx.budget.expired() and code not in ("R10",):
                ctx.skip(code, title, "The total time budget ran out before this stage.")
                ctx.limit(code, "total", "stage not run")
                continue
            ctx.progress(code)
            try:
                fn(ctx)
            except Exception as e:  # noqa: BLE001 - no stage halts the audit
                logger.error("audit stage %s failed: %s\n%s", code, e, traceback.format_exc())
                ctx.stages[code] = {"title": title, "status": "error",
                                    "summary": f"The stage stopped with an error: "
                                               f"{type(e).__name__}: {str(e)[:300]}", "notes": {}}
        shacl_check.link(ctx)
        lens_tables = lenses.run_lenses(ctx) if lenses_enabled else []
        report = AuditReport(
            artifact=art.name,
            audited_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            tool_version=tool_version(), profile=prof["name"], manifest=art.manifest(),
            stages=ctx.stages, findings=ctx.findings, patches=ctx.patches,
            limits_hit=ctx.limits_hit, lenses=lens_tables)
        report.stages.setdefault("R0", {})["notes"] = {"elapsed_seconds": round(ctx.budget.elapsed(), 1)}
        return report
    finally:
        art.cleanup()
