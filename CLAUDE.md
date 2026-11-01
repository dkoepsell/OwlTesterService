# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
# Development server
python main.py

# Production-like (matches deployment)
gunicorn --bind 0.0.0.0:5000 --reload main:app
```

**Required environment variables:**
- `DATABASE_URL` — PostgreSQL connection string (defaults to SQLite `owl_tester.db` if unset)
- `OPENAI_API_KEY` — For AI-powered implication generation and suggestions
- `SESSION_SECRET` — Flask session encryption key

## Database

The app uses **PostgreSQL in production** and **SQLite as fallback**. Tables are auto-created via `db.create_all()` on startup. When adding new columns, create a migration script (see `migrate_db.py`, `migrate_db_transparency.py`, `migrate_file_history.py` as examples) rather than modifying existing ones.

## Architecture

**Entry point:** `main.py` → imports `app` from `app.py` and calls `app.run()`.

**`app.py`** (2,669 lines) is the monolithic core containing all 40+ Flask routes and request handlers. Routes are organized into groups: auth, file upload/management, analysis, visualization, sandbox (ontology builder), and JSON API endpoints.

**`owl_tester.py`** (938 lines) is the ontology analysis engine. It handles OWL parsing via Owlready2 (primary) with RDFlib as a fallback, consistency checking with multiple reasoners (Pellet/HermiT via Java), expressivity detection, and axiom extraction.

**`models.py`** defines all SQLAlchemy models: `User`, `OntologyFile`, `OntologyAnalysis`, `FOLExpression`, `SandboxOntology`, `OntologyClass`, `OntologyProperty`, `OntologyIndividual`. Many fields store JSON blobs (axioms, implications, reasoning traces, entity lists).

**`improved_openai_utils.py` / `openai_utils.py`** handle GPT-4o API calls for generating real-world implications from ontology premises and AI-powered class/BFO-category suggestions.

**`bfo_2020_definitions.py`** contains the complete BFO-2020 class hierarchy and relation definitions used for FOL expression validation and BFO compatibility checking.

**`owl_format_detector.py`** auto-detects and converts between OWL serialization formats (RDF/XML, Turtle, N-Triples, OFN, OWX) before parsing.

**Visualization pipeline:** `bvss_model.py` converts OWL to BVSS (Barwise Visual Symbol System) format → `bvss_validator.py` validates it → D3.js renders interactive diagrams in `static/js/ontology-visualizer.js`.

**`plantuml_generator.py`** generates UML class hierarchy diagrams from ontology data using PlantUML (requires Java).

## Key API Endpoints

- `POST /api/test-expression` — validates FOL expressions for BFO compatibility
- `GET /api/analyze/<filename>` — returns full ontology analysis as JSON
- `POST /api/analysis/<id>/implications` — triggers OpenAI implication generation
- `GET /api/diagram-data/<filename>` — returns D3.js-ready graph data
- `GET /api/bvss/<filename>` — returns BVSS visualization data
- `GET /api/get-bfo-classes` / `GET /api/get-bfo-relations` — BFO vocabulary

## File Upload

Uploads go to `uploads/` directory. Allowed extensions: `owl`, `rdf`, `xml`, `ttl`, `n3`, `nt`, `ofn`, `own`, `owx`. Max 16MB. The format detector normalizes files before analysis.

**Multi-file (modular) uploads:** several files or a `.zip` (optionally with `catalog-v001.xml`) go through `ontology_bundle.py`, which resolves `owl:imports` locally (IRI / version IRI / catalog / file name; BFO → vendored), merges the top-level module's import closure into the single stored file, and writes `<file>.bundle.json` (manifest, per-entity module) plus a `<stem>_modules/` dir. `bundle_layers.py` + `/api/bundle/<filename>/layers` reason over each module's closure bottom-up to find the first breaking layer.

**Full artifact audit (`SPEC-audit.md`):** `owltester/audit/` audits a released artifact (ontology, vocabularies, SHACL shapes, data; usually a zip) in stages R0 (roles, data sets, owned namespaces; `artifact.py`, `files.py`, optional `audit.yaml`) to R10, plus conceptual lenses (`lenses.py`, `lens_files/`). No stage halts the audit; findings are folded (`AuditFinding`/`AuditReport` in `owltester/model.py`, codes in `errors.py`). Reasoning goes through `kindwork.module_reasoner.consistency` (HermiT, Pellet cross-check) on a datatype-patched copy. CLI: `python -m owltester.cli audit <zip|dir> [--json|--html|--md]` (exit 1 only on `fail`). Web: `POST /owltester/audit` starts a background job (`audit/jobs.py`, sidecar under `uploads/audits/<job_id>/`), `/audit/<job_id>` polls and renders; audits are private: sign-in required, only accounts in `AUDIT_ALLOWED_USERS` may start one (empty means nobody), and a job is visible only to its owner (no public or anonymous audits). Golden fixture `fixtures/audit/lomo-1.0.0-trimmed/` with `expected-lomo.json`; mini fixtures are overlays on `fixtures/audit/mini/clean/`.

**Guided release repair (`SPEC-audit-repair.md`):** `owltester/release_repair/` turns a finished audit into a fix plan. `catalog*.py` build one `Remedy` per finding (options with exact ops and previews, computed from the release itself); `ops.py` is the closed op set (`rewrite_iri`, `set_literal`, `add_triples`, `remove_triples`, `retype`, `merge_nodes`, `write_text`, `exclude_file`), each with a guard, writing Turtle through `turtle_splice.py` so untouched statements keep their bytes; `templates.py` holds the only text templates `write_text` may render; `planner.py` records decisions (accept, skip, declare with a reason, reopen, revert); `apply.py` copies the release, enforces the removal bound (`REPAIR_MAX_REMOVED`, axioms counted by top-level statement), applies in plan order, writes the repaired zip (deterministic), `repair.patch`, `FIXLOG.json/.md`, a CHANGELOG draft and both audits, then re-audits and compares. Routes in `owltester/repair_service.py` (`/audit/<job_id>/repair...`, JSON under `/owltester/audit/<job_id>/repair/...`); access in `release_repair/access.py`: `REPAIR_ALLOWED_USERS` empty means nobody, never anonymous, plans shared per plan as approver or reviewer. The audit keeps the release (`<job>/release/`) only when its owner may repair. CLI: `repair-plan`, `repair-apply`.

**Audited releases (`SPEC-release.md`):** `owltester/release/`. Part A (gate): `gate.py` (`--fail-on`, CI summary, shields badge), `record.py` (`VERIFICATION.json/.md`, `audit/report.*` inside the release, `verify` with checksums and `--reaudit`; the audit loader skips these files, `NOT_AUDITED` in `audit/artifact.py`), R10 credits the OwlTester Action/CLI as SHACL and reasoning and reports `I_VERIFIED` / `W_RECORD_MISMATCH`. CLI: `audit --fail-on --summary-md`, `record`, `verify`, `build`; exit 2 = tool or input error. `Dockerfile` target `cli` (slim, `requirements-cli.txt`); the Action is `action/` (composite: runs the CLI image, `owltester.release.action` is its entry point; templates in `action/templates/`, kept equal to `owltester/release/templates/workflow-*.tmpl` by a test); `.github/workflows/cli-image.yml` publishes to GHCR on tags, `action-selftest.yml` runs the Action on `fixtures/release/gate-repo`. Part B (builder): `builder.build()` = metadata, imports (supplied files or vendored BFO whole / BOT module), ROBOT base + merged/reasoned full + formats (as the LOF Makefile), docs (terms, offline SVG diagram, CHANGELOG from the diff), QC/CQ/SHACL starters, audit, record, deterministic zips, repository scaffold, w3id `.htaccess`. Text files only from `owltester/release/templates/*.tmpl` via `docs.render` (strict `{{slot}}`). Web: `owltester/release_service.py` (`/release/new`, steps, `/release/<id>`; `BUILD_ALLOWED_USERS` empty means nobody; hand-off to guided repair; GitHub publish with the owner's token, dry run then confirm). Builds need ROBOT: `robot` on PATH or `ROBOT_JAR`.

## Kindwork

Guided ontology building for laypeople, specified in `kindwork_core/docs/` (module spec 0.2.0 and the ecosystem spec).

- **`kindwork_core/`** holds the Kindwork implementation and runs it as a Node sidecar (`bin/kindwork-core.mjs`, one JSON request per process). `core/kindwork.html` is **forked** here (since the Connect step): OwlTester is its upstream, so edit it in place, never copy a newer reference page over it without merging by hand. After any change run `npm test` there plus `tests/test_kindwork*.py`, and put the new `X-Kindwork-Core` hash in the commit.
- **Connect** (step 3) turns the taxonomy into an ontology: per-kind relation slots in `SLOTS`, each read as a rule ("Every X ... some Y", the OWL existential) with teaching text in `SAY`. `partOf` maps to continuant or occurrent part of by kind; `precedes`, `resultsIn` (RO has output) and `keptOn` (generically depends on) are the structural additions. `propose` takes `kind: "relations"` for suggested connections, filtered to the slots on both the sidecar and the OpenAI paths.
- **`kindwork/module_routes.py`** serves `GET /kindwork` (the vendored page with one injected `KINDWORK_HOST` script, which also carries the measurement beacon and the AI key bar), `/kindwork/v1/{health,ingest,propose,check,build,import,lint,event}` and `/kindwork/mcp`.
- **Check** runs `kindwork/module_reasoner.py`: HermiT with a Pellet cross-check over BFO 2020 plus the IAO bridge, offline.
- **Propose** uses only the visitor's own key, the same session key as implications (`api_key_utils`), or `X-AI-Key` for API/MCP clients. Server keys are stripped from the sidecar on purpose.
- **`kindwork/metrics.py`** keeps the P1 log: counts only, 12-month retention.
- **`kindwork/routes.py`** holds the export check (`POST /kindwork/check`), `/kindwork/workbench` and the `kwv:` vocabulary.
- **`KINDWORK_MODE`**: `triage` (public, rate-limited) or `full` (sign-in required).
- Browser tests (`tests/test_kindwork_ui.py`) need `pip install playwright` and `playwright install chromium-headless-shell`.

## Frontend

Templates use Jinja2 with Bootstrap 5 dark theme. D3.js v7 handles interactive ontology graphs. Key JS files: `static/js/script.js` (main page FOL tester), `static/js/sandbox.js` (ontology builder), `static/js/ontology-visualizer.js` (D3 visualization).

## Self-Hosting / VPS Deployment

The app ships with a Docker Compose stack: `app` (Flask/gunicorn), `db` (PostgreSQL 16), and a bundled `nginx` (reverse proxy). See `deploy.md` for full instructions — there are **two topologies**, and the production box does **not** use the default one:

- **Topology A — self-contained (repo default):** the bundled `nginx` container owns 80/443 and terminates TLS. Use on a dedicated single-app server.
- **Topology B — behind an existing host nginx (PRODUCTION):** a host-level Ubuntu nginx owns 80/443 and reverse-proxies the domain to the app. The bundled `nginx` service is removed.

> ⚠️ **Production reality:** `ontology.davidkoepsell.com` runs on a Hetzner host (`204.168.167.44`, project dir `/root/OwlTesterService`) that **also hosts a separate app** (Everdice / realmofeverdice.com). A host nginx fronts both. On that box the `nginx` service has been deleted from `docker-compose.yml` and `app` is published on `127.0.0.1:5000`; the host nginx vhost `/etc/nginx/sites-available/ontology` proxies to it, with TLS via the host's certbot (`--nginx` plugin). Do **not** redeploy it with the repo-default bundled nginx — it will collide on 80/443 and crash-loop (`host not found in upstream "app"`). That host also only has `docker-compose` v1, which needs `docker rm -f <container>` before `docker-compose up -d` to dodge a `KeyError: 'ContainerConfig'` recreate bug.

**First-time setup (Topology A):**
```bash
cp .env.example .env
# Edit .env — set SESSION_SECRET, OPENAI_API_KEY, POSTGRES_PASSWORD
docker compose up -d --build
```

**Gunicorn config:** `gunicorn.conf.py` — worker timeout is 180 s to accommodate slow OWL reasoners. Increase if you see 502 errors on large ontologies.

**Persistent data:** uploads and PostgreSQL data are stored in named Docker volumes (`uploads`, `postgres_data`). Back these up before any `docker compose down -v`.

**Database migrations:** Run migration scripts directly inside the app container:
```bash
docker compose exec app python migrate_db.py
```
