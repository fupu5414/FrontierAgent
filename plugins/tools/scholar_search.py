"""OpenAlex academic discovery tool."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from frontier_agent.core.tool import tool
from frontier_agent.infra.config import get_config

logger = logging.getLogger(__name__)
_MAX_RETRIES = 3


@tool
async def scholar_search(
    q: str,
    num_results: int = 10,
    from_year: int | None = None,
    to_year: int | None = None,
) -> str:
    """Search OpenAlex for academic works.

    Args:
        q: Academic search query.
        num_results: Number of works to return, from 1 through 25.
        from_year: Optional inclusive publication year.
        to_year: Optional inclusive publication year.

    Returns:
        Compact work metadata with OpenAlex and open-access links where available.
    """
    if not isinstance(q, str) or not q.strip():
        return "Error: search query cannot be empty."
    if type(num_results) is not int:
        return "Error: num_results must be an integer."
    if any(year is not None and type(year) is not int for year in (from_year, to_year)):
        return "Error: publication years must be integers."
    if from_year is not None and to_year is not None and from_year > to_year:
        return "Error: from_year cannot exceed to_year."

    config = get_config()
    if not config.openalex_api_key:
        return "Error: OPENALEX_API_KEY is required for scholar_search."

    params: dict[str, str | int] = {
        "search": q.strip(),
        "per-page": max(1, min(num_results, 25)),
    }
    filters = []
    if from_year is not None:
        filters.append(f"from_publication_date:{from_year}-01-01")
    if to_year is not None:
        filters.append(f"to_publication_date:{to_year}-12-31")
    if filters:
        params["filter"] = ",".join(filters)

    url = f"{config.openalex_base_url.rstrip('/')}/works"
    headers = {"Authorization": f"Bearer {config.openalex_api_key}"}
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, params=params, headers=headers)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                return f"Error: OpenAlex search failed with HTTP {response.status_code}."
            response.raise_for_status()
            return _format_results(response.json())
        except httpx.HTTPError as exc:
            logger.warning("OpenAlex search failed for %r: %s", q[:80], exc)
            return "Error: OpenAlex search request failed."
    raise AssertionError("OpenAlex retry loop did not return")


def _format_results(payload: Any) -> str:
    works = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(works, list) or not works:
        return "No OpenAlex works found."
    return "\n\n".join(_format_work(index, work) for index, work in enumerate(works, 1))


def _format_work(index: int, work: Any) -> str:
    work = work if isinstance(work, dict) else {}
    authors = ", ".join(
        author.get("author", {}).get("display_name", "")
        for author in work.get("authorships", [])
        if isinstance(author, dict) and isinstance(author.get("author"), dict)
        and author["author"].get("display_name")
    ) or "Unknown"
    location = work.get("primary_location") if isinstance(work.get("primary_location"), dict) else {}
    source = location.get("source") if isinstance(location.get("source"), dict) else {}
    oa_location = work.get("best_oa_location") if isinstance(work.get("best_oa_location"), dict) else {}
    open_access = work.get("open_access") if isinstance(work.get("open_access"), dict) else {}
    lines = [
        f"[{index}] {work.get('title') or 'Untitled'}",
        f"Year: {work.get('publication_year') or 'Unknown'} | Authors: {authors}",
        f"Source: {source.get('display_name') or 'Unknown'} | Citations: {work.get('cited_by_count', 0)}",
        f"DOI: {work.get('doi') or 'None'}",
        f"OpenAlex ID: {work.get('id') or 'Unknown'}",
    ]
    if oa_url := oa_location.get("landing_page_url") or open_access.get("oa_url"):
        lines.append(f"OA URL: {oa_url}")
    return "\n".join(lines)
