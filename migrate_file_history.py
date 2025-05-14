import logging
import os

from app import app, db
from sqlalchemy import Column, Boolean, Integer, ForeignKey, text
from models import OntologyFile

logger = logging.getLogger(__name__)

def add_sandbox_fields():
    """Add sandbox-related fields to the OntologyFile table."""
    try:
        # Ensure we have an application context
        ctx = app.app_context()
        ctx.push()
        
        # Check if the column exists
        inspector = db.inspect(db.engine)
        columns = [column['name'] for column in inspector.get_columns('ontology_file')]
        
        # Add from_sandbox column if it doesn't exist
        if 'from_sandbox' not in columns:
            logger.info("Adding from_sandbox column to OntologyFile table")
            db.session.execute(text('ALTER TABLE ontology_file ADD COLUMN from_sandbox BOOLEAN NOT NULL DEFAULT FALSE'))
            
        # Add sandbox_ontology_id column if it doesn't exist
        if 'sandbox_ontology_id' not in columns:
            logger.info("Adding sandbox_ontology_id column to OntologyFile table")
            db.session.execute(text('ALTER TABLE ontology_file ADD COLUMN sandbox_ontology_id INTEGER REFERENCES sandbox_ontology(id)'))
            
        db.session.commit()
        logger.info("Added sandbox fields to OntologyFile table")
        
        # Print the current table structure
        inspector = db.inspect(db.engine)
        columns_after = [column['name'] for column in inspector.get_columns('ontology_file')]
        logger.info(f"Columns: {columns_after}")
        
        ctx.pop()
        return True
    except Exception as e:
        logger.error(f"Error adding sandbox fields to OntologyFile table: {str(e)}")
        try:
            db.session.rollback()
        except:
            pass
        return False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    success = add_sandbox_fields()
    if success:
        print("Migration completed successfully")
    else:
        print("Migration failed")