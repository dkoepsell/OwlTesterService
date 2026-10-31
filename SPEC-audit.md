# Build Spec: Full Artifact Audit

**Target repo:** `OwlTesterService` (dkoepsell)
**Role of this feature:** audit a *released ontology artifact* (ontology, controlled vocabularies, SHACL shapes and instance data, usually shipped as a zip) the way a careful reviewer would, and produce one report with a scorecard, located findings and suggested fixes.
**Goal:** what was done by hand for LOMO 1.0.0 on 31 Oct 2026 (see "Reference case") becomes one upload and one report.
**Status:** built. Code in `owltester/audit/` (engine), `owltester/audit_service.py` (HTTP), `templates/audit_*.html`; tests in `tests/test_audit.py`; fixtures in `fixtures/audit/`. The JSON report is documented in the appendix.

Do not introduce em-dashes into any user-facing copy, docstrings, or report templates in this project.

---

## Reference case: LOMO 1.0.0

The EU Publications Office's Legal Obligation Metadata Ontology (`lomo-v1.0.0.zip`, CC BY 4.0, 368 files, 72 Turtle files, 31,368 triples) was audited by hand with rdflib, pyshacl and HermiT. The findings are the acceptance target for this spec. Every one of them must be found by the audit without hand work:

| ID | Finding | Stage that must catch it |
| --- | --- | --- |
| L1 | Vocabularies define `.../deontic-modality/Obligation` (slash); every data file uses `.../deontic-modality#Obligation` (hash). About 1,260 dangling references | R5 reference integrity (namespace-mismatch rule) |
| L2 | `xsd:duration`, `xsd:date`, `xsd:time`, `xsd:g*` ranges: HermiT refuses to load the ontology | R2 OWL 2 profile |
| L3 | CI runs only a Turtle syntax check; no SHACL, no reasoner | R10 release hygiene |
| L4 | TBox consistent, 0 unsatisfiable classes (after datatype patch) | R3 reasoning |
| L5 | 2 of 7 legacy data files inconsistent; minimal causes: a language-tagged literal on an `xsd:string` property, and a ConstitutiveRule typed into PrescriptiveRule by a property domain (disjoint) | R3 reasoning + explanation |
| L6 | SHACL with the artifact's own shapes: examples 10/10 files fail (85), LFDS 39/46 (726), legacy 7/7 (490) | R4 SHACL |
| L7 | `hasDeonticModality`: OWL `minCardinality 1`, SHACL `minCount 0`, documentation "MUST" | R6 constraint layers |
| L8 | Terms in notes or examples but never declared: `hasCondition`, `usesDefinition`, `hasReferent`, `TemporalRule`, `isSemanticDefinition`; `establishedInResource` in 7 data files; 33 undeclared terms in legacy data | R5 + R7 |
| L9 | The ontology's own usage example for PrescriptiveRule omits the required `produces` | R7 self-examples |
| L10 | LFDS data (20,454 triples) uses only `LegalRule`: no subclasses, no deontic modality, no rule relations, BENEF role never used | R8 data profile |
| L11 | 1,550 agent roles point to 608 untyped `example.org` IRIs; 77 variants contain "commission"; 189 exact-duplicate temporal blank nodes | R8 data profile |
| L12 | No property characteristics at all; `before`/`after` not inverse; only one disjointness axiom | R2b design lint |
| L13 | 109 untagged strings on `rdf:langString`-ranged properties | R5 range conformance |

A trimmed copy of the release (with its NOTICE, as CC BY 4.0 requires) becomes the golden fixture (section 8).

---

## 0. Seams in the existing code

Build on these; do not duplicate them.

| Existing module | Reused for |
| --- | --- |
| `ontology_bundle.py` (`save_uploads`, `_extract_zip`, zip limits, catalog and import resolution) | R0 ingest. The merge step is **not** reused for data files: data files do not import the ontology, so they would be dropped as `unused` |
| `owl_format_detector.py` | Parsing non-Turtle formats |
| `owltester/stages/stage_c.py`, `kindwork/module_reasoner.py` (HermiT with Pellet cross-check, offline) | R3 reasoning |
| `external_reasoner.py` (ROBOT/ELK) | Optional fast pre-pass on large TBoxes |
| `shacl_tools.validate`, `shacl_tools.lint_shapes` | R4 SHACL and shapes lint |
| `owltester/stages/stage_b.py`, `bfo_lint.py`, `bfo/catalog.py` | R9 BFO alignment |
| `owltester/model.py` (`Finding`, `StageResult`, `Report`) | Extended, not replaced (section 3) |
| `bundle_layers.py` (JSON sidecar, running marker, stale timeout, daemon thread) | The job pattern for the async audit (section 6) |
| `ownership.owns_filename`, `abuse_limits.limit_endpoint`, `report_store` | Access control and limits for the new endpoints |

Two facts about the environment shape the design:

- `owlready2` is pinned to 0.47 so Pellet runs on the Java 21 image. Reasoning must go through the existing wrappers, not new ones.
- `gunicorn.conf.py` allows 180 s per request. The LOMO audit takes minutes, so the audit must run as a background job (section 6), never inside a request.

The current gate (Stages A to E) is SOoL-specific: A4 requires BFO anchors and A5 sizes the artifact against the SOoL kernel. Run unchanged on LOMO, it fails at A4 and halts. The audit therefore has **profiles** (section 7); the gate becomes one of them.

---

## 1. Ingest and role detection (R0)

**Input:** a zip, a directory (CLI), or several files. Optional `audit.yaml` (or `audit.json`) at the archive root overrides anything detected.

**Task.**

1. Extract with the existing zip safeguards (`MAX_ZIP_MEMBERS`, `MAX_ZIP_UNCOMPRESSED`, `secure_filename`). Files in the archive are untrusted data: parse them, never execute them. Scripts, notebooks and build files are read as text only (R10 inspects CI configuration as text).
2. Parse every RDF file (by extension, then sniffing). Record parse failures as `E_PARSE` findings with the parser message, and continue with the rest.
3. Assign each RDF file one **role**, by content rather than path:

| Role | Rule (first match wins) |
| --- | --- |
| `shapes` | Declares any `sh:NodeShape` or `sh:PropertyShape` |
| `ontology` | Has an `owl:Ontology` header and declares at least 3 classes or properties, and has more schema triples than instance triples |
| `vocabulary` | The majority of typed subjects are `skos:Concept`, `skos:ConceptScheme` or `skos:Collection` |
| `data` | Types subjects with classes declared by an `ontology` file, or uses its properties |
| `other` | Anything else (listed, not audited) |

4. Group `data` files into **data sets** by their parent directory (`data/examples`, `data/lfds/ttl`, `data/other` for LOMO). Reasoning and SHACL run per data set and per file; the report summarizes per data set.
5. Compute **owned namespaces**: namespaces of the ontology and vocabulary IRIs, plus the namespaces of terms those files declare. Only owned namespaces are checked for reference integrity; references to other namespaces are counted as external.
6. Resolve `owl:imports` with the bundle resolver (local files, catalog, vendored BFO). Unresolvable imports are an `info` finding and are removed before reasoning, as now.

**Output:** an audit **manifest** (files, roles, data sets, owned namespaces, unresolved imports), shown at the top of the report so a wrong role assignment is visible and correctable with `audit.yaml`.

```yaml
# audit.yaml (all keys optional)
ontology: [ontologies/lomo-ontology.ttl]
vocabularies: [ontologies/deontic-modality.ttl, ...]
shapes: [shapes/lomo-shapes.ttl]
data_sets:
  examples: [data/examples/**/*.ttl]
  lfds: [data/lfds/ttl/*.ttl]
ignore: [data/lfds/tables/**]
profile: general
```

**Acceptance.** On the LOMO fixture: 1 ontology, 4 vocabularies, 1 shapes file (plus `iopa-shapes.ttl`, assigned `shapes` but outside the LOMO namespace and reported separately), 3 data sets, owned namespaces `http://data.europa.eu/leg/lomo#` and the four `http://data.europa.eu/leg/<vocab>/` namespaces.

---

## 2. Audit stages

Stages run in order. Unlike the gate, **no stage halts the audit**: a failure in one stage is a finding, and later stages still run (they may run on a patched copy, see R2). Each stage reports `pass`, `fail`, `warn` or `skipped` with a reason.

### R1. Parse and inventory

Per file: triple count, role, declared classes, properties and individuals, ontology IRI, version IRI. Totals for the artifact. Reuse `owltester/counts.py`.

### R2. OWL 2 profile

1. **Datatype map.** Every datatype used in a range, a data range or a typed literal must be in the OWL 2 datatype map. Anything else (`xsd:duration`, `xsd:date`, `xsd:time`, `xsd:gYear` and the other `xsd:g*`, custom datatypes without a definition) is `E_DATATYPE_PROFILE` (critical): standard OWL 2 reasoners refuse or misread the file.
2. **Patch to continue.** For the rest of the audit, reason over a patched copy in which those ranges become `rdfs:Literal` and those literals become plain strings. The report lists the patch under "Patches applied", and every reasoning result is labeled "with datatype patch".
3. **Profile membership** (info): report whether the TBox fits OWL 2 DL, EL, QL or RL, using the OWL API profile checker through ROBOT where available (`robot validate-profile`); skip with a reason when Java or ROBOT is missing.

Acceptance: LOMO yields `E_DATATYPE_PROFILE` naming `lomo:duration`, `lomo:frequency`, `lomo:instant` and the 8 datatypes; reasoning then proceeds (L2).

### R2b. Design lint (minor/info)

Cheap graph checks that point at missing logical structure. Each is a suggestion, not an error:

- No property in the ontology declares any characteristic (functional, transitive, symmetric, asymmetric, irreflexive, inverse).
- Name-paired properties not declared inverse: `before`/`after`, `hasX`/`isXOf`, `X`/`isXBy`, `starts`/`startedBy`, `precedes`/`follows`, `hasNext`/`hasPrevious`.
- Likely-transitive properties not declared transitive (`before`, `after`, `partOf`, `isComposedOf`, `ancestorOf`, local names ending in `Of` used in self-chains in the data).
- Class pairs `X` and `XType` (or `X` and `XCategory`) with no disjointness; sibling classes under one parent with no disjointness at all.
- Domain or range axioms placed on another vocabulary's classes (for example `dcterms:Software`), which retype every subject that uses the property.
- `allValuesFrom` over a `oneOf` with no `owl:AllDifferent` or `differentFrom`: under the open world a reasoner infers equality instead of reporting a wrong value.

Acceptance: L12 is reported.

### R3. Reasoning

1. **TBox:** ontology plus vocabularies (plus vendored BFO when the profile asks for it). Consistency, unsatisfiable classes, count of inferred subsumptions (reuse Stage C, including its non-triviality note, but as information rather than a gate failure).
2. **Per data set**, then **per file** for any data set that is inconsistent: ontology plus vocabularies plus the data.
3. **Explanation.** For each inconsistent file (up to `--max-explanations`, default 3), find a minimal inconsistent set of data triples by delta debugging over that file's triples, with the TBox held fixed. Budget: 120 s per file. Report the triples in Turtle, with labels, and one plain-language sentence where a pattern is recognized:
   - a language-tagged or untagged literal against a datatype range;
   - an individual typed into two disjoint classes, directly or through a property domain or range (name the property and the axiom);
   - a cardinality or `oneOf` violation.
   When the budget runs out, report the smallest set found so far and say it may not be minimal.
4. Cross-check HermiT against Pellet where both run (as `kindwork/module_reasoner.py` does); disagreement is a tool finding, reported loudly.

Codes: `E_INCONSISTENT` (TBox, critical), `E_UNSAT` (named unsatisfiable class, critical), `E_ABOX_INCONSISTENT` (data file, critical when in a data set marked as published, major in a set named `other`, `legacy`, `old` or `deprecated`, or marked so in `audit.yaml`).

Acceptance: L4 and L5, with the two minimal causes stated in plain language.

### R4. SHACL with the artifact's own shapes

1. Lint the shapes (`shacl_tools.lint_shapes`, including SHACL-SHACL).
2. Validate each data file against the artifact's shapes, with the ontology and vocabularies as the ontology graph and RDFS inference (`shacl_tools.validate`).
3. Validate the vocabularies against the shapes too (LOMO's shapes target the concept schemes).
4. Aggregate violations by (shape, path, constraint) per data set, with counts, two example focus nodes, and the offending value. Show per data set: files failing out of files total, violations total.
5. When a violation's value is a dangling reference already explained by R5 (for example the namespace mismatch), link the two so the report says "726 violations, all caused by finding R5-1".

Code: `E_SHACL` (major per data set; critical when every file in a published data set fails).

Acceptance: L6 counts reproduced exactly on the fixture's files.

### R5. Reference integrity

1. **Declared terms:** everything declared in ontology and vocabulary files (classes, properties, individuals, concepts, schemes, collections).
2. **Dangling references:** an IRI in an owned namespace, used anywhere in the artifact (as subject type, predicate, or object), that is not declared. Code `E_UNDECLARED_TERM` (major), grouped by term with use counts and files.
3. **Namespace mismatch rule:** for each dangling IRI, try the variants that commonly break releases: `#` and `/` swapped, trailing slash added or dropped, `http` and `https` swapped, an old ontology base replaced by the current one (taken from `owl:versionIRI`, `owl:priorVersion`, or a CHANGELOG mention of a namespace change). If a variant is declared, report `E_NS_MISMATCH` (critical) once per namespace pair, with the files and reference counts on each side and the one-line fix ("replace `...#` with `.../` in N data files"). Values that resolve under no variant stay `E_UNDECLARED_TERM` (LOMO's `ProcessAutomation`).
4. **Range conformance:** literals whose datatype or language tag does not match the declared range (`rdf:langString` vs plain string, `xsd:string` vs language-tagged), and IRIs used as objects of object properties whose declared range class they are never typed with. Code `W_RANGE` (minor), counted per property. Untyped objects are counted separately ("608 objects of `forAgent` are untyped"), since under RDFS they are silently retyped.
5. **External references:** count by namespace (ELI, OP authority tables, ...), not checked.

Acceptance: L1 as one `E_NS_MISMATCH` per vocabulary (4) with file counts 17/47/38/2; L8 data-side terms; L13.

### R6. Constraint layers: OWL, SHACL, documentation

Compare what each layer says about the same (class, property) pair, including subclass targets:

| From OWL | From SHACL | From documentation |
| --- | --- | --- |
| `min/max/exactCardinality`, `someValuesFrom` (min 1), functional (max 1) | `sh:minCount`, `sh:maxCount` | "MUST", "mandatory", "required", "exactly one", "at least one" in `rdfs:comment`, `skos:scopeNote`, `skos:definition` of the property or class |
| `allValuesFrom` over `oneOf` or a class | `sh:in`, `sh:class` | "MUST use values from" |
| `rdfs:range` datatype | `sh:datatype` | |

Report every pair where two layers disagree (`E_LAYER_CONFLICT`, major), and every documented "MUST" with no enforcing axiom or shape (`W_UNENFORCED`, minor). Report `TODO` and `FIXME` comments in the source next to an axiom (read from the raw Turtle text) as info, since they mark open modeling decisions.

Acceptance: L7, with the TODO on the PrescriptiveRule cardinality shown.

### R7. Documentation integrity and self-examples

1. **Terms mentioned in documentation:** scan annotation literals for CURIEs with an owned prefix and for identifier-shaped tokens (`hasCondition`, `usesDefinition`, a CamelCase word in parentheses such as `(TemporalRule)`). Tokens whose local name matches no declared term are `W_DOC_TERM` (minor). Keep the token rules conservative and list them in the report, so false positives are easy to dismiss.
2. **Self-examples:** many ontologies carry Turtle in `vann:usageExample`, `skos:example` or `rdfs:comment`. Extract those snippets, add the ontology's prefixes, parse them, and then (a) check them for undeclared terms, as R5 does, and (b) validate them against the artifact's own shapes. An example that fails the artifact's own shapes is `E_SELF_EXAMPLE` (major): the documentation teaches users to write invalid data.

Acceptance: L8 documentation-side terms and L9.

### R8. Data profile

The questions a reviewer asks of shipped data. All informational unless stated.

1. **Feature use matrix:** for every class and property in the ontology, its use count in each data set. Highlight:
   - declared but never used in any data set;
   - **subclass collapse**: a data set uses a superclass but none of its subclasses (`W_SUBCLASS_COLLAPSE`, minor), as LOMO's LFDS uses `LegalRule` only;
   - controlled-vocabulary values never used (BENEF).
2. **Placeholder IRIs:** subjects or objects under `example.org`, `example.com`, `example.net`, `localhost`, `system.org` and other configurable hosts, as a share of all subjects per data set (`W_PLACEHOLDER_IRI`, minor; major above 50% in a published set).
3. **Identity fragmentation:** cluster IRIs and labels used as values of agent-like or entity-like properties by normalized tokens; report clusters with several variants of one token ("77 IRIs contain `commission`") and compound values joining several entities with `and`, `or` or `-` (`W_IDENTITY`, minor).
4. **Duplicate nodes:** identical blank-node structures attached to the same subject by the same property (`W_DUPLICATE_NODE`, minor, with a count).
5. **Domain-driven retyping:** subjects that become instances of a more specific class only through a property's domain (LFDS rules inferred to be PrescriptiveRules without a modality). Report the count per class and property (info).

Acceptance: L10 and L11.

### R9. BFO alignment

Run Stage B (`B1` orphans, `B2` partition straddles, `B3` kernel typing when the profile has a kernel) and `bfo_lint` over the ontology. In the `general` profile these are **advisory**: an artifact that does not use BFO gets one info finding ("No BFO alignment: 17 classes have no BFO parent") rather than 17 failures. In `sool` and `bfo` profiles they keep their gate severity.

Acceptance: LOMO in the `general` profile: one advisory finding, no failures from R9.

### R10. Release hygiene

Read as text, never executed:

1. **Ontology header:** license, version IRI, `owl:versionInfo`, creator or editors, modified date. Missing license or version IRI is minor; no named editors or contact is info.
2. **Version agreement:** `owl:versionInfo`, the version IRI, `pyproject.toml` or `package.json` version, the newest CHANGELOG heading and the archive name should agree.
3. **CI coverage:** find `.gitlab-ci.yml`, `.github/workflows/*.yml`, `Makefile`, `tox.ini`, `noxfile.py`. Report which kinds of checks they invoke, matched by command name: syntax (`rdflib` parse scripts, `riot --validate`), SHACL (`pyshacl`, `shacl validate`, `jena shacl`), reasoning (`robot reason`, `robot explain`, `hermit`, `owlready`), and tests (`pytest`). If shapes ship with the artifact and no CI step runs SHACL, report `W_CI_NO_SHACL` (major), and similarly `W_CI_NO_REASONER`.
4. **Changelog claims:** files the newest CHANGELOG entry says were added that are absent from the archive (info).

Acceptance: L3 reported as `W_CI_NO_SHACL` and `W_CI_NO_REASONER`.

---

## 3. Finding and report model

Extend `owltester/model.py`; keep the gate's types working.

```python
@dataclass
class AuditFinding(Finding):          # code, message, iri, suggested_rewrite
    stage: str                         # "R0".."R10"
    severity: str                      # critical | major | minor | info
    title: str                         # one line for the scorecard
    files: list                        # paths inside the artifact
    count: int = 1                     # occurrences folded into this finding
    evidence: dict = field(default_factory=dict)   # triples (Turtle), examples, mappings
    related: list = field(default_factory=list)    # ids of findings that explain this one
    fix: str = ""                      # plain-language fix

@dataclass
class AuditReport:
    artifact: str
    audited_at: str
    tool_version: str                  # git hash
    profile: str
    manifest: dict                     # R0
    stages: dict                       # "R1" -> {status, summary, notes}
    findings: list                     # AuditFinding, sorted by severity then stage
    patches: list                      # e.g. datatype patch, removed imports
    limits_hit: list                   # budgets that ran out, files skipped
    @property
    def verdict(self): ...             # "fail" if any critical, "warn" if any major, else "pass"
    def scorecard(self): ...           # one row per check, as in the LOMO audit doc
```

New codes go in `owltester/errors.py` with descriptions: `E_DATATYPE_PROFILE`, `E_UNSAT`, `E_ABOX_INCONSISTENT`, `E_SHACL`, `E_UNDECLARED_TERM`, `E_NS_MISMATCH`, `E_LAYER_CONFLICT`, `E_SELF_EXAMPLE`, and warnings `W_RANGE`, `W_UNENFORCED`, `W_DOC_TERM`, `W_SUBCLASS_COLLAPSE`, `W_PLACEHOLDER_IRI`, `W_IDENTITY`, `W_DUPLICATE_NODE`, `W_CI_NO_SHACL`, `W_CI_NO_REASONER`, plus `W_LINT_*` for R2b.

Findings are **folded**: one finding per (code, term or namespace pair or shape-path), carrying a count and a few examples, never one finding per triple. The LOMO report should have tens of findings, not thousands.

---

## 4. Report outputs

1. **JSON:** `AuditReport.to_dict()`, stable keys, documented in this spec's appendix when built.
2. **HTML page** (`templates/audit_report.html`, extends `layout.html`): the verdict line; the scorecard table; the manifest (collapsed); findings grouped by stage, each with severity, title, count, files, evidence and fix; patches and limits. Plain language throughout, in the voice of the existing report pages.
3. **Markdown export:** the scorecard and findings as Markdown, so a report can be pasted into a document, an issue or a comment letter. One finding per issue is also offered as a `.zip` of Markdown files, ready to file on the artifact's tracker.

---

## 5. Interfaces

- **CLI:** `python -m owltester.cli audit <zip|dir|files...> [--profile general|bfo|sool] [--json out.json] [--html out.html] [--md out.md] [--budget 900] [--max-explanations 3] [--no-explain] [--config audit.yaml]`. Exit 0 on `pass` or `warn`, 1 on `fail`, so it can run in the artifact's own CI.
- **HTTP** (on the existing `owltester` blueprint):
  - `POST /owltester/audit` (multipart zip or files) returns `202 {"job_id": ...}`.
  - `GET /owltester/audit/<job_id>` returns `{"status": "queued|running|done|error", "stage": "R4", "progress": ...}`, and the report when done.
  - `GET /owltester/audit/<job_id>/report.html`, `.../report.md`.
  - Rate limit with `UPLOAD_LIMIT`; access through `ownership` exactly as the SHACL workbench does.
- **Web:** on `upload.html`, a third option beside single file and bundle: "Audit a release (zip)". It leads to `/audit/<job_id>`, which polls and then renders the report.

---

## 6. Execution, budgets and safety

- **Job runner:** the `bundle_layers.py` pattern: a JSON sidecar per job in the upload folder (status, current stage, partial results), a running marker with a stale timeout, and a daemon thread. Every gunicorn worker can read the sidecar. If the app later gains a queue (RQ, Celery), the runner is the only part to change.
- **Budgets** (configurable): total 900 s; each reasoner call 60 s; explanation 120 s per file, 3 files; SHACL per file 60 s. When a budget runs out, the stage reports what it finished and lists the rest under `limits_hit`. The audit never fails silently because of a budget.
- **Size limits:** reuse the zip limits; add `AUDIT_MAX_TRIPLES` (default 2,000,000) and `AUDIT_MAX_DATA_FILES` (default 300).
- **No network:** imports resolve locally or are removed and reported. pyshacl and owlready2 run offline.
- **Untrusted content:** nothing in the archive is executed or imported as code. Text from the archive is escaped in HTML. Parsing runs in the worker with the same limits as uploads.
- **Who may run it:** an audit is far heavier than a check. Require sign-in when `KINDWORK_MODE`-style public triage is on, or add `AUDIT_MODE=public|signed-in` (default `signed-in`).

---

## 7. Profiles

| Profile | Use | R9 BFO alignment | Gate stages A to E |
| --- | --- | --- | --- |
| `general` (default) | Any released ontology, BFO or not | Advisory | Not run |
| `bfo` | Artifacts that claim BFO alignment | Severity as in the gate | B only |
| `sool` | SOoL kernel artifacts | As in the gate | All, with the kernel, as `owltester check` does now |

A profile is a small dict (stages on or off, severity overrides, placeholder hosts, data-set names treated as legacy). Lenses (section 9) attach to profiles later.

---

## 8. Tests and fixtures

1. `fixtures/audit/lomo-1.0.0-trimmed/`: the ontology, 4 vocabularies, `lomo-shapes.ttl`, `.gitlab-ci.yml`, `CHANGELOG`, `NOTICE`, `LICENSE`, 2 example files, 3 LFDS files and the 2 inconsistent legacy files. CC BY 4.0 permits this with attribution; keep their NOTICE and add a README line naming the source and version. Target size under 1 MB.
2. `fixtures/audit/expected-lomo.json`: the findings each test asserts (codes, counts, minimal triples for L5). Counts are recomputed for the trimmed subset when the fixture is built.
3. `fixtures/audit/mini/`: one tiny artifact per check, each designed to trigger exactly one finding (a slash/hash split; one `xsd:duration` range; one inconsistent data file with a disjointness clash; OWL min 1 vs SHACL min 0; a usage example missing a required property; a CI file with no SHACL step), plus one clean artifact that must pass with no findings above info.
4. `tests/test_audit.py`: one test per mini fixture, one golden test over the LOMO fixture, CLI exit codes, and a test that a budget overrun yields `limits_hit` rather than an exception. Mark the reasoner tests `@pytest.mark.java` so they skip cleanly without Java, as the existing reasoner tests do.

Hand-run reference for the full release (not committed): the scripts used for the 31 Oct 2026 audit (`inv.py`, `reason.py`, `bisect.py`, `shacl.py`), which the implementation should match on the full archive.

---

## 9. Later: conceptual lenses

The hand audit also judged LOMO conceptually (no breach or remedy, deontic values with no logic, types modeled as individuals) against LOF's Minimum Legal Chain. That judgment is not automatable today, but it can be **structured**:

- A **lens** is a file listing the questions a reviewer asks of a domain (for law: the eight chain nodes, Hohfeldian positions, conflict handling). Each question carries SPARQL or label patterns that find candidate terms in the artifact.
- The audit fills a coverage table (node, candidate terms, evidence) and marks each row `proposed`. A reviewer confirms or rejects each row in the report page before export; nothing is presented as a finding until confirmed.
- An optional AI draft of the rows uses only the visitor's own key (`api_key_utils`), as Propose does.

Ship lenses after R0 to R10 are stable. The SOoL kernel and the LOF ODPs are the natural first lenses.

---

## 10. Open decisions

1. Should an artifact with no BFO alignment ever fail an audit in the `general` profile, or is alignment always advisory there? (This spec: advisory.)
2. Is the trimmed LOMO fixture acceptable in a public repo under CC BY 4.0 with attribution, or should the golden fixture be synthetic, with LOMO kept as a hand-run reference?
3. Public or signed-in only? (This spec: signed-in by default.)
4. HermiT or Pellet as the primary reasoner for the audit? Stage C uses Pellet; Kindwork uses HermiT with a Pellet cross-check. (This spec: follow Kindwork.)
5. Should the audit write a durable record (database row, history page) or only the JSON sidecar? (This spec: sidecar first, as `bundle_layers` does.)

---

## Suggested order

1. **Engine core:** R0, R1, R2, R3 without explanation, R4, R5, the report model, CLI and JSON. Golden test on the LOMO fixture for L1, L2, L4 and L6. This alone would have caught every critical LOMO finding.
2. **Depth:** R3 explanation, R6, R7, R8, R10, R2b.
3. **Surface:** async job, HTTP endpoints, HTML page, Markdown export, upload option.
4. **Alignment and lenses:** R9 profiles, then section 9.

---

## Appendix: the JSON report (`AuditReport.to_dict()`)

Keys are stable; new keys may be added, existing keys keep their meaning.

| Key | Type | Meaning |
| --- | --- | --- |
| `artifact` | string | Archive name (top folder of the zip, or the directory or file name) |
| `audited_at` | string | ISO 8601 time, UTC |
| `tool_version` | string | Git short hash of OwlTester (or `OWLTESTER_VERSION`) |
| `profile` | string | `general`, `bfo` or `sool` |
| `verdict` | string | `fail` if any critical finding, `warn` if any major, else `pass` |
| `severity_counts` | object | `{critical, major, minor, info}` counts |
| `scorecard` | list | One row per stage: `{stage, check, status, worst, findings, summary}` |
| `manifest` | object | R0: `name`, `files_total`, `rdf_files`, `triples`, `roles` (role, or `role (external)`, to paths), `data_sets` (name to `{files, legacy, paths}`), `owned_namespaces`, `imports` (`resolved`, `unresolved`), `config`, `config_unknown_keys`, `files` (per file: `path, kind, role, scope, triples, data_set, error, ontology_iri, version_iri, role_source, notes`) |
| `stages` | object | Stage code (`R0`..`R10`, `R2b`) to `{title, status, summary, notes}`; `status` is `pass`, `warn`, `fail`, `skipped` or `error`; `notes` holds stage detail (R3: verdicts per TBox, data set and file; R4: `{files, failing, violations}` per data set) |
| `findings` | list | Sorted by severity, then stage. Each: `id` (`R5-1`), `stage`, `code`, `severity` (`critical`, `major`, `minor`, `info`), `title`, `message`, `files`, `count` (occurrences folded into the finding), `iri`, `evidence` (code-specific; R3 inconsistencies carry `minimal_triples` in Turtle, `minimal`, `causes`, `labels`), `related` (ids of findings that explain this one), `fix`, `suggested_rewrite` |
| `patches` | list | `{name, detail, ...}`, for example the datatype patch |
| `limits_hit` | list | `{stage, limit, detail}` for every budget or size limit that cut work short |
| `lenses` | list | Section 9 coverage tables: `{lens, title, about, rows: [{id, group, node, question, candidates: [{iri, term, label, evidence}], more, status, note, source}]}`; `status` is `proposed`, `confirmed`, `rejected` or `no candidates` |

The HTTP job status (`GET /owltester/audit/<job_id>`) is `{job_id, status, stage, progress, artifact, profile, started_at, finished_at, error}`, plus `report` (the object above) when `status` is `done`. `status` is `queued`, `running`, `done`, `error` or `stale`.

### Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `AUDIT_MODE` | `signed-in` | `public` lets anonymous visitors run audits |
| `AUDIT_MAX_TRIPLES` | 2,000,000 | Files past this total are listed but not parsed |
| `AUDIT_MAX_DATA_FILES` | 300 | Data files past this count are not audited |
| `AUDIT_STALE_SECONDS` | 1800 | A running job older than this is reported as stale |
| `KINDWORK_REASONER_TIMEOUT_MS` | 60000 | Shared reasoner wrapper setting (the audit passes its own per-call budget) |

Budgets (CLI flags or `audit.yaml` keys `budget`, `max_explanations`): total 900 s, each reasoner call 60 s, explanation 120 s per file for 3 files, SHACL 60 s per file.

### Notes from building it

- `ontology_bundle._extract_zip` flattens paths, so R0 extracts with the same limits (`MAX_ZIP_MEMBERS`, `MAX_ZIP_UNCOMPRESSED`) but keeps sanitised relative paths: data sets are grouped by directory.
- A vocabulary is the artifact's own when the ontology or its own shapes refer to it; LOMO's IOPA code list is in the same IRI family but nothing refers to it, so it is listed as external.
- Pellet 2.3 predates `rdf:langString` and calls correct LOMO data inconsistent. The cross-check gives Pellet a copy where `rdf:langString` ranges read as `rdf:PlainLiteral`; the R3 notes say so.
- HermiT needs about 90 s for the 20,454-triple LFDS set, past the 60 s per-call budget; R3 then reasons file by file, and `limits_hit` records it.
- On the full LOMO release the identity check finds 91 agent values containing "commission" by substring; the hand audit counted 77 with a tokenisation that was not kept.
- Self-examples: an example that shows a whole instance of the class it documents and fails the shapes is `E_SELF_EXAMPLE` (major); examples on properties that leave out unrelated required fields are folded into one minor finding.
