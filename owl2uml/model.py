"""UML class-diagram model produced from an OWL/RDFS ontology."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Attr:
    """A datatype property rendered as a class attribute."""
    name: str
    type: str = ""

    def label(self) -> str:
        return f"{self.name}: {self.type}" if self.type else self.name


@dataclass
class Edge:
    """A relationship between two classes."""
    src: str           # class id (URI string)
    dst: str           # class id (URI string)
    kind: str          # "generalization" | "association"
    label: str = ""    # property name for associations


@dataclass
class UClass:
    """A UML class box."""
    id: str
    name: str
    attrs: list[Attr] = field(default_factory=list)
    stereotype: str = ""

    # filled in by the layout pass
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    layer: int = 0


@dataclass
class UModel:
    classes: dict[str, UClass] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def cls(self, cid: str, name: str | None = None) -> UClass:
        """Get or create a class node by id."""
        c = self.classes.get(cid)
        if c is None:
            c = UClass(id=cid, name=name or cid)
            self.classes[cid] = c
        elif name and (c.name == c.id or not c.name):
            c.name = name
        return c
