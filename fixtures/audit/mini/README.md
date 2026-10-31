# Mini audit fixtures

`clean/` is a tiny, complete release (ontology, vocabulary, shapes, one data set,
CI that runs SHACL and a reasoner). The full audit must pass it with no finding
above `info`.

Every other directory is an overlay: it holds only the files that differ from
`clean/`. `tests/test_audit.py` copies `clean/`, lays the overlay on top and
audits the result, so each case is the clean release plus exactly one defect.

| Case | Defect | Expected finding |
| --- | --- | --- |
| `ns-mismatch` | one data value uses `modality#May` instead of `modality/May` | `E_NS_MISMATCH` (R5), with the SHACL violation it causes linked to it |
| `datatype` | a property with range `xsd:duration` | `E_DATATYPE_PROFILE` (R2) |
| `inconsistent` | an individual typed into two disjoint classes | `E_ABOX_INCONSISTENT` (R3) with the minimal cause |
| `layer-conflict` | OWL `minCardinality 1`, SHACL `sh:minCount 0` | `E_LAYER_CONFLICT` (R6) |
| `self-example` | the usage example on `:Rule` omits the required `:requires` | `E_SELF_EXAMPLE` (R7) |
| `ci-no-shacl` | CI runs a reasoner but no SHACL | `W_CI_NO_SHACL` (R10) |
