"""Ontology-specific context for AI implication generation.

The implications prompt used to receive only placeholder premises
(``instance_of(x, C, t)`` per class, ``r(x, y, t)`` per property), which carry no
logical content, so the model fell back on generic statements about the domain
name. This module gathers what actually distinguishes an ontology -- its
asserted and inferred axioms (already label-rendered by the analysis), the
textual definitions of its own terms, its individuals and known problems -- and
gives each item a citable ID (A#, I#, D#) so generated implications can be
checked against, and displayed with, the axioms they rest on.
"""
import logging
import re

logger = logging.getLogger(__name__)

# Upstream/foundational vocabulary (BFO, RO, IAO, ...) is context, not the
# ontology's own content; axioms purely among such terms are dropped.
_UPPER_ID = re.compile(r'^(BFO|RO|IAO|OBI|COB|UO|PATO)_\d+$')
_TOKEN = re.compile(r'[\w.\-]+')

# Axiom kinds most likely to yield non-obvious consequences come first.
_AXIOM_PRIORITY = {'EquivalentClass': 0, 'DisjointWith': 1, 'SubClassOf': 2,
                   'Domain': 3, 'Range': 3}

MAX_AXIOMS = 200
MAX_INFERRED = 50
MAX_DEFINITIONS = 120
MAX_TERMS = 300
MAX_INDIVIDUALS = 50
MAX_TEXT = 300


def _is_upper(name):
    return bool(_UPPER_ID.match(name or ''))


def _clip(text, n=MAX_TEXT):
    text = ' '.join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + '…'


def _names(items):
    """Entity names from a stored list of strings or {'name': ...} dicts."""
    out = []
    for item in items or []:
        name = item.get('name') if isinstance(item, dict) else item
        if isinstance(name, str) and name and name not in ('Thing', 'Nothing'):
            out.append(name)
    return out


def _term(name, labels):
    label = labels.get(name)
    return f"{name} ({label})" if label and label != name else name


def _mentions_domain(axiom, domain):
    raw = axiom.get('description_ids') or axiom.get('description') or ''
    return any(tok in domain for tok in _TOKEN.findall(raw))


def _definitions(file_path, domain, labels):
    """Textual definitions/comments for the ontology's own terms, read from the
    stored file. Best-effort: a parse failure only loses this section."""
    if not file_path:
        return []
    try:
        import rdflib
        from rdflib.namespace import RDFS, SKOS
        from owl_format_detector import parse_rdf_file
        g = parse_rdf_file(file_path)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Implication context: could not read definitions from {file_path}: {e}")
        return []

    iao_def = rdflib.URIRef('http://purl.obolibrary.org/obo/IAO_0000115')
    found = {}
    for pred in (iao_def, SKOS.definition, RDFS.comment):  # most specific first
        for s, o in g.subject_objects(pred):
            if not isinstance(s, rdflib.URIRef) or not isinstance(o, rdflib.Literal):
                continue
            lang = (o.language or '').lower()
            if lang and not lang.startswith('en'):
                continue
            name = re.split(r'[#/]', str(s))[-1]
            if name in domain and name not in found and str(o).strip():
                found[name] = str(o)
    return [f"{_term(n, labels)}: {_clip(found[n])}" for n in sorted(found)][:MAX_DEFINITIONS]


def build_context(analysis, file_path=None):
    """Collect the citable, ontology-specific material for one analysis."""
    labels = analysis.entity_labels or {}
    classes = [n for n in _names(analysis.class_list) if not _is_upper(n)]
    obj_props = [n for n in _names(analysis.object_property_list) if not _is_upper(n)]
    data_props = [n for n in _names(analysis.data_property_list) if not _is_upper(n)]
    individuals = [n for n in _names(analysis.individual_list) if not _is_upper(n)]
    domain = set(classes) | set(obj_props) | set(data_props) | set(individuals)

    asserted = [a for a in (analysis.axioms or [])
                if isinstance(a, dict) and a.get('description') and _mentions_domain(a, domain)]
    asserted.sort(key=lambda a: (_AXIOM_PRIORITY.get(a.get('type'), 4),
                                 not a.get('anonymous')))
    axioms = [{'id': f"A{i}", 'type': a.get('type', 'Axiom'),
               'text': _clip(a['description'])}
              for i, a in enumerate(asserted[:MAX_AXIOMS], 1)]

    inferred_src = [a for a in (analysis.inferred_axioms or [])
                    if isinstance(a, dict) and a.get('description')]
    inferred = [{'id': f"I{i}", 'type': a.get('type', 'Inferred'),
                 'text': _clip(a['description'])}
                for i, a in enumerate(inferred_src[:MAX_INFERRED], 1)]

    definitions = [{'id': f"D{i}", 'text': text}
                   for i, text in enumerate(_definitions(file_path, domain, labels), 1)]

    problems = []
    for cls in analysis.unsatisfiable_classes or []:
        name = cls.get('label') or cls.get('name') if isinstance(cls, dict) else cls
        if name:
            problems.append(f"Unsatisfiable class (can have no instances): {name}")

    return {
        'ontology_name': analysis.ontology_name or 'Unnamed ontology',
        'ontology_iri': analysis.ontology_iri or '',
        'classes': [_term(n, labels) for n in classes[:MAX_TERMS]],
        'object_properties': [_term(n, labels) for n in obj_props[:MAX_TERMS]],
        'data_properties': [_term(n, labels) for n in data_props[:MAX_TERMS]],
        'individuals': [_term(n, labels) for n in individuals[:MAX_INDIVIDUALS]],
        'axioms': axioms,
        'inferred': inferred,
        'definitions': definitions,
        'problems': problems[:10],
    }


def render_context(ctx):
    """The context as prompt text, one citable item per line."""
    parts = [f"Ontology: {ctx['ontology_name']}"]
    if ctx['ontology_iri']:
        parts.append(f"IRI: {ctx['ontology_iri']}")

    def section(title, lines):
        if lines:
            parts.append(f"\n## {title}\n" + '\n'.join(lines))

    section("Classes", [', '.join(ctx['classes'])] if ctx['classes'] else [])
    section("Object properties", [', '.join(ctx['object_properties'])] if ctx['object_properties'] else [])
    section("Data properties", [', '.join(ctx['data_properties'])] if ctx['data_properties'] else [])
    section("Named individuals", [', '.join(ctx['individuals'])] if ctx['individuals'] else [])
    section("Asserted axioms (⊑ subclass of, ≡ equivalent to, ⊥ disjoint with)",
            [f"{a['id']} [{a['type']}] {a['text']}" for a in ctx['axioms']])
    section("Inferred by the reasoner", [f"{a['id']} [{a['type']}] {a['text']}" for a in ctx['inferred']])
    section("Definitions of this ontology's terms", [f"{d['id']} {d['text']}" for d in ctx['definitions']])
    section("Known problems", ctx['problems'])
    return '\n'.join(parts)


def citable(ctx):
    """ID -> display text for every citable item in the context."""
    items = {a['id']: f"{a['id']}: {a['text']}" for a in ctx['axioms'] + ctx['inferred']}
    items.update({d['id']: f"{d['id']}: {d['text']}" for d in ctx['definitions']})
    return items


def resolve_citations(implications, ctx):
    """Replace cited IDs with the axiom text they name, and drop implications
    that cite nothing from the ontology (the generic kind this module exists to
    prevent) -- unless that would leave none at all."""
    lookup = citable(ctx)
    if not lookup:
        return implications
    grounded = []
    for imp in implications:
        if not isinstance(imp, dict):
            continue
        cited = imp.get('premises_used') or []
        if isinstance(cited, str):
            cited = [cited]
        resolved, hits = [], 0
        for ref in cited:
            ids = re.findall(r'\b[AID]\d+\b', str(ref))
            known = [lookup[i] for i in ids if i in lookup]
            if known:
                hits += 1
                resolved.extend(k for k in known if k not in resolved)
            else:
                resolved.append(str(ref))
        imp['premises_used'] = resolved
        if hits:
            grounded.append(imp)
    return grounded or implications
