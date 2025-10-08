"""Core data models for representing the candidate profile and job preferences.

These helpers focus on storing structured data that other services (matching,
application scheduling, document generation) can consume. They intentionally
avoid persistence and I/O so they can be reused in different environments
(e.g. CLI, web API, background worker).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class JobPreference:
    """Filters used when searching for roles.

    Attributes:
        min_salary: Minimum annual salary in USD the user will consider.
        locations: Preferred geographic locations. "Remote" should be included
            explicitly when remote work is desired.
        focus_domains: Industries or domains to prioritise when running
            searches.
        felon_friendly_only: Whether to restrict searches to postings that
            indicate they are open to candidates with felonies.
    """

    min_salary: Optional[int] = None
    locations: List[str] = field(default_factory=list)
    focus_domains: List[str] = field(default_factory=list)
    felon_friendly_only: bool = False

    def to_dict(self) -> Dict[str, object]:
        """Serialise the preference to a plain dictionary."""

        return asdict(self)

    def update(
        self,
        *,
        min_salary: Optional[int] | None = None,
        locations: Optional[List[str]] = None,
        focus_domains: Optional[List[str]] = None,
        felon_friendly_only: Optional[bool] = None,
    ) -> None:
        """Update the preference in-place with non-``None`` values."""

        if min_salary is not None:
            self.min_salary = min_salary
        if locations is not None:
            self.locations = locations
        if focus_domains is not None:
            self.focus_domains = focus_domains
        if felon_friendly_only is not None:
            self.felon_friendly_only = felon_friendly_only


@dataclass
class Experience:
    """Represents a single work history item."""

    company: str
    role: str
    start_date: datetime
    end_date: Optional[datetime] = None
    achievements: List[str] = field(default_factory=list)

    def current(self) -> bool:
        return self.end_date is None or self.end_date > datetime.now()


@dataclass
class CandidateProfile:
    """Aggregate model describing the user applying to jobs."""

    name: str
    email: str
    phone: Optional[str] = None
    summary: Optional[str] = None
    skills: List[str] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    experiences: List[Experience] = field(default_factory=list)
    job_preferences: JobPreference = field(default_factory=JobPreference)
    additional_notes: Dict[str, str] = field(default_factory=dict)

    def add_skill(self, skill: str) -> None:
        """Add a skill if it is not already present (case insensitive)."""

        normalised = skill.strip()
        if not normalised:
            return

        if normalised.lower() not in {s.lower() for s in self.skills}:
            self.skills.append(normalised)

    def record_experience(self, experience: Experience) -> None:
        """Append a new work history entry."""

        self.experiences.append(experience)

    def update_contact(self, *, email: Optional[str] = None, phone: Optional[str] = None) -> None:
        """Update contact fields with any provided values."""

        if email:
            self.email = email
        if phone:
            self.phone = phone

    def add_note(self, topic: str, note: str) -> None:
        """Store free-form notes (e.g. felony considerations, availability)."""

        if topic.strip():
            self.additional_notes[topic.strip()] = note.strip()

    def to_dict(self) -> Dict[str, object]:
        """Return a serialisable representation of the profile."""

        profile = asdict(self)
        profile["experiences"] = [
            {
                "company": exp.company,
                "role": exp.role,
                "start_date": exp.start_date.isoformat(),
                "end_date": exp.end_date.isoformat() if exp.end_date else None,
                "achievements": list(exp.achievements),
            }
            for exp in self.experiences
        ]
        profile["job_preferences"] = self.job_preferences.to_dict()
        return profile

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "CandidateProfile":
        """Hydrate a :class:`CandidateProfile` from saved data."""

        pref_data = data.get("job_preferences", {})
        job_preferences = JobPreference(
            min_salary=pref_data.get("min_salary"),
            locations=list(pref_data.get("locations", [])),
            focus_domains=list(pref_data.get("focus_domains", [])),
            felon_friendly_only=pref_data.get("felon_friendly_only", False),
        )

        experiences = [
            Experience(
                company=exp["company"],
                role=exp["role"],
                start_date=datetime.fromisoformat(exp["start_date"]),
                end_date=datetime.fromisoformat(exp["end_date"]) if exp.get("end_date") else None,
                achievements=list(exp.get("achievements", [])),
            )
            for exp in data.get("experiences", [])
        ]

        return cls(
            name=data["name"],
            email=data["email"],
            phone=data.get("phone"),
            summary=data.get("summary"),
            skills=list(data.get("skills", [])),
            certifications=list(data.get("certifications", [])),
            experiences=experiences,
            job_preferences=job_preferences,
            additional_notes=dict(data.get("additional_notes", {})),
        )
