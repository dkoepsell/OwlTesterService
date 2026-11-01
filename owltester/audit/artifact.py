"""R0: ingest a released artifact and decide what each file is.

Input is a zip, a directory or a list of files. Paths inside the archive are
kept (data sets are grouped by directory), but every path component is
sanitised and the existing zip limits apply. Nothing from the archive is ever
executed: RDF is parsed, everything else is read as text on demand.
"""

import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field

import rdflib
from rdflib import OWL, RDF, RDFS, BNode, URIRef
from rdflib.namespace import SKOS

from ontology_bundle import BFO_IRI_PREFIX, CATALOG_NAMES, _norm, _resolve, read_catalog
from .config import ConfigError, find_config, load_config
from .files import (ArtifactError, _file_kind, _glob_match, _parse, _walk,  # noqa: F401
                    extract_zip, parse_text_snippet)

SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")

SCHEMA_TYPES = (OWL.Class, RDFS.Class, OWL.ObjectProperty, OWL.DatatypeProperty,
                OWL.AnnotationProperty, RDF.Property)
SKOS_TYPES = {SKOS.Concept, SKOS.ConceptScheme, SKOS.Collection, SKOS.OrderedCollection}
STANDARD_NS = ("http://www.w3.org/", "http://purl.org/dc/", "http://xmlns.com/foaf/",
               "http://purl.org/vocab/vann/", "http://schema.org/", "https://schema.org/")
BATCH_DIR = re.compile(r"^(batch|part|chunk|set|vol|volume)[-_ ]?\d+$|^\d+$", re.I)


def max_triples():
    return int(os.environ.get("AUDIT_MAX_TRIPLES", "2000000"))


def max_data_files():
    return int(os.environ.get("AUDIT_MAX_DATA_FILES", "300"))


def split_iri(iri):
    """(namespace, local name), splitting at the last '#' or else the last '/'."""
    iri = str(iri)
    cut = iri.rfind("#")
    if cut < 0:
        cut = iri.rfind("/")
    return (iri[:cut + 1], iri[cut + 1:]) if cut >= 0 else (iri, "")


def is_standard(iri):
    return str(iri).startswith(STANDARD_NS)


@dataclass
class ArtifactFile:
    path: str                 # relative to the artifact root, '/'-separated
    abspath: str
    kind: str                 # rdf | text | binary
    role: str = ""            # shapes | ontology | vocabulary | data | other
    scope: str = "primary"    # primary | external
    graph: object = None
    triples: int = 0
    error: str = ""
    data_set: str = ""
    ontology_iri: str = ""
    version_iri: str = ""
    role_source: str = "detected"   # detected | audit.yaml
    notes: list = field(default_factory=list)

    def text(self, limit=4_000_000):
        with open(self.abspath, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)

    def summary(self):
        return {"path": self.path, "kind": self.kind, "role": self.role, "scope": self.scope,
                "triples": self.triples, "data_set": self.data_set, "error": self.error,
                "ontology_iri": self.ontology_iri, "version_iri": self.version_iri,
                "role_source": self.role_source, "notes": self.notes}


class Artifact:
    def __init__(self, name, root, files, config, workdir=None):
        self.name, self.root, self.files, self.config = name, root, files, config
        self.workdir = workdir
        self.data_sets = {}          # name -> {"files": [path], "legacy": bool}
        self.owned_bases = set()     # normalised (no trailing # or /)
        self.owned_namespaces = []
        self.imports = {"resolved": [], "unresolved": []}
        self.limits = []
        self._cache = {}

    # -- views -----------------------------------------------------------------

    def get(self, path):
        return next((f for f in self.files if f.path == path), None)

    def by_role(self, role, scope="primary"):
        return [f for f in self.files if f.role == role and f.graph is not None
                and (scope is None or f.scope == scope)]

    def rdf_files(self):
        return [f for f in self.files if f.kind == "rdf"]

    def text_files(self):
        return [f for f in self.files if f.kind == "text"]

    def is_owned(self, iri):
        return _norm(split_iri(iri)[0]) in self.owned_bases

    def _union(self, key, files, drop_imports=True):
        if key not in self._cache:
            g = rdflib.Graph()
            for f in files:
                for prefix, ns in f.graph.namespaces():
                    g.bind(prefix, ns, override=False)
                for t in f.graph:
                    if not (drop_imports and t[1] == OWL.imports):
                        g.add(t)
            self._cache[key] = g
        return self._cache[key]

    def ontology_graph(self):
        return self._union("ontology", self.by_role("ontology"))

    def vocabulary_graph(self):
        return self._union("vocabulary", self.by_role("vocabulary"))

    def tbox(self):
        """Ontology plus vocabularies, imports removed (they never load from the network)."""
        return self._union("tbox", self.by_role("ontology") + self.by_role("vocabulary"))

    def shapes_graph(self):
        return self._union("shapes", self.by_role("shapes"), drop_imports=False)

    def data_files(self, data_set=None):
        return [f for f in self.by_role("data")
                if data_set is None or f.data_set == data_set]

    def data_graph(self, data_set):
        return self._union("data:" + data_set, self.data_files(data_set), drop_imports=False)

    def manifest(self):
        roles = {}
        for f in self.files:
            if f.kind == "rdf":
                role = f.role or ("unparsed" if f.error else "other")
                key = role if f.scope == "primary" else f"{role} (external)"
                roles.setdefault(key, []).append(f.path)
        return {
            "name": self.name,
            "files_total": len(self.files),
            "rdf_files": len(self.rdf_files()),
            "triples": sum(f.triples for f in self.files),
            "roles": roles,
            "data_sets": {k: {"files": len(v["files"]), "legacy": v["legacy"],
                              "paths": v["files"]} for k, v in self.data_sets.items()},
            "owned_namespaces": self.owned_namespaces,
            "imports": self.imports,
            "config": {k: v for k, v in self.config.items() if not k.startswith("_")},
            "config_unknown_keys": self.config.get("_unknown_keys", []),
            "files": [f.summary() for f in self.files],
        }

    def cleanup(self):
        if self.workdir:
            shutil.rmtree(self.workdir, ignore_errors=True)


# -- roles -------------------------------------------------------------------------------

def _declared_schema(g):
    out = set()
    for t in SCHEMA_TYPES:
        out.update(s for s in g.subjects(RDF.type, t) if isinstance(s, URIRef))
    return out


def _is_ontology(g, header):
    declared = _declared_schema(g)
    if header is None or len(declared) < 3:
        return False
    schema = sum(1 for s, p, _ in g if s in declared or s == header or isinstance(s, BNode)
                 and (str(p).startswith(str(OWL)) or p in (RDF.first, RDF.rest)))
    return schema > len(g) - schema


def _is_vocabulary(g):
    typed = {s for s in g.subjects(RDF.type, None) if isinstance(s, URIRef)}
    if not typed:
        return False
    skos = sum(1 for s in typed if any(t in SKOS_TYPES for t in g.objects(s, RDF.type)))
    return skos * 2 > len(typed)


def _uses_schema(g, classes, props):
    if any(o in classes for o in g.objects(None, RDF.type)):
        return True
    return any(p in props for p in g.predicates())


def _shape_iris(g):
    out = []
    for p in (SH.targetClass, SH["class"], SH.path, SH.targetNode, SH.hasValue,
              SH.targetSubjectsOf, SH.targetObjectsOf):
        out.extend(o for o in g.objects(None, p) if isinstance(o, URIRef) and not is_standard(o))
    return out


def assign_roles(artifact):
    cfg = artifact.config
    rdf = [f for f in artifact.rdf_files() if f.graph is not None]
    forced = {}
    for key, role in (("ontology", "ontology"), ("vocabularies", "vocabulary"), ("shapes", "shapes")):
        for f in rdf:
            if _glob_match(f.path, cfg.get(key)):
                forced[f.path] = role
    data_globs = [g for globs in (cfg.get("data_sets") or {}).values() for g in globs or ()]
    for f in rdf:
        if _glob_match(f.path, data_globs) and f.path not in forced:
            forced[f.path] = "data"

    for f in rdf:
        g = f.graph
        header = next((s for s in g.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)), None)
        f.ontology_iri = str(header) if header is not None else ""
        v = g.value(header, OWL.versionIRI) if header is not None else None
        f.version_iri = str(v) if v is not None else ""
        if f.path in forced:
            f.role, f.role_source = forced[f.path], "audit.yaml"
        elif any(True for _ in g.subjects(RDF.type, SH.NodeShape)) or \
                any(True for _ in g.subjects(RDF.type, SH.PropertyShape)):
            f.role = "shapes"
        elif _is_ontology(g, header):
            f.role = "ontology"
        elif _is_vocabulary(g):
            f.role = "vocabulary"
    onto = [f for f in rdf if f.role == "ontology"]
    classes, props = set(), set()
    for f in onto:
        for s in _declared_schema(f.graph):
            (props if (s, RDF.type, OWL.Class) not in f.graph
             and (s, RDF.type, RDFS.Class) not in f.graph else classes).add(s)
    for f in rdf:
        if not f.role:
            f.role = "data" if _uses_schema(f.graph, classes, props) else "other"


def _term_namespaces(f):
    ns = {}
    for s in f.graph.subjects(RDF.type, None):
        if isinstance(s, URIRef) and str(s) != f.ontology_iri:
            n = split_iri(s)[0]
            ns[n] = ns.get(n, 0) + 1
    return ns


def _referenced_bases(files):
    out = set()
    for f in files:
        for t in f.graph:
            for x in (t[0], t[2]):
                if isinstance(x, URIRef):
                    out.add(_norm(split_iri(x)[0]))
                    out.add(_norm(x))
    return out


def compute_scope_and_owned(artifact):
    """Owned namespaces, and which vocabularies and shapes belong to another family.

    Shapes are the artifact's own when most of what they target is in the
    ontology's namespaces. A vocabulary is the artifact's own when the ontology
    or its own shapes refer to it; one nothing refers to (an add-on code list)
    is listed but reported separately."""
    onto = artifact.by_role("ontology")

    def owned_of(f):
        bases = set()
        if f.ontology_iri:
            bases.add(_norm(f.ontology_iri))
        nss = _term_namespaces(f)
        anchor = _norm(f.ontology_iri) if f.ontology_iri else None
        for n, count in nss.items():
            nn = _norm(n)
            if is_standard(n):
                continue
            if anchor and (nn == anchor or nn.startswith(anchor + "/") or anchor.startswith(nn)):
                bases.add(nn)
            elif not anchor and count * 2 > sum(nss.values()):
                bases.add(nn)
        return bases

    def set_owned(files):
        owned, display = set(), set()
        for f in files:
            mine = owned_of(f)
            owned |= mine
            display.update(n for n in _term_namespaces(f) if _norm(n) in mine)
        artifact.owned_bases = owned
        artifact.owned_namespaces = sorted(display)

    set_owned(onto + artifact.by_role("vocabulary"))
    if onto:
        for f in artifact.by_role("shapes"):
            if f.role_source == "audit.yaml":
                continue
            iris = _shape_iris(f.graph)
            mine = sum(1 for i in iris if artifact.is_owned(i))
            if iris and mine * 2 < len(iris):
                f.scope = "external"
                f.notes.append("its shapes mostly target another namespace, reported separately")
        referenced = _referenced_bases(onto + artifact.by_role("shapes"))
        for f in artifact.by_role("vocabulary"):
            if f.role_source != "audit.yaml" and not (owned_of(f) & referenced):
                f.scope = "external"
                f.notes.append("neither the ontology nor its shapes refer to it, reported separately")
    set_owned(onto + artifact.by_role("vocabulary"))


def group_data_sets(artifact):
    cfg = artifact.config
    legacy_names = set(artifact.config.get("_legacy_names") or ())
    named = cfg.get("data_sets") or {}
    for f in artifact.by_role("data"):
        name = next((n for n, globs in named.items() if _glob_match(f.path, globs)), None)
        if name is None:
            parts = f.path.split("/")[:-1]
            while parts and BATCH_DIR.match(parts[-1]) and len(parts) > 1:
                parts.pop()
            name = "/".join(parts) or "."
        f.data_set = name
        artifact.data_sets.setdefault(name, {"files": [], "legacy": False})["files"].append(f.path)
    legacy_cfg = set(cfg.get("legacy") or ())
    published_cfg = set(cfg.get("published") or ())
    for name, ds in artifact.data_sets.items():
        last = name.rstrip("/").rsplit("/", 1)[-1].lower()
        ds["legacy"] = (name in legacy_cfg or last in legacy_names) and name not in published_cfg

    cap = max_data_files()
    data = artifact.by_role("data")
    if len(data) > cap:
        for f in data[cap:]:
            artifact.data_sets[f.data_set]["files"].remove(f.path)
            f.role, f.data_set = "other", ""
            f.notes.append(f"not audited: more than {cap} data files (AUDIT_MAX_DATA_FILES)")
        artifact.limits.append({"stage": "R0", "limit": "AUDIT_MAX_DATA_FILES",
                                "detail": f"{len(data) - cap} data files beyond {cap} were not audited"})
        artifact.data_sets = {k: v for k, v in artifact.data_sets.items() if v["files"]}


def resolve_imports(artifact):
    by_iri, by_stem = {}, {}
    for f in artifact.rdf_files():
        for iri in (f.ontology_iri, f.version_iri):
            if iri:
                by_iri[_norm(iri)] = f.path
        by_stem[f.path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()] = f.path
    catalog = {}
    for f in artifact.files:
        if f.path.rsplit("/", 1)[-1].lower() in CATALOG_NAMES:
            for k, v in read_catalog(f.abspath).items():
                hit = next((p for p in by_stem.values() if p.endswith(v)), None)
                if hit:
                    catalog[k] = hit
    for f in artifact.by_role("ontology") + artifact.by_role("vocabulary"):
        for o in f.graph.objects(None, OWL.imports):
            iri = str(o)
            if iri.lower().startswith(BFO_IRI_PREFIX):
                artifact.imports["resolved"].append({"from": f.path, "iri": iri, "to": "vendored BFO 2020"})
                continue
            target = _resolve(iri, by_iri, catalog, by_stem)
            if target:
                artifact.imports["resolved"].append({"from": f.path, "iri": iri, "to": target})
            else:
                artifact.imports["unresolved"].append({"from": f.path, "iri": iri})


# -- entry point ---------------------------------------------------------------------------

# The verification record and the report shipped with it describe the release; an
# audit of a recorded release must not count them (SPEC-release.md, section 2).
NOT_AUDITED = ("VERIFICATION.json", "VERIFICATION.md", "VERIFICATION.sigstore.json",
               "audit/report.json", "audit/report.md", "audit-badge.json")


def load_artifact(source, config_path=None, profile=None):
    """Load a zip, a directory or a list of files into an Artifact."""
    workdir = None
    sources = source if isinstance(source, (list, tuple)) else [source]
    if len(sources) == 1 and os.path.isdir(sources[0]):
        root = os.path.abspath(sources[0])
        name = os.path.basename(root.rstrip(os.sep))
        entries = _walk(root)
    elif len(sources) == 1 and zipfile.is_zipfile(sources[0]):
        workdir = tempfile.mkdtemp(prefix="owltester-audit-")
        root = os.path.join(workdir, "artifact")
        os.makedirs(root)
        stripped = extract_zip(sources[0], root)
        name = stripped or os.path.splitext(os.path.basename(sources[0]))[0]
        entries = _walk(root)
    else:
        missing = [s for s in sources if not os.path.isfile(s)]
        if missing:
            raise ArtifactError(f"No such file: {missing[0]}")
        root = os.path.dirname(os.path.abspath(sources[0]))
        name = os.path.basename(sources[0]) if len(sources) == 1 else f"{len(sources)} files"
        entries = [(os.path.basename(s), os.path.abspath(s)) for s in sources]

    cfg_path = config_path or find_config(root)
    try:
        config = load_config(cfg_path) if cfg_path else {}
    except ConfigError as e:
        # A broken optional config must not cost the whole audit: carry on with
        # the detected roles and report the problem in R0.
        config = {"_config_error": f"{os.path.basename(cfg_path)}: {e}"}
    from .profiles import LEGACY_NAMES
    config["_legacy_names"] = list((profile or {}).get("legacy_names") or LEGACY_NAMES)
    ignore = config.get("ignore") or ()

    files, total, cap = [], 0, max_triples()
    limits = []
    for rel, ab in entries:
        # The release's own config (at the root, or the file passed in) is not audited;
        # a workflow that happens to be called audit.yml is.
        if _glob_match(rel, ignore) or rel in ("audit.yaml", "audit.yml", "audit.json") \
                or (cfg_path and os.path.abspath(ab) == os.path.abspath(cfg_path)) or rel in NOT_AUDITED:
            continue
        kind, ext = _file_kind(rel)
        f = ArtifactFile(path=rel, abspath=ab, kind=kind)
        if kind == "rdf":
            if total >= cap:
                f.error = f"not parsed: the artifact passed {cap:,} triples (AUDIT_MAX_TRIPLES)"
                limits.append({"stage": "R0", "limit": "AUDIT_MAX_TRIPLES", "detail": rel})
            else:
                f.graph, f.error = _parse(ab, ext)
                if f.error == "not RDF":
                    f.kind, f.error, f.graph = "text", "", None
                elif f.graph is not None:
                    f.triples = len(f.graph)
                    total += f.triples
        files.append(f)

    art = Artifact(name, root, files, config, workdir)
    art.limits = limits
    assign_roles(art)
    compute_scope_and_owned(art)
    group_data_sets(art)
    resolve_imports(art)
    return art
