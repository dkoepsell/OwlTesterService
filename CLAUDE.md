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
