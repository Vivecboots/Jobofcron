"""Utilities for managing queued job applications."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, List, Optional

from .job_matching import JobPosting


@dataclass
class QueuedApplication:
    """Metadata for an application to execute at a future time."""

    posting: JobPosting
    apply_at: datetime
    status: str = "pending"
    resume_path: Optional[str] = None
    cover_letter_path: Optional[str] = None
    resume_template: str = "traditional"
    cover_letter_template: str = "traditional"
    custom_resume_template: Optional[str] = None
    custom_cover_letter_template: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    attempts: int = 0
    last_error: Optional[str] = None
    outcome: Optional[str] = None
    outcome_recorded_at: Optional[datetime] = None

    @property
    def job_id(self) -> str:
        if self.posting.id:
            return str(self.posting.id)
        return f"{self.posting.title}@{self.posting.company}"

    def mark_success(self) -> None:
        self.status = "applied"
        self.attempts += 1
        self.last_error = None
        self.notes.append(f"Applied successfully on {datetime.now().isoformat(timespec='seconds')}")
        self.outcome = "applied"
        self.outcome_recorded_at = datetime.now()

    def mark_failure(self, error: str) -> None:
        self.status = "pending"
        self.attempts += 1
        self.last_error = error
        self.notes.append(f"Attempt failed on {datetime.now().isoformat(timespec='seconds')}: {error}")

    def defer(self, new_time: datetime) -> None:
        self.apply_at = new_time

    def record_outcome(self, outcome: str, *, note: Optional[str] = None) -> None:
        outcome_normalised = outcome.strip().lower()
        timestamp = datetime.now().isoformat(timespec="seconds")
        self.outcome = outcome_normalised
        self.outcome_recorded_at = datetime.now()
        self.status = outcome_normalised
        base_note = f"Outcome recorded ({outcome_normalised}) on {timestamp}."
        self.notes.append(base_note)
        if note and note.strip():
            self.notes.append(note.strip())

    def to_dict(self) -> dict:
        return {
            "posting": {
                "id": self.posting.id,
                "title": self.posting.title,
                "company": self.posting.company,
                "location": self.posting.location,
                "salary_text": self.posting.salary_text,
                "description": self.posting.description,
                "tags": list(self.posting.tags),
                "felon_friendly": self.posting.felon_friendly,
                "apply_url": self.posting.apply_url,
                "contact_email": self.posting.contact_email,
            },
            "apply_at": self.apply_at.isoformat(),
            "status": self.status,
            "resume_path": self.resume_path,
            "cover_letter_path": self.cover_letter_path,
            "resume_template": self.resume_template,
            "cover_letter_template": self.cover_letter_template,
            "custom_resume_template": self.custom_resume_template,
            "custom_cover_letter_template": self.custom_cover_letter_template,
            "notes": list(self.notes),
            "attempts": self.attempts,
            "last_error": self.last_error,
            "outcome": self.outcome,
            "outcome_recorded_at": self.outcome_recorded_at.isoformat()
            if self.outcome_recorded_at
            else None,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "QueuedApplication":
        posting_data = payload.get("posting", {})
        posting = JobPosting(
            id=posting_data.get("id"),
            title=posting_data.get("title", ""),
            company=posting_data.get("company", ""),
            location=posting_data.get("location"),
            salary_text=posting_data.get("salary_text"),
            description=posting_data.get("description", ""),
            tags=list(posting_data.get("tags", [])),
            felon_friendly=posting_data.get("felon_friendly"),
            apply_url=posting_data.get("apply_url"),
            contact_email=posting_data.get("contact_email"),
        )
        apply_at = datetime.fromisoformat(payload["apply_at"])
        return cls(
            posting=posting,
            apply_at=apply_at,
            status=payload.get("status", "pending"),
            resume_path=payload.get("resume_path"),
            cover_letter_path=payload.get("cover_letter_path"),
            resume_template=payload.get("resume_template", "traditional"),
            cover_letter_template=payload.get("cover_letter_template", "traditional"),
            custom_resume_template=payload.get("custom_resume_template"),
            custom_cover_letter_template=payload.get("custom_cover_letter_template"),
            notes=list(payload.get("notes", [])),
            attempts=payload.get("attempts", 0),
            last_error=payload.get("last_error"),
            outcome=payload.get("outcome"),
            outcome_recorded_at=datetime.fromisoformat(payload["outcome_recorded_at"])
            if payload.get("outcome_recorded_at")
            else None,
        )


@dataclass
class ApplicationQueue:
    """Collection helper with convenience methods for queue operations."""

    items: List[QueuedApplication] = field(default_factory=list)

    def add(self, application: QueuedApplication) -> None:
        existing = self.get(application.job_id)
        if existing:
            # Replace existing entry while preserving accumulated notes.
            application.notes = existing.notes + application.notes
            application.attempts = existing.attempts
            application.last_error = existing.last_error
            self.items = [app for app in self.items if app.job_id != application.job_id]
        self.items.append(application)

    def get(self, job_id: str) -> Optional[QueuedApplication]:
        for application in self.items:
            if application.job_id == job_id:
                return application
        return None

    def due(self, when: datetime) -> List[QueuedApplication]:
        pending = [app for app in self.items if app.status == "pending" and app.apply_at <= when]
        return sorted(pending, key=lambda app: app.apply_at)

    def pending(self) -> List[QueuedApplication]:
        return [app for app in self.items if app.status == "pending"]

    def to_snapshot(self) -> List[dict]:
        return [app.to_dict() for app in self.items]

    @classmethod
    def from_snapshot(cls, payload: Iterable[dict]) -> "ApplicationQueue":
        items = []
        for entry in payload or []:
            try:
                items.append(QueuedApplication.from_dict(entry))
            except Exception as exc:  # pragma: no cover - defensive programming
                # Skip malformed entries but capture context.
                broken = QueuedApplication(
                    posting=JobPosting(title="Unknown", company="Unknown"),
                    apply_at=datetime.now(),
                    status="failed",
                    notes=[f"Could not load entry: {exc}"],
                )
                items.append(broken)
        return cls(items=items)
