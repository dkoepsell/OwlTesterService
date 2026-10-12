"""Add foreign-key indexes to the sandbox tables.

Without them, deleting a sandbox (cascade over its classes/properties/
individuals) and every per-sandbox listing does a sequential scan of
ontology_class, which hurts badly once that table holds millions of rows.
Creates:
  - ix_ontology_class_ontology_id   ON ontology_class (ontology_id)
  - ix_ontology_class_parent_id     ON ontology_class (parent_id)
  - ix_ontology_individual_class_id ON ontology_individual (class_id)
  - ix_ontology_property_domain     ON ontology_property (domain_class_id)
  - ix_ontology_property_range      ON ontology_property (range_class_id)

The names match the __table_args__ in models.py, so a fresh database built by
db.create_all() already has them and this script is a no-op there. Idempotent
(IF NOT EXISTS) on both PostgreSQL and SQLite.

Run inside the app container against PostgreSQL:
    docker compose exec app python migrate_db_sandbox_indexes.py
"""

import os

from sqlalchemy import create_engine, text

INDEXES = [
    ("ix_ontology_class_ontology_id", "ontology_class", "ontology_id"),
    ("ix_ontology_class_parent_id", "ontology_class", "parent_id"),
    ("ix_ontology_individual_class_id", "ontology_individual", "class_id"),
    ("ix_ontology_property_domain", "ontology_property", "domain_class_id"),
    ("ix_ontology_property_range", "ontology_property", "range_class_id"),
]

STATEMENTS = [
    f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column});"
    for name, table, column in INDEXES
]


def migrate_database():
    """Run the migration. Returns True on success."""
    print("Starting sandbox index migration...")

    database_url = os.environ.get('DATABASE_URL', 'sqlite:///owl_tester.db')
    engine = create_engine(database_url)

    try:
        with engine.connect() as conn:
            for stmt in STATEMENTS:
                print(f"  {stmt}")
                conn.execute(text(stmt))
            conn.commit()

        print("Migration completed successfully!")
        return True

    except Exception as e:
        print(f"Error during migration: {str(e)}")
        return False


if __name__ == "__main__":
    migrate_database()
