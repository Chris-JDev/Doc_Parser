"""SQLAlchemy ORM models."""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean, ForeignKey, Float
from sqlalchemy.orm import relationship
from app.db import Base


def generate_uuid():
    return str(uuid.uuid4())


class Document(Base):
    """Document model storing processed PDF information."""
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    original_filename = Column(String(255), nullable=False)
    stored_pdf_path = Column(String(512), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default="queued")  # queued|processing|done|failed|canceled
    page_count = Column(Integer, default=0)
    total_time_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Processing options
    translate_to_english = Column(Boolean, default=False)
    
    # Number of invoices detected in this document
    invoice_count = Column(Integer, default=0)
    
    # Path to combined JSON (all invoices)
    json_path = Column(String(512), nullable=True)
    
    # Relationships
    pages = relationship("Page", back_populates="document", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="document", cascade="all, delete-orphan")
    job = relationship("Job", back_populates="document", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Document(id={self.id}, filename={self.original_filename}, status={self.status})>"


class Page(Base):
    """Page model storing per-page extraction data."""
    __tablename__ = "pages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=False)
    page_index = Column(Integer, nullable=False)  # 0-based
    image_path = Column(String(512), nullable=True)
    extracted_text_path = Column(String(512), nullable=True)
    extracted_text_preview = Column(Text, nullable=True)  # First ~500 chars for quick display
    page_time_ms = Column(Integer, nullable=True)
    status = Column(String(50), default="pending")  # pending|processing|done|failed
    raw_json_path = Column(String(512), nullable=True)  # Path to raw/failed JSON output
    error_message = Column(Text, nullable=True)  # Error message if structuring failed

    # Relationship
    document = relationship("Document", back_populates="pages")

    def __repr__(self):
        return f"<Page(id={self.id}, doc_id={self.document_id}, page={self.page_index})>"


class Invoice(Base):
    """Invoice model storing individual invoice data extracted from a document."""
    __tablename__ = "invoices"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=False)
    invoice_index = Column(Integer, nullable=False)  # 0-based index within document
    
    # Page range for this invoice (inclusive)
    start_page = Column(Integer, nullable=True)
    end_page = Column(Integer, nullable=True)
    
    # Extracted identifiers
    document_number = Column(String(100), nullable=True)  # Invoice/Receipt/Bill/Order number
    reference_numbers_json = Column(Text, nullable=True)
    issue_date = Column(String(20), nullable=True)
    supplier_name = Column(String(255), nullable=True)
    customer_name = Column(String(255), nullable=True)
    gross_amount = Column(Float, nullable=True)
    currency = Column(String(10), nullable=True)
    
    # Path to individual invoice JSON
    json_path = Column(String(512), nullable=True)
    
    # Relationship
    document = relationship("Document", back_populates="invoices")

    def __repr__(self):
        return f"<Invoice(id={self.id}, doc_id={self.document_id}, index={self.invoice_index})>"


class Job(Base):
    """Job model for tracking processing state and cancellation."""
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("documents.id"), unique=True, nullable=False)
    cancel_requested = Column(Boolean, default=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    current_page = Column(Integer, default=0)
    
    # Relationship
    document = relationship("Document", back_populates="job")

    def __repr__(self):
        return f"<Job(id={self.id}, doc_id={self.document_id}, canceled={self.cancel_requested})>"
