"""Multi-file ontology bundles.

A modular ontology is often shipped as several files, each importing the one
below it (e.g. thesis module → core vocabulary → design patterns → BFO). The
analysis pipeline works on one file, so a bundle upload is resolved here:

1. the uploaded files (or a .zip, optionally with a Protégé ``catalog-v001.xml``)
   are saved into a per-upload modules directory;
2. every ``owl:imports`` is resolved against those local files only — by
   ontology IRI, version IRI, catalog entry, or file name — never the network.
   BFO imports that were not uploaded resolve to the vendored BFO 2020, which the
   loader attaches anyway;
3. the import closure of the top-level module is merged into one RDF/XML file
   that the rest of the app analyses unchanged, and a manifest records which
   module each entity came from, the import graph, and anything unresolved.

The manifest is a JSON sidecar (``<stored name>.bundle.json``) next to the
merged file, so no database migration is needed.
"""

import json
import logging
import os
import shutil
import xml.etree.ElementTree as ET
import zipfile

import rdflib
from rdflib.namespace import OWL, RDF, RDFS
from werkzeug.utils import secure_filename

from owl_format_detector import auto_convert_ontology, parse_rdf_file

logger = logging.getLogger(__name__)

CATALOG_NAMES = {'catalog-v001.xml', 'catalog.xml'}
MAX_ZIP_MEMBERS = 500
MAX_ZIP_UNCOMPRESSED = 256 * 1024 * 1024
BFO_IRI_PREFIX = 'http://purl.obolibrary.org/obo/bfo'

_ENTITY_KINDS = {
    OWL.Class: 'classes',
    OWL.ObjectProperty: 'object_properties',
    OWL.DatatypeProperty: 'data_properties',
    OWL.AnnotationProperty: 'annotation_properties',
    OWL.NamedIndividual: 'individuals',
}
_DC_TITLES = (rdflib.URIRef('http://purl.org/dc/terms/title'),
              rdflib.URIRef('http://purl.org/dc/elements/1.1/title'), RDFS.label)


class BundleError(Exception):
    """A bundle upload that cannot be analysed; the message is user-facing."""


def _norm(iri):
    return (iri or '').strip().rstrip('#/')


def _unique_name(dest_dir, name):
    stem, ext = os.path.splitext(name)
    candidate, n = name, 1
    while os.path.exists(os.path.join(dest_dir, candidate)):
        n += 1
        candidate = f"{stem}_{n}{ext}"
    return candidate


def _extract_zip(stream, dest_dir, allowed_ext):
    """Extract ontology files and a catalog from a zip, flattening paths.

    Member names are reduced to a secure basename (no zip-slip), and the member
    count and total uncompressed size are capped (no zip bombs)."""
    saved = []
    try:
        zf = zipfile.ZipFile(stream)
    except zipfile.BadZipFile as e:
        raise BundleError(f"Not a valid zip archive: {e}")
    with zf:
        members = [m for m in zf.infolist() if not m.is_dir()
                   and '__MACOSX' not in m.filename]
        if len(members) > MAX_ZIP_MEMBERS:
            raise BundleError(f"Zip has too many files ({len(members)} > {MAX_ZIP_MEMBERS}).")
        if sum(m.file_size for m in members) > MAX_ZIP_UNCOMPRESSED:
            raise BundleError("Zip expands to more than 256 MB.")
        for m in members:
            base = secure_filename(os.path.basename(m.filename))
            if not base or base.startswith('.'):
                continue
            ext = base.rsplit('.', 1)[-1].lower() if '.' in base else ''
            if base.lower() not in CATALOG_NAMES and ext not in allowed_ext:
                continue
            name = _unique_name(dest_dir, base)
            with zf.open(m) as src, open(os.path.join(dest_dir, name), 'wb') as dst:
                shutil.copyfileobj(src, dst)
            saved.append(name)
    return saved


def save_uploads(file_storages, dest_dir, allowed_ext):
    """Save uploaded FileStorage objects (ontology files and/or zips) into
    dest_dir. Returns (module_filenames, catalog_filename_or_None)."""
    os.makedirs(dest_dir, exist_ok=True)
    names = []
    for fs in file_storages:
        base = secure_filename(fs.filename or '')
        if not base:
            continue
        ext = base.rsplit('.', 1)[-1].lower() if '.' in base else ''
        if ext == 'zip':
            names.extend(_extract_zip(fs.stream, dest_dir, allowed_ext))
        elif ext in allowed_ext or base.lower() in CATALOG_NAMES:
            name = _unique_name(dest_dir, base)
            fs.save(os.path.join(dest_dir, name))
            names.append(name)
        else:
            raise BundleError(f"Unsupported file in bundle: {fs.filename}")
    catalog = next((n for n in names if n.lower() in CATALOG_NAMES), None)
    modules = [n for n in names if n != catalog]
    if not modules:
        raise BundleError("The upload contained no ontology files.")
    return modules, catalog


def read_catalog(path):
    """Parse an OASIS XML catalog (Protégé's catalog-v001.xml) into
    {normalised IRI: local file basename}."""
    mapping = {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        logger.warning(f"Ignoring unreadable catalog {path}: {e}")
        return mapping
    for el in root.iter():
        if el.tag.rsplit('}', 1)[-1] == 'uri' and el.get('name') and el.get('uri'):
            mapping[_norm(el.get('name'))] = os.path.basename(el.get('uri'))
    return mapping


def _describe_module(name, graph):
    """Ontology header, imports and declared entities of one module graph."""
    header = next(iter(graph.subjects(RDF.type, OWL.Ontology)), None)
    iri = str(header) if isinstance(header, rdflib.URIRef) else None
    version = graph.value(header, OWL.versionIRI) if header is not None else None
    title = None
    if header is not None:
        for p in _DC_TITLES:
            if graph.value(header, p) is not None:
                title = str(graph.value(header, p))
                break
    imports = [str(o) for o in graph.objects(header, OWL.imports)] if header is not None else []
    entities = {}
    counts = {k: 0 for k in _ENTITY_KINDS.values()}
    for rdf_type, kind in _ENTITY_KINDS.items():
        for s in graph.subjects(RDF.type, rdf_type):
            if isinstance(s, rdflib.URIRef):
                entities[str(s)] = kind
                counts[kind] += 1
    return {
        'name': name,
        'ontology_iri': iri,
        'version_iri': str(version) if version else None,
        'title': title,
        'import_iris': imports,
        'counts': counts,
        'triples': len(graph),
        '_header': header,
        '_entities': entities,
    }


def _resolve(iri, by_iri, catalog, by_stem):
    """Map an import IRI to a local module name, or None."""
    key = _norm(iri)
    if key in by_iri:
        return by_iri[key]
    target = catalog.get(key)
    if target and target in by_stem.values():
        return target
    last = key.rsplit('/', 1)[-1].lower()
    return by_stem.get(last) or by_stem.get(last.rsplit('.', 1)[0])


def build_bundle(modules_dir, module_names, catalog_name=None, root_name=None):
    """Resolve imports between the saved modules and merge the root's closure.

    Returns (merged_graph, manifest)."""
    graphs, mods = {}, {}
    for name in module_names:
        path = os.path.join(modules_dir, name)
        converted = auto_convert_ontology(path, target_format='xml')
        if converted != path:
            shutil.move(converted, path)
        try:
            graphs[name] = parse_rdf_file(path)
        except Exception as e:
            raise BundleError(f"Could not parse {name}: {e}")
        mods[name] = _describe_module(name, graphs[name])

    catalog = read_catalog(os.path.join(modules_dir, catalog_name)) if catalog_name else {}
    by_iri, by_stem = {}, {}
    for name, m in mods.items():
        for iri in (m['ontology_iri'], m['version_iri']):
            if iri:
                by_iri.setdefault(_norm(iri), name)
        stem = name.lower()
        by_stem[stem] = name
        by_stem.setdefault(stem.rsplit('.', 1)[0], name)

    unresolved = []
    for name, m in mods.items():
        m['imports'] = []
        for iri in m['import_iris']:
            target = _resolve(iri, by_iri, catalog, by_stem)
            if target == name:
                target = None
            if target:
                status = 'local'
            elif _norm(iri).startswith(BFO_IRI_PREFIX):
                status = 'bfo'
            else:
                status = 'unresolved'
                unresolved.append({'module': name, 'iri': iri})
            m['imports'].append({'iri': iri, 'module': target, 'status': status})

    imported = {i['module'] for m in mods.values() for i in m['imports'] if i['module']}
    roots = [n for n in module_names if n not in imported]
    if root_name:
        if root_name not in mods:
            raise BundleError(f"Top-level ontology '{root_name}' is not in the upload.")
        tops = [root_name]
    elif roots:
        tops = roots
    else:  # every module is imported by another: an import cycle
        tops = [module_names[0]]

    # Bottom-up order of the closure (post-order DFS; cycle-safe).
    order, seen = [], set()

    def visit(n):
        if n in seen:
            return
        seen.add(n)
        for imp in mods[n]['imports']:
            if imp['module']:
                visit(imp['module'])
        order.append(n)

    for t in tops:
        visit(t)
    for depth_name in order:
        deps = [mods[i['module']].get('layer', 0)  # missing only inside a cycle
                for i in mods[depth_name]['imports'] if i['module']]
        mods[depth_name]['layer'] = 1 + max(deps, default=-1)

    merged = rdflib.Graph()
    for n in order:
        g = graphs[n]
        header = mods[n]['_header']
        keep_header = n == tops[0]
        for s, p, o in g:
            if p == OWL.imports:
                continue
            if header is not None and s == header and not keep_header:
                continue
            merged.add((s, p, o))
        for prefix, ns in g.namespaces():
            merged.bind(prefix, ns, override=False)

    entity_module = {}
    for n in order:  # bottom-up: the lowest module that declares an entity owns it
        for iri in mods[n]['_entities']:
            entity_module.setdefault(iri, n)

    manifest = {
        'root': tops[0],
        'roots': tops,
        'order': order,
        'unused': [n for n in module_names if n not in seen],
        'catalog': catalog_name,
        'unresolved': unresolved,
        'bfo_vendored': any(i['status'] == 'bfo' for n in order for i in mods[n]['imports']),
        'modules': [{k: v for k, v in mods[n].items() if not k.startswith('_')}
                    for n in order] + [
                    {k: v for k, v in mods[n].items() if not k.startswith('_')}
                    for n in module_names if n not in seen],
        'entity_module': entity_module,
    }
    return merged, manifest


def module_closure_graph(modules_dir, manifest, module_name):
    """Merged graph of one module plus everything it (transitively) imports,
    with owl:imports stripped, used by the layer-by-layer check."""
    by_name = {m['name']: m for m in manifest['modules']}
    names, stack = [], [module_name]
    while stack:
        n = stack.pop()
        if n in names:
            continue
        names.append(n)
        stack.extend(i['module'] for i in by_name[n]['imports'] if i['module'])
    g = rdflib.Graph()
    for n in names:
        sub = parse_rdf_file(os.path.join(modules_dir, n))
        header = next(iter(sub.subjects(RDF.type, OWL.Ontology)), None)
        for s, p, o in sub:
            if p == OWL.imports or (n != module_name and header is not None and s == header):
                continue
            g.add((s, p, o))
    return g, names


def manifest_path(file_path):
    return file_path + '.bundle.json'


def modules_dir_for(file_path):
    return os.path.splitext(file_path)[0] + '_modules'


def load_manifest(file_path):
    """The bundle manifest for a stored ontology file, or None for single files."""
    path = manifest_path(file_path or '')
    if not file_path or not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        logger.warning(f"Unreadable bundle manifest {path}: {e}")
        return None


def create_bundle(file_storages, upload_dir, stored_name, allowed_ext, root_name=None):
    """Save, resolve and merge a bundle upload.

    Writes the merged ontology to upload_dir/stored_name, the original modules
    to a sibling ``_modules`` directory, and the manifest sidecar. Returns
    (merged_file_path, manifest). Cleans up after itself on failure."""
    final_path = os.path.join(upload_dir, stored_name)
    modules_dir = modules_dir_for(final_path)
    try:
        names, catalog = save_uploads(file_storages, modules_dir, allowed_ext)
        root = secure_filename(root_name) if root_name else None
        merged, manifest = build_bundle(modules_dir, names, catalog, root)
        merged.serialize(destination=final_path, format='xml')
        with open(manifest_path(final_path), 'w') as fh:
            json.dump(manifest, fh)
    except Exception:
        shutil.rmtree(modules_dir, ignore_errors=True)
        for p in (final_path, manifest_path(final_path)):
            if os.path.exists(p):
                os.remove(p)
        raise
    logger.info(f"Bundle {stored_name}: root={manifest['root']} order={manifest['order']} "
                f"unresolved={len(manifest['unresolved'])}")
    return final_path, manifest
