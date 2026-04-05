"""Unit tests for Ollama provider runtime behavior."""

from __future__ import annotations

import pytest

from lira.core import llm as llm_module
from lira.core.llm import OllamaProvider


class DummyAsyncClient:
    """Minimal AsyncClient replacement for lifecycle tests."""

    instances: list[DummyAsyncClient] = []

    def __init__(self, timeout: int) -> None:
        self.timeout = timeout
        self.closed = False
        DummyAsyncClient.instances.append(self)

    @property
    def is_closed(self) -> bool:
        return self.closed

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_get_client_reuses_same_loop_client(monkeypatch) -> None:
    """Provider should reuse one client within the same running loop."""
    DummyAsyncClient.instances.clear()
    monkeypatch.setattr(llm_module.httpx, "AsyncClient", DummyAsyncClient)

    provider = OllamaProvider()

    first = await provider._get_client()
    second = await provider._get_client()

    assert first is second
    assert len(DummyAsyncClient.instances) == 1

    await provider.close()
    assert second.closed is True


@pytest.mark.asyncio
async def test_get_client_recreates_when_loop_changes(monkeypatch) -> None:
    """Provider should replace client if subsequent calls use a different event loop."""
    DummyAsyncClient.instances.clear()
    monkeypatch.setattr(llm_module.httpx, "AsyncClient", DummyAsyncClient)

    provider = OllamaProvider()

    first = await provider._get_client()

    # Simulate a loop switch by forcing a loop mismatch sentinel.
    provider._client_loop = None

    second = await provider._get_client()

    assert second is not first
    assert first.closed is True
    assert len(DummyAsyncClient.instances) == 2

    await provider.close()
    assert second.closed is True
