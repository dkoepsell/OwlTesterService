"""Audited releases (SPEC-release.md).

Part A, the audit as a release gate:
    gate.py      --fail-on thresholds, the CI summary, the shields badge
    record.py    the verification record (VERIFICATION.json / .md) and ``verify``
    tools.py     tool versions for the record, and how to run ROBOT
    action.py    the GitHub Action's entry point (runs inside the CLI image)

Part B, the release builder (OWL file in, audited release out):
    answers.py   the builder's answers (build.yaml), validated
    metadata.py  identity, header and version suggestion
    imports.py   owl:imports, BFO (whole or a BOT module), the catalog
    robot.py     the ROBOT steps (base, full, formats, diff), offline
    docs.py      README, terms table, diagram, CHANGELOG, NOTICE, CITATION.cff
    quality.py   QC queries, competency-question and SHACL starters
    package.py   audit.yaml, record, MANIFEST, zips, repository scaffold, w3id
    builder.py   the steps in order (CLI ``build`` and the web pages)
    templates/   every generated Makefile, workflow and text file
"""
