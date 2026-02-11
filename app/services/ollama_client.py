"""Ollama API clients for vision and text generation."""
import base64
import httpx
import logging
from pathlib import Path
from typing import Optional
from app.config import OLLAMA_BASE_URL, VISION_MODEL, STRUCTURING_MODEL

logger = logging.getLogger(__name__)


class OllamaClient:
    """HTTP client for Ollama API."""
    
    def __init__(self, base_url: str = OLLAMA_BASE_URL, timeout: float = 600.0):
        """
        Initialize Ollama client.
        
        Args:
            base_url: Base URL for Ollama API (default: http://localhost:11434)
            timeout: Request timeout in seconds (default: 300s for large models)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
    
    def _encode_image_base64(self, image_path: Path) -> str:
        """Encode an image file to base64 string."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    async def generate(
        self,
        model: str,
        prompt: str,
        images: Optional[list[str]] = None,
        stream: bool = False
    ) -> str:
        """
        Call Ollama generate API.
        
        Args:
            model: Model name (e.g., 'qwen-vl-4b', 'phi-4')
            prompt: Text prompt
            images: List of base64-encoded images (for vision models)
            stream: Whether to stream response (default False)
        
        Returns:
            Generated text response
        """
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream
        }
        
        if images:
            payload["images"] = images
        
        logger.info(f"Calling Ollama model '{model}' with prompt length {len(prompt)}")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data.get("response", "")
            except httpx.HTTPStatusError as e:
                logger.error(f"Ollama HTTP error: {e.response.status_code} - {e.response.text}")
                raise RuntimeError(f"Ollama API error: {e.response.status_code}")
            except httpx.RequestError as e:
                logger.error(f"Ollama request error: {e}")
                raise RuntimeError(f"Failed to connect to Ollama: {e}")
    
    async def generate_with_image(
        self,
        model: str,
        prompt: str,
        image_path: Path
    ) -> str:
        """
        Generate text from an image using a vision model.
        
        Args:
            model: Vision model name (e.g., 'qwen-vl-4b')
            prompt: Text prompt describing what to extract
            image_path: Path to the image file
        
        Returns:
            Generated text response
        """
        image_b64 = self._encode_image_base64(image_path)
        return await self.generate(
            model=model,
            prompt=prompt,
            images=[image_b64],
            stream=False
        )
    
    async def check_model_available(self, model: str) -> bool:
        """Check if a model is available in Ollama."""
        url = f"{self.base_url}/api/tags"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                # Check if model name matches (with or without tag)
                return any(model in m or m.startswith(f"{model}:") for m in models)
            except Exception as e:
                logger.warning(f"Could not check model availability: {e}")
                return False
    
    async def health_check(self) -> bool:
        """Check if Ollama is running and accessible."""
        url = f"{self.base_url}/api/tags"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(url)
                return response.status_code == 200
            except Exception:
                return False


# Global client instances - separate for vision and structuring
class VisionClient(OllamaClient):
    """Client specifically for vision model (qwen3-vl)."""
    
    def __init__(self):
        super().__init__(timeout=600.0)  # Longer timeout for vision
        self.default_model = VISION_MODEL
        logger.info(f"VisionClient initialized with model: {self.default_model}")
    
    async def extract_text_from_image(self, image_path: Path, prompt: str) -> str:
        """Extract text from image using vision model."""
        return await self.generate_with_image(
            model=self.default_model,
            prompt=prompt,
            image_path=image_path
        )


class StructuringClient(OllamaClient):
    """Client specifically for text structuring model (phi4, llama, etc.)."""
    
    def __init__(self):
        super().__init__(timeout=600.0)  # Longer timeout for complex prompts
        self.default_model = STRUCTURING_MODEL
        logger.info(f"StructuringClient initialized with model: {self.default_model}")
    
    async def structure_text(self, prompt: str) -> str:
        """Generate structured output from text prompt."""
        return await self.generate(
            model=self.default_model,
            prompt=prompt,
            stream=False
        )
    
    async def translate_to_english(self, text: str) -> str:
        """
        Translate text to English.
        
        Args:
            text: Text in any language to translate
            
        Returns:
            English translation of the text
        """
        prompt = f"""Translate the following text to English. 
If the text is already in English, return it unchanged.
Output ONLY the translation, nothing else - no explanations, no notes.

TEXT TO TRANSLATE:
{text}

ENGLISH TRANSLATION:"""
        
        return await self.generate(
            model=self.default_model,
            prompt=prompt,
            stream=False
        )
    
    async def translate_json_to_english(self, json_str: str) -> str:
        """
        Translate JSON content values to English while preserving structure.
        
        Args:
            json_str: JSON string with values in any language
            
        Returns:
            JSON string with values translated to English
        """
        prompt = f"""Translate ALL text values in this JSON to English.
Keep the JSON structure and keys EXACTLY the same.
Only translate the string VALUES to English.
If a value is already in English, keep it unchanged.
Keep numbers, null values, and arrays/objects structure intact.
Output ONLY the translated JSON, nothing else - no explanations, no markdown.

JSON TO TRANSLATE:
{json_str}

TRANSLATED JSON:"""
        
        return await self.generate(
            model=self.default_model,
            prompt=prompt,
            stream=False
        )


# Global client instances
vision_client = VisionClient()
structuring_client = StructuringClient()

# Legacy compatibility
ollama_client = OllamaClient()
