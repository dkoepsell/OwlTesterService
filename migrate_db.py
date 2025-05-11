import os
import sys
from sqlalchemy import create_engine, Column, JSON, text
from sqlalchemy.sql import ddl
from models import db, OntologyAnalysis

def migrate_database():
    """Run database migrations to add new columns."""
    print("Starting database migration...")
    
    # Get connection from environment
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("Error: DATABASE_URL environment variable not set")
        return False
    
    # Create engine
    engine = create_engine(database_url)
    
    try:
        # Check if columns exist
        with engine.connect() as conn:
            # Add class_list column if it doesn't exist
            conn.execute(text("""
                ALTER TABLE ontology_analysis 
                ADD COLUMN IF NOT EXISTS class_list JSONB;
            """))
            
            # Add object_property_list column if it doesn't exist
            conn.execute(text("""
                ALTER TABLE ontology_analysis 
                ADD COLUMN IF NOT EXISTS object_property_list JSONB;
            """))
            
            # Add data_property_list column if it doesn't exist
            conn.execute(text("""
                ALTER TABLE ontology_analysis 
                ADD COLUMN IF NOT EXISTS data_property_list JSONB;
            """))
            
            # Add individual_list column if it doesn't exist
            conn.execute(text("""
                ALTER TABLE ontology_analysis 
                ADD COLUMN IF NOT EXISTS individual_list JSONB;
            """))
            
            conn.commit()
        
        print("Migration completed successfully!")
        return True
        
    except Exception as e:
        print(f"Error during migration: {str(e)}")
        return False

if __name__ == "__main__":
    migrate_database()