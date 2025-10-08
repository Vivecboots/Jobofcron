"""Skill inventory utilities.

The inventory collects skills, certifications, and personal notes discovered
while applying for jobs. It can surface growth opportunities by tracking how
frequently each skill appears in matching job descriptions and which ones lead
to interviews or offers.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List


@dataclass
class SkillRecord:
    """Tracks how often a skill is observed and its outcomes."""

    name: str
    occurrences: int = 0
    interviews: int = 0
    offers: int = 0
    notes: List[str] = field(default_factory=list)

    def register_observation(self, count: int = 1) -> None:
        self.occurrences += count

    def record_interview(self) -> None:
        self.interviews += 1

    def record_offer(self) -> None:
        self.offers += 1

    def add_note(self, note: str) -> None:
        if note.strip():
            self.notes.append(note.strip())


class SkillsInventory:
    """Manages a collection of :class:`SkillRecord` instances."""

    def __init__(self) -> None:
        self._skills: Dict[str, SkillRecord] = {}

    def ensure(self, skill_name: str) -> SkillRecord:
        key = skill_name.lower().strip()
        if not key:
            raise ValueError("Skill name cannot be blank")
        if key not in self._skills:
            self._skills[key] = SkillRecord(name=skill_name.strip())
        return self._skills[key]

    def observe_skills(self, skills: Iterable[str]) -> None:
        cleaned = [skill.strip() for skill in skills if skill and skill.strip()]
        counts = Counter(skill.lower() for skill in cleaned)
        for key, count in counts.items():
            record = self._skills.get(key)
            if record is None:
                original = next(skill for skill in cleaned if skill.lower() == key)
                record = SkillRecord(name=original)
                self._skills[key] = record
            record.register_observation(count)

    def record_interview(self, skill_name: str) -> None:
        self.ensure(skill_name).record_interview()

    def record_offer(self, skill_name: str) -> None:
        self.ensure(skill_name).record_offer()

    def add_note(self, skill_name: str, note: str) -> None:
        self.ensure(skill_name).add_note(note)

    def to_snapshot(self) -> Dict[str, Dict[str, object]]:
        return {
            key: {
                "name": record.name,
                "occurrences": record.occurrences,
                "interviews": record.interviews,
                "offers": record.offers,
                "notes": list(record.notes),
            }
            for key, record in self._skills.items()
        }

    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Dict[str, object]]) -> "SkillsInventory":
        inventory = cls()
        for key, data in snapshot.items():
            inventory._skills[key] = SkillRecord(
                name=data.get("name", key),
                occurrences=data.get("occurrences", 0),
                interviews=data.get("interviews", 0),
                offers=data.get("offers", 0),
                notes=list(data.get("notes", [])),
            )
        return inventory

    def sorted_by_opportunity(self) -> List[SkillRecord]:
        """Return skills sorted by high demand but low success so far."""

        return sorted(
            self._skills.values(),
            key=lambda record: (
                -(record.occurrences - record.interviews - record.offers),
                -record.occurrences,
                record.name.lower(),
            ),
        )
