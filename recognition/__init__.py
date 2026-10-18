"""Recognition-layer evaluation of social ontologies.

The gate in ``owltester/`` asks whether an artifact is a well-formed *logical*
object. This package asks the further question the Recognition Layer paper
poses: what kind of *institutional* object is it, and where along its
recognition chain does it break?

Two ideas carry the whole package.

1. ``typology = kernel x chain`` (paper §6.2). Twelve domain-neutral
   contradiction primitives, instantiated over the loci of a domain's
   recognition chain, generate that domain's contradiction typology as
   theorems rather than as a hand-enumerated list.

2. A reasoner is necessary and never sufficient (§6.3). The primitives
   partition by the *instrument* each requires, and half the kernel is
   invisible to description logic in principle. Any report that lists only
   reasoner output is reporting Stratum A plus part of C and silently scoring
   the rest as zero. Everything here is arranged so that "not assessed" is a
   first-class verdict that can never be mistaken for "clean".
"""

from .kernel import (
    CHAIN_LOCI,
    CLASSIFICATORY_TYPES,
    INSTRUMENTS,
    KERNEL,
    STRATA,
    SYSTEM_CLASSES,
    classificatory_type,
    primitive,
)

__all__ = [
    "CHAIN_LOCI",
    "CLASSIFICATORY_TYPES",
    "INSTRUMENTS",
    "KERNEL",
    "STRATA",
    "SYSTEM_CLASSES",
    "classificatory_type",
    "primitive",
]
