"""Job processing service with SSE events and cancellation support."""
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, AsyncGenerator, Optional
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from app.models import Document, Page, Job, Invoice
from app.services.pdf_to_images import pdf_converter
from app.services.extractor import text_extractor
from app.services.structurer import json_structurer
from app.services.ollama_client import structuring_client

# ============================================================================
# OLLAMA INTEGRATION POINTS - Import these for your processing
# ============================================================================
# See app/services/ollama_example.py for detailed examples
#
# from app.services.ollama_example import (
#     send_image_to_ollama,      # Send image + prompt -> get text
#     send_prompt_to_ollama,     # Send text prompt -> get response
#     encode_image_to_base64,    # Helper to encode images
# )
# ============================================================================

logger = logging.getLogger(__name__)


@dataclass
class JobEvent:
    """Event emitted during job processing."""
    event_type: str  # status, page_done, error, canceled, done
    data: dict = field(default_factory=dict)
    
    def to_sse(self) -> str:
        """Format as SSE message."""
        data_json = json.dumps(self.data)
        return f"event: {self.event_type}\ndata: {data_json}\n\n"


class JobRegistry:
    """In-memory registry for active jobs and their cancel flags."""
    
    def __init__(self):
        self._cancel_flags: Dict[str, bool] = {}
        self._event_queues: Dict[str, asyncio.Queue] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
    
    def register_job(self, job_id: str):
        """Register a new job."""
        self._cancel_flags[job_id] = False
        self._event_queues[job_id] = asyncio.Queue()
        self._locks[job_id] = asyncio.Lock()
        logger.info(f"Registered job {job_id}")
    
    def unregister_job(self, job_id: str):
        """Unregister a completed job."""
        self._cancel_flags.pop(job_id, None)
        self._event_queues.pop(job_id, None)
        self._locks.pop(job_id, None)
        logger.info(f"Unregistered job {job_id}")
    
    def request_cancel(self, job_id: str):
        """Request cancellation of a job."""
        if job_id in self._cancel_flags:
            self._cancel_flags[job_id] = True
            logger.info(f"Cancel requested for job {job_id}")
    
    def is_cancel_requested(self, job_id: str) -> bool:
        """Check if cancellation was requested."""
        return self._cancel_flags.get(job_id, False)
    
    async def emit_event(self, job_id: str, event: JobEvent):
        """Emit an event for a job."""
        if job_id in self._event_queues:
            await self._event_queues[job_id].put(event)
    
    async def get_events(self, job_id: str) -> AsyncGenerator[JobEvent, None]:
        """Get event stream for a job."""
        if job_id not in self._event_queues:
            return
        
        queue = self._event_queues[job_id]
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield event
                if event.event_type in ("done", "canceled", "error"):
                    break
            except asyncio.TimeoutError:
                # Send keepalive
                yield JobEvent("keepalive", {"timestamp": datetime.utcnow().isoformat()})


# Global job registry
job_registry = JobRegistry()


class JobProcessor:
    """Process document jobs with page-by-page extraction and structuring."""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def process_document(self, document_id: str, job_id: str):
        """
        Main processing pipeline for a document.
        
        Args:
            document_id: Document ID to process
            job_id: Job ID for tracking
        """
        start_time = time.time()
        
        # Get document and job from DB
        document = self.db.query(Document).filter(Document.id == document_id).first()
        job = self.db.query(Job).filter(Job.id == job_id).first()
        
        if not document or not job:
            logger.error(f"Document or job not found: doc={document_id}, job={job_id}")
            return
        
        # Register job for cancellation tracking
        job_registry.register_job(job_id)
        
        try:
            # Update status to processing
            document.status = "processing"
            job.started_at = datetime.utcnow()
            self.db.commit()
            
            await job_registry.emit_event(job_id, JobEvent("status", {
                "status": "processing",
                "message": "Starting document processing..."
            }))
            
            # Step 1: Convert PDF to images
            pdf_path = Path(document.stored_pdf_path)
            
            await job_registry.emit_event(job_id, JobEvent("status", {
                "status": "converting",
                "message": "Converting PDF to images..."
            }))
            
            try:
                image_paths = pdf_converter.convert(pdf_path, document_id)
            except Exception as e:
                raise RuntimeError(f"PDF conversion failed: {e}")
            
            document.page_count = len(image_paths)
            self.db.commit()
            
            # Emit event for each converted image
            await job_registry.emit_event(job_id, JobEvent("pdf_converted", {
                "message": f"PDF converted to {len(image_paths)} images",
                "total_pages": len(image_paths),
                "images": [{"page_index": idx, "page_number": idx + 1} for idx in range(len(image_paths))]
            }))
            
            # Create page records
            for idx, image_path in enumerate(image_paths):
                page = Page(
                    document_id=document_id,
                    page_index=idx,
                    image_path=str(image_path),
                    status="pending"
                )
                self.db.add(page)
            self.db.commit()
            
            await job_registry.emit_event(job_id, JobEvent("status", {
                "status": "extracting",
                "message": f"Processing {len(image_paths)} pages...",
                "total_pages": len(image_paths)
            }))
            
            # Step 2: Process each page - extract text AND structure JSON for each page
            pages_processed = 0
            invoices_created = 0
            
            for idx, image_path in enumerate(image_paths):
                page_number = idx + 1
                
                # Check for cancellation before each page
                if job_registry.is_cancel_requested(job_id) or self._check_db_cancel(job_id):
                    await self._handle_cancellation(document, job, job_id, pages_processed, start_time)
                    return
                
                # Get page record
                page = self.db.query(Page).filter(
                    Page.document_id == document_id,
                    Page.page_index == idx
                ).first()
                
                page.status = "processing"
                job.current_page = idx
                self.db.commit()
                
                try:
                    # Step 2a: Extract text from page
                    await job_registry.emit_event(job_id, JobEvent("status", {
                        "status": "extracting",
                        "message": f"Extracting text from page {page_number}/{len(image_paths)}..."
                    }))
                    
                    extracted_text, extract_time_ms = await text_extractor.extract_text(Path(image_path))
                    
                    # Save extracted text
                    text_path = text_extractor.save_extracted_text(
                        extracted_text, document_id, idx
                    )
                    
                    # Update page record
                    page.extracted_text_path = str(text_path)
                    page.extracted_text_preview = extracted_text[:500] if extracted_text else ""
                    self.db.commit()
                    
                    # Emit text extracted event with full text
                    await job_registry.emit_event(job_id, JobEvent("text_extracted", {
                        "page_index": idx,
                        "page_number": page_number,
                        "total_pages": len(image_paths),
                        "text": extracted_text,
                        "text_length": len(extracted_text),
                        "extract_time_ms": extract_time_ms
                    }))
                    
                    # Step 2b: Structure page text into JSON
                    await job_registry.emit_event(job_id, JobEvent("status", {
                        "status": "structuring",
                        "message": f"Structuring page {page_number}/{len(image_paths)}..."
                    }))
                    
                    invoice_schema, raw_json, struct_time_ms, error = await json_structurer.structure_single_page(
                        extracted_text, page_number, allow_repair=True
                    )
                    
                    page_time_ms = extract_time_ms + struct_time_ms
                    page.page_time_ms = page_time_ms
                    
                    if invoice_schema is not None:
                        # Step 2c: Translate JSON to English if requested (AFTER structuring)
                        if document.translate_to_english:
                            await job_registry.emit_event(job_id, JobEvent("status", {
                                "status": "translating",
                                "message": f"Translating page {page_number} to English..."
                            }))
                            try:
                                import json
                                json_str = json.dumps(invoice_schema.model_dump(), ensure_ascii=False)
                                translated_json = await structuring_client.translate_json_to_english(json_str)
                                # Parse translated JSON back
                                translated_json = translated_json.strip()
                                # Extract JSON if wrapped in markdown
                                if '```' in translated_json:
                                    import re
                                    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', translated_json)
                                    if match:
                                        translated_json = match.group(1).strip()
                                # Find JSON object
                                start_idx = translated_json.find('{')
                                end_idx = translated_json.rfind('}')
                                if start_idx != -1 and end_idx != -1:
                                    translated_json = translated_json[start_idx:end_idx + 1]
                                
                                translated_data = json.loads(translated_json)
                                from app.schemas import DocumentSchema
                                invoice_schema = DocumentSchema(**translated_data)
                                invoice_schema.page_start = page_number
                                invoice_schema.page_end = page_number
                                logger.info(f"Successfully translated page {page_number} JSON to English")
                            except Exception as e:
                                logger.warning(f"Translation failed for page {page_number}, using original: {e}")
                        
                        # Save page JSON
                        page_json_path = json_structurer.save_page_json(invoice_schema, document_id, page_number)
                        
                        # Create Invoice record for this page
                        invoice_record = Invoice(
                            document_id=document_id,
                            invoice_index=idx,
                            start_page=page_number,
                            end_page=page_number,
                            json_path=str(page_json_path)
                        )
                        
                        # Extract identifiers
                        self._update_invoice_identifiers(invoice_record, invoice_schema)
                        self.db.add(invoice_record)
                        invoices_created += 1
                        
                        page.status = "done"
                        
                        # Emit json structured event with the JSON data
                        await job_registry.emit_event(job_id, JobEvent("json_structured", {
                            "page_index": idx,
                            "page_number": page_number,
                            "total_pages": len(image_paths),
                            "json_data": invoice_schema.model_dump(),
                            "struct_time_ms": struct_time_ms
                        }))
                    else:
                        # Save raw output for debugging and display
                        raw_json_path = json_structurer.save_raw_json(raw_json, document_id, f"_page_{page_number}_failed")
                        page.status = "failed"
                        page.raw_json_path = str(raw_json_path)
                        page.error_message = error or "Unknown structuring error"
                        logger.warning(f"Page {page_number} structuring failed: {error}")
                        
                        # Emit json_failed event with raw output
                        await job_registry.emit_event(job_id, JobEvent("json_failed", {
                            "page_index": idx,
                            "page_number": page_number,
                            "error": error or "Unknown structuring error",
                            "raw_output": raw_json or ""
                        }))
                    
                    self.db.commit()
                    pages_processed += 1
                    
                    # Emit page done event
                    await job_registry.emit_event(job_id, JobEvent("page_done", {
                        "page_index": idx,
                        "page_number": page_number,
                        "total_pages": len(image_paths),
                        "time_ms": page_time_ms,
                        "extract_time_ms": extract_time_ms,
                        "struct_time_ms": struct_time_ms,
                        "text_preview": extracted_text[:200] if extracted_text else "",
                        "text_length": len(extracted_text),
                        "structured": invoice_schema is not None
                    }))
                    
                except Exception as e:
                    logger.error(f"Error processing page {idx}: {e}")
                    page.status = "failed"
                    self.db.commit()
                    
                    await job_registry.emit_event(job_id, JobEvent("page_error", {
                        "page_index": idx,
                        "error": str(e)
                    }))
            
            # Update document with invoice count
            document.invoice_count = invoices_created
            
            # Set status based on results
            if invoices_created > 0:
                document.status = "done"
            elif pages_processed > 0:
                document.status = "failed"
                document.error_message = "No invoices could be structured from any page"
            else:
                document.status = "failed"
                document.error_message = "No pages were processed successfully"
            
            # Calculate total time
            total_time_ms = int((time.time() - start_time) * 1000)
            document.total_time_ms = total_time_ms
            job.finished_at = datetime.utcnow()
            self.db.commit()
            
            # Emit final event
            if document.status == "done":
                await job_registry.emit_event(job_id, JobEvent("done", {
                    "status": "done",
                    "document_id": document_id,
                    "total_time_ms": total_time_ms,
                    "invoice_count": document.invoice_count,
                    "message": f"Processing complete! Created {document.invoice_count} JSON file(s) - one per page."
                }))
            else:
                await job_registry.emit_event(job_id, JobEvent("error", {
                    "status": "failed",
                    "error": document.error_message,
                    "document_id": document_id
                }))
                
        except Exception as e:
            logger.exception(f"Job processing error: {e}")
            document.status = "failed"
            document.error_message = str(e)
            document.total_time_ms = int((time.time() - start_time) * 1000)
            job.finished_at = datetime.utcnow()
            self.db.commit()
            
            await job_registry.emit_event(job_id, JobEvent("error", {
                "status": "failed",
                "error": str(e),
                "document_id": document_id
            }))
        finally:
            job_registry.unregister_job(job_id)
    
    def _check_db_cancel(self, job_id: str) -> bool:
        """Check DB for cancel flag (in case of process restart)."""
        job = self.db.query(Job).filter(Job.id == job_id).first()
        return job.cancel_requested if job else False
    
    async def _handle_cancellation(
        self,
        document: Document,
        job: Job,
        job_id: str,
        pages_processed: int,
        start_time: float
    ):
        """Handle job cancellation."""
        logger.info(f"Job {job_id} canceled after {pages_processed} pages")
        
        document.status = "canceled"
        document.total_time_ms = int((time.time() - start_time) * 1000)
        job.finished_at = datetime.utcnow()
        self.db.commit()
        
        await job_registry.emit_event(job_id, JobEvent("canceled", {
            "status": "canceled",
            "document_id": document.id,
            "pages_processed": pages_processed,
            "message": "Processing canceled by user"
        }))
    
    def _update_document_identifiers(self, document: Document, model):
        """Extract and store key identifiers from structured JSON (legacy)."""
        try:
            identifiers = model.document.identifiers
            document.document_number = identifiers.document_number
            document.reference_numbers_json = json.dumps(identifiers.reference_numbers or [])
            
            dates = model.document.dates
            document.issue_date = dates.issue_date
            
            document.supplier_name = model.parties.supplier.name
            document.customer_name = model.parties.customer.name
        except Exception as e:
            logger.warning(f"Error extracting identifiers: {e}")
    
    def _update_invoice_identifiers(self, invoice: Invoice, model):
        """Extract and store key identifiers from an invoice schema."""
        try:
            identifiers = model.document.identifiers
            invoice.document_number = identifiers.document_number
            invoice.reference_numbers_json = json.dumps(identifiers.reference_numbers or [])
            
            dates = model.document.dates
            invoice.issue_date = dates.issue_date
            
            invoice.supplier_name = model.parties.supplier.name
            invoice.customer_name = model.parties.customer.name
            
            # Extract totals
            if model.totals.gross_amount is not None:
                invoice.gross_amount = model.totals.gross_amount
            
            if model.document.locale.currency:
                invoice.currency = model.document.locale.currency
                
        except Exception as e:
            logger.warning(f"Error extracting invoice identifiers: {e}")


async def run_job(document_id: str, job_id: str, db: Session):
    """Run a processing job (to be called as background task)."""
    processor = JobProcessor(db)
    await processor.process_document(document_id, job_id)
