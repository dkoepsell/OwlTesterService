"""Add provable-FOL-export columns to ontology_analysis (SPEC Task 5).

Mirrors migrate_db_coherence.py. Adds:
  - fol_prover9 (text): the ontology's axioms in Prover9 / LADR syntax
  - fol_clif (text): the ontology's axioms in CLIF (Common Logic) syntax
  - fol_export_stats (JSON): counts (classes, subsumptions, disjoint axioms, ...)
  - prover_cross_check (JSON): prover9/mace4 verdict vs the OWL reasoner

Run inside the app container against PostgreSQL:
    docker compose exec app python migrate_db_prover.py

PostgreSQL supports ADD COLUMN IF NOT EXISTS. SQLite does not, so for the SQLite
fallback we add each column individually and ignore "duplicate column" errors;
fresh SQLite databases get these columns from db.create_all() anyway.
"""

import os

from sqlalchemy import create_engine, text

PG_STATEMENTS = [
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS fol_prover9 TEXT;",
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS fol_clif TEXT;",
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS fol_export_stats JSONB;",
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS prover_cross_check JSONB;",
]

SQLITE_STATEMENTS = [
    "ALTER TABLE ontology_analysis ADD COLUMN fol_prover9 TEXT;",
    "ALTER TABLE ontology_analysis ADD COLUMN fol_clif TEXT;",
    "ALTER TABLE ontology_analysis ADD COLUMN fol_export_stats JSON;",
    "ALTER TABLE ontology_analysis ADD COLUMN prover_cross_check JSON;",
]


def migrate_database():
    """Run the migration. Returns True on success."""
    print("Starting provable-FOL-export migration...")

    database_url = os.environ.get('DATABASE_URL', 'sqlite:///owl_tester.db')
    engine = create_engine(database_url)
    is_sqlite = engine.dialect.name == 'sqlite'

    try:
        with engine.connect() as conn:
            if is_sqlite:
                for stmt in SQLITE_STATEMENTS:
                    try:
                        conn.execute(text(stmt))
                    except Exception as e:
                        if 'duplicate column' in str(e).lower():
                            print(f"  skipping (already present): {stmt}")
                        else:
                            raise
            else:
                for stmt in PG_STATEMENTS:
                    conn.execute(text(stmt))
            conn.commit()

        print("Migration completed successfully!")
        return True

    except Exception as e:
        print(f"Error during migration: {str(e)}")
        return False


if __name__ == "__main__":
    migrate_database()
