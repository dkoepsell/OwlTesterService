"""Add recognition-layer columns to ontology_analysis.

Mirrors migrate_db_prover.py. Adds:
  - recognition_binding (JSON): entity IRI -> recognition-chain locus, declared
    by the user where the automatic proposal cannot decide
  - institutional_record (JSON): the adjudications, acts, and modal pairs that
    Stratum D needs and that no OWL file can supply
  - recognition_report (JSON): the last built report, cached
  - declared_object_class (varchar): which row of the system-class table the
    ontology's *object* occupies, which the artifact cannot tell us

Run inside the app container against PostgreSQL:
    docker compose exec app python migrate_db_recognition.py

PostgreSQL supports ADD COLUMN IF NOT EXISTS. SQLite does not, so for the SQLite
fallback we add each column individually and ignore "duplicate column" errors;
fresh SQLite databases get these columns from db.create_all() anyway.
"""

import os

from sqlalchemy import create_engine, text

PG_STATEMENTS = [
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS recognition_binding JSON;",
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS institutional_record JSON;",
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS recognition_report JSON;",
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS declared_object_class VARCHAR(32);",
]

SQLITE_STATEMENTS = [
    "ALTER TABLE ontology_analysis ADD COLUMN recognition_binding JSON;",
    "ALTER TABLE ontology_analysis ADD COLUMN institutional_record JSON;",
    "ALTER TABLE ontology_analysis ADD COLUMN recognition_report JSON;",
    "ALTER TABLE ontology_analysis ADD COLUMN declared_object_class VARCHAR(32);",
]


def migrate_database():
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
