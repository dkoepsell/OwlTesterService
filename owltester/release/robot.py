"""The ROBOT steps of a build (SPEC-release.md, section 9.3), offline.

The release files are made as the LOF Makefile makes them:

    <name>-base.owl  remove --select imports --trim false, annotate
    <name>.owl       merge (catalog), reason HermiT --equivalent-classes-allowed asserted-only, annotate
    <name>.ttl       convert; .ofn optional; .jsonld from the same graph (owltester.release.jsonld)

Every call has a timeout, and the catalog resolves every import, so ROBOT never
needs the network.
"""

import os
import subprocess
import time

from .tools import ToolError, require_robot

JAVA_OPTS = "-Xmx2g -Djava.awt.headless=true"


class RobotError(Exception):
    pass


class Budget:
    def __init__(self, seconds):
        self.deadline = time.monotonic() + seconds

    def left(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise RobotError("the build ran out of time (budget)")
        return left


def run(args, cwd, budget, log=None):
    cmd = require_robot() + list(args)
    env = dict(os.environ, ROBOT_JAVA_ARGS=os.environ.get("ROBOT_JAVA_ARGS", JAVA_OPTS))
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env,
                             timeout=budget.left(), check=False)
    except subprocess.TimeoutExpired as e:
        raise RobotError(f"ROBOT timed out: {' '.join(args[:2])}") from e
    except FileNotFoundError as e:
        raise ToolError(f"ROBOT could not start: {e}") from e
    if log is not None:
        log.append({"robot": list(args), "exit": out.returncode,
                    "stderr": (out.stderr or "")[-2000:]})
    if out.returncode != 0:
        msg = (out.stderr or out.stdout or "").strip().splitlines()
        raise RobotError(f"ROBOT {args[0]} failed: {' '.join(msg[-6:])[:1500]}")
    return out.stdout


def annotate_args(ontology_iri, version_iri, version):
    return ["annotate", "--ontology-iri", ontology_iri, "--version-iri", version_iri,
            "--annotation", "owl:versionInfo", version]


def build_base(edit, catalog, out, a, budget, log):
    from .answers import base_iri, version_iri
    run(["remove", "--input", edit, "--select", "imports", "--trim", "false"]
        + annotate_args(base_iri(a), version_iri(a, f"{a['name']}-base.owl"), a["version"])
        + ["--output", out], os.path.dirname(edit), budget, log)


def build_full(edit, catalog, out, a, budget, log):
    from .answers import version_iri
    run(["merge", "--catalog", catalog, "--input", edit,
         "reason", "--reasoner", "HermiT", "--equivalent-classes-allowed", "asserted-only"]
        + annotate_args(a["ontology_iri"], version_iri(a), a["version"])
        + ["--output", out], os.path.dirname(edit), budget, log)


def convert(src, out, budget, log, catalog=None):
    args = ["convert", "--input", src]
    if catalog:
        args = ["convert", "--catalog", catalog, "--input", src]
    run(args + ["--output", out], os.path.dirname(src), budget, log)


def extract_bot(bfo_owl, terms_file, out, ontology_iri, budget, log):
    run(["extract", "--input", bfo_owl, "--method", "BOT", "--term-file", terms_file,
         "annotate", "--ontology-iri", ontology_iri, "--output", out],
        os.path.dirname(out), budget, log)


def diff(left, right, out, budget, log):
    """``robot diff`` as Markdown (empty when the logical and annotation axioms match)."""
    run(["diff", "--left", left, "--right", right, "--format", "markdown", "--output", out],
        os.path.dirname(out), budget, log)
    with open(out, encoding="utf-8") as fh:
        return fh.read()


def suggest_version(previous_graph, new_graph, previous_version, own):
    """The semantic-version bump from the previous release (section 9.1):
    removed terms or changed logical axioms: major; new terms: minor; labels and
    definitions only: patch. Returns (version, reason, changes)."""
    import re
    from rdflib import OWL, RDF, BNode, Literal

    def terms(g):
        kinds = (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty,
                 OWL.NamedIndividual)
        return {str(s) for k in kinds for s in g.subjects(RDF.type, k) if own(str(s))}

    def describe(g, node, depth=0):
        """A blank node's structure as a sortable tuple (restrictions, lists)."""
        if not isinstance(node, BNode) or depth > 8:
            return str(node)
        return tuple(sorted((str(p), describe(g, o, depth + 1)) for p, o in g.predicate_objects(node)))

    def axioms(g, keep):
        """Per shared term: its logical (non-literal) and its annotation (literal) statements."""
        logic, notes = set(), set()
        for t in keep:
            for p, o in g.predicate_objects(__import__("rdflib").URIRef(t)):
                (notes if isinstance(o, Literal) else logic).add((t, str(p), describe(g, o)))
        return logic, notes

    old_t, new_t = terms(previous_graph), terms(new_graph)
    changes = {"added": sorted(new_t - old_t), "removed": sorted(old_t - new_t)}
    shared = old_t & new_t
    old_logic, old_notes = axioms(previous_graph, shared)
    new_logic, new_notes = axioms(new_graph, shared)
    logic_changed = old_logic != new_logic
    notes_changed = old_notes != new_notes
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", previous_version or "0.0.0")
    major, minor, patch = (int(x) for x in m.groups()) if m else (0, 0, 0)
    if changes["removed"] or logic_changed:
        return f"{major + 1}.0.0", "terms removed or logical axioms changed", changes
    if changes["added"]:
        return f"{major}.{minor + 1}.0", f"{len(changes['added'])} new term(s)", changes
    if notes_changed:
        return f"{major}.{minor}.{patch + 1}", "labels, definitions or other annotations changed", changes
    return f"{major}.{minor}.{patch + 1}", "no change found; a patch release", changes
