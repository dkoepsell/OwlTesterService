# Kindwork, BFO-Agent, OwlTester: Interchange Spec

Draft 0.1.0, October 18, 2026. David R. Koepsell.
Vocabulary namespace: `https://ontology.davidkoepsell.com/kindwork/vocab#` (prefix `kwv:`)

Three tools, one loop. Kindwork is the front door for people who are not ontologists. BFO-Agent populates a model from documents behind a reasoner gate. OwlTester verifies with a DL reasoner. This spec fixes the files they exchange, so each tool can be built and tested on its own and still compose.

Kindwork's side is built and live. This spec is the work order for the BFO-Agent and OwlTester adapters.

## 1. Roles and the loop

| Tool | Reads | Writes | Its question |
|---|---|---|---|
| Kindwork | a task description, OWL (Turtle or RDF/XML), `kindwork-model`, `owltester-findings` | OWL, SHACL, keyword source, `kindwork-model`, tracker HTML | What kinds of thing does this task involve, in the user's words? |
| BFO-Agent | source documents, optional `kindwork-model` seed | OWL with provenance and `kwv:keyword` annotations | What does this text support, and what can the reasoner accept? |
| OwlTester | OWL, optional `kindwork-model` | `owltester-findings` | Is it consistent, coherent, and conformant, and where is it not? |

The loop: Kindwork models the task, then emits a seed. BFO-Agent populates from documents and emits OWL. Kindwork imports that OWL and merges it, keeping source passages. Kindwork builds and emits OWL plus the manifest. OwlTester checks them and emits findings. Kindwork shows the findings as cards, the user resolves them, and the next build goes out.

Every file a tool emits must be importable by the next tool without hand editing. That is the acceptance bar for this spec.

## 2. Shared OWL conventions

These apply to every OWL file any of the three tools writes.

1. **Upper ontology.** Classes are placed under BFO 2020 (`http://purl.obolibrary.org/obo/bfo.owl`). Information artifacts use IAO `IAO_0000030`.
2. **Keyword annotation.** Each domain class carries `kwv:keyword` with one of the fifteen keyword literals: `thing group place quality tendency function role authority record code status obligation happening moment period`. Kindwork uses it to restore placement exactly on re-import. A class without it is placed by walking its `rdfs:subClassOf` chain to a BFO anchor.
3. **Labels and definitions.** `rdfs:label` (English) and `obo:IAO_0000115` for the definition.
4. **Provenance.** A class justified by a passage carries `dcterms:source` with the passage text as a literal. A pointer to the source document, where one exists, is `prov:wasDerivedFrom` with an IRI. Kindwork reads both and shows them as quotes on the term.
5. **Links.** Class-level links are existential restrictions (`rdfs:subClassOf [ owl:onProperty P ; owl:someValuesFrom C ]`) using these properties, and only these:

| Kindwork link | Property |
|---|---|
| participant | `obo:BFO_0000057` has participant |
| at (happening, moment) | `obo:BFO_0000066` occurs in |
| at (thing) | `obo:BFO_0000171` located in |
| bearer | `obo:BFO_0000197` inheres in (Kindwork also reads `obo:BFO_0000196` bearer of, reversed) |
| during | `obo:BFO_0000199` occupies temporal region |
| about | `obo:IAO_0000136` is about |
| designates | `obo:IAO_0000219` denotes |
| member | `obo:RO_0002351` has member |
| heldBy, issuedBy, owedBy, owedTo, marks | `kwv:heldBy`, `kwv:issuedBy`, `kwv:owedBy`, `kwv:owedTo`, `kwv:marks` |
| scope | `kwv:canGrant` |

6. **No domain or range axioms** on these properties. Domain and range infer instead of constrain, and they move errors far from where they were made. Closed-world requirements live in SHACL.
7. **IRIs are stable.** A tool that receives a class IRI keeps it. Kindwork preserves imported IRIs on export, so findings keyed by IRI map back to the right term.

## 3. `kindwork-model` (JSON)

Written by Kindwork as `<slug>.kindwork.json`. Read by BFO-Agent as a seed and by OwlTester as a label map.

```json
{
  "format": "kindwork-model",
  "version": "0.1",
  "generator": "Kindwork",
  "generated": "2026-10-18T19:20:00.000Z",
  "app": "Job site tracker",
  "namespace": "https://example.org/kindwork/job-site-tracker",
  "vocabulary": "https://ontology.davidkoepsell.com/kindwork/vocab#",
  "task": "We manage electrical subcontractors on commercial job sites...",
  "terms": [
    {
      "id": "lic",
      "iri": "https://example.org/kindwork/job-site-tracker#ElectricalLicense",
      "name": "Electrical license",
      "definition": "The state license that lets a worker do electrical work.",
      "keyword": "status",
      "bfo": "BFO:0000031",
      "answers": { "r1": "n", "r2": "y", "b1": "n", "b2": "n", "b3": "y" },
      "signals": { "held": true },
      "provenance": [ { "quote": "track their state electrical license", "source": "" } ],
      "imported": null
    }
  ],
  "relations": [
    { "from": "lic", "rel": "heldBy", "to": "w", "property": "https://ontology.davidkoepsell.com/kindwork/vocab#heldBy" }
  ],
  "conflicts": [
    { "id": "auth-lic", "term": "lic", "type": "auth", "severity": "chain", "title": "Who issues it?" }
  ],
  "findings": []
}
```

Field rules:

- `keyword` is `null` when the interview is unfinished. Consumers must treat such a term as unplaced, never guess.
- `answers` keys are the interview question ids (`r1 r2 a1 a2 b1 b2 b3 c1 c2 c3 c4 c5 c5b c6`), values `y` or `n`. Only the path actually walked is present.
- `relations[].rel` is one of the link names in section 2, or `isA` for a domain subclass link. `property` is the full IRI that link compiles to.
- `conflicts` are Kindwork's open cards at export time. Severity is `partition`, `within`, or `chain`.
- Consumers ignore unknown fields. Producers never remove a field listed here.

## 4. `owltester-findings` (JSON)

Written by OwlTester. Read by Kindwork, which shows each finding as a card linked to the terms it names.

```json
{
  "format": "owltester-findings",
  "version": "0.1",
  "generated": "2026-10-18T19:40:00Z",
  "ontology": "https://example.org/kindwork/job-site-tracker",
  "reasoner": { "name": "HermiT", "version": "1.4.5.519", "profile": "OWL 2 DL" },
  "verdict": { "consistent": true, "coherent": false },
  "findings": [
    {
      "id": "coh-001",
      "check": "coherence",
      "severity": "partition",
      "verdict": "fail",
      "classes": [ "http://ex.org/x#Episode" ],
      "title": "Manic episode is entailed to be both a process and a disposition",
      "explanation": "The class sits under process through one parent and under disposition through another. BFO makes those disjoint, so the class is unsatisfiable and every inference that touches it is unsound.",
      "axioms": [ "Episode SubClassOf Disorder", "Disorder SubClassOf BFO_0000016", "Episode SubClassOf BFO_0000015" ]
    }
  ]
}
```

Field rules:

- `check`: `consistency`, `coherence`, `entailment`, `conformance`, or `chain`.
- `severity`: `partition` (crosses continuant and occurrent), `within` (disjoint categories on one side), `chain` (a recognition chain that does not close), `info`.
- `verdict` is three-valued: `fail`, `undetermined`, `pass`. A reasoner timeout, an unsupported construct, or a profile violation that prevents a decision is `undetermined`, never `pass`. Kindwork shows undetermined findings as open.
- `classes` are full IRIs exactly as they appear in the input ontology.
- `title` and `explanation` are written for the person who answered the interview: plain words, no logic notation. Notation goes in `axioms`.
- `verdict.consistent` and `verdict.coherent` may be `null` when the reasoner did not finish.

## 5. Work order: OwlTester adapter

Goal: OwlTester accepts what Kindwork exports and returns a findings file Kindwork can read.

1. **Accept the bundle.** Load `<slug>.ttl` (with `owl:imports` of BFO resolved), and optionally `<slug>-shapes.ttl` and `<slug>.kindwork.json`, from one upload or a zip.
2. **Label from the manifest.** When a `kindwork-model` is present, use its `name` fields, matched by IRI, in every `title` and `explanation`.
3. **Run the existing checks.** Consistency, coherence including partition straddle, and entailment. Map each to a finding with the severity rules in section 4.
4. **Add chain checks.** For each class with `kwv:keyword "status"`, fail with `severity: "chain"` if it has no `kwv:issuedBy` restriction, or if the issuing class lacks a `kwv:canGrant` restriction back to it. For each `"obligation"`, fail if it has no `kwv:owedTo` restriction.
5. **Run SHACL when shapes are present,** against any ABox in the upload. Each violation becomes a finding with `check: "conformance"` and the shape's `sh:message` as `title`.
6. **Emit `owltester-findings`** as a download, named `<slug>.findings.json`.

Hard stops:

- Never emit `verdict: "pass"` for a check that did not run to completion.
- Never rewrite or normalize class IRIs.
- Never put logic notation in `title` or `explanation`.

## 6. Work order: BFO-Agent adapter

Goal: BFO-Agent takes a Kindwork seed with documents and returns OWL that Kindwork merges with sources intact.

1. **Accept the seed.** Read `kindwork-model`. Treat each term with a non-null `keyword` as a target class with a fixed BFO parent, and each `relations` entry as an allowed link between targets.
2. **Propose against the seed first.** Extraction proposes subclasses of, instances of, and links between seed classes before anything else. New top-level classes are allowed and placed by the gate like any other proposal.
3. **Gate as now.** Each candidate is checked against BFO and the seed, and committed only if the reasoner accepts it. Refusals are logged with the candidate and the reason.
4. **Annotate what it commits.** Each committed class carries `rdfs:label`, `obo:IAO_0000115` where the text supports a definition, `kwv:keyword` for its keyword (derived from its BFO parent with the table in section 7), and `dcterms:source` with the exact passage.
5. **Keep seed IRIs.** Seed classes are written back under the IRIs the seed gave them.
6. **Emit** `<slug>.populated.ttl` and a refusal log `<slug>.refused.json`.

Hard stops:

- Never commit a class or axiom the gate refused.
- Never emit a committed class without `dcterms:source`.
- Never place a class under two BFO categories that BFO makes disjoint.
- Never change a seed class's BFO parent. A conflict with the seed is a refusal, logged with the passage.

## 7. Keyword and BFO table (normative)

| Keyword | BFO 2020 parent | Kindwork walks up from |
|---|---|---|
| thing | `BFO_0000040` material entity | object `0000030`, fiat object part `0000024` |
| group | `BFO_0000027` object aggregate | |
| place | `BFO_0000029` site | spatial region `0000006` |
| quality | `BFO_0000019` quality | relational quality `0000145` |
| tendency | `BFO_0000016` disposition | |
| function | `BFO_0000034` function | |
| role | `BFO_0000023` role | |
| authority | `BFO_0000023` role, authority pattern | |
| record | `IAO_0000030` information content entity | |
| code | `IAO_0000030`, designative | |
| status | `BFO_0000031` generically dependent continuant, recognition pattern | |
| obligation | `BFO_0000031`, obligation pattern | |
| happening | `BFO_0000015` process | history `0000182`, process profile `0000144` |
| moment | `BFO_0000035` process boundary | |
| period | `BFO_0000038` one-dimensional temporal region | temporal region `0000008`, temporal interval `0000202`, zero-dimensional ones |

An anchor above the keyword level fixes only the answers it settles. A class under realizable entity arrives with six answers set and the last questions asked. A class under generically dependent continuant arrives with two set. That is the bridge between the interview and an existing ontology, and both adapters should produce classes Kindwork can place this way.

## 8. Acceptance fixtures

Fixtures ship in `fixtures/`.

| Fixture | What it proves |
|---|---|
| `job-site-tracker.ttl`, `job-site-tracker-shapes.ttl`, `job-site-tracker.kindwork.json` | Kindwork export. OwlTester must load all three with no errors and emit a findings file Kindwork imports. Expected: consistent, plus two `chain` findings (license without an issuer, duty without a claimant). |
| `straddle.ttl` | A five-class clinic fragment. Expected in OwlTester: one `partition` fail (Manic episode, process plus disposition) and one `within` fail (Severity score, quality plus information content entity). Kindwork already shows the same two as cards on import. |
| `findings-sample.json` | A valid `owltester-findings` file keyed to `straddle.ttl`. Kindwork imports it and links the first finding to Manic episode. OwlTester's output on `straddle.ttl` should match its shape. |

Round trips already verified on Kindwork's side:

- Kindwork OWL, re-imported as Turtle: 14 of 14 classes, 14 of 14 links, zero keyword changes.
- The same OWL as RDF/XML: 14 of 14 classes and links, all placed.
- `kindwork-model` re-imported: zero keyword changes.
- Generated OWL and SHACL parse in rdflib (190 and 216 triples).

## 9. Scope limits

- Kindwork reads the asserted hierarchy only. It does not reason, so an inferred straddle reaches the user only through OwlTester findings.
- Kindwork imports at most 150 classes from one ontology, the ones closest to BFO. A 6,900-class ontology like SOoL is audited in OwlTester, not interviewed whole.
- Kindwork reads Turtle and RDF/XML. OWL functional syntax and OWL/XML are refused with a message to re-save.
- The artifact cannot call either tool over the network. The handoff is by file. A live connection is A3.

## ADJUDICATE

- **A1. Vocabulary home.** `kwv:` sits under `ontology.davidkoepsell.com`. Keep it there, or move it to a Legal Ontologies Foundry namespace once that exists. Either way, publish the vocabulary file at its IRI before any client sees an export.
- **A2. Chain checks: OwlTester or Kindwork.** Kindwork already raises chain conflicts from the interview. OwlTester raising them too gives a second, reasoner-side witness, but duplicates cards. Proposed: Kindwork suppresses a findings card when the same term has an open interview card of the same type.
- **A3. Live handoff.** Files work today. A shared endpoint on the Hetzner server (`POST /check` returning `owltester-findings`, `POST /populate` returning OWL) would let Kindwork call both tools in place, through the artifact's connector capability once they are exposed as MCP servers. Decide whether that is worth building before the March 31 gate.
- **A4. Provenance granularity.** `dcterms:source` with the passage text is readable but not locatable. Add `kwv:sourceDocument` and `kwv:sourceSpan` (character offsets) now, or wait until a client needs audit-grade traceability.
- **A5. Seed strictness.** Should BFO-Agent refuse classes outside the seed, or only rank them lower? Strict keeps a client's model tidy; open finds what the client did not know to ask about.
- **A6. Status compile target.** Inherited from the keyword spec (A1 there): a GDC concretized in a role of the holder. Both adapters should follow whatever is settled there.
- **A7. Namespace default.** Kindwork defaults client models to `https://example.org/kindwork/<slug>`. Clients should set their own; decide whether Kindwork should refuse to export with the example namespace.

## Running the fixtures

Kindwork: open it, choose "Bring an ontology", load a fixture. OwlTester and BFO-Agent: per their own READMEs once the adapters land. Every Markdown deliverable built from this spec is checked for em-dashes before release.
