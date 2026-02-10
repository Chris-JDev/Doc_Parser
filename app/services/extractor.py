"""Text extraction service using vision model."""
import logging
import time
from pathlib import Path
from app.config import VISION_MODEL, TEXT_DIR
from app.services.ollama_client import vision_client

logger = logging.getLogger(__name__)

# Prompt for text extraction
EXTRACTION_PROMPT = """Extract ALL text from this document image exactly as it appears."""
#Preserve:
#- Line breaks and text layout
#- All amounts, prices, and numbers
#- All dates in their original format
#- Invoice numbers, receipt numbers, reference numbers
#- Names and addresses
#- Any tables or itemized lists
#
#Output ONLY the extracted text, nothing else. Be thorough and accurate."""


class TextExtractor:
    """Extract text from images using vision model."""
    
    def __init__(self, model: str = VISION_MODEL, max_retries: int = 3, min_text_length: int = 10):
        """
        Initialize extractor.
        
        Args:
            model: Vision model name (default from config)
            max_retries: Maximum number of retries if no text is extracted
            min_text_length: Minimum text length to consider extraction successful
        """
        self.model = model
        self.max_retries = max_retries
        self.min_text_length = min_text_length
    
    async def extract_text(self, image_path: Path) -> tuple[str, int]:
        """
        Extract text from a single image. Retries if no text is extracted.
        
        Args:
            image_path: Path to the image file
        
        Returns:
            Tuple of (extracted_text, time_ms)
        """
        logger.info(f"Extracting text from image: {image_path}")
        
        start_time = time.time()
        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                text = await vision_client.extract_text_from_image(
                    image_path=image_path,
                    prompt=EXTRACTION_PROMPT
                )
                
                text = text.strip() if text else ""
                
                # Check if we got meaningful text
                if len(text) >= self.min_text_length:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    logger.info(f"Extracted {len(text)} chars in {elapsed_ms}ms (attempt {attempt})")
                    return text, elapsed_ms
                
                # Not enough text, retry
                logger.warning(f"Attempt {attempt}: Got only {len(text)} chars (min: {self.min_text_length}), retrying...")
                last_error = f"Insufficient text: {len(text)} chars"
                
            except Exception as e:
                logger.warning(f"Attempt {attempt} failed: {e}")
                last_error = str(e)
        
        # All retries exhausted
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        # If we got some text (even if below minimum), return it
        if text and len(text) > 0:
            logger.warning(f"Returning {len(text)} chars after {self.max_retries} attempts")
            return text, elapsed_ms
        
        # No text at all after all retries
        logger.error(f"Failed to extract text after {self.max_retries} attempts: {last_error}")
        raise RuntimeError(f"Text extraction failed after {self.max_retries} attempts: {last_error}")
    
    def save_extracted_text(
        self,
        text: str,
        document_id: str,
        page_index: int
    ) -> Path:
        """
        Save extracted text to file.
        
        Args:
            text: Extracted text content
            document_id: Document identifier
            page_index: 0-based page index
        
        Returns:
            Path to saved text file
        """
        # Create output directory for this document
        output_dir = TEXT_DIR / document_id
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save text file
        text_filename = f"page_{page_index + 1:04d}.txt"
        text_path = output_dir / text_filename
        
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(text)
        
        logger.debug(f"Saved extracted text to {text_path}")
        return text_path
    
    def combine_page_texts(
        self,
        document_id: str,
        page_count: int
    ) -> str:
        """
        Combine all page texts into a single string with page markers.
        
        Args:
            document_id: Document identifier
            page_count: Number of pages to combine
        
        Returns:
            Combined text with page separators
        """
        combined_parts = []
        text_dir = TEXT_DIR / document_id
        
        for page_idx in range(page_count):
            text_filename = f"page_{page_idx + 1:04d}.txt"
            text_path = text_dir / text_filename
            
            if text_path.exists():
                with open(text_path, "r", encoding="utf-8") as f:
                    page_text = f.read()
                combined_parts.append(f"--- PAGE {page_idx + 1} ---\n{page_text}")
            else:
                combined_parts.append(f"--- PAGE {page_idx + 1} ---\n[No text extracted]")
        
        return "\n\n".join(combined_parts)


# Global extractor instance
text_extractor = TextExtractor()
