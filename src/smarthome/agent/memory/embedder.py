"""OllamaEmbedder: async HTTP client for local embeddings via ollama."""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"
EMBEDDING_MODEL = "embeddinggemma:300m"
EMBEDDING_DIMS = 384


class OllamaEmbedder:
    """Async embedder using ollama's local embedding API.

    Requires: `ollama serve` running + `ollama pull embeddinggemma` done once.
    Falls back gracefully to None if ollama is unavailable.
    """

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = EMBEDDING_MODEL,
        timeout: float = 30.0,
    ):
        self._base_url = base_url
        self._model = model
        self._timeout = timeout
        self._available: Optional[bool] = None  # None = not yet checked

    async def _check_availability(self) -> bool:
        """Ping ollama once to set availability flag."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self._base_url}/api/tags")
                self._available = r.status_code == 200
        except Exception:
            self._available = False
        if not self._available:
            logger.warning(
                "ollama not reachable at %s — vector search disabled (BM25 only)",
                self._base_url,
            )
        return self._available

    async def embed(self, text: str) -> Optional[list[float]]:
        """Embed text. Returns list[float] of length 384, or None on failure."""
        if self._available is False:
            return None
        if self._available is None:
            if not await self._check_availability():
                return None

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": text},
                )
                r.raise_for_status()
                data = r.json()
                # ollama /api/embed returns {"embeddings": [[...]], ...}
                embeddings = data.get("embeddings") or data.get("embedding")
                if embeddings is None:
                    logger.error("Unexpected ollama response: %s", data)
                    return None
                if isinstance(embeddings[0], list):
                    return embeddings[0]
                return embeddings
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.error(
                    "Model '%s' not found in ollama. Run: ollama pull embeddinggemma",
                    self._model,
                )
                self._available = False
            else:
                logger.error("ollama HTTP error: %s", e)
            return None
        except Exception as e:
            logger.warning("Embedding failed: %s", e)
            return None
