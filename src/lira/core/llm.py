"""Ollama LLM provider for L.I.R.A. agent."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OllamaProvider:
    """LLM provider using Ollama API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "gemma4:31b",
        temperature: float = 0.7,
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def acomplete(self, prompt: str, **kwargs: Any) -> str:
        """Generate async completion.

        Args:
            prompt: The prompt to send
            **kwargs: Additional parameters (temperature, etc.)

        Returns:
            Generated text response
        """
        client = await self._get_client()

        payload = {
            "model": self.model,
            "prompt": prompt,
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", self.temperature),
            },
        }

        try:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip()

        except httpx.HTTPError as e:
            logger.error("Ollama request failed: %s", e)
            raise RuntimeError(f"Ollama API error: {e}") from e

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Generate sync completion.

        Args:
            prompt: The prompt to send
            **kwargs: Additional parameters

        Returns:
            Generated text response
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self.acomplete(prompt, **kwargs))

        return loop.run_until_complete(self.acomplete(prompt, **kwargs))

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def list_models(self) -> list[str]:
        """List available models.

        Returns:
            List of model names
        """
        client = await self._get_client()

        try:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except httpx.HTTPError as e:
            logger.error("Failed to list models: %s", e)
            return []

    async def health_check(self) -> bool:
        """Check if Ollama is available.

        Returns:
            True if Ollama is healthy
        """
        try:
            client = await self._get_client()
            response = await client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception:
            return False


_default_provider: OllamaProvider | None = None


def get_ollama_provider(
    base_url: str = "http://localhost:11434",
    model: str = "gemma4:31b",
) -> OllamaProvider:
    """Get or create the default Ollama provider.

    Args:
        base_url: Ollama server URL
        model: Model name to use

    Returns:
        OllamaProvider instance
    """
    global _default_provider

    if _default_provider is None:
        _default_provider = OllamaProvider(base_url=base_url, model=model)

    return _default_provider
