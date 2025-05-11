import logging
import sys
import os
import datetime
from sqlalchemy import inspect, text
from app import app, db

def add_transparency_fields():
    """Add transparency fields to the OntologyAnalysis table."""
    app.logger.info("Starting database migration to add transparency fields")
    
    try:
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('ontology_analysis')]
        
        with app.app_context():
            # Add reasoning_methodology field if it doesn't exist
            if 'reasoning_methodology' not in columns:
                app.logger.info("Adding reasoning_methodology field")
                db.session.execute(text("ALTER TABLE ontology_analysis ADD COLUMN reasoning_methodology JSONB"))
            
            # Add derivation_steps field if it doesn't exist
            if 'derivation_steps' not in columns:
                app.logger.info("Adding derivation_steps field")
                db.session.execute(text("ALTER TABLE ontology_analysis ADD COLUMN derivation_steps JSONB"))
                
            db.session.commit()
            app.logger.info("Migration successful")
            return True
    except Exception as e:
        app.logger.error(f"Error during migration: {str(e)}")
        return False

if __name__ == "__main__":
    app.logger.info("Running database migration for transparency fields")
    if add_transparency_fields():
        app.logger.info("Migration completed successfully")
    else:
        app.logger.error("Migration failed")
        sys.exit(1)