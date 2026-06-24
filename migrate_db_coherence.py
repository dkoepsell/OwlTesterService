"""Add coherence and BFO conformance lint columns to ontology_analysis.

Mirrors migrate_db.py. Adds:
  - unsatisfiable_classes (JSON): named classes proven equal to owl:Nothing
  - lint_findings (JSON): BFO partition-straddle findings
  - coherence_status (varchar): coherent | incoherent | inconsistent | unknown

Run inside the app container against PostgreSQL:
    docker compose exec app python migrate_db_coherence.py

PostgreSQL supports ADD COLUMN IF NOT EXISTS. SQLite does not, so for the SQLite
fallback we add each column individually and ignore "duplicate column" errors;
fresh SQLite databases get these columns from db.create_all() anyway.
"""

import os

from sqlalchemy import create_engine, text

PG_STATEMENTS = [
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS unsatisfiable_classes JSONB;",
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS lint_findings JSONB;",
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS coherence_status VARCHAR(20);",
]

SQLITE_STATEMENTS = [
    "ALTER TABLE ontology_analysis ADD COLUMN unsatisfiable_classes JSON;",
    "ALTER TABLE ontology_analysis ADD COLUMN lint_findings JSON;",
    "ALTER TABLE ontology_analysis ADD COLUMN coherence_status VARCHAR(20);",
]


def migrate_database():
    """Run the migration. Returns True on success."""
    print("Starting coherence/lint migration...")

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
