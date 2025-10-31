"""Wrapper around SerpApi (or similar) web search APIs."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Sequence, Tuple

try:
    from serpapi import GoogleSearch
except ImportError:  # pragma: no cover - optional dependency
    GoogleSearch = None  # type: ignore

logger = logging.getLogger(__name__)

SearchResult = Tuple[str, str]


class SearchClient:
    """Perform web searches using SerpApi when configured."""

    def __init__(self, api_key: Optional[str], engine: Optional[str]) -> None:
        self._api_key = api_key
        self._engine = engine or "google"

    @property
    def enabled(self) -> bool:
        return bool(self._api_key and GoogleSearch is not None)

    async def search(self, query: str, *, limit: int = 5) -> Sequence[SearchResult]:
        if not self.enabled:
            raise RuntimeError("検索APIが設定されていません。")
        params = {
            "q": query,
            "api_key": self._api_key,
            "engine": self._engine,
        }

        def _request() -> List[SearchResult]:
            search = GoogleSearch(params)
            response = search.get_dict()
            results: List[SearchResult] = []
            for item in response.get("organic_results", [])[:limit]:
                title = item.get("title") or "(no title)"
                link = item.get("link") or ""
                results.append((title, link))
            return results

        return await asyncio.to_thread(_request)
