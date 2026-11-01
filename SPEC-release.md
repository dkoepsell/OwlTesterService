# Build Spec: Audited Releases

**Target repo:** `OwlTesterService` (dkoepsell)
**Builds on:** `SPEC-audit.md` (the full artifact audit), `SPEC-audit-repair.md` (guided repair)
**Status:** plan only. No code in this change.

This spec covers two features for two audiences:

- **Part A, for experts:** the audit as a **release gate** in the ontology's own CI, a **verification record** shipped inside every release, and a command that **verifies** a release against its record. Experts keep their own build (ROBOT, ODK, Makefiles); OwlTester adds the checks those builds lack.
- **Part B, for everyone else:** a **release builder** that takes an OWL file (from Protégé, bfo-agent or Kindwork) and produces a complete, audited release, plus the git repository scaffolding that lets the author move to the Part A workflow.

Part A comes first: it is smaller, it serves the people whose adoption gives OwlTester standing, and Part B reuses all of it.

Do not introduce em-dashes into any user-facing copy, docstrings, or report templates in this project.

---

## Reference cases

| Case | Role in this spec |
| --- | --- |
| The four LOF ODP repositories | First adopters of Part A. Their CI runs `make test` (HermiT and QC queries) but never SHACL, which the audit reports as `W_CI_NO_SHACL`. Adding the Action closes it |
| `lof-odps-2026-10-31.zip` | The reference release layout and verification record (see its README, MANIFEST.json and `audit.yaml`) |
| LOMO 1.0.0 | What a gate would have stopped: the release passed its own CI and failed the audit on namespace integrity, datatypes and SHACL |
| A bfo-agent output, a Kindwork export | Part B inputs: an OWL file with no release around it |

---

## Principles

1. **Git is the source of truth.** OwlTester never becomes the canonical store of an ontology. Part A runs on the author's repository; Part B's output includes a repository to continue in.
2. **The tag is the release.** A release corresponds to one tagged commit; its version IRI, its files and its verification record all name that tag.
3. **Reproducible or it does not count.** The same source, tool version and configuration give byte-identical outputs and the same verdict, locally, in CI and on the server.
4. **Evidence, not claims.** "Audited" means a verification record exists, matches the files by checksum, and can be checked by anyone with the CLI.
5. **No network during builds or audits**, apart from the explicit, opt-in publishing steps (Part B, section 9).
6. **Access as in repair:** the web builder is closed to everyone except named accounts (section 8). The CLI and Action run wherever the author runs them.

---

# Part A: the audit as a release gate

## 1. CLI additions

The `owltester audit` command exists (`owltester/cli.py`). Add:

| Command or flag | Purpose |
| --- | --- |
| `audit --fail-on {critical,major,minor}` | Exit non-zero when any non-expected finding is at or above this severity. Default `critical`, the current behaviour (exit 1 only on `fail`). A gate typically uses `major` |
| `audit --summary-md PATH` | A short Markdown summary (verdict, scorecard, top findings) sized for a CI job summary or a pull-request comment |
| `record <release-dir> --report audit.json [--commit SHA] [--tag TAG] --out VERIFICATION.json` | Write the verification record (section 2) |
| `verify <release.zip or dir> [--reaudit]` | Check a release against its record: checksums, record integrity, and with `--reaudit` that a fresh audit gives the same verdict and findings |

Exit codes: 0 pass; 1 the gate rejected the release; 2 usage or environment error (missing Java, unreadable input). CI must be able to tell "bad release" from "broken tool".

## 2. The verification record

Two files at the root of every audited release: `VERIFICATION.json` (machine-readable) and `VERIFICATION.md` (the same, for people).

```json
{
  "record_version": "1",
  "release": {"name": "lof-odp-004", "version": "0.2.0", "tag": "v0.2.0",
              "commit": "<full sha>", "repository": "https://github.com/legal-ontologies-foundry/lof-odp-004",
              "ontology_iri": "https://w3id.org/lof/odp-004.owl",
              "version_iri": "https://w3id.org/lof/odp-004/releases/0.2.0/lof-odp-004.owl"},
  "tool": {"owltester": "<commit or src-hash>", "image": "ghcr.io/dkoepsell/owltester-cli@sha256:...",
           "robot": "1.9.6", "hermit": "...", "pyshacl": "...", "rdflib": "..."},
  "audit": {"profile": "bfo", "config_sha256": "...", "verdict": "pass", "fail_on": "major",
            "severity_counts": {"critical": 0, "major": 0, "minor": 4, "info": 4, "expected": 5},
            "expected": [{"code": "E_ABOX_INCONSISTENT", "file": "...", "reason": "..."}],
            "report_sha256": "...", "audited_at": "2026-11-15T14:02:11Z"},
  "files": [{"path": "lof-odp-004.owl", "sha256": "...", "bytes": 0}, "..."],
  "attestation": {"kind": "github-artifact-attestation", "bundle": "VERIFICATION.sigstore.json"}
}
```

- `files` lists every file in the release except the two record files and the attestation bundle. The audit report itself ships as `audit/report.json` and `audit/report.md` and is listed.
- `VERIFICATION.md` opens with one line a reader can trust at a glance: "Audited by OwlTester `<version>` on `<date>`: pass (0 critical, 0 major, 4 minor; 5 expected outcomes declared in audit.yaml)."
- **Attestation (optional, recommended in CI):** sign the record with GitHub's artifact attestations (`actions/attest-build-provenance`, Sigstore). Then `gh attestation verify` proves the record was produced by that repository's workflow at that commit. Without CI, the record is unsigned and says so.
- `verify` fails when a listed file is missing or altered, when a file is present that the record does not list (other than allowed extras: none by default), or when the record's own hashes do not match.

## 3. A container image for the CLI

The web image (Flask, gunicorn, Kindwork's Node sidecar, Postgres client) is heavier than CI needs. Add a build target that holds only the audit toolchain:

- `Dockerfile` gains `FROM ... AS cli`: Python, Java 21, ROBOT, owlready2 0.47, pyshacl, rdflib, PyYAML, the vendored BFO, and the `owltester` package, with `ENTRYPOINT ["python", "-m", "owltester.cli"]`.
- Published to GitHub Container Registry as `ghcr.io/dkoepsell/owltester-cli`, tagged by version and by commit, built by a workflow in OwlTesterService on each tag. The commit is passed as `OWLTESTER_VERSION`, so records name it.
- Callers pin the image by digest for reproducibility; the Action does so by default.

## 4. The GitHub Action

Published from a small public repository, `dkoepsell/owltester-action` (or a directory in OwlTesterService, if a separate repository is unwanted), as a Docker action over the CLI image.

**Inputs**

| Input | Default | Meaning |
| --- | --- | --- |
| `path` | `.` | Directory or zip to audit |
| `profile` | `general` | `general`, `bfo` or `sool` |
| `config` | `audit.yaml` if present | Audit configuration |
| `fail-on` | `major` | Gate threshold |
| `budget` | `900` | Seconds |
| `record` | `false` | Also write `VERIFICATION.json` / `.md` into `path` |
| `comment` | `false` | Post the summary as a pull-request comment (needs `pull-requests: write`) |

**Outputs:** `verdict`, `report-json`, `report-md`, `record` (path), `counts` (JSON).

**Behaviour:** writes the Markdown summary to the job summary; uploads the full report as a workflow artifact; fails the step per `fail-on`.

**Recommended workflows** (shipped as copy-paste templates in the Action's README):

```yaml
# .github/workflows/audit.yml: every push and pull request
on: [push, pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make -C src/ontology test        # the repository's own build, unchanged
      - uses: dkoepsell/owltester-action@v1
        with: {profile: bfo, fail-on: major, comment: true}
```

```yaml
# .github/workflows/release.yml: on a version tag
on:
  push:
    tags: ['v*']
permissions: {contents: write, id-token: write, attestations: write}
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make -C src/ontology release VERSION=${GITHUB_REF_NAME#v}
      - run: ./scripts/stage-release.sh dist/       # copies the release files (template provided)
      - id: audit
        uses: dkoepsell/owltester-action@v1
        with: {path: dist, profile: bfo, fail-on: major, record: true}
      - uses: actions/attest-build-provenance@v1
        with: {subject-path: dist/VERIFICATION.json}
      - run: cd dist && zip -r ../${{ github.event.repository.name }}-${GITHUB_REF_NAME}.zip .
      - uses: softprops/action-gh-release@v2
        with: {files: '*.zip', body_path: dist/VERIFICATION.md}
```

The release job stops before anything is published if the audit fails. The GitHub Release body is the verification summary.

## 5. Recognising the gate in R10

R10 (release hygiene) must credit a CI step that runs the OwlTester Action or `owltester audit` with **both** SHACL and reasoning, since the audit performs both. Add the patterns `dkoepsell/owltester-action`, `owltester.cli audit`, `owltester audit` to the `shacl` and `reasoning` checks in `owltester/audit/hygiene.py`. A release that carries a `VERIFICATION.json` whose checksums verify is reported in R10 as `I_VERIFIED` (info, positive).

## 6. Status badge

No server needed: the Action can write `audit-badge.json` in the shields.io endpoint format (`{"schemaVersion":1,"label":"OwlTester","message":"pass","color":"green"}`) to a `badges` branch or to GitHub Pages. The README shows it with a standard shields endpoint URL.

## 7. LOF adoption (acceptance for Part A)

1. Add `audit.yml` and `release.yml` to the four LOF pattern repositories (by pull request, reviewed by the founding coordinators). LOF does not want AI co-authorship on its GitHub work, so these commits carry no AI attribution lines.
2. Each pattern gets an `audit.yaml` declaring its designed outcomes, as the bundle already does.
3. Acceptance: on the next release of each pattern, the GitHub Release carries `VERIFICATION.json`, `VERIFICATION.md` and the attestation; `owltester verify --reaudit` on the downloaded zip passes; the audit of the bundle no longer reports `W_CI_NO_SHACL`.
4. The LOF site's release SOP (`docs/sop/release.md`) gains one step: "The release workflow audits the tag; a release is published only with its verification record."

---

# Part B: the release builder

## 8. Access

Same rules as `SPEC-audit-repair.md` section 1:

- `BUILD_ALLOWED_USERS`: empty or unset means nobody; never anonymous; builds belong to the account that started them.
- For now, the owner only. Collaborators later through the same per-item sharing (reviewer, approver), with only the owner able to publish (section 9).
- The CLI form (`owltester build`) runs wherever its user runs it, like `audit`.

## 9. What the builder does

Input: one OWL file in any format OwlTester reads, optionally with SHACL shapes, controlled vocabularies, example data and a previous release zip.

A guided sequence, one page per step, each step saved so it can be resumed:

**1. Identity and metadata.** The builder reads what the file already declares and asks only for what is missing or wrong:

| Field | Source and checks |
| --- | --- |
| Title, description | From `dcterms:title`/`rdfs:label` and `dcterms:description`; required |
| Ontology IRI and base | Read from the header; checked against the IRIs of the ontology's own terms (a mismatch is the LOMO namespace problem waiting to happen). Persistent-IRI guidance: suggest `https://w3id.org/<project>/` and generate the w3id `.htaccess` (section 11) |
| Version | Semantic version; suggested from the diff against the previous release when one is given (new terms: minor; removed terms or changed logical axioms: major; labels and definitions only: patch), via `robot diff` |
| Version IRI | Generated: `<base>/releases/<version>/<name>.owl` |
| License | Choice list (CC BY 4.0 default, CC0, others); writes `dcterms:license` and the LICENSE text |
| Creators, contributors | Names and optional ORCID iDs; written to the header and to CITATION.cff |
| Prior version | Filled from the previous release, if given |

**2. Imports and BFO.** Detect `owl:imports` and external terms. For BFO, offer to import the vendored BFO 2020 whole, or a module extracted with `robot extract --method BOT` for the terms used (the LOF pattern). Unresolvable imports must be supplied or removed before continuing. Writes `imports/` and `catalog-v001.xml`.

**3. Build.** With ROBOT, offline:
- `<name>-base.owl`: the ontology's own axioms, imports removed;
- `<name>.owl`: merged with imports and reasoned (HermiT; `--equivalent-classes-allowed asserted-only`), as the LOF Makefile does;
- `<name>.ttl` and optionally `<name>.ofn`, `<name>.jsonld`.

**4. Documentation.** Generated from the ontology, editable before packaging:
- `README.md`: title, IRI, version, scope (from the description), how to load it, how to cite;
- `docs/terms.md`: one table per kind (classes, object properties, data properties), with label, IRI, BFO parent, definition; missing labels or definitions are listed for the author to fill, not invented;
- `docs/diagram.svg`: the class hierarchy (the existing UML generator);
- `CHANGELOG.md`: a new entry drafted from the diff against the previous release;
- `NOTICE` (attribution for BFO and other imports), `CITATION.cff`.

**5. Quality layer.** Optional but encouraged, each with a starter the author edits:
- QC queries (the LOF set: missing label, missing definition, duplicate label, IRI pattern, no BFO ancestor);
- competency questions as SPARQL, with the author's expected answers;
- SHACL shapes: a scaffold generated from the ontology's axioms (`shacl_tools.generate_shapes`, which exists), to review;
- examples: carried over if supplied.

**6. Audit and repair.** Run the full audit on the assembled release. If it fails at the chosen threshold, offer guided repair (`SPEC-audit-repair.md`) on the assembled release; repairs are applied to the build, and the audit runs again. The author can declare expected outcomes, which are written to `audit.yaml`.

**7. Package.** Write `audit.yaml`, the verification record (section 2, unsigned, with `"attestation": null`), `MANIFEST` checksums, and the zip.

**8. Repository scaffold (the on-ramp to Part A).** Alongside the zip, offer `<name>-repo.zip`: the same content laid out as a git repository the author can push, so the next release is made with git and the Action:

```
src/ontology/<name>-edit.ttl     the source, as Turtle
src/ontology/imports/            BFO module, other imports
src/ontology/catalog-v001.xml
src/ontology/Makefile            test, release targets (LOF template)
src/shapes/ src/examples/ src/sparql/
.github/workflows/audit.yml      section 4 templates, filled in
.github/workflows/release.yml
audit.yaml  README.md  CHANGELOG.md  LICENSE  NOTICE  CITATION.cff
```

**9. Publish (optional, owner only, explicit confirmation each time).** With the owner's own GitHub token (stored per user, encrypted, never a server token): create the repository or push a branch, tag, and create a GitHub Release with the zip. Zenodo: link the repository through Zenodo's GitHub integration (the author does this once on Zenodo; the builder only explains it). OwlTester never serves release files as their permanent home.

## 10. Templates

All generated text files (Makefile, workflows, README, CITATION.cff, NOTICE, `.htaccess`) come from fixed templates in `owltester/release/templates/`, with named slots filled from validated fields. No free-form text is ever written into a Makefile or workflow.

## 11. Persistent IRIs

For a `w3id.org` base, generate the `.htaccess` the w3id.org repository expects (a redirect for the plain IRI to the latest release, and for `releases/<version>/` to the tagged files), and the text of a pull request to `perma-id/w3id.org`. The builder does not submit it.

## 12. Execution and limits

As for the audit: a background job with a sidecar (`jobs.py` pattern), budgets (build 300 s, audit as configured), no network, no execution of uploaded content, size limits. Builds are deterministic: the same inputs and answers give byte-identical zips (fixed timestamps in the zip, sorted entries, stable serialisation).

---

## 13. Interfaces

- **CLI:** `owltester audit` (with section 1 flags), `owltester record`, `owltester verify`, `owltester build <file.owl> --answers build.yaml --out dist/` (the builder's answers can be supplied as a file, so a build is repeatable without the web pages).
- **Web:** `/release/new` (owner-only) leading through the steps; `/release/<build_id>` for status, outputs and the audit; publish actions as POSTs with confirmation.
- **Action:** section 4.

---

## 14. Tests and fixtures

**Part A**
- `record` then `verify` on the LOF bundle: passes; altering one byte of any listed file, adding an unlisted file, or editing the record makes `verify` fail with a message naming the file.
- `verify --reaudit` reproduces the verdict and finding codes recorded.
- `--fail-on major` exits 1 on the LOF bundle without the CI fix (`W_CI_NO_SHACL`) and 0 with the Action workflow added.
- R10 credits `owltester-action` as SHACL and reasoning.
- The Action runs end to end on a fixture repository in OwlTesterService's own CI (`act` locally, or a workflow on a test repository).

**Part B**
- Build from `lof-odp-001`'s edit file with answers matching its 0.1.0 release: `robot diff` between the built and committed `lof-odp-001.owl` is empty apart from header annotations the builder adds.
- Build from a bfo-agent output fixture: the zip has every part listed in section 9, the audit runs, missing labels are listed rather than invented.
- The repository scaffold runs `make test` successfully and its workflows pass `actionlint`.
- Determinism: two builds from the same inputs give identical zips.
- Access: empty `BUILD_ALLOWED_USERS` refuses everyone; publish refuses non-owners.

---

## 15. Open decisions

1. Action home: a separate public repository (`dkoepsell/owltester-action`, the usual form for Marketplace actions) or a directory in OwlTesterService? (This spec: separate repository.)
2. Should the LOF repositories adopt the Action through pull requests reviewed by Mandrick and Smith, or start in one pattern (ODP-004) as a trial? (This spec: ODP-004 first.)
3. Should the record be signed only in CI (GitHub attestations), or should the web builder also sign, which needs a server key? (This spec: CI only; web builds are unsigned and say so.)
4. Default gate threshold: `major` or `critical`? (This spec: `major` for releases, `critical` for pushes.)
5. Should Part B require competency questions before packaging, or only encourage them? (This spec: encourage.)

---

## Suggested order

1. **A1:** CLI flags (`--fail-on`, `--summary-md`), `record`, `verify`, R10 recognition. Tests on the LOF bundle.
2. **A2:** the `cli` image target and its publishing workflow; the Action and its templates.
3. **A3:** LOF adoption, starting with ODP-004 (section 7).
4. **B1:** builder core: metadata, imports, build, audit, package (CLI `build` first, then the pages).
5. **B2:** documentation generation, quality-layer starters, guided repair hook.
6. **B3:** repository scaffold, w3id files, publish to GitHub.
