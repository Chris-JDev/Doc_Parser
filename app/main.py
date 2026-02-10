"""FastAPI main application with all routes."""
import asyncio
import json
import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List

from app.config import UPLOADS_DIR, JSON_DIR, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, FRONTEND_ORIGINS
from app.db import get_db, init_db
from app.models import Document, Page, Job, Invoice
from app.services.jobs import job_registry, run_job

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Document Parser",
    description="Parse scanned PDF invoices/receipts using Ollama vision models",
    version="1.0.0"
)


# CORS for GitHub Pages / other frontends
if FRONTEND_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Get base directory
BASE_DIR = Path(__file__).resolve().parent

# Mount static files
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Setup templates
templates_dir = BASE_DIR / "templates"
templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(templates_dir))


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized")


# =============================================================================
# PAGE ROUTES (HTML)
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Dashboard page showing list of processed documents and invoices."""
    documents = db.query(Document).order_by(Document.created_at.desc()).all()
    invoices = db.query(Invoice).order_by(Invoice.id.desc()).all()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "documents": documents,
        "invoices": invoices,
        "title": "Document Dashboard"
    })


@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    """Upload page for new documents."""
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "title": "Upload Documents",
        "max_upload_mb": MAX_UPLOAD_MB
    })


@app.get("/batch", response_class=HTMLResponse)
async def batch_progress_page(request: Request, jobs: str, db: Session = Depends(get_db)):
    """Batch progress page for multiple uploads."""
    job_ids = [j.strip() for j in jobs.split(",") if j.strip()]
    
    jobs_data = []
    for job_id in job_ids:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            jobs_data.append({
                "id": job.id,
                "document_id": job.document_id,
                "filename": job.document.original_filename,
                "status": job.document.status
            })
    
    return templates.TemplateResponse("batch.html", {
        "request": request,
        "jobs": jobs_data,
        "job_ids": job_ids,
        "title": f"Processing {len(jobs_data)} Documents"
    })


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_progress_page(request: Request, job_id: str, db: Session = Depends(get_db)):
    """Job progress page with live updates."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    document = job.document
    
    return templates.TemplateResponse("job.html", {
        "request": request,
        "job": job,
        "document": document,
        "title": f"Processing: {document.original_filename}"
    })


@app.get("/docs/{doc_id}", response_class=HTMLResponse)
async def document_detail_page(request: Request, doc_id: str, db: Session = Depends(get_db)):
    """Document detail page showing all extracted data and invoices."""
    document = db.query(Document).filter(Document.id == doc_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    pages = db.query(Page).filter(Page.document_id == doc_id).order_by(Page.page_index).all()
    invoices = db.query(Invoice).filter(Invoice.document_id == doc_id).order_by(Invoice.invoice_index).all()
    
    # Load full page texts
    for page in pages:
        if page.extracted_text_path and Path(page.extracted_text_path).exists():
            with open(page.extracted_text_path, "r", encoding="utf-8") as f:
                page.full_text = f.read()
        else:
            page.full_text = page.extracted_text_preview or "[No text extracted]"
        
        # Load raw JSON for failed pages
        if page.status == "failed" and page.raw_json_path and Path(page.raw_json_path).exists():
            with open(page.raw_json_path, "r", encoding="utf-8") as f:
                page.raw_json = f.read()
        else:
            page.raw_json = None
    
    # Load invoice JSONs
    for inv in invoices:
        if inv.json_path and Path(inv.json_path).exists():
            with open(inv.json_path, "r", encoding="utf-8") as f:
                inv.json_data = json.load(f)
        else:
            inv.json_data = None
    
    # Load combined JSON if available
    structured_json = None
    if document.json_path and Path(document.json_path).exists():
        with open(document.json_path, "r", encoding="utf-8") as f:
            structured_json = json.load(f)
    
    return templates.TemplateResponse("detail.html", {
        "request": request,
        "document": document,
        "pages": pages,
        "invoices": invoices,
        "structured_json": structured_json,
        "structured_json_str": json.dumps(structured_json, indent=2) if structured_json else None,
        "title": f"Document: {document.original_filename}"
    })


@app.get("/invoices/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail_page(request: Request, invoice_id: str, db: Session = Depends(get_db)):
    """Individual invoice detail page."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    document = invoice.document
    
    # Load invoice JSON
    invoice_json = None
    if invoice.json_path and Path(invoice.json_path).exists():
        with open(invoice.json_path, "r", encoding="utf-8") as f:
            invoice_json = json.load(f)
    
    return templates.TemplateResponse("invoice_detail.html", {
        "request": request,
        "invoice": invoice,
        "document": document,
        "invoice_json": invoice_json,
        "invoice_json_str": json.dumps(invoice_json, indent=2) if invoice_json else None,
        "title": f"Invoice: {invoice.document_number or f'#{invoice.invoice_index + 1}'}"
    })


@app.get("/download/invoice/{invoice_id}")
async def download_invoice_json(invoice_id: str, db: Session = Depends(get_db)):
    """Download individual invoice JSON."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice or not invoice.json_path:
        raise HTTPException(status_code=404, detail="Invoice JSON not found")
    
    json_path = Path(invoice.json_path)
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="Invoice JSON file not found")
    
    filename = f"invoice_{invoice.document_number or invoice.id}.json"
    return FileResponse(json_path, filename=filename, media_type="application/json")


# =============================================================================
# API ROUTES
# =============================================================================

@app.post("/upload")
async def upload_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    translate_to_english: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Upload one or more PDF documents for processing.
    Creates document and job records for each file, then starts background processing.
    """
    # Parse translate option (checkbox sends "true" when checked)
    do_translate = translate_to_english == "true"
    
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="No files uploaded")
    
    job_ids = []
    
    for file in files:
        # Validate file type
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"Only PDF files are allowed: {file.filename}")
        
        # Check file size
        contents = await file.read()
        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File too large ({file.filename}). Maximum size is {MAX_UPLOAD_MB}MB"
            )
        
        # Generate IDs
        document_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        
        # Create safe filename
        safe_filename = f"{document_id}.pdf"
        stored_path = UPLOADS_DIR / safe_filename
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Save file
        with open(stored_path, "wb") as f:
            f.write(contents)
        
        logger.info(f"Saved uploaded file to {stored_path}")
        
        # Create document record
        document = Document(
            id=document_id,
            original_filename=file.filename,
            stored_pdf_path=str(stored_path),
            status="queued",
            translate_to_english=do_translate
        )
        db.add(document)
        
        # Create job record
        job = Job(
            id=job_id,
            document_id=document_id
        )
        db.add(job)
        job_ids.append(job_id)
    
    db.commit()
    logger.info(f"Created {len(job_ids)} documents and jobs")
    
    # Start background processing for each document
    from app.db import SessionLocal
    
    for i, job_id in enumerate(job_ids):
        doc_id = db.query(Job).filter(Job.id == job_id).first().document_id
        
        async def process_job(document_id=doc_id, job_id=job_id):
            db_session = SessionLocal()
            try:
                await run_job(document_id, job_id, db_session)
            finally:
                db_session.close()
        
        background_tasks.add_task(process_job)
    
    # If single file, redirect to job progress page
    # If multiple files, redirect to dashboard with processing indicator
    if len(job_ids) == 1:
        return RedirectResponse(url=f"/jobs/{job_ids[0]}", status_code=303)
    else:
        # Redirect to a batch progress page or dashboard
        return RedirectResponse(url=f"/batch?jobs={','.join(job_ids)}", status_code=303)


@app.post("/api/upload")
async def api_upload_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    translate_to_english: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """JSON API: upload PDFs and start processing. Returns job ids and URLs."""
    do_translate = translate_to_english == "true"

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    job_ids = []

    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"Only PDF files are allowed: {file.filename}")

        contents = await file.read()
        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File too large ({file.filename}). Maximum size is {MAX_UPLOAD_MB}MB"
            )

        document_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())

        safe_filename = f"{document_id}.pdf"
        stored_path = UPLOADS_DIR / safe_filename
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

        with open(stored_path, "wb") as f:
            f.write(contents)

        document = Document(
            id=document_id,
            original_filename=file.filename,
            stored_pdf_path=str(stored_path),
            status="queued",
            translate_to_english=do_translate
        )
        db.add(document)

        job = Job(id=job_id, document_id=document_id)
        db.add(job)
        job_ids.append(job_id)

    db.commit()

    from app.db import SessionLocal

    for job_id in job_ids:
        doc_id = db.query(Job).filter(Job.id == job_id).first().document_id

        async def process_job(document_id=doc_id, job_id=job_id):
            db_session = SessionLocal()
            try:
                await run_job(document_id, job_id, db_session)
            finally:
                db_session.close()

        background_tasks.add_task(process_job)

    job_urls = [f"/jobs/{jid}" for jid in job_ids]
    batch_url = f"/batch?jobs={','.join(job_ids)}" if len(job_ids) > 1 else None

    return JSONResponse({
        "job_ids": job_ids,
        "job_urls": job_urls,
        "batch_url": batch_url
    })


@app.get("/api/jobs/{job_id}/events")
async def job_events_sse(job_id: str, db: Session = Depends(get_db)):
    """SSE endpoint for job progress events."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    document = job.document
    
    async def event_generator():
        # Send initial state
        initial_data = {
            "status": document.status,
            "page_count": document.page_count,
            "current_page": job.current_page,
            "document_id": document.id
        }
        yield f"event: initial\ndata: {json.dumps(initial_data)}\n\n"
        
        # If job is already complete, send final event immediately
        if document.status in ("done", "failed", "canceled"):
            if document.status == "done":
                yield f"event: done\ndata: {json.dumps({'document_id': document.id, 'status': 'done'})}\n\n"
            elif document.status == "canceled":
                yield f"event: canceled\ndata: {json.dumps({'document_id': document.id, 'status': 'canceled'})}\n\n"
            else:
                yield f"event: error\ndata: {json.dumps({'document_id': document.id, 'error': document.error_message or 'Unknown error'})}\n\n"
            return
        
        # Stream events from job registry
        async for event in job_registry.get_events(job_id):
            yield event.to_sse()
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, db: Session = Depends(get_db)):
    """Cancel a running job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Set cancel flag in DB
    job.cancel_requested = True
    db.commit()
    
    # Set cancel flag in memory
    job_registry.request_cancel(job_id)
    
    logger.info(f"Cancel requested for job {job_id}")
    
    return JSONResponse({"status": "cancel_requested", "job_id": job_id})


@app.get("/api/jobs/{job_id}/status")
async def job_status(job_id: str, db: Session = Depends(get_db)):
    """Get current job status."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    document = job.document
    pages_done = db.query(Page).filter(
        Page.document_id == document.id,
        Page.status == "done"
    ).count()
    
    return JSONResponse({
        "job_id": job_id,
        "document_id": document.id,
        "status": document.status,
        "page_count": document.page_count,
        "pages_done": pages_done,
        "current_page": job.current_page,
        "cancel_requested": job.cancel_requested,
        "error_message": document.error_message
    })


# =============================================================================
# DOWNLOAD ROUTES
# =============================================================================

@app.get("/pages/{doc_id}/{page_index}")
async def get_page_image(doc_id: str, page_index: int, db: Session = Depends(get_db)):
    """Serve a page image for display in the web app."""
    from app.config import PAGES_DIR
    
    page = db.query(Page).filter(
        Page.document_id == doc_id,
        Page.page_index == page_index
    ).first()
    
    if not page or not page.image_path:
        raise HTTPException(status_code=404, detail="Page image not found")
    
    image_path = Path(page.image_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Page image file not found")
    
    return FileResponse(
        path=image_path,
        media_type="image/png"
    )


@app.get("/api/pages/{doc_id}/{page_index}/text")
async def get_page_text(doc_id: str, page_index: int, db: Session = Depends(get_db)):
    """Get extracted text for a page."""
    page = db.query(Page).filter(
        Page.document_id == doc_id,
        Page.page_index == page_index
    ).first()
    
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    full_text = ""
    if page.extracted_text_path and Path(page.extracted_text_path).exists():
        with open(page.extracted_text_path, "r", encoding="utf-8") as f:
            full_text = f.read()
    else:
        full_text = page.extracted_text_preview or ""
    
    return JSONResponse({
        "page_index": page_index,
        "text": full_text,
        "text_length": len(full_text)
    })


@app.get("/api/pages/{doc_id}/{page_index}/json")
async def get_page_json(doc_id: str, page_index: int, db: Session = Depends(get_db)):
    """Get structured JSON for a page."""
    invoice = db.query(Invoice).filter(
        Invoice.document_id == doc_id,
        Invoice.invoice_index == page_index
    ).first()
    
    if not invoice or not invoice.json_path:
        raise HTTPException(status_code=404, detail="Page JSON not found")
    
    json_path = Path(invoice.json_path)
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="Page JSON file not found")
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    return JSONResponse(data)


@app.get("/download/pdf/{doc_id}")
async def download_pdf(doc_id: str, db: Session = Depends(get_db)):
    """Download the original PDF file."""
    document = db.query(Document).filter(Document.id == doc_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    pdf_path = Path(document.stored_pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")
    
    return FileResponse(
        path=pdf_path,
        filename=document.original_filename,
        media_type="application/pdf"
    )


@app.get("/download/json/{doc_id}")
async def download_json(doc_id: str, db: Session = Depends(get_db)):
    """Download the structured JSON file."""
    document = db.query(Document).filter(Document.id == doc_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if not document.json_path:
        raise HTTPException(status_code=404, detail="JSON not yet generated")
    
    json_path = Path(document.json_path)
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="JSON file not found")
    
    # Use original filename but with .json extension
    json_filename = Path(document.original_filename).stem + ".json"
    
    return FileResponse(
        path=json_path,
        filename=json_filename,
        media_type="application/json"
    )


@app.get("/view/json/{doc_id}")
async def view_json(doc_id: str, db: Session = Depends(get_db)):
    """View the structured JSON."""
    document = db.query(Document).filter(Document.id == doc_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if not document.json_path:
        raise HTTPException(status_code=404, detail="JSON not yet generated")
    
    json_path = Path(document.json_path)
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="JSON file not found")
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    return JSONResponse(data)


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    from app.services.ollama_client import ollama_client
    
    ollama_healthy = await ollama_client.health_check()
    
    return JSONResponse({
        "status": "healthy",
        "ollama": "connected" if ollama_healthy else "disconnected"
    })
