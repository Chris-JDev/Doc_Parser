"""Application configuration."""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Data directories
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
PAGES_DIR = DATA_DIR / "pages"
JSON_DIR = DATA_DIR / "json"
TEXT_DIR = DATA_DIR / "text"

# Create directories if they don't exist
for dir_path in [DATA_DIR, UPLOADS_DIR, PAGES_DIR, JSON_DIR, TEXT_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Ollama configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Vision model for text extraction from images
# Default: qwen3-vl:235b-cloud (multimodal vision-language model)
VISION_MODEL = os.getenv("VISION_MODEL", "qwen3-vl:235b-cloud")

# Structuring model for JSON generation
# Default: phi4-json (custom Modelfile with strict JSON system prompt)
STRUCTURING_MODEL = os.getenv("STRUCTURING_MODEL", "qwen3-vl:235b-cloud")

# Upload configuration
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/app.db")
