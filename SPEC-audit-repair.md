# Build Spec: Guided Release Repair

**Target repo:** `OwlTesterService` (dkoepsell)
**Builds on:** `SPEC-audit.md` (the full artifact audit), `owltester/repair.py`, `ontology_fixer.py`
**Role of this feature:** turn an audit report into a **fix plan**, walk the user through it finding by finding, apply only the changes the user accepts to a *copy* of the release, and prove the result with a second audit.
**Status:** plan only. No code in this change.
**Who may use it:** the owner of the service only, until the owner names others (section 1).

Do not introduce em-dashes into any user-facing copy, docstrings, or report templates in this project.

---

## Principles

These carry over from `owltester/repair.py` ("never silently delete; a coherent-but-empty artifact fails") and extend it to whole releases.

1. **The user decides.** The tool proposes and explains; nothing changes until the user accepts a specific option. There is no "fix everything" button.
2. **The original is never touched.** Every change is applied to a copy of the uploaded release.
3. **Every change is logged and traceable.** Each changed triple or line points to the operation that made it, the finding that motivated it, the option chosen, who chose it, and why.
4. **A fix is proven, not asserted.** After applying, the release is audited again. The plan reports which findings closed, which remain, and whether anything new appeared.
5. **Repairs are small and bounded.** Removals are capped, as in `repair.py` (default 2% of axioms), and must each cite a finding. A plan that would hollow out the release fails, as Stage E does now.
6. **Guidance over automation where judgment is needed.** A modeling gap is explained and scaffolded, never "fixed" by the tool on its own.
7. **No network, no execution.** As in the audit: files are parsed, never run. AI help uses only the user's own key and is never applied without acceptance.

---

## 1. Access control (first, and fail closed)

Repair is far more consequential than an audit: it writes new releases and can open pull requests. It is therefore **closed to everyone by default** and open only to accounts named in configuration.

### 1.1 Now: the owner only

- New setting `REPAIR_ALLOWED_USERS`: comma-separated usernames or emails, matched case-insensitively against the signed-in account (the same convention as `AUDIT_ALLOWED_USERS` in `owltester/audit_service.py`).
- **Empty or unset means nobody.** This is the opposite of `AUDIT_ALLOWED_USERS`, where empty means "anyone `AUDIT_MODE` lets in". A missing setting must never open repair to the public.
- Repair is **never available anonymously**, whatever `AUDIT_MODE` says. There is no `REPAIR_MODE=public`.
- Every repair route checks, in this order: signed in; account in `REPAIR_ALLOWED_USERS`; the account owns the audit job the plan was built from (the job sidecar's `owner.user_id`, as `_job_or_404` does). A failure at any step returns 404 for plans and jobs (so their existence is not revealed) and 403 for the start route.
- The "Fix this release" button on the audit report renders only for allowed users. Its absence is not the protection; the route checks are.
- **Production setting for this phase:** `REPAIR_ALLOWED_USERS=<owner account>` and, so the audit is equally private, `AUDIT_ALLOWED_USERS=<owner account>`. Today `AUDIT_ALLOWED_USERS` empty means any signed-in account may start an audit; the deploy notes must set it explicitly. A startup log line states who may audit and who may repair, so a misconfiguration is visible in the logs.

### 1.2 Later: named collaborators (for example, a co-reviewer such as Dwayne)

Designed now so that adding someone later is configuration plus one share action, with no change to the security model:

| Role | May |
| --- | --- |
| `owner` | Everything below, plus share and unshare a plan, apply changes, export, open pull requests |
| `approver` | Accept or reject options, apply, export a patched release; not open pull requests or share |
| `reviewer` | View the plan, comment on cards, propose an option for the owner to accept; not apply or export |

- An account must be in `REPAIR_ALLOWED_USERS` **and** be added to the specific plan by its owner. Being allowed to use repair does not grant access to anyone else's plans.
- Sharing is per plan, recorded in the plan sidecar (`members: [{user_id, role, added_by, added_at}]`), and revocable.
- Every action records the acting account in the fix log, so a jointly made release shows who chose what.
- `AUDIT_ALLOWED_USERS` gains the same account when a collaborator should also start audits.

Until the owner adds someone, sections 4 to 7 behave as if `owner` were the only role.

---

## 2. Seams in the existing code

| Existing module | Reused for |
| --- | --- |
| `owltester/audit/` (runner, `AuditReport`, `AuditFinding`, codes in `errors.py`) | The input to a plan, and the second audit that verifies it |
| Findings' `fix` text and `evidence` (minimal triples, groups, mappings) | The starting point for each remedy; extended into structured remedies (section 3) |
| `owltester/audit/jobs.py` (sidecar per job, owner, background thread) | Plan storage (`uploads/audits/<job_id>/repair/<plan_id>/`) and the apply job |
| `owltester/audit_service.py` (`may_start_audit`, `_job_or_404`) | The access checks of section 1, alongside new `may_repair()` |
| `owltester/repair.py` (bounded relaxation, quarantine) and Stage E | The removal bound and the "no unlogged loss" invariant |
| `ontology_fixer.fix_straddle` | The BFO partition-straddle remedy, unchanged |
| `owltester/audit/render.py` (`issues_zip`) | Exporting fixes as issues with patches attached |
| `api_key_utils`, Kindwork Propose | Optional AI suggestions with the visitor's own key |
| Kindwork's guided UI | The pattern for modeling-gap guidance (section 4.4) |

---

## 3. The remedy model

### 3.1 Remedy kinds

| Kind | Meaning | Interaction |
| --- | --- | --- |
| `mechanical` | One correct change; the tool can compute it exactly | Preview with counts, one accept |
| `choice` | Two or three defensible changes; only the user can choose | Options with consequences and a preview of each |
| `guided` | Modeling or authoring work; no change can be computed | Explanation, a pattern or template, a draft the user edits; nothing applied until the user writes or accepts the content |
| `declare` | The outcome is by design | Writes an `expected` entry into the release's `audit.yaml`, with the user's reason |

Every remedy also offers **skip** (with an optional note, kept in the log) and, where it makes sense, **declare expected**.

### 3.2 Data structures

```python
@dataclass
class RemedyOption:
    id: str                 # "a", "b", ...
    label: str              # "Rewrite data to the vocabulary's slash IRIs"
    consequence: str        # what changes, and what it costs
    ops: list               # list[ChangeOp]; empty for guided until the user supplies content
    preview: dict           # counts per file, sample before/after, Turtle snippets
    recommended: bool = False

@dataclass
class Remedy:
    id: str                 # "M-<finding id>"
    finding_id: str         # e.g. "R5-1"
    code: str               # e.g. "E_NS_MISMATCH"
    kind: str               # mechanical | choice | guided | declare
    title: str
    rationale: str          # why it matters, in plain language
    options: list           # list[RemedyOption]
    depends_on: list        # remedy ids that should be decided first
    status: str = "open"    # open | accepted | skipped | declared | applied | reverted
    decision: dict = None   # {option, by, at, note, ai_assisted}
```

### 3.3 A closed set of change operations

Repair may do only these things. Anything else is out of scope by construction.

| Op | Effect | Guard |
| --- | --- | --- |
| `rewrite_iri` | Replace one IRI (or one namespace prefix) with another across named files | Counts before and after must match the preview |
| `set_literal` | Change a literal's language tag or datatype | Only literals named in the finding's evidence |
| `add_triples` | Add triples (a declaration, a header annotation, an axiom, a shape) | Turtle validated before apply; new terms must be in an owned namespace or already declared |
| `remove_triples` | Remove named triples | Each must appear in the finding's evidence; total under the removal bound |
| `retype` | Replace an `rdf:type` on named subjects | Subjects listed one by one in the decision |
| `merge_nodes` | Collapse identical blank nodes, or map variant IRIs to one entity | Mapping table confirmed row by row |
| `write_text` | Create or patch a text file (CI workflow, CHANGELOG, `audit.yaml`) from a template | Templates only; no free-form shell |
| `exclude_file` | Leave a file out of the patched release, or move it under `legacy/` | Listed in the release notes |

Each op records `{op, args, files, triples_added, triples_removed, lines_changed, finding_id, remedy_id, option, by, at}`.

### 3.4 Remedy catalog by finding code

| Code | Kind | Options (recommended first) |
| --- | --- | --- |
| `E_NS_MISMATCH` | mechanical | Rewrite data to the namespace the vocabulary declares; or (choice) add `owl:sameAs`/redirect notes and change the vocabulary instead |
| `E_UNDECLARED_TERM` | choice | Map to the most similar declared term (string and label similarity, shown with scores); or declare it (draft declaration to complete); or remove its uses |
| `W_RANGE` | mechanical | Add the language tag (default from the file's dominant tag) or change the datatype to match the range |
| `E_DATATYPE_PROFILE` | choice | Use `xsd:dateTime`/`xsd:string` with a pattern shape; or move the property to an annotation property; or adopt OWL-Time (guided) |
| `E_INCONSISTENT`, `E_ABOX_INCONSISTENT` | choice | From the minimal triples: remove or correct the offending triple(s); retype the subject; relax the clashing axiom (shown with what else it would allow); or declare expected (for designed tests) |
| `E_UNSAT`, `E_DISJOINT` (straddle) | choice | Keep one BFO category, drop the other edge (`fix_straddle`), with the consequence of each |
| `E_SHACL` | choice | Complete the data (a form listing each missing value per focus node); correct the shape if it is wrong; or declare expected. Linked findings (for example a namespace mismatch) are decided first and the counts refreshed |
| `E_LAYER_CONFLICT` | choice | Make OWL authoritative and align the shape; make SHACL authoritative and align the axiom; or align both to the documentation |
| `W_UNENFORCED` | choice | Generate the missing shape; or soften the documentation |
| `W_DOC_TERM` | choice | Declare the term (draft); or edit the note to name the right term |
| `E_SELF_EXAMPLE` | guided | Show the shape violations on the example and let the user complete it; AI may draft the missing lines |
| `W_SUBCLASS_COLLAPSE` | choice | A table, one row per instance, to pick the specific subclass (AI may pre-fill suggestions); or accept the general class as intended |
| `W_PLACEHOLDER_IRI` | choice | Map `example.org` to a real base IRI; or declare expected for examples and tests |
| `W_IDENTITY` | guided | A reconciliation table: each variant mapped to one entity, optionally to an authority table IRI the user supplies; then `merge_nodes` |
| `W_DUPLICATE_NODE` | mechanical | Collapse identical blank nodes |
| `W_CI_NO_SHACL`, `W_CI_NO_REASONER` | mechanical | Add a step to the detected CI system from a template (GitHub Actions, GitLab CI, a Makefile target wired into the target CI already runs); preview the patch |
| `W_HEADER`, `W_VERSION` | mechanical | Fill the missing annotation from the values found elsewhere (version IRI pattern, license file, CHANGELOG) |
| `W_LINT_*` | choice | Add the characteristic, inverse or disjointness; or dismiss with a note |
| `W_CONFIG` | mechanical | Correct or remove the configuration entry |
| `E_PARSE` | guided | Show the parser error and location; no automatic change |
| Lens gaps (section 9 of `SPEC-audit.md`) | guided | Explain the gap and offer a pattern (for law, the LOF ODPs, for example ODP-004 for breach, effect and remedy) as a template module the user fills in |

Findings already marked expected by the release produce no remedy.

---

## 4. The guided flow

### 4.1 Starting a plan

From a finished audit report, an allowed user presses **Fix this release**. The tool builds the plan:

1. One remedy per finding with a catalog entry, using the finding's evidence.
2. Dependencies, so that causes come before effects. A namespace mismatch comes before the SHACL violations it explains (the audit's `related` links), and a datatype change comes before range findings on the same property.
3. Order: critical, then major, minor, info; within a severity, causes first.

### 4.2 The plan page

- A header with the release, the audit it came from, the plan status, and a progress bar (decided out of total).
- A list of **cards**, each showing the finding (severity, title, count, files), why it matters, the options with their consequences, and a **preview** (counts per file, a short before/after diff, the Turtle that would be added or removed). Choices are radio buttons. Skip and declare-expected are always present.
- **Bulk cards** (subclass choices, identity reconciliation, missing SHACL values) open as an editable table. Rows can be filled in one at a time or by rule ("all instances in this file"). The table saves as the user goes.
- **Guided cards** open a side panel: the explanation, the pattern or template, and an editor for the draft. The tool validates the draft (parses, checks terms, runs the relevant shape) before it can be accepted.
- Decisions save immediately; a plan can be left and resumed.
- Wording follows the existing report pages: plain language, no jargon without a gloss.

### 4.3 Consequence text

Every choice option states what it costs, specifically. For example:

- "Drop `owl:disjointWith` between ConstitutiveRule and PrescriptiveRule: provisions may then be typed as both, and the reasoner will no longer catch a rule typed as both by mistake."
- "Make SHACL authoritative: the OWL `minCardinality 1` on hasDeonticModality is removed, so a reasoner no longer expects every prescriptive rule to have a modality."

### 4.4 AI assistance (optional)

- Off unless the user has set their own key (`api_key_utils`); server keys are never used, as in Kindwork Propose.
- Used only to pre-fill: subclass suggestions, a draft definition, a draft example, a mapping suggestion. Every AI value is labeled as such on the card, must be accepted by the user, and is recorded in the decision as `ai_assisted: true`.
- Prompts carry only the snippets needed (the term, its definition, its neighbours), never the whole release.

---

## 5. Apply and verify

**Apply** is a background job (the `jobs.py` pattern), started from the plan page by the owner (or, later, an approver):

1. Copy the release's extracted tree to `repair/<plan_id>/work/`.
2. Apply the accepted ops in dependency order. Each op checks its guard and its preview counts; a mismatch stops the apply with a clear message and leaves the copy untouched.
3. Enforce the bounds: total removed axioms under the removal bound; nothing removed that no finding cites; no op outside the release tree.
4. Write the outputs (section 6).
5. **Re-audit** the patched copy with the same profile and configuration (plus any new `expected` entries).
6. Show **before and after**: the two scorecards side by side; findings closed, findings remaining, findings new. A new finding at or above the severity of the ones closed is flagged at the top. The plan is not called "fixed" if the second audit's verdict is worse on any stage the user did not touch.

**Revert:** any applied remedy can be reverted, which reruns the apply without it. Applies are deterministic: the same plan on the same release gives byte-identical files.

---

## 6. Outputs and handoff

| Output | Content |
| --- | --- |
| `<release>-repaired.zip` | The patched release, same layout as the original |
| `FIXLOG.json` | Every op with its finding, remedy, option, actor, time, note, AI flag and counts |
| `FIXLOG.md` | The same, readable, grouped by finding; suitable for a release note |
| CHANGELOG draft | A new entry summarizing the changes, for the user to edit |
| `audit-before.json`, `audit-after.json` | The two reports |
| `repair.patch` | A unified diff of all text files, applicable with `git apply` in the source repository |
| Issues export | `issues_zip` extended: each issue carries its proposed fix and patch, for releases the user does not maintain (LOMO) |
| Pull request (optional) | With the owner's explicit confirmation, a branch and pull request on the release's source repository, using the **owner's own** GitHub token (stored per user, encrypted, never a server token). Only `owner` may do this |

Nothing is published or pushed automatically.

---

## 7. Safety and limits

- Every rule from `SPEC-audit.md` section 6 applies: no execution, no network (except the opt-in pull request in section 6), escaped HTML, size limits.
- Templates for text files are fixed and reviewed; user input fills named slots only.
- The removal bound (default 2% of axioms) and the per-op guards are not configurable by plan members; changing them is a server setting.
- Plans and outputs inherit the job's ownership and are deleted with it. A retention period (`REPAIR_RETENTION_DAYS`, default 90) applies to work trees; fix logs are kept with the report.
- All repair routes are rate limited (`UPLOAD_LIMIT` for apply, `AI_LIMIT` for suggestions).

---

## 8. Interfaces

- **Web:** `/audit/<job_id>/repair` (create or resume the plan), `/audit/<job_id>/repair/<plan_id>` (the plan page), apply and status endpoints as JSON under `/owltester/audit/<job_id>/repair/...`.
- **CLI** (for the owner, on the server or locally): `python -m owltester.cli repair-plan <audit.json> --release <zip> --out plan.json`; `python -m owltester.cli repair-apply plan.json --release <zip> --out repaired.zip` (decisions are read from the plan file; the CLI applies no option the file does not record as accepted).
- The CLI does not check `REPAIR_ALLOWED_USERS` (it runs as whoever has shell access); the web routes always do.

---

## 9. Tests and fixtures

**Access (no reasoner needed):**
- Unset or empty `REPAIR_ALLOWED_USERS`: every repair route refuses, including for an account in `AUDIT_ALLOWED_USERS`.
- Anonymous visitor: refused even with `AUDIT_MODE=public`.
- Allowed account, someone else's job: 404.
- The "Fix this release" button is absent for non-allowed accounts.
- Later, with sharing: a reviewer can view and comment but not apply; removing a member revokes access at once.

**Remedies (on existing fixtures):**
- `fixtures/audit/mini/ns-mismatch`: the mechanical rewrite closes `E_NS_MISMATCH` and the linked `E_SHACL`; the second audit has nothing above info.
- `mini/datatype`, `mini/inconsistent`, `mini/layer-conflict`, `mini/self-example`, `mini/ci-no-shacl`: each remedy closes its finding, and the second audit introduces nothing new.
- LOMO trimmed fixture: the namespace rewrite closes the four `E_NS_MISMATCH` findings and removes every SHACL violation linked to them; the legacy inconsistency remedies close both `E_ABOX_INCONSISTENT` findings.
- LOF bundle: the CI template closes `W_CI_NO_SHACL`; the subclass-collapse table closes the two `W_SUBCLASS_COLLAPSE` findings when filled.

**Invariants:**
- A plan that removes more than the bound fails, and leaves no output.
- An op whose preview counts no longer match fails cleanly.
- Apply is deterministic (two applies, byte-identical zips).
- Revert of every remedy reproduces the original files.

---

## 10. Open decisions

1. Removal bound for releases: keep 2% of axioms, or count data triples separately (a namespace rewrite changes many data triples but removes none)? (This spec: the bound applies to axioms; rewrites are not removals.)
2. Should accepting `declare expected` require a written reason? (This spec: yes.)
3. Pull requests: allow them in the first release of the feature, or start with `repair.patch` only? (This spec: patch first, pull request in phase 3.)
4. When collaborators arrive, should an approver's apply need the owner's confirmation? (This spec: no; the owner chooses who is an approver.)
5. Retention of work trees: 90 days, or until the owner deletes the plan?

---

## Suggested order

1. **Access and plumbing:** `REPAIR_ALLOWED_USERS` (fail closed), `may_repair()`, plan storage, the remedy model, the op set with guards, apply and re-audit, `FIXLOG`, CLI. Mechanical remedies only: `E_NS_MISMATCH`, `W_RANGE`, `W_DUPLICATE_NODE`, `W_HEADER`, `W_CI_NO_SHACL`/`W_CI_NO_REASONER`. Set `AUDIT_ALLOWED_USERS` in production at the same time.
2. **Choices:** the plan page and cards; `E_ABOX_INCONSISTENT`, `E_LAYER_CONFLICT`, `E_UNDECLARED_TERM`, `E_DATATYPE_PROFILE`, `E_SHACL`, `W_SUBCLASS_COLLAPSE`, straddles.
3. **Guidance and handoff:** guided cards, AI pre-fill, lens-gap templates, issues with patches, pull requests.
4. **Collaborators:** plan sharing and roles (section 1.2).
