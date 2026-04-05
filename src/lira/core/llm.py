"""Ollama LLM provider for L.I.R.A. agent."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    async def acomplete(self, prompt: str, **kwargs: Any) -> str: ...

    def astream_complete(
        self, prompt: str, **kwargs: Any
    ) -> AsyncIterator[str]: ...

    def complete(self, prompt: str, **kwargs: Any) -> str: ...

    async def close(self) -> None: ...


class OllamaProvider:
    """LLM provider using Ollama API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "gemma4:e4b",
        temperature: float = 0.7,
        timeout: int | None = None,
        keep_alive: int | str = "20m",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.keep_alive = keep_alive
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

    async def _close_client_safely(self) -> None:
        """Close current HTTP client, tolerating closed loop scenarios."""
        if self._client is None:
            return

        try:
            await self._client.aclose()
        except RuntimeError as e:
            logger.debug("Ignoring client close runtime error: %s", e)
        finally:
            self._client = None
            self._client_loop = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        current_loop = asyncio.get_running_loop()

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._client_loop = current_loop
            return self._client

        if self._client.is_closed or self._client_loop is not current_loop:
            await self._close_client_safely()
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._client_loop = current_loop

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
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive

        try:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return str(data.get("response", "")).strip()
        except httpx.HTTPError as e:
            logger.error("Ollama request failed: %s", e)
            raise RuntimeError(f"Ollama API error: {e}") from e

    async def astream_complete(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        """Generate async streamed completion tokens.

        Args:
            prompt: The prompt to send.
            **kwargs: Additional parameters (temperature, etc.).

        Yields:
            Response chunks as they are produced by the model.
        """
        client = await self._get_client()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", self.temperature),
            },
        }
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive

        try:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    chunk = data.get("response", "")
                    if chunk:
                        yield chunk

                    if data.get("done"):
                        break
        except httpx.HTTPError as e:
            logger.error("Ollama streaming request failed: %s", e)
            raise RuntimeError(f"Ollama API error: {e}") from e

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Generate sync completion.

        Args:
            prompt: The prompt to send
            **kwargs: Additional parameters

        Returns:
            Generated text response
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.acomplete(prompt, **kwargs))

        msg = "complete() cannot run inside an active event loop; use acomplete() instead."
        raise RuntimeError(msg)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._close_client_safely()

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


def get_ollama_provider(
    base_url: str = "http://localhost:11434",
    model: str = "gemma4:31b",
) -> OllamaProvider:
    """Create an Ollama provider.

    Args:
        base_url: Ollama server URL
        model: Model name to use

    Returns:
        OllamaProvider instance
    """
    return OllamaProvider(base_url=base_url, model=model)


class GroqProvider:
    """LLM provider using Groq API."""

    def __init__(
        self,
        api_key: str,
        model: str = "llama3-8b-8192",
        temperature: float = 0.7,
        timeout: int | None = None,
    ) -> None:
        self.base_url = "https://api.groq.com/openai/v1"
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

    async def _close_client_safely(self) -> None:
        """Close current HTTP client, tolerating closed loop scenarios."""
        if self._client is None:
            return

        try:
            await self._client.aclose()
        except RuntimeError as e:
            logger.debug("Ignoring client close runtime error: %s", e)
        finally:
            self._client = None
            self._client_loop = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        current_loop = asyncio.get_running_loop()

        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            self._client_loop = current_loop
            return self._client

        if self._client.is_closed or self._client_loop is not current_loop:
            await self._close_client_safely()
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            self._client_loop = current_loop

        return self._client

    async def acomplete(self, prompt: str, **kwargs: Any) -> str:
        client = await self._get_client()

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": False,
        }

        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"]).strip()
        except httpx.HTTPError as e:
            logger.error("Groq request failed: %s", e)
            raise RuntimeError(f"Groq API error: {e}") from e

    async def astream_complete(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        client = await self._get_client()

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": True,
        }

        try:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    json_str = line[len("data: ") :]
                    if json_str == "[DONE]":
                        break

                    try:
                        data = json.loads(json_str)
                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                    except json.JSONDecodeError:
                        continue
        except httpx.HTTPError as e:
            logger.error("Groq streaming request failed: %s", e)
            raise RuntimeError(f"Groq API error: {e}") from e

    def complete(self, prompt: str, **kwargs: Any) -> str:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.acomplete(prompt, **kwargs))

        msg = "complete() cannot run inside an active event loop; use acomplete() instead."
        raise RuntimeError(msg)

    async def close(self) -> None:
        await self._close_client_safely()


def get_llm_provider() -> LLMProvider:
    """Get the configured LLM provider."""
    from lira.core.config import settings

    if settings.llm_provider == "groq":
        if not settings.groq_api_key:
            raise ValueError("groq_api_key configuration is missing or empty")
        return GroqProvider(
            api_key=settings.groq_api_key,
            model=settings.llm_model,
        )

    # Default to ollama
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.llm_model,
        keep_alive=settings.ollama_keep_alive,
    )
