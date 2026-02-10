"""Application configuration."""
import os
from pathlib import Path

# Base directory (repo root /formator)
BASE_DIR = Path(__file__).resolve().parent.parent

# Data directory (override for Render persistent disk)
# Example: DATA_DIR=/var/data
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))

# Data subdirectories
UPLOADS_DIR = DATA_DIR / "uploads"
PAGES_DIR = DATA_DIR / "pages"
JSON_DIR = DATA_DIR / "json"
TEXT_DIR = DATA_DIR / "text"

# Create directories if they don't exist
for dir_path in [DATA_DIR, UPLOADS_DIR, PAGES_DIR, JSON_DIR, TEXT_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Ollama configuration
# Local dev: http://localhost:11434
# Ollama Cloud: https://ollama.com/api
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "").strip()

# Vision model for text extraction from images
# Examples:
# - qwen3-vl:4b (local)
# - qwen3-vl:235b-cloud (Ollama Cloud)
VISION_MODEL = os.getenv("VISION_MODEL", "qwen3-vl:235b-cloud")

# Structuring model for JSON generation (can also be a *-cloud tag)
STRUCTURING_MODEL = os.getenv("STRUCTURING_MODEL", "phi4-json")

# Upload configuration
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/app.db")

# CORS (for GitHub Pages / other frontends)
# Comma-separated list of origins. Example:
# FRONTEND_ORIGINS=https://<user>.github.io,https://<user>.github.io/<repo>
FRONTEND_ORIGINS = [o.strip() for o in os.getenv("FRONTEND_ORIGINS", "").split(",") if o.strip()]
