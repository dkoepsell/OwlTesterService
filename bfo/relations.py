"""
BFO relation signatures.

Placeholder for the deferred relation-injection work (SPEC-owltester.md Task 4),
which will encode BFO's intended domains, ranges, and characteristics for the
core object properties (inheres_in, participates_in, has_role, part_of, ...) and
expose them as an opt-in overlay during reasoning.

The public function is defined now so the bfo/ bundle API stays stable for the
sibling bfo-agent project; it returns an empty mapping until Task 4 fills it.
"""


def relation_signatures():
    """Return BFO relation domain/range/characteristic signatures.

    Currently empty. Task 4 will populate this from a vendored relation-signatures
    TTL keyed by relation IRI.
    """
    return {}
