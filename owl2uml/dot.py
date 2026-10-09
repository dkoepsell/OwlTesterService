"""Render a UModel to SVG via Graphviz `dot` (scalable layered layout).

Locates a `dot` binary on PATH (graphviz in the Docker image) and renders
UML class boxes using Graphviz HTML-like table labels.

Vendored from the standalone owl2uml tool (owltouml.davidkoepsell.com).
"""
from __future__ import annotations

import shutil
import subprocess
from html import escape as _h

from .model import UModel, UClass


def _gv() -> tuple[str | None, dict | None]:
    """Return (dot_path, env) from the system PATH."""
    sysdot = shutil.which("dot")
    return (sysdot, None) if sysdot else (None, None)


def dot_available() -> bool:
    return _gv()[0] is not None


def _attr(s: str) -> str:
    """Escape a value used inside a double-quoted DOT string."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# Wrap class titles longer than this (in characters) onto multiple lines.
# rdfs:labels can be whole phrases ("inference from background scientific
# knowledge"); without wrapping a single box would stretch across the diagram.
_WRAP_AT = 24


def _wrap(text: str, width: int = _WRAP_AT) -> list[str]:
    """Greedy word-wrap; falls back to hard-splitting tokens longer than width."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        while len(word) > width:
            head, word = word[:width], word[width:]
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(head)
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [text]


# PlantUML-style palette for class boxes: light border, faint green-tinted
# header, white body, and a green disc "C" class icon.
_BORDER = "#A0A0A0"
_HEADER_BG = "#EEF6EE"
_BODY_BG = "#FFFFFF"
_ICON_BG = "#84BE84"
_ICON_BORDER = "#5B9A5B"


def _icon() -> str:
    """A small green rounded 'C' badge, mimicking PlantUML's class icon."""
    return (
        f'<table border="1" color="{_ICON_BORDER}" cellborder="0" '
        f'cellspacing="0" cellpadding="0" bgcolor="{_ICON_BG}" style="rounded">'
        '<tr><td width="15" height="15" align="center">'
        '<font color="white" point-size="10"><b>C</b></font>'
        '</td></tr></table>'
    )


def _label(c: UClass) -> str:
    """HTML-like table label for one UML class box (PlantUML-style)."""
    title = ""
    if c.stereotype:
        title += f'<font point-size="9">&#171;{_h(c.stereotype)}&#187;</font><br/>'
    title += "<br/>".join(f"<b>{_h(line)}</b>" for line in _wrap(c.name))
    # Header: green class icon to the left of the (optionally stereotyped) name.
    header = (
        '<table border="0" cellborder="0" cellspacing="0" cellpadding="0"><tr>'
        f'<td valign="middle">{_icon()}</td>'
        '<td width="6"></td>'
        f'<td valign="middle">{title}</td>'
        '</tr></table>'
    )
    rows = [
        f'<table border="1" color="{_BORDER}" cellborder="0" cellspacing="0" '
        f'cellpadding="6" bgcolor="{_BODY_BG}">',
        f'<tr><td bgcolor="{_HEADER_BG}" align="center">{header}</td></tr>',
    ]
    if c.attrs:
        rows.append("<hr/>")
        body = "<br/>".join(_h(a.label()) for a in c.attrs)
        rows.append(f'<tr><td align="left" balign="left">{body}</td></tr>')
    rows.append("</table>")
    return "".join(rows)


# Above this many classes, use straight-line edges: spline/polyline routing
# becomes slow and unreliable on large, dense graphs.
_SPLINE_LIMIT = 300

# Above this many classes the hierarchical `dot` engine becomes prohibitively
# slow (super-linear), so we switch to `sfdp` (scalable force-directed).
_SFDP_LIMIT = 500

# Hard cap on how long `dot` may run before we fall back to `sfdp`.
_DOT_TIMEOUT_S = 45


def _engine_for(m: UModel) -> str:
    return "sfdp" if len(m.classes) > _SFDP_LIMIT else "dot"


def to_dot(m: UModel) -> str:
    # Curved splines look best for small diagrams; straight lines scale.
    splines = "true" if len(m.classes) <= _SPLINE_LIMIT else "line"
    # sfdp ignores rankdir/ranksep; overlap removal keeps boxes from stacking.
    big = len(m.classes) > _SFDP_LIMIT
    overlap = '  graph [overlap="prune", sep="+8"];\n' if big else ""
    lines = [
        "digraph G {",
        overlap +
        f'  graph [rankdir=BT, bgcolor="#f7f5ef", splines={splines}, '
        "nodesep=0.4, ranksep=0.7, pad=0.3];",
        '  node [shape=plaintext, fontname="Helvetica,Arial,sans-serif", fontsize=12];',
        '  edge [fontname="Helvetica,Arial,sans-serif", fontsize=10];',
    ]
    ids: dict[str, str] = {}
    for i, (cid, c) in enumerate(m.classes.items()):
        nid = f"n{i}"
        ids[cid] = nid
        lines.append(f'  {nid} [label=<{_label(c)}>, tooltip="{_attr(cid)}"];')

    for e in m.edges:
        if e.src not in ids or e.dst not in ids:
            continue
        s, d = ids[e.src], ids[e.dst]
        if e.kind == "generalization":
            lines.append(
                f'  {s} -> {d} [arrowhead=empty, color="#33312e", penwidth=1.2];'
            )
        else:
            lbl = f', label="{_attr(e.label)}"' if e.label else ""
            lines.append(
                f'  {s} -> {d} [arrowhead=vee, color="#3a5a8c", '
                f"fontcolor=\"#3a5a8c\", constraint=false{lbl}];"
            )
    lines.append("}")
    return "\n".join(lines)


def _run_engine(dot: str, engine: str, src: bytes, env: dict | None,
                timeout: float | None) -> subprocess.CompletedProcess:
    # `dot` is the binary; -K selects the actual layout engine (dot/sfdp/...).
    return subprocess.run(
        [dot, f"-K{engine}", "-Tsvg"],
        input=src, capture_output=True, env=env, timeout=timeout,
    )


def render_dot_svg(m: UModel) -> str:
    dot, env = _gv()
    if not dot:
        raise RuntimeError("graphviz 'dot' not found (run scripts/setup.sh)")
    src = to_dot(m).encode("utf-8")
    engine = _engine_for(m)

    try:
        timeout = _DOT_TIMEOUT_S if engine == "dot" else None
        proc = _run_engine(dot, engine, src, env, timeout)
    except subprocess.TimeoutExpired:
        # `dot` is too slow for this graph; fall back to the scalable engine.
        proc = _run_engine(dot, "sfdp", src, env, None)

    out = proc.stdout.decode("utf-8")
    # On large/dense graphs the engine may emit recoverable warnings (e.g.
    # "trouble in init_rank") and exit non-zero while still producing a valid
    # SVG. Accept the output whenever it actually contains an <svg> element.
    if "<svg" in out:
        return out
    raise RuntimeError(proc.stderr.decode("utf-8", "replace") or "dot produced no SVG")
