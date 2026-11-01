"""Minimal-diff writing for Turtle files.

Instead of re-serialising a whole file after a change, split it into top-level
statements, keep every statement whose triples are unchanged byte for byte,
rewrite only the statements that lost or gained triples, and append triples about
new subjects at the end. The caller checks that the result parses to exactly the
intended graph and falls back to a full rewrite if it does not.
"""

import re

import rdflib
from rdflib import BNode
from rdflib.compare import to_canonical_graph

DIRECTIVE = re.compile(r"^\s*(@prefix|@base|prefix\b|base\b)", re.I)


def split_statements(text):
    """[(kind, text)] where kind is 'gap' (whitespace and comments), 'directive' or
    'statement'. Joining every text gives the input back. Returns None if the
    file cannot be split safely (unterminated string, IRI or bracket)."""
    out, i, n = [], 0, len(text)
    while i < n:
        j = i
        while j < n:                       # whitespace and comments between statements
            if text[j].isspace():
                j += 1
            elif text[j] == "#":
                while j < n and text[j] != "\n":
                    j += 1
            else:
                break
        if j > i:
            out.append(("gap", text[i:j]))
            i = j
        if i >= n:
            break
        end = _statement_end(text, i)
        if end is None:
            return None
        chunk = text[i:end]
        out.append(("directive" if DIRECTIVE.match(chunk) else "statement", chunk))
        i = end
    return out


def _statement_end(text, i):
    n = len(text)
    if re.match(r"(?i)(prefix|base)\b", text[i:i + 6]):          # SPARQL-style: ends at '>'
        close = text.find(">", i)
        return None if close < 0 else close + 1
    depth, j = 0, i
    while j < n:
        c = text[j]
        if c == "<" and not text.startswith("<=", j):
            close = text.find(">", j)
            if close < 0:
                return None
            j = close + 1
            continue
        if c in "\"'":
            q3 = text[j:j + 3]
            if q3 in ('"""', "'''"):
                close = text.find(q3, j + 3)
                while close > 0 and _escaped(text, close):
                    close = text.find(q3, close + 1)
                if close < 0:
                    return None
                j = close + 3
                continue
            k = j + 1
            while k < n and text[k] != c:
                if text[k] == "\\":
                    k += 1
                elif text[k] == "\n":
                    return None
                k += 1
            if k >= n:
                return None
            j = k + 1
            continue
        if c == "#":
            while j < n and text[j] != "\n":
                j += 1
            continue
        if c in "[(":
            depth += 1
        elif c in "])":
            depth -= 1
        elif c == "." and depth == 0 and (j + 1 >= n or text[j + 1].isspace() or text[j + 1] == "#"):
            return j + 1
        j += 1
    return None


def _escaped(text, pos):
    k, count = pos - 1, 0
    while k >= 0 and text[k] == "\\":
        count += 1
        k -= 1
    return count % 2 == 1


def _canon(g):
    out = rdflib.Graph()
    for t in to_canonical_graph(g):
        out.add(t)
    return out


def _closure(start, pool):
    """``start`` plus every triple in ``pool`` hanging off a blank node it reaches."""
    out, todo = set(start), [t[2] for t in start if isinstance(t[2], BNode)]
    while todo:
        b = todo.pop()
        for t in pool:
            if t[0] == b and t not in out:
                out.add(t)
                if isinstance(t[2], BNode):
                    todo.append(t[2])
    return out


def _body(g, namespaces):
    """Turtle for ``g`` without its @prefix lines."""
    sub = rdflib.Graph()
    for prefix, ns in namespaces:
        sub.bind(prefix, ns, override=True, replace=True)
    for t in g:
        sub.add(t)
    text = sub.serialize(format="turtle")
    lines = [line for line in text.splitlines() if not DIRECTIVE.match(line)]
    return "\n".join(lines).strip()


def splice(text, new_graph):
    """Text whose graph should equal ``new_graph`` (canonical blank nodes), or None."""
    parts = split_statements(text)
    if parts is None:
        return None
    header = "".join(t + "\n" for k, t in parts if k == "directive")
    namespaces = list(new_graph.namespaces())
    want = set(_canon(new_graph)) if any(isinstance(x, BNode) for t in new_graph for x in t) \
        else set(new_graph)
    emitted = set()
    out = []
    for kind, chunk in parts:
        if kind != "statement":
            out.append(chunk)
            continue
        g = rdflib.Graph()
        try:
            g.parse(data=header + chunk + "\n", format="turtle")
        except Exception:  # noqa: BLE001 - not splittable: let the caller rewrite the file
            return None
        has_b = any(isinstance(x, BNode) for t in g for x in t)
        mine = set(_canon(g)) if has_b else set(g)
        nodes = {s for s, _, _ in mine} | {o for _, _, o in mine if isinstance(o, BNode)}
        pending = want - emitted - mine
        # New triples on one of this statement's blank nodes must be written inside
        # it: a blank node cannot be referred to from another statement.
        if mine <= want and not any(isinstance(t[0], BNode) and t[0] in nodes for t in pending):
            out.append(chunk)
            emitted |= mine
            continue
        keep = mine & want
        extra = _closure({t for t in pending if t[0] in nodes}, pending)
        new = rdflib.Graph()
        for t in keep | extra:
            new.add(t)
        emitted |= keep | extra
        if len(new):
            out.append(_body(new, namespaces))
        elif out and out[-1].strip() == "":
            out[-1] = out[-1].rstrip("\n") + ("\n" if out[-1].count("\n") else "")
    rest = want - emitted
    result = "".join(out).rstrip("\n") + "\n"
    if rest:
        g = rdflib.Graph()
        for t in rest:
            g.add(t)
        used = {p for p, ns in namespaces if any(str(x).startswith(str(ns)) for t in rest for x in t)}
        have = set(re.findall(r"(?im)^\s*@?prefix\s+([\w-]*):", text))
        missing = [(p, ns) for p, ns in namespaces if p in used and p not in have and p]
        result = "".join(f"@prefix {p}: <{ns}> .\n" for p, ns in missing) + result if missing else result
        result += "\n" + _body(g, namespaces) + "\n"
    return result
