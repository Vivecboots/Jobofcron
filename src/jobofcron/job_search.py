"""Helpers for discovering job postings via Google search results.

This module provides a light wrapper around the SerpAPI Google Search endpoint
so we can query for job postings and then prioritise company career pages over
job-board aggregators like Indeed. The idea is to locate direct-apply links that
minimise the risk of automated filters catching us for coming from an external
board.

The implementation is intentionally thin: we only depend on ``requests`` and we
work with plain dataclasses so the search component can be reused outside of the
CLI (e.g. inside a web worker or an orchestration flow).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional
from urllib.parse import urlparse

import requests

SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"


AGGREGATOR_DOMAINS = {
    "indeed.com",
    "linkedin.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "monster.com",
    "simplyhired.com",
    "snagajob.com",
    "careerbuilder.com",
    "lever.co",
    "greenhouse.io",
    "angel.co",
}


@dataclass
class SearchResult:
    """A single Google search result parsed into structured data."""

    title: str
    link: str
    snippet: str
    source: str
    is_company_site: bool


class GoogleJobSearch:
    """Search Google via SerpAPI and highlight company career pages."""

    def __init__(self, api_key: str, *, engine: str = "google", session: Optional[requests.Session] = None) -> None:
        if not api_key:
            raise ValueError("An API key is required to query SerpAPI")
        self.api_key = api_key
        self.engine = engine
        self.session = session or requests.Session()

    def search_jobs(
        self,
        *,
        title: str,
        location: str,
        max_results: int = 10,
        remote: bool = False,
        extra_terms: Optional[Iterable[str]] = None,
    ) -> List[SearchResult]:
        """Run a Google search tailored for job discovery.

        Args:
            title: Role title or keywords to search for.
            location: Geographic location to append to the query.
            max_results: Maximum number of search results to return.
            remote: Whether to append a remote-work hint to the query.
            extra_terms: Optional additional search tokens (e.g. company
                domains, industry keywords).
        """

        query_parts = [title, "job", location]
        if remote:
            query_parts.append("remote")
        if extra_terms:
            query_parts.extend(term for term in extra_terms if term)
        query = " ".join(part for part in query_parts if part)

        params = {
            "engine": self.engine,
            "q": query,
            "api_key": self.api_key,
            "num": min(max_results, 20),
        }

        response = self.session.get(SERPAPI_SEARCH_URL, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        return self.parse_results(payload)[:max_results]

    @staticmethod
    def _normalise_domain(url: str) -> str:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        return domain.lstrip("www.")

    @classmethod
    def parse_results(cls, payload: dict) -> List[SearchResult]:
        """Convert a SerpAPI payload into :class:`SearchResult` objects."""

        results: List[SearchResult] = []
        for entry in payload.get("organic_results", []):
            link = entry.get("link") or ""
            title = entry.get("title") or ""
            snippet = entry.get("snippet") or ""
            domain = cls._normalise_domain(link)
            is_company = bool(domain) and not cls._is_aggregator(domain)
            results.append(
                SearchResult(
                    title=title.strip(),
                    link=link,
                    snippet=snippet.strip(),
                    source=domain or "unknown",
                    is_company_site=is_company,
                )
            )
        return results

    @staticmethod
    def _is_aggregator(domain: str) -> bool:
        domain = domain.lower()
        return any(domain == agg or domain.endswith(f".{agg}") for agg in AGGREGATOR_DOMAINS)

    @classmethod
    def filter_direct_apply(cls, results: Iterable[SearchResult]) -> List[SearchResult]:
        """Return only results that appear to come from company-owned domains."""

        return [result for result in results if result.is_company_site]
