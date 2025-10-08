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

import html
import re
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
    description: Optional[str] = None
    contact_email: Optional[str] = None
    match_score: Optional[float] = None


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


class CraigslistSearch:
    """Scrape Craigslist job listings for a region using the public HTML pages."""

    def __init__(
        self,
        *,
        location: str,
        site_hint: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.location = location
        self.base_url = self._resolve_base(site_hint or location)
        self.session = session or requests.Session()

    @staticmethod
    def _resolve_base(hint: str) -> str:
        slug = hint.strip().lower().replace(" ", "").replace(",", "")
        if not slug:
            slug = "www"
        if slug.startswith("http://") or slug.startswith("https://"):
            return slug.rstrip("/")
        if ".craigslist.org" in slug:
            return f"https://{slug.rstrip('/')}"
        return f"https://{slug}.craigslist.org"

    def search_jobs(
        self,
        *,
        title: str,
        max_results: int = 10,
        remote: bool = False,
        extra_terms: Optional[Iterable[str]] = None,
    ) -> List[SearchResult]:
        query_parts = [title]
        if remote:
            query_parts.append("remote")
        if extra_terms:
            query_parts.extend(term for term in extra_terms if term)
        query = " ".join(part for part in query_parts if part)

        url = f"{self.base_url}/search/jjj"
        headers = {"User-Agent": "jobofcron-bot/0.1"}
        response = self.session.get(url, params={"query": query, "sort": "date"}, headers=headers, timeout=30)
        response.raise_for_status()
        return self._parse_results(response.text)[:max_results]

    def _parse_results(self, html_text: str) -> List[SearchResult]:
        results: List[SearchResult] = []
        anchor_pattern = re.compile(
            r"<a[^>]+href=\"(?P<link>[^\"]+)\"[^>]*class=\"[^\"]*(?:result-title|titlestring)[^\"]*\"[^>]*>(?P<title>.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )
        snippet_pattern = re.compile(
            r"<span[^>]+class=\"[^\"]*(?:result-meta|meta)[^\"]*\"[^>]*>(?P<snippet>.*?)</span>",
            re.IGNORECASE | re.DOTALL,
        )
        for match in anchor_pattern.finditer(html_text):
            raw_title = re.sub(r"<.*?>", "", match.group("title"))
            title = html.unescape(raw_title).strip()
            link = html.unescape(match.group("link"))
            snippet = ""
            snippet_match = snippet_pattern.search(html_text, match.end(), match.end() + 400)
            if snippet_match:
                snippet_raw = re.sub(r"<.*?>", " ", snippet_match.group("snippet"))
                snippet = re.sub(r"\s+", " ", html.unescape(snippet_raw)).strip()

            source = GoogleJobSearch._normalise_domain(link)
            description, contact_email = self._fetch_listing_details(link)
            results.append(
                SearchResult(
                    title=title,
                    link=link,
                    snippet=snippet,
                    source=source or "craigslist",
                    is_company_site=True,
                    description=description or snippet,
                    contact_email=contact_email,
                )
            )
        return results

    def _fetch_listing_details(self, link: str) -> tuple[Optional[str], Optional[str]]:
        headers = {"User-Agent": "jobofcron-bot/0.1"}
        try:
            response = self.session.get(link, headers=headers, timeout=30)
            response.raise_for_status()
        except requests.RequestException:
            return None, None

        html_text = response.text
        body_match = re.search(
            r"<section[^>]+id=\"postingbody\"[^>]*>(?P<body>.*?)</section>",
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        description = None
        if body_match:
            body = body_match.group("body")
            body = re.sub(r"<script.*?</script>", "", body, flags=re.IGNORECASE | re.DOTALL)
            body = re.sub(r"<style.*?</style>", "", body, flags=re.IGNORECASE | re.DOTALL)
            body = re.sub(r"<.*?>", " ", body)
            description = re.sub(r"\s+", " ", html.unescape(body)).strip()

        email_match = re.search(r"mailto:([^\"?]+)", html_text, flags=re.IGNORECASE)
        contact_email = None
        if email_match:
            contact_email = html.unescape(email_match.group(1))

        if not contact_email:
            data_email_match = re.search(r"data-email=\"([^\"]+)\"", html_text, flags=re.IGNORECASE)
            if data_email_match:
                contact_email = html.unescape(data_email_match.group(1))

        return description, contact_email
