from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

scholar_module = importlib.import_module("plugins.tools.scholar_search")


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise scholar_module.httpx.HTTPStatusError(
                "fixture", request=scholar_module.httpx.Request("GET", "https://example.test"), response=self
            )

    def json(self) -> dict:
        return self._payload


class _Client:
    def __init__(self, responses: list[_Response], calls: list[dict]) -> None:
        self.responses = responses
        self.calls = calls

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_scholar_search_uses_openalex_and_formats_compact_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    response = _Response(200, {"results": [{
        "title": "A useful result",
        "publication_year": 2024,
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        "primary_location": {"source": {"display_name": "Journal"}},
        "cited_by_count": 7,
        "doi": "https://doi.org/10.1000/example",
        "id": "https://openalex.org/W1",
        "best_oa_location": {"landing_page_url": "https://example.test/oa"},
    }]})
    monkeypatch.setattr(
        scholar_module, "get_config", lambda: SimpleNamespace(
            openalex_api_key="fixture-key", openalex_base_url="https://api.openalex.test"
        )
    )
    monkeypatch.setattr(
        scholar_module.httpx, "AsyncClient", lambda **_: _Client([response], calls)
    )

    result = await scholar_module.scholar_search.ainvoke(
        {"q": "fracture mechanics", "num_results": 99, "from_year": 2020, "to_year": 2024}
    )

    assert calls == [{
        "url": "https://api.openalex.test/works",
        "params": {
            "search": "fracture mechanics",
            "per-page": 25,
            "filter": "from_publication_date:2020-01-01,to_publication_date:2024-12-31",
        },
        "headers": {"Authorization": "Bearer fixture-key"},
    }]
    for expected in ("A useful result", "Ada Lovelace", "Journal", "Citations: 7", "DOI:", "OpenAlex ID:", "OA URL:"):
        assert expected in result


@pytest.mark.asyncio
async def test_scholar_search_retries_rate_limits_and_requires_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scholar_module, "get_config", lambda: SimpleNamespace(
            openalex_api_key="", openalex_base_url="https://api.openalex.org"
        )
    )
    assert "OPENALEX_API_KEY" in await scholar_module.scholar_search.ainvoke({"q": "test"})

    calls: list[dict] = []
    responses = [_Response(429, {}), _Response(200, {"results": []})]
    monkeypatch.setattr(
        scholar_module, "get_config", lambda: SimpleNamespace(
            openalex_api_key="fixture-key", openalex_base_url="https://api.openalex.org"
        )
    )
    monkeypatch.setattr(
        scholar_module.httpx, "AsyncClient", lambda **_: _Client(responses, calls)
    )
    monkeypatch.setattr(scholar_module.asyncio, "sleep", lambda _: _done())
    assert await scholar_module.scholar_search.ainvoke({"q": "test"}) == "No OpenAlex works found."
    assert len(calls) == 2


async def _done() -> None:
    return None
