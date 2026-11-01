"""Documentation generated from the ontology (SPEC-release.md, section 9.4), and
the template renderer every generated text file goes through (section 10).

Missing labels and definitions are listed for the author to fill, never invented.
"""

import os
import re
from xml.sax.saxutils import escape

from rdflib import RDFS, URIRef

from . import metadata
from .answers import LICENSES, version_iri

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
SLOT = re.compile(r"\{\{([a-z_]+)\}\}")
BFO_ENTITY = "http://purl.obolibrary.org/obo/BFO_0000001"


class TemplateError(ValueError):
    pass


def render(_template, **slots):
    """Fill templates/<_template>.tmpl. Every slot must be given, and only those."""
    name = _template
    with open(os.path.join(TEMPLATES, name + ".tmpl"), encoding="utf-8") as fh:
        text = fh.read()
    wanted = set(SLOT.findall(text))
    missing, extra = wanted - set(slots), set(slots) - wanted
    if missing or extra:
        raise TemplateError(f"{name}: missing slots {sorted(missing)}, unknown slots {sorted(extra)}")
    for k, v in slots.items():
        if "{{" in str(v):
            raise TemplateError(f"{name}: slot {k} contains a placeholder")
    return SLOT.sub(lambda m: str(slots[m.group(1)]), text)


def _cell(text):
    return " ".join(str(text or "").split()).replace("|", "\\|")


def _yaml_str(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def holders(a):
    return ", ".join(p["name"] for p in a["creators"])


def bfo_parent(g, s, bfo_labels):
    """The nearest BFO ancestor of class ``s`` (breadth first over rdfs:subClassOf)."""
    seen, frontier = {s}, [s]
    while frontier:
        nxt = []
        for c in frontier:
            for sup in sorted(g.objects(c, RDFS.subClassOf), key=str):
                if not isinstance(sup, URIRef) or sup in seen:
                    continue
                if str(sup).startswith("http://purl.obolibrary.org/obo/BFO_"):
                    return str(sup), bfo_labels.get(str(sup), str(sup).rsplit("/", 1)[-1])
                seen.add(sup)
                nxt.append(sup)
        frontier = nxt
    return None, None


def terms(g, a):
    """Rows per kind for docs/terms.md, and the gaps (missing labels / definitions)."""
    own = metadata.own_terms(g, a["ontology_iri"])
    lab = metadata.labels(g)
    rows, gaps = {}, {"label": [], "definition": []}
    for iri, kind in sorted(own.items(), key=lambda x: (x[1], lab.get(x[0], x[0]).lower(), x[0])):
        if kind == "annotation property" and not iri.startswith(a["base"].rsplit("/", 1)[0]):
            continue
        d = metadata.definition(g, iri)
        parent = bfo_parent(g, URIRef(iri), lab) if kind == "class" else (None, None)
        rows.setdefault(kind, []).append({"iri": iri, "label": lab.get(iri), "definition": d,
                                          "bfo": parent[1], "bfo_iri": parent[0]})
        if not lab.get(iri):
            gaps["label"].append(iri)
        if not d:
            gaps["definition"].append(iri)
    return rows, gaps


def terms_md(g, a):
    rows, gaps = terms(g, a)
    out = [f"# Terms of {a['title']} {a['version']}", ""]
    titles = {"class": "Classes", "object property": "Object properties",
              "data property": "Data properties", "annotation property": "Annotation properties",
              "individual": "Individuals"}
    for kind in ("class", "object property", "data property", "annotation property", "individual"):
        if not rows.get(kind):
            continue
        out += [f"## {titles[kind]}", "", "| Label | IRI | BFO parent | Definition |", "| --- | --- | --- | --- |"]
        for r in rows[kind]:
            out.append(f"| {_cell(r['label']) or '*(no label)*'} | `{r['iri']}` | {_cell(r['bfo']) or ''} | "
                       f"{_cell(r['definition']) or '*(no definition)*'} |")
        out.append("")
    out += ["## To complete", ""]
    if gaps["label"] or gaps["definition"]:
        out.append("These terms need text from the author; the builder does not invent it.")
        out.append("")
        out += [f"- no label: `{t}`" for t in gaps["label"]]
        out += [f"- no definition: `{t}`" for t in gaps["definition"]]
    else:
        out.append("Every term has a label and a definition.")
    return "\n".join(out) + "\n", gaps


def diagram_svg(g, a):
    """The class hierarchy as a plain SVG tree (offline, deterministic)."""
    own = {t for t, k in metadata.own_terms(g, a["ontology_iri"]).items() if k == "class"}
    lab = metadata.labels(g)
    name = lambda t: lab.get(t) or t.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    parents = {t: sorted(str(o) for o in g.objects(URIRef(t), RDFS.subClassOf)
                         if isinstance(o, URIRef) and (str(o) in own or str(o).startswith(
                             "http://purl.obolibrary.org/obo/BFO_"))) for t in own}
    children = {}
    for t, ps in parents.items():
        for p in ps:
            children.setdefault(p, []).append(t)
    roots = sorted({p for ps in parents.values() for p in ps if p not in own} |
                   {t for t, ps in parents.items() if not ps}, key=lambda t: name(t).lower())
    lines, seen = [], set()

    def walk(t, depth):
        lines.append((depth, t, t not in own))
        if t in seen:
            return
        seen.add(t)
        for c in sorted(children.get(t, []), key=lambda x: name(x).lower()):
            walk(c, depth + 1)

    for r in roots:
        walk(r, 0)
    lines = lines[:2000]
    h, width = 24, max([60] + [d * 24 + len(name(t)) * 8 + 40 for d, t, _ in lines])
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{len(lines) * h + 40}" '
           f'font-family="sans-serif" font-size="13">',
           f'<title>{escape(a["title"])}: class hierarchy</title>',
           f'<text x="10" y="20" font-weight="bold">{escape(a["title"])} {escape(a["version"])}</text>']
    for i, (depth, t, foreign) in enumerate(lines):
        y = 44 + i * h
        x = 10 + depth * 24
        if depth:
            out.append(f'<path d="M{x - 16} {y - 18} V{y - 4} H{x - 4}" fill="none" stroke="#999"/>')
        fill = "#666" if foreign else "#000"
        out.append(f'<text x="{x}" y="{y}" fill="{fill}">{escape(name(t))}'
                   f'<title>{escape(t)}</title></text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def citation(a):
    names = "; ".join(p["name"] for p in a["creators"])
    return f"{names} ({a['release_date'][:4]}). *{a['title']}*, version {a['version']}. {version_iri(a)}"


def citation_cff(a):
    authors = []
    for p in a["creators"]:
        parts = p["name"].rsplit(" ", 1)
        entry = (f"  - family-names: {_yaml_str(parts[-1])}\n    given-names: {_yaml_str(parts[0])}"
                 if len(parts) == 2 else f"  - name: {_yaml_str(p['name'])}")
        if p.get("orcid"):
            entry += f"\n    orcid: \"https://orcid.org/{p['orcid']}\""
        authors.append(entry)
    keywords = ("keywords:\n" + "\n".join(f"  - {_yaml_str(k)}" for k in a["keywords"])) if a["keywords"] else ""
    return render("CITATION.cff", title_yaml=_yaml_str(a["title"]), version=a["version"],
                  release_date=a["release_date"], license=a["license"],
                  repository_line=(f"repository-code: {a['repository']}\n" if a["repository"] else ""),
                  ontology_iri=a["ontology_iri"], version_iri=version_iri(a),
                  authors="\n".join(authors), keywords=keywords).rstrip() + "\n"


def readme(a, files):
    lic = LICENSES[a["license"]]
    return render("README.md", title=a["title"], description=a["description"],
                  ontology_iri=a["ontology_iri"], version=a["version"], version_iri=version_iri(a),
                  license_name=lic[0], license_url=lic[1], release_date=a["release_date"],
                  files="\n".join(f"- `{f}`: {d}" for f, d in files), name=a["name"],
                  citation=citation(a))


def notice(a, import_files):
    lic = LICENSES[a["license"]]
    attributions = []
    for rel in sorted(import_files):
        if "bfo" in rel.lower():
            attributions.append(f"- `{rel}`: Basic Formal Ontology (BFO) 2020, ISO/IEC 21838-2, "
                                "by Barry Smith et al., CC BY 4.0, http://purl.obolibrary.org/obo/bfo.owl")
        else:
            attributions.append(f"- `{rel}`: see the license stated in that file's header.")
    return render("NOTICE", title=a["title"], year=a["release_date"][:4], holders=holders(a),
                  license_name=lic[0], license_url=lic[1],
                  attributions="\n".join(attributions) or "- (no imported material)")


def license_text(a):
    lic = LICENSES[a["license"]]
    return render("LICENSE", title=a["title"], year=a["release_date"][:4], holders=holders(a),
                  license_name=lic[0], license_url=lic[1])


def changelog(a, changes=None, diff_md="", previous_log=""):
    """A new CHANGELOG entry drafted from the diff against the previous release."""
    out = ["# Changelog", "", f"## {a['version']} ({a['release_date']})", ""]
    if changes is None:
        out.append("- First release.")
    else:
        if changes.get("added"):
            out += [f"- Added `{t}`" for t in changes["added"][:200]]
        if changes.get("removed"):
            out += [f"- Removed `{t}`" for t in changes["removed"][:200]]
        if not changes.get("added") and not changes.get("removed"):
            out.append(f"- {changes.get('reason') or 'Revised axioms and annotations'}.")
        if diff_md.strip():
            out += ["", "<details><summary>robot diff against the previous release</summary>", "",
                    diff_md.strip()[:20000], "", "</details>"]
    old = previous_log.split("\n", 1)[1].lstrip("\n") if previous_log.startswith("# Changelog") else previous_log
    if old.strip():
        out += ["", old.strip()]
    return "\n".join(out) + "\n"
