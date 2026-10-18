"""Add the entity_labels column to ontology_analysis.

Mirrors migrate_db_coherence.py. Adds:
  - entity_labels (JSON): IRI local name -> rdfs:label / skos:prefLabel, so
    ontologies with opaque IRIs display human-readable entity names.

Run inside the app container against PostgreSQL:
    docker compose exec app python migrate_db_labels.py

Existing analyses keep a NULL map (they display IDs as before); re-analyse a
file to populate it. Fresh SQLite databases get the column from db.create_all().
"""

import os

from sqlalchemy import create_engine, text

PG_STATEMENTS = [
    "ALTER TABLE ontology_analysis ADD COLUMN IF NOT EXISTS entity_labels JSONB;",
]

SQLITE_STATEMENTS = [
    "ALTER TABLE ontology_analysis ADD COLUMN entity_labels JSON;",
]


def migrate_database():
    """Run the migration. Returns True on success."""
    print("Starting entity_labels migration...")

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
