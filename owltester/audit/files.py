"""Reading a released artifact from disk: path-preserving zip extraction with
the bundle limits, directory walking, and RDF parsing by extension and sniffing.
Nothing read here is ever executed."""

import fnmatch
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

import rdflib
from rdflib import OWL, RDF, URIRef

from ontology_bundle import MAX_ZIP_MEMBERS, MAX_ZIP_UNCOMPRESSED

RDF_FORMATS = {"ttl": "turtle", "n3": "n3", "nt": "nt", "nq": "nquads", "trig": "trig",
               "jsonld": "json-ld", "owl": None, "rdf": "xml", "xml": None, "owx": None,
               "ofn": None, "omn": None}
TEXT_EXT = {"yml", "yaml", "md", "txt", "toml", "ini", "cfg", "json", "py", "sh", "rq",
            "sparql", "html", "csv", "tsv", "lock", "mk", "nox"}
TEXT_NAMES = {"makefile", "changelog", "notice", "license", "readme", "dockerfile"}
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._()+=-]")


class ArtifactError(ValueError):
    """The input cannot be audited at all; the message is user-facing."""


# -- extraction ----------------------------------------------------------------------

def _safe_relpath(name):
    parts = []
    for p in name.replace("\\", "/").split("/"):
        if p in ("", ".", ".."):
            continue
        p = _SAFE_COMPONENT.sub("_", p)[:180]
        if p.strip("."):
            parts.append(p)
    return "/".join(parts)


def extract_zip(zip_path, dest):
    """Extract with the bundle limits, keeping (sanitised) relative paths."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise ArtifactError(f"Not a valid zip archive: {e}")
    with zf:
        members = [m for m in zf.infolist() if not m.is_dir() and "__MACOSX" not in m.filename]
        if len(members) > MAX_ZIP_MEMBERS:
            raise ArtifactError(f"Zip has too many files ({len(members)} > {MAX_ZIP_MEMBERS}).")
        if sum(m.file_size for m in members) > MAX_ZIP_UNCOMPRESSED:
            raise ArtifactError("Zip expands to more than 256 MB.")
        rels = [_safe_relpath(m.filename) for m in members]
        firsts = {r.split("/", 1)[0] for r in rels if r}
        strip = next(iter(firsts)) if len(firsts) == 1 and all("/" in r for r in rels if r) else ""
        for m, rel in zip(members, rels):
            if strip:
                rel = rel[len(strip) + 1:]
            if not rel:
                continue
            target = os.path.join(dest, *rel.split("/"))
            if not os.path.realpath(target).startswith(os.path.realpath(dest) + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(m) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return strip


def _walk(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in (".git", "__pycache__", "node_modules"))
        for fn in sorted(filenames):
            ab = os.path.join(dirpath, fn)
            if os.path.islink(ab):
                continue
            out.append((os.path.relpath(ab, root).replace(os.sep, "/"), ab))
    return out


def _glob_match(path, patterns):
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path, p.rstrip("/") + "/*")
               for p in patterns or ())


# -- parsing ---------------------------------------------------------------------------

def _sniff_xml(head):
    if "rdf:RDF" in head or "22-rdf-syntax-ns" in head:
        return "xml"
    if "<Ontology" in head and "owl" in head:
        return "owx"
    return None


OWL_SYNTAX_NAMES = {"ofn": "OWL Functional Syntax", "omn": "Manchester Syntax", "owx": "OWL/XML"}
ROBOT_CONVERT_SECONDS = 120


def _owl_syntax(ext, fmt, head):
    """'ofn', 'omn' or 'owx' for the OWL syntaxes rdflib cannot read, else None."""
    start = head.lstrip()
    if ext == "ofn" or start.startswith(("Prefix(", "Ontology(")):
        return "ofn"
    if ext == "omn" or start.startswith(("Prefix:", "Ontology:")):
        return "omn"
    if ext == "owx" or fmt == "owx":
        return "owx"
    return None


_IMPORT_RES = {
    "ofn": re.compile(r"^[ \t]*Import\(\s*<([^>]+)>\s*\)[ \t]*$", re.M),
    "omn": re.compile(r"^[ \t]*Import:\s*<([^>]+)>[ \t]*$", re.M),
    "owx": re.compile(r"<(?:owl:)?Import>\s*([^<\s]+)\s*</(?:owl:)?Import>"),
}


def _parse_owl_syntax(path, syntax):
    """Read an OWL Functional, Manchester or OWL/XML file through ROBOT.

    Import declarations are removed before conversion, so ROBOT never fetches
    anything, and are put back as owl:imports triples so R0 reports them like
    any other import. Without ROBOT the file is listed, not parsed, at info level.
    """
    name = OWL_SYNTAX_NAMES[syntax]
    from external_reasoner import robot_available
    if not robot_available():
        return None, (f"not parsed: {name} needs ROBOT, which is not installed here; "
                      "the release's RDF files were audited instead")
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    imports = _IMPORT_RES[syntax].findall(text)
    stripped = _IMPORT_RES[syntax].sub("", text)
    work = tempfile.mkdtemp(prefix="owltester-owl-")
    src = os.path.join(work, "in." + syntax)
    out = os.path.join(work, "out.ttl")
    try:
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(stripped)
        proc = subprocess.run(["robot", "convert", "--input", src, "--format", "ttl", "--output", out],
                              capture_output=True, text=True, timeout=ROBOT_CONVERT_SECONDS, check=False)
        if proc.returncode != 0 or not os.path.isfile(out):
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["no output"]
            return None, f"{name} could not be read by ROBOT: {detail[0][:300]}"
        g = rdflib.Graph()
        g.parse(out, format="turtle")
        header = next(iter(g.subjects(RDF.type, OWL.Ontology)), None)
        if header is not None:
            for iri in imports:
                g.add((header, OWL.imports, URIRef(iri)))
        return g, ""
    except subprocess.TimeoutExpired:
        return None, f"not parsed: ROBOT took longer than {ROBOT_CONVERT_SECONDS} s to read this {name} file"
    except Exception as e:  # noqa: BLE001 - rdflib or OS errors
        return None, f"{type(e).__name__}: {str(e)[:400]}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _parse(path, ext):
    """(graph, error). Formats are chosen by extension, then by sniffing."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        head = fh.read(4000)
    fmt = RDF_FORMATS.get(ext)
    if ext in ("owl", "xml"):
        fmt = _sniff_xml(head) or ("turtle" if ext == "owl" else None)
        if fmt is None:
            return None, "not RDF"
    syntax = _owl_syntax(ext, fmt, head)
    if syntax:
        return _parse_owl_syntax(path, syntax)
    if fmt == "json-ld":
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if re.search(r'"@context"\s*:\s*(\[[^\]]*)?"https?://', text):
            return None, "not parsed: the JSON-LD @context is remote and the audit never uses the network"
    g = rdflib.Graph()
    try:
        g.parse(path, format=fmt)
        return g, ""
    except Exception as e:  # noqa: BLE001 - rdflib raises many parser types
        if fmt == "turtle" and ext == "owl":
            try:
                return rdflib.Graph().parse(path, format="xml"), ""
            except Exception:  # noqa: BLE001
                pass
        return None, f"{type(e).__name__}: {str(e)[:400]}"


def _file_kind(rel):
    base = rel.rsplit("/", 1)[-1]
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    if ext in RDF_FORMATS:
        return "rdf", ext
    if ext in TEXT_EXT or base.lower().split(".")[0] in TEXT_NAMES or base.startswith("."):
        return "text", ext
    return "binary", ext



def parse_text_snippet(text, prefixes):
    """Parse a Turtle snippet with the given prefixes; (graph, error)."""
    header = "".join(f"@prefix {p}: <{ns}> .\n" for p, ns in prefixes)
    g = rdflib.Graph()
    try:
        g.parse(data=header + text, format="turtle")
        return g, ""
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:300]}"
