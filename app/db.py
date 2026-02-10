"""Database setup and session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency to get DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_db():
    """Run simple migrations for new columns."""
    from sqlalchemy import text
    
    with engine.connect() as conn:
        # Check if raw_json_path column exists in pages table
        result = conn.execute(text("PRAGMA table_info(pages)"))
        columns = [row[1] for row in result.fetchall()]
        
        if "raw_json_path" not in columns:
            conn.execute(text("ALTER TABLE pages ADD COLUMN raw_json_path VARCHAR(512)"))
            conn.commit()
        
        if "error_message" not in columns:
            conn.execute(text("ALTER TABLE pages ADD COLUMN error_message TEXT"))
            conn.commit()
        
        # Ensure document_number exists in invoices table
        result = conn.execute(text("PRAGMA table_info(invoices)"))
        inv_columns = [row[1] for row in result.fetchall()]
        
        if "document_number" not in inv_columns:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN document_number VARCHAR(100)"))
            conn.commit()


def init_db():
    """Initialize database tables."""
    from app.models import Document, Page, Job  # noqa: F401
    Base.metadata.create_all(bind=engine)
    migrate_db()
