"""R10: release hygiene. Everything here is read as text and never executed."""

import json
import re

from rdflib import OWL, RDF, URIRef

from .. import errors

DCT = "http://purl.org/dc/terms/"
DC = "http://purl.org/dc/elements/1.1/"
LICENSE = [URIRef(DCT + "license"), URIRef(DCT + "rights"), URIRef(DC + "rights"),
           URIRef("http://creativecommons.org/ns#license"), URIRef("http://schema.org/license"),
           URIRef("https://schema.org/license")]
PEOPLE = [URIRef(DCT + x) for x in ("creator", "contributor", "publisher")] + \
    [URIRef(DC + x) for x in ("creator", "contributor", "publisher")] + \
    [URIRef("http://xmlns.com/foaf/0.1/maker"), URIRef("http://schema.org/author"),
     URIRef("http://purl.org/pav/authoredBy"), URIRef("http://purl.org/pav/createdBy")]
MODIFIED = [URIRef(DCT + "modified"), URIRef(DCT + "date"), URIRef(DCT + "issued")]
VERSION = re.compile(r"(?<![\w.])v?(\d+\.\d+(?:\.\d+)?(?:[-.]?(?:rc|alpha|beta)\d*)?)(?![\w.])", re.I)
CI_FILES = re.compile(r"(^|/)(\.gitlab-ci\.ya?ml|\.github/workflows/[^/]+\.ya?ml|Makefile|tox\.ini|"
                      r"noxfile\.py|\.circleci/config\.ya?ml|Jenkinsfile|azure-pipelines\.ya?ml|"
                      r"\.travis\.ya?ml|bitbucket-pipelines\.ya?ml)$")
CHECKS = {
    "syntax": re.compile(r"riot\s+--validate|rapper|rdflib|validate[_-]?(ttl|turtle|rdf|syntax)|"
                         r"turtle[_-]?(lint|validate)|ttl[_-]?lint", re.I),
    "shacl": re.compile(r"pyshacl|shacl\s+validate|jena\s+shacl|shaclvalidate|topbraid|\bshacl\b", re.I),
    "reasoning": re.compile(r"robot\s+(reason|explain)|hermit|pellet|owlready|\belk\b|"
                            r"konclude|openllet|sync_reasoner", re.I),
    "tests": re.compile(r"pytest|unittest|\bnox\b|\btox\b", re.I),
}
SCRIPT_REF = re.compile(r"(?:python3?|bash|sh)\s+([\w./-]+\.(?:py|sh))")


def _header(art):
    rows = []
    for f in art.by_role("ontology") + art.by_role("vocabulary"):
        g = f.graph
        h = next((s for s in g.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)), None)
        if h is None:
            rows.append({"file": f.path, "header": False})
            continue
        def has(preds):
            return any(g.value(h, p) is not None for p in preds)
        rows.append({"file": f.path, "header": True, "license": has(LICENSE),
                     "version_iri": g.value(h, OWL.versionIRI) is not None,
                     "version_info": has([OWL.versionInfo]), "people": has(PEOPLE),
                     "modified": has(MODIFIED), "role": f.role,
                     "versions": [str(v) for v in g.objects(h, OWL.versionInfo)] +
                                 [str(v) for v in g.objects(h, OWL.versionIRI)]})
    return rows


def _versions(art, header_rows):
    found = {}
    for r in header_rows:
        if r.get("role") == "ontology":
            for v in r.get("versions", []):
                m = VERSION.search(v)
                if m:
                    found.setdefault(m.group(1).lstrip("vV"), []).append(f"{r['file']} header")
    for f in art.text_files():
        base = f.path.rsplit("/", 1)[-1].lower()
        if f.path.count("/"):
            continue
        text = ""
        try:
            text = f.text(400_000)
        except OSError:
            continue
        if base == "pyproject.toml":
            m = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.M)
            if m:
                found.setdefault(m.group(1), []).append("pyproject.toml")
        elif base == "package.json":
            try:
                v = json.loads(text).get("version")
            except (ValueError, AttributeError):
                v = None
            if v:
                found.setdefault(v, []).append("package.json")
        elif base.startswith(("changelog", "history", "news")):
            for line in text.splitlines():
                if line.startswith("#") or re.match(r"^\[?\d", line):
                    m = VERSION.search(line)
                    if m:
                        found.setdefault(m.group(1).lstrip("vV"), []).append(f.path)
                        break
    m = VERSION.search(art.name or "")
    if m:
        found.setdefault(m.group(1).lstrip("vV"), []).append("archive name")
    return found


def _ci(art):
    configs = [f for f in art.files if CI_FILES.search(f.path) and f.kind != "binary"]
    by_path = {f.path: f for f in art.files}
    kinds, sources = set(), {}
    for f in configs:
        text = f.text(400_000)
        texts = [(f.path, text)]
        for ref in SCRIPT_REF.findall(text):   # one level into scripts CI runs, as text
            target = by_path.get(ref.lstrip("./"))
            if target is not None and target.kind == "text":
                texts.append((target.path, target.text(400_000)))
        for where, t in texts:
            for kind, rx in CHECKS.items():
                if rx.search(t):
                    kinds.add(kind)
                    sources.setdefault(kind, set()).add(where)
    return configs, kinds, {k: sorted(v) for k, v in sources.items()}


def _changelog_claims(art):
    log = next((f for f in art.text_files() if "/" not in f.path and
                f.path.lower().startswith(("changelog", "history"))), None)
    if log is None:
        return None, []
    lines, section, started = log.text(400_000).splitlines(), [], False
    for line in lines:
        if re.match(r"^#{1,2}\s", line) and VERSION.search(line):
            if started:
                break
            started = True
            continue
        if started:
            section.append(line)
    basenames = {f.path.rsplit("/", 1)[-1] for f in art.files}
    paths = {f.path for f in art.files}
    missing = []
    for line in section:
        if not re.search(r"\badd(ed|s)?\b", line, re.I):
            continue
        for tok in re.findall(r"`([^`\s]+)`", line):
            if "." in tok.rsplit("/", 1)[-1] and not tok.startswith(("http", "dctype:", "adms:")) \
                    and ":" not in tok and tok not in paths and tok.rsplit("/", 1)[-1] not in basenames:
                missing.append(tok)
    return log.path, sorted(set(missing))


def run_r10(ctx):
    art = ctx.artifact
    header = _header(art)
    onto_rows = [r for r in header if r.get("role") == "ontology"]
    for r in onto_rows:
        missing = [k.replace("_", " ") for k in ("license", "version_iri") if not r.get(k)]
        if not r.get("header"):
            missing = ["owl:Ontology header"]
        if missing:
            ctx.add("R10", errors.W_HEADER, "minor", f"{r['file']}: no {', '.join(missing)}",
                    files=[r["file"]], fix="Add the missing header annotations.")
        elif not r.get("people"):
            ctx.add("R10", errors.W_HEADER, "info", f"{r['file']}: no named creator or editors",
                    files=[r["file"]], fix="Add dcterms:creator or dcterms:contributor.")

    versions = _versions(art, header)
    if len(versions) > 1:
        ctx.add("R10", errors.W_VERSION, "minor",
                f"Version numbers disagree: {', '.join(sorted(versions))}",
                files=sorted({w for ws in versions.values() for w in ws if "/" in w or "." in w}),
                count=len(versions), evidence={"versions": versions},
                fix="Bump every version marker together when releasing.")

    configs, kinds, sources = _ci(art)
    shapes = art.by_role("shapes")
    where = (", ".join(f.path for f in configs) if configs else "no CI configuration was found")
    if shapes and "shacl" not in kinds:
        ctx.add("R10", errors.W_CI_NO_SHACL, "major",
                "Shapes ship with the artifact, but no CI step runs SHACL",
                f"Checked: {where}. Nothing stops a release whose data fails its own shapes.",
                files=[f.path for f in configs], evidence={"ci_checks": sorted(kinds), "sources": sources},
                fix="Add a CI step that validates every data file against the shapes "
                    "(for example: pyshacl -s shapes.ttl -e ontology.ttl -i rdfs data.ttl).")
    if art.by_role("ontology") and "reasoning" not in kinds:
        ctx.add("R10", errors.W_CI_NO_REASONER, "major",
                "No CI step runs a reasoner",
                f"Checked: {where}. Inconsistencies and unsatisfiable classes reach the release "
                "unnoticed.", files=[f.path for f in configs],
                evidence={"ci_checks": sorted(kinds), "sources": sources},
                fix="Add a CI step such as: robot reason --reasoner HermiT --input ontology.ttl.")

    log, missing = _changelog_claims(art)
    if missing:
        ctx.add("R10", errors.W_CHANGELOG, "info",
                f"The newest changelog entry names {len(missing)} file(s) not in the release",
                files=[log], count=len(missing), evidence={"files": missing})
    ctx.finish("R10", "Release hygiene",
               summary=(f"CI runs: {', '.join(sorted(kinds)) or 'nothing recognised'}"
                        f" ({len(configs)} CI file(s)); versions found: "
                        f"{', '.join(sorted(versions)) or 'none'}."),
               notes={"header": header, "versions": versions, "ci_files": [f.path for f in configs],
                      "ci_checks": sorted(kinds), "ci_sources": sources, "changelog": log})
