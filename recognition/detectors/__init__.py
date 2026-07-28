"""Detectors, partitioned by instrument (paper §6.3, Table 7).

One module per detectability class, because the partition is a matter of
principle rather than of tooling maturity:

    dl          description-logic reasoner
    structural  structural analysis of axioms
    world       world-facing data          (see stratum_d)
    process     process-level modelling    (see stratum_d)

The report's coverage footer is derived from which of these actually ran, so
that a stratum nobody looked at is reported unassessed rather than clean. This
is the concrete form of the paper's constraint that a reasoner is necessary and
never sufficient.

``prover`` is not a fifth instrument. It promotes a structural suspicion to a
demonstrated unintended model where a finite model finder can witness one, and
deliberately attempts no primitive of its own -- so a missing Mace4 weakens
evidence without ever changing which strata read as assessed.
"""

from . import dl, prover, stratum_d, structural

__all__ = ["dl", "prover", "stratum_d", "structural"]
