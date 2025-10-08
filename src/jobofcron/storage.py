"""Simple JSON-based persistence for the job application assistant."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .profile import CandidateProfile
from .skills_inventory import SkillsInventory


class Storage:
    """Persist profile and skills inventory to a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[CandidateProfile | None, SkillsInventory | None]:
        if not self.path.exists():
            return None, None

        data = json.loads(self.path.read_text(encoding="utf-8"))
        profile_data: Dict[str, Any] | None = data.get("profile")
        skills_data: Dict[str, Dict[str, Any]] | None = data.get("skills")

        profile = CandidateProfile.from_dict(profile_data) if profile_data else None
        skills = SkillsInventory.from_snapshot(skills_data) if skills_data else None
        return profile, skills

    def save(self, profile: CandidateProfile, skills: SkillsInventory) -> None:
        payload = {
            "profile": profile.to_dict(),
            "skills": skills.to_snapshot(),
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
