"""
OLLAMA INTEGRATION EXAMPLES
============================
This file shows exactly how to push images and prompts to Ollama.

Two main use cases:
1. Vision (Image + Prompt) -> Text extraction from images
2. Text (Prompt only) -> Text generation/structuring
"""
import base64
import httpx
from pathlib import Path


# =============================================================================
# CONFIGURATION
# =============================================================================

OLLAMA_BASE_URL = "http://localhost:11434"  # Default Ollama URL
VISION_MODEL = "qwen3-vl:235b-cloud"               # Vision model for images
TEXT_MODEL = "llama3.2:3b"                   # Text-only model


# =============================================================================
# 1. BASIC: Send prompt to Ollama (text only)
# =============================================================================

async def send_prompt_to_ollama(prompt: str, model: str = TEXT_MODEL) -> str:
    """
    Send a text prompt to Ollama and get the response.
    
    Args:
        prompt: Your text prompt
        model: Ollama model name (e.g., "llama3.2:3b", "phi4", "qwen3:4b")
    
    Returns:
        Generated text response from Ollama
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"
    
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False  # Set True if you want streaming responses
    }
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "")


# Example usage:
# result = await send_prompt_to_ollama("What is 2 + 2?", model="llama3.2:3b")
# print(result)


# =============================================================================
# 2. VISION: Send image + prompt to Ollama
# =============================================================================

def encode_image_to_base64(image_path: Path) -> str:
    """Convert an image file to base64 string (required by Ollama API)."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def send_image_to_ollama(
    image_path: Path, 
    prompt: str, 
    model: str = VISION_MODEL
) -> str:
    """
    Send an image with a prompt to Ollama vision model.
    
    Args:
        image_path: Path to the image file (PNG, JPG, etc.)
        prompt: Text prompt describing what you want from the image
        model: Vision-capable model (e.g., "qwen3-vl:235b-cloud", "llava:7b")
    
    Returns:
        Generated text response from Ollama
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"
    
    # Encode image to base64
    image_base64 = encode_image_to_base64(image_path)
    
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_base64],  # List of base64 encoded images
        "stream": False
    }
    
    async with httpx.AsyncClient(timeout=600.0) as client:  # Longer timeout for vision
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "")


# Example usage:
# result = await send_image_to_ollama(
#     image_path=Path("page_1.png"),
#     prompt="Extract all text from this document image",
#     model="qwen3-vl:235b-cloud"
# )
# print(result)


# =============================================================================
# 3. VISION: Send multiple images + prompt
# =============================================================================

async def send_multiple_images_to_ollama(
    image_paths: list[Path],
    prompt: str,
    model: str = VISION_MODEL
) -> str:
    """
    Send multiple images with a prompt to Ollama.
    
    Args:
        image_paths: List of image file paths
        prompt: Text prompt
        model: Vision-capable model
    
    Returns:
        Generated text response
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"
    
    # Encode all images to base64
    images_base64 = [encode_image_to_base64(p) for p in image_paths]
    
    payload = {
        "model": model,
        "prompt": prompt,
        "images": images_base64,  # Multiple images
        "stream": False
    }
    
    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "")


# =============================================================================
# 4. STREAMING: Get response as it generates
# =============================================================================

async def send_prompt_streaming(prompt: str, model: str = TEXT_MODEL):
    """
    Send prompt and yield response chunks as they arrive.
    
    Yields:
        Response text chunks as they're generated
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"
    
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True  # Enable streaming
    }
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            async for line in response.aiter_lines():
                if line:
                    import json
                    data = json.loads(line)
                    chunk = data.get("response", "")
                    if chunk:
                        yield chunk
                    if data.get("done", False):
                        break


# Example usage:
# async for chunk in send_prompt_streaming("Tell me a story"):
#     print(chunk, end="", flush=True)


# =============================================================================
# 5. CHAT API (alternative to generate)
# =============================================================================

async def chat_with_ollama(
    messages: list[dict],
    model: str = TEXT_MODEL,
    images: list[str] = None
) -> str:
    """
    Use Ollama's chat API (better for conversations).
    
    Args:
        messages: List of {"role": "user/assistant", "content": "..."}
        model: Model name
        images: Optional list of base64 images (for vision models)
    
    Returns:
        Assistant's response
    """
    url = f"{OLLAMA_BASE_URL}/api/chat"
    
    # Add images to the last user message if provided
    if images and messages:
        messages[-1]["images"] = images
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "")


# Example usage:
# result = await chat_with_ollama([
#     {"role": "user", "content": "What is Python?"},
# ])


# =============================================================================
# 6. UTILITY: Check if Ollama is running / check available models
# =============================================================================

async def check_ollama_health() -> bool:
    """Check if Ollama is running and accessible."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            return response.status_code == 200
    except:
        return False


async def list_available_models() -> list[str]:
    """Get list of models available in Ollama."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
        response.raise_for_status()
        data = response.json()
        return [m.get("name", "") for m in data.get("models", [])]


# =============================================================================
# QUICK REFERENCE - Common Vision Models:
# =============================================================================
#
# qwen3-vl:235b-cloud     - Good balance of speed/quality for document OCR
# llava:7b        - Fast, general purpose vision
# llava:13b       - Better quality, slower
# bakllava        - Good for detailed analysis
# moondream       - Very lightweight vision model
#
# =============================================================================
# QUICK REFERENCE - Common Text Models:
# =============================================================================
#
# llama3.2:3b     - Fast, good for simple tasks
# llama3.2:8b     - Better quality
# phi4            - Excellent reasoning
# qwen3:4b        - Good for structured output
# mistral         - Fast and capable
#
