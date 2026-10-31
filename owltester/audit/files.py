"""Reading a released artifact from disk: path-preserving zip extraction with
the bundle limits, directory walking, and RDF parsing by extension and sniffing.
Nothing read here is ever executed."""

import fnmatch
import os
import re
import shutil
import zipfile

import rdflib

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


def _parse(path, ext):
    """(graph, error). Formats are chosen by extension, then by sniffing."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        head = fh.read(4000)
    fmt = RDF_FORMATS.get(ext)
    if ext in ("owl", "xml"):
        fmt = _sniff_xml(head) or ("turtle" if ext == "owl" else None)
        if fmt is None:
            return None, "not RDF"
    if ext in ("ofn", "omn", "owx") or fmt == "owx" or head.lstrip().startswith(("Prefix(", "Ontology(")):
        from owl_format_detector import parse_rdf_file
        try:
            return parse_rdf_file(path), ""
        except Exception as e:  # noqa: BLE001
            return None, f"{type(e).__name__}: {str(e)[:400]}"
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
