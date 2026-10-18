"""Compute box sizes and positions for the UML model (layered layout)."""
from __future__ import annotations

from .model import UModel, UClass

# Geometry constants (pixels).
CHAR_W = 7.2          # approx width of a 12px char
TITLE_PAD = 16
ROW_H = 18
TITLE_H = 26
PAD_X = 14
MIN_W = 90
H_GAP = 60            # horizontal gap between boxes in a layer
V_GAP = 90            # vertical gap between layers
MARGIN = 40


def _measure(c: UClass) -> None:
    longest = len(c.name) + (len(c.stereotype) + 4 if c.stereotype else 0)
    for a in c.attrs:
        longest = max(longest, len(a.label()))
    c.w = max(MIN_W, longest * CHAR_W + 2 * PAD_X)
    body = (ROW_H * len(c.attrs) + 8) if c.attrs else 0
    extra = ROW_H if c.stereotype else 0
    c.h = TITLE_H + extra + body


def _assign_layers(m: UModel) -> None:
    parents: dict[str, list[str]] = {cid: [] for cid in m.classes}
    for e in m.edges:
        if e.kind == "generalization" and e.src in m.classes and e.dst in m.classes:
            parents[e.src].append(e.dst)

    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def depth(cid: str) -> int:
        if cid in memo:
            return memo[cid]
        if cid in visiting:        # cycle guard
            return 0
        visiting.add(cid)
        ps = parents.get(cid, [])
        d = 0 if not ps else 1 + max((depth(p) for p in ps), default=-1)
        visiting.discard(cid)
        memo[cid] = d
        return d

    for cid, c in m.classes.items():
        c.layer = depth(cid)


def layout(m: UModel) -> tuple[float, float]:
    """Position every class; return (width, height) of the canvas."""
    for c in m.classes.values():
        _measure(c)
    _assign_layers(m)

    layers: dict[int, list[UClass]] = {}
    for c in m.classes.values():
        layers.setdefault(c.layer, []).append(c)

    y = MARGIN
    canvas_w = 0.0
    for li in sorted(layers):
        row = sorted(layers[li], key=lambda c: c.name.lower())
        row_h = max((c.h for c in row), default=0)
        x = MARGIN
        for c in row:
            c.x = x
            c.y = y + (row_h - c.h) / 2
            x += c.w + H_GAP
        canvas_w = max(canvas_w, x - H_GAP + MARGIN)
        y += row_h + V_GAP

    canvas_h = y - V_GAP + MARGIN
    return canvas_w, canvas_h
