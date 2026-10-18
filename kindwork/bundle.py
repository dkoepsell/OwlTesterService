"""Load a Kindwork export: one upload, several files, or a zip of them.

Files are recognised by name: `<slug>.kindwork.json` is the manifest,
`<slug>-shapes.ttl` holds the SHACL shapes, and any other Turtle or RDF/XML file
is RDF. The RDF file that declares an owl:Ontology is the ontology; every RDF
file (the ontology included) is data for the SHACL check. OWL functional syntax
and OWL/XML are refused, as Kindwork itself refuses them (spec section 9).
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import rdflib
from rdflib import OWL, RDF, RDFS, Namespace, URIRef

KWV = Namespace("https://ontology.davidkoepsell.com/kindwork/vocab#")

RDF_SUFFIXES = (".ttl", ".owl", ".rdf", ".xml")
MAX_UNZIPPED_BYTES = 64 * 1024 * 1024


class BundleRefused(ValueError):
    """The upload cannot be read as a Kindwork export. The message is user-facing."""


def local_name(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] or iri


@dataclass
class Bundle:
    slug: str
    ontology: rdflib.Graph
    ontology_iri: str | None
    data: rdflib.Graph
    shapes: rdflib.Graph | None = None
    manifest: dict | None = None
    names: dict = field(default_factory=dict)

    def label_for(self, iri: str) -> str:
        """Manifest name, then rdfs:label (English or untagged), then local name."""
        if iri in self.names:
            return self.names[iri]
        best = None
        for lit in self.ontology.objects(URIRef(iri), RDFS.label):
            lang = getattr(lit, "language", None)
            if lang in (None, "en"):
                return str(lit)
            best = best or str(lit)
        return best or local_name(iri)


def _expand(files):
    """Flatten (name, bytes) pairs, opening any zip. Skips OS litter."""
    out = []
    for name, data in files:
        if name.lower().endswith(".zip"):
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile as e:
                raise BundleRefused(f"{name} is not a readable zip file.") from e
            total = 0
            for info in zf.infolist():
                inner = PurePosixPath(info.filename)
                if info.is_dir() or "__MACOSX" in inner.parts or inner.name.startswith("."):
                    continue
                total += info.file_size
                if total > MAX_UNZIPPED_BYTES:
                    raise BundleRefused(f"{name} unpacks to more than 64 MB.")
                out.append((inner.name, zf.read(info)))
        else:
            out.append((PurePosixPath(name).name, data))
    return [(n, d) for n, d in out if not n.endswith(":Zone.Identifier")]


def _rdf_format(name: str, data: bytes) -> str:
    head = data[:4096].lstrip().decode("utf-8", errors="replace")
    if head.startswith(("Prefix(", "Ontology(")):
        raise BundleRefused(
            f"{name} is OWL functional syntax. Re-save it as Turtle or RDF/XML and upload again.")
    if "<Ontology" in head and "<rdf:RDF" not in head:
        raise BundleRefused(
            f"{name} is OWL/XML. Re-save it as Turtle or RDF/XML and upload again.")
    if head.startswith(("<?xml", "<rdf:RDF")):
        return "xml"
    return "turtle"


def _parse(name: str, data: bytes) -> rdflib.Graph:
    g = rdflib.Graph()
    try:
        g.parse(data=data, format=_rdf_format(name, data))
    except BundleRefused:
        raise
    except Exception as e:
        raise BundleRefused(f"{name} could not be parsed: {e}") from e
    return g


def load_bundle(files) -> Bundle:
    """Build a Bundle from [(filename, bytes)]. Raises BundleRefused."""
    manifest = shapes = None
    rdf = []
    for name, data in _expand(files):
        low = name.lower()
        if low.endswith(".kindwork.json"):
            try:
                manifest = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise BundleRefused(f"{name} is not valid JSON: {e}") from e
            if manifest.get("format") != "kindwork-model":
                raise BundleRefused(f"{name} is not a kindwork-model manifest.")
        elif low.endswith(".ofn") or low.endswith(".owx"):
            _rdf_format(name, data)  # raises with the re-save message
            raise BundleRefused(f"{name}: re-save it as Turtle or RDF/XML and upload again.")
        elif low.endswith("-shapes.ttl"):
            shapes = _parse(name, data)
        elif low.endswith(RDF_SUFFIXES):
            rdf.append((name, _parse(name, data)))
    if not rdf:
        raise BundleRefused("No ontology found. Upload a .ttl or RDF/XML file.")

    declares = [(n, g) for n, g in rdf if (None, RDF.type, OWL.Ontology) in g]
    main_name, ontology = (declares or rdf)[0]
    data = rdflib.Graph()
    for _, g in rdf:
        data += g

    iri = next((str(s) for s in ontology.subjects(RDF.type, OWL.Ontology)
                if isinstance(s, URIRef)), None)
    stem = PurePosixPath(main_name).stem
    names = {}
    if manifest:
        names = {t["iri"]: t["name"] for t in manifest.get("terms", [])
                 if t.get("iri") and t.get("name")}
    return Bundle(slug=stem, ontology=ontology, ontology_iri=iri, data=data,
                  shapes=shapes, manifest=manifest, names=names)
