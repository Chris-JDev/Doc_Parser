"""PDF to images conversion service using pdf2image."""
import logging
from pathlib import Path
from typing import List
from pdf2image import convert_from_path
from app.config import PAGES_DIR

logger = logging.getLogger(__name__)


class PDFToImagesConverter:
    """Convert PDF pages to images."""
    
    def __init__(self, dpi: int = 300, fmt: str = "JPEG"):
        """
        Initialize converter.
        
        Args:
            dpi: Resolution for rendered images (default: 300)
            fmt: Image format (default: JPEG)
        """
        self.dpi = dpi
        self.fmt = fmt
    
    def convert(self, pdf_path: Path, document_id: str) -> List[Path]:
        """
        Convert PDF to images, one per page.
        
        Args:
            pdf_path: Path to the PDF file
            document_id: Unique document identifier for organizing output
        
        Returns:
            List of paths to generated image files
        """
        # Create output directory for this document's pages
        output_dir = PAGES_DIR / document_id
        output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Converting PDF '{pdf_path}' to images in '{output_dir}'")
        
        try:
            # Convert PDF to images
            images = convert_from_path(
                pdf_path,
                dpi=self.dpi,
                fmt=self.fmt
            )
            
            image_paths = []
            for idx, image in enumerate(images):
                # Use 4-digit page numbering (page_0001.jpg, page_0002.jpg, ...)
                image_filename = f"page_{idx + 1:04d}.jpg"
                image_path = output_dir / image_filename
                
                image.save(str(image_path), self.fmt, quality=85)
                image_paths.append(image_path)
                logger.debug(f"Saved page {idx + 1} to {image_path}")
            
            logger.info(f"Successfully converted {len(image_paths)} pages")
            return image_paths
            
        except Exception as e:
            logger.error(f"Error converting PDF to images: {e}")
            raise RuntimeError(f"Failed to convert PDF: {e}")
    
    def get_page_count(self, pdf_path: Path) -> int:
        """
        Get the number of pages in a PDF without fully converting.
        
        Args:
            pdf_path: Path to the PDF file
        
        Returns:
            Number of pages
        """
        try:
            # Convert just to count pages (low res for speed)
            images = convert_from_path(pdf_path, dpi=50, first_page=1, last_page=1)
            # Use info to get total count
            from pdf2image.pdf2image import pdfinfo_from_path
            info = pdfinfo_from_path(pdf_path)
            return info.get("Pages", len(images))
        except Exception as e:
            logger.warning(f"Could not get page count: {e}")
            return 0


# Global converter instance
pdf_converter = PDFToImagesConverter()
