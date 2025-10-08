"""Simple JSON-based persistence for the job application assistant."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .application_queue import ApplicationQueue
from .job_history import AppliedJobRegistry
from .profile import CandidateProfile
from .skills_inventory import SkillsInventory


class Storage:
    """Persist profile and skills inventory to a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(
        self,
    ) -> tuple[
        CandidateProfile | None,
        SkillsInventory | None,
        ApplicationQueue | None,
        AppliedJobRegistry | None,
    ]:
        if not self.path.exists():
            return None, None, ApplicationQueue(), AppliedJobRegistry()

        data = json.loads(self.path.read_text(encoding="utf-8"))
        profile_data: Dict[str, Any] | None = data.get("profile")
        skills_data: Dict[str, Dict[str, Any]] | None = data.get("skills")
        queue_data = data.get("queue", [])
        history_data = data.get("history")

        profile = CandidateProfile.from_dict(profile_data) if profile_data else None
        skills = SkillsInventory.from_snapshot(skills_data) if skills_data else None
        queue = ApplicationQueue.from_snapshot(queue_data) if queue_data is not None else ApplicationQueue()
        history = AppliedJobRegistry.from_snapshot(history_data)
        return profile, skills, queue, history

    def save(
        self,
        profile: CandidateProfile,
        skills: SkillsInventory,
        queue: ApplicationQueue | None = None,
        history: AppliedJobRegistry | None = None,
    ) -> None:
        queue = queue or ApplicationQueue()
        history = history or AppliedJobRegistry()
        payload = {
            "profile": profile.to_dict(),
            "skills": skills.to_snapshot(),
            "queue": queue.to_snapshot(),
            "history": history.to_snapshot(),
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
