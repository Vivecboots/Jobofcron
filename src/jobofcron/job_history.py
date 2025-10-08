"""Track previously applied jobs to avoid duplicate submissions."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

from .job_matching import JobPosting


def _normalise_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def _normalise_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    if not netloc and not path:
        return None
    return f"url::{netloc}{path}{query}"


def _combo_key(title: Optional[str], company: Optional[str]) -> Optional[str]:
    title_key = _normalise_text(title)
    company_key = _normalise_text(company)
    if not title_key and not company_key:
        return None
    return f"role::{company_key}::{title_key}"


@dataclass
class AppliedJobRecord:
    """Metadata describing when a job was last actioned."""

    key: str
    title: str
    company: str
    apply_url: Optional[str]
    first_seen_at: datetime
    last_seen_at: datetime
    last_status: Optional[str] = None
    occurrences: int = 1

    def touch(self, *, status: Optional[str] = None) -> None:
        self.last_seen_at = datetime.now()
        if status:
            self.last_status = status
        self.occurrences += 1

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "company": self.company,
            "apply_url": self.apply_url,
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "last_status": self.last_status,
            "occurrences": self.occurrences,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppliedJobRecord":
        return cls(
            key=data["key"],
            title=data.get("title", ""),
            company=data.get("company", ""),
            apply_url=data.get("apply_url"),
            first_seen_at=datetime.fromisoformat(data["first_seen_at"]),
            last_seen_at=datetime.fromisoformat(data["last_seen_at"]),
            last_status=data.get("last_status"),
            occurrences=int(data.get("occurrences", 1)),
        )


@dataclass
class AppliedJobRegistry:
    """Lookup helper to detect if a job has already been actioned."""

    records: Dict[str, AppliedJobRecord] = field(default_factory=dict)
    aliases: Dict[str, str] = field(default_factory=dict)

    def _keys_for(self, posting: JobPosting) -> List[str]:
        keys: List[str] = []
        url_key = _normalise_url(posting.apply_url)
        if url_key:
            keys.append(url_key)
        combo = _combo_key(posting.title, posting.company)
        if combo:
            keys.append(combo)
        if not keys:
            fallback = _normalise_text(posting.title) or "unknown"
            keys.append(f"fallback::{fallback}")
        return keys

    def find(self, posting: JobPosting) -> Optional[AppliedJobRecord]:
        for key in self._keys_for(posting):
            target = self.aliases.get(key, key)
            if target in self.records:
                return self.records[target]
        return None

    def record(self, posting: JobPosting, *, status: Optional[str] = None) -> AppliedJobRecord:
        now = datetime.now()
        keys = self._keys_for(posting)
        existing = None
        for key in keys:
            target = self.aliases.get(key)
            if target and target in self.records:
                existing = self.records[target]
                break

        if existing:
            existing.touch(status=status)
            if status and not existing.last_status:
                existing.last_status = status
            for key in keys:
                self.aliases[key] = existing.key
            if posting.apply_url:
                existing.apply_url = posting.apply_url
            if posting.company:
                existing.company = posting.company
            if posting.title:
                existing.title = posting.title
            return existing

        primary_key = keys[0]
        record = AppliedJobRecord(
            key=primary_key,
            title=posting.title,
            company=posting.company,
            apply_url=posting.apply_url,
            first_seen_at=now,
            last_seen_at=now,
            last_status=status,
        )
        self.records[primary_key] = record
        for key in keys:
            self.aliases[key] = primary_key
        return record

    def to_snapshot(self) -> dict:
        return {
            "records": [record.to_dict() for record in self.records.values()],
            "aliases": dict(self.aliases),
        }

    @classmethod
    def from_snapshot(cls, payload: Optional[dict]) -> "AppliedJobRegistry":
        if not payload:
            return cls()
        records = {
            entry["key"]: AppliedJobRecord.from_dict(entry)
            for entry in payload.get("records", [])
            if "key" in entry
        }
        aliases = {key: value for key, value in (payload.get("aliases") or {}).items() if value in records}
        return cls(records=records, aliases=aliases)

    def known_keys(self) -> Iterable[str]:
        return self.aliases.keys()

