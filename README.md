# Document Parser Web Application

A complete web application for processing scanned PDF invoices and receipts using Ollama's local AI models. The app extracts text from image-only PDFs using a vision model and structures the data into a predefined JSON schema.

## Features

- **PDF Upload**: Upload scanned PDF invoices/receipts (up to 25MB by default)
- **Vision-Based Text Extraction**: Uses `qwen3-vl:235b-cloud` model to extract text from scanned document images
- **Structured JSON Output**: Uses `qwen3-vl:235b-cloud` model to convert extracted text into a strict JSON schema
- **Real-Time Progress**: Live updates via Server-Sent Events (SSE) showing page-by-page processing
- **Cancel Support**: Cancel processing mid-way and keep partial results
- **Dashboard**: View all processed documents with key identifiers
- **Detail View**: See page-by-page extracted text and final structured JSON
- **Download**: Download original PDFs and generated JSON files
- **Processing Statistics**: Track total and per-page processing times

## Prerequisites

### 1. Python 3.10+

Make sure you have Python 3.10 or later installed.

### 2. Ollama

Install and run Ollama locally:

```bash
# Install Ollama (see https://ollama.ai)
# On Windows: Download from https://ollama.ai/download

# Pull required models
ollama pull qwen3-vl:235b-cloud

# Verify Ollama is running
curl http://localhost:11434/api/tags
```

### 3. Poppler (for PDF to Image conversion)

#### Windows
1. Download Poppler for Windows from: https://github.com/osber/poppler/releases
2. Extract to a folder (e.g., `C:\Program Files\poppler`)
3. Add the `bin` folder to your PATH:
   - `C:\Program Files\poppler\Library\bin`
   - Or set environment variable: `set PATH=%PATH%;C:\Program Files\poppler\Library\bin`

Alternatively, using Chocolatey:
```powershell
choco install poppler
```

Or using Scoop:
```powershell
scoop install poppler
```

#### macOS
```bash
brew install poppler
```

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get install poppler-utils
```

#### Linux (Fedora)
```bash
sudo dnf install poppler-utils
```

## Installation

1. **Clone or navigate to the project directory**:
```bash
cd "c:\Users\chris\Desktop\doc parser ollama quewn vison\formator"
```

2. **Create a virtual environment** (recommended):
```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

## Configuration

Set environment variables (optional - defaults shown):

```bash
# Windows PowerShell
$env:OLLAMA_BASE_URL = "http://localhost:11434"
$env:VISION_MODEL = "qwen3-vl:235b-cloud"
$env:STRUCTURING_MODEL = "qwen3-vl:235b-cloud"
$env:MAX_UPLOAD_MB = "25"

# Windows CMD
set OLLAMA_BASE_URL=http://localhost:11434
set VISION_MODEL=qwen3-vl:235b-cloud
set STRUCTURING_MODEL=qwen3-vl:235b-cloud
set MAX_UPLOAD_MB=25

# macOS/Linux
export OLLAMA_BASE_URL=http://localhost:11434
export VISION_MODEL=qwen3-vl:235b-cloud
export STRUCTURING_MODEL=qwen3-vl:235b-cloud
export MAX_UPLOAD_MB=25
```

## Running the Application

1. **Make sure Ollama is running** with the required models pulled

2. **Start the application**:
```bash
# Using uvicorn directly (if in PATH)
uvicorn app.main:app --reload

# Or using Python module (recommended)
python -m uvicorn app.main:app --reload
```

3. **Open your browser** to: http://localhost:8000

## Usage

### Uploading a Document

1. Click "Upload" in the navigation bar
2. Drag and drop a PDF file or click to browse
3. Click "Upload & Process" to start processing
4. Watch real-time progress as each page is processed
5. View results when processing completes

### Dashboard

The dashboard shows all processed documents with:
- Filename
- Status (queued, processing, done, failed, canceled)
- Invoice/Receipt/Document/PO numbers
- Reference numbers
- Supplier name
- Issue date
- Processing time
- Quick action buttons (View, Download PDF, Download JSON)

### Document Detail View

Click on any document to see:
- Summary of extracted identifiers
- Processing statistics
- Page-by-page extracted text
- Complete structured JSON output

### Canceling Processing

During processing, click the "Cancel Processing" button to stop:
- Current page will complete
- No further pages will be processed
- No JSON structuring will occur
- Partial results are preserved

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Dashboard page |
| GET | `/upload` | Upload page |
| POST | `/upload` | Upload and process PDF |
| GET | `/jobs/{job_id}` | Job progress page |
| GET | `/api/jobs/{job_id}/events` | SSE endpoint for live updates |
| POST | `/api/jobs/{job_id}/cancel` | Cancel a running job |
| GET | `/api/jobs/{job_id}/status` | Get job status |
| GET | `/docs/{doc_id}` | Document detail page |
| GET | `/download/pdf/{doc_id}` | Download original PDF |
| GET | `/download/json/{doc_id}` | Download structured JSON |
| GET | `/view/json/{doc_id}` | View JSON as API response |
| GET | `/health` | Health check |

## JSON Output Schema

The structured output strictly follows this schema:

```json
{
  "document": {
    "type": null,
    "category": null,
    "subcategory": null,
    "locale": {
      "language": null,
      "currency": null,
      "country": null
    },
    "identifiers": {
      "document_number": null,
      "invoice_number": null,
      "po_number": null,
      "receipt_number": null,
      "reference_numbers": []
    },
    "dates": {
      "issue_date": null,
      "due_date": null,
      "payment_date": null,
      "time": null
    },
    "status": {
      "payment_status": null
    }
  },
  "parties": {
    "supplier": {
      "name": null,
      "address": null,
      "email": null,
      "phone": null,
      "website": null,
      "registrations": [],
      "payment_details": []
    },
    "customer": {
      "name": null,
      "customer_id": null,
      "address": null,
      "billing_address": null,
      "shipping_address": null,
      "company_registrations": []
    }
  },
  "line_items": [],
  "totals": {
    "net_amount": null,
    "tax_amount": null,
    "gross_amount": null,
    "tip_amount": null
  },
  "taxes": [],
  "extraction_metadata": {
    "fields": {}
  }
}
```

## Data Storage

The application stores data in the `data/` directory:

```
data/
├── app.db          # SQLite database
├── uploads/        # Original PDF files
├── pages/          # Converted page images (PNG)
│   └── {doc_id}/   # Per-document folder
├── text/           # Extracted text files
│   └── {doc_id}/   # Per-document folder
└── json/           # Structured JSON output
```

## Troubleshooting

### "Failed to convert PDF" error
- Ensure Poppler is installed and in your PATH
- On Windows, verify `pdftoppm.exe` is accessible

### "Failed to connect to Ollama" error
- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Check the `OLLAMA_BASE_URL` environment variable

### Models not found
- Pull the required models:
  ```bash
  ollama pull qwen3-vl:235b-cloud
  ```

### JSON validation failures
- The app will attempt one repair pass
- Check `data/json/{doc_id}_failed.json` for raw model output
- Ensure the document contains readable text

### Processing is slow
- Vision model processing depends on your hardware
- Consider using a GPU-enabled Ollama setup
- Processing time scales with number of pages

## Development

### Project Structure

```
formator/
├── app/
│   ├── __init__.py
│   ├── config.py           # Configuration settings
│   ├── db.py               # Database setup
│   ├── main.py             # FastAPI application
│   ├── models.py           # SQLAlchemy models
│   ├── schemas.py          # Pydantic JSON schema
│   ├── services/
│   │   ├── __init__.py
│   │   ├── extractor.py    # Vision model text extraction
│   │   ├── jobs.py         # Job processing & SSE
│   │   ├── ollama_client.py# Ollama API client
│   │   ├── pdf_to_images.py# PDF conversion
│   │   └── structurer.py   # JSON structuring
│   ├── static/
│   │   └── app.css         # Stylesheet
│   └── templates/
│       ├── base.html       # Base template
│       ├── dashboard.html  # Dashboard page
│       ├── detail.html     # Document detail page
│       ├── job.html        # Job progress page
│       └── upload.html     # Upload page
├── data/                   # Generated data directory
├── requirements.txt
└── README.md
```

### Adding New Features

1. Models are defined in `app/models.py`
2. Routes are in `app/main.py`
3. Business logic is in `app/services/`
4. Templates use Jinja2 in `app/templates/`

## License

MIT License
