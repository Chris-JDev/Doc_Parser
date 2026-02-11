# Document Parser 
qwen3-vl:235b-cloud

## Prerequisites
Python 

### 2. Ollama
 
```bash
# Install Ollama (see https://ollama.ai)
# On Windows: Download from https://ollama.ai/download

# Pull required models
ollama pull qwen3-vl:235b-cloud

# Verify Ollama is running
curl http://localhost:11434/api/tags
```

### 3. Poppler (for PDF to Image conversion)

1.Poppler for Windows- https://github.com/osber/poppler/releases

2. Extract to a folder (e.g., `C:\Program Files\poppler`)

3. Add the `bin` folder to your PATH:
   - `C:\Program Files\poppler\Library\bin`
   - Or set environment variable: `set PATH=%PATH%;C:\Program Files\poppler\Library\bin`

## Installation

 **Create a virtual environment** (recommended):
```bash
python -m venv venv

.\venv\Scripts\activate

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

```

## Running the Application

1. **Make sure Ollama is running** with the required models pulled

2. **Start the application**:
```bash
python -m uvicorn app.main:app --reload
```

3. **Open your browser** to: http://localhost:8000


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

