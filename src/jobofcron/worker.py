"""Background worker for orchestrating scheduled applications."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .application_automation import AutomationDependencyError, DirectApplyAutomation
from .application_queue import ApplicationQueue, QueuedApplication
from .document_generation import generate_cover_letter, generate_resume
from .job_matching import MatchAssessment, analyse_job_fit
from .profile import CandidateProfile
from .skills_inventory import SkillsInventory
from .storage import Storage


def _slugify(*parts: str) -> str:
    cleaned = "-".join(part.strip().lower().replace(" ", "-") for part in parts if part)
    return "".join(char for char in cleaned if char.isalnum() or char in {"-", "_"})


class JobAutomationWorker:
    """Run pending applications from the queue using the automation helpers."""

    def __init__(
        self,
        storage_path: Path,
        *,
        documents_dir: Optional[Path] = None,
        headless: bool = True,
        timeout: int = 90,
        retry_delay: timedelta = timedelta(minutes=45),
    ) -> None:
        self.storage = Storage(storage_path)
        self.documents_dir = documents_dir or Path("generated_documents")
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.retry_delay = retry_delay
        self.automation = DirectApplyAutomation(headless=headless, timeout=timeout)

    def run_once(self, *, dry_run: bool = False) -> None:
        profile, inventory, queue = self._load_state()
        now = datetime.now()
        due = queue.due(now)

        if not due:
            print("No pending applications ready to run.")
            return

        for task in due:
            print(f"Processing {task.posting.title} at {task.posting.company} (job id: {task.job_id})")
            assessment = analyse_job_fit(profile, task.posting)
            inventory.observe_skills(assessment.required_skills)

            resume_path, cover_path = self._ensure_documents(task, profile, assessment)

            try:
                if dry_run:
                    print(f"[dry-run] Would submit application to {task.posting.apply_url}")
                    task.notes.append("Dry run executed; application remains queued for a real run.")
                    task.defer(now + self.retry_delay)
                    continue
                else:
                    submitted = self.automation.apply(
                        profile,
                        task.posting,
                        resume_path=resume_path,
                        cover_letter_path=cover_path,
                    )
                    if submitted:
                        task.mark_success()
                    else:
                        task.mark_failure("No submit button detected")
                        task.defer(now + self.retry_delay)
                        print("Submit control not detected; task re-queued.")
                        continue
            except AutomationDependencyError as exc:
                task.mark_failure(str(exc))
                task.defer(now + self.retry_delay)
                print(f"Automation dependency missing: {exc}")
            except Exception as exc:  # pragma: no cover - integration heavy
                task.mark_failure(str(exc))
                task.defer(now + self.retry_delay)
                print(f"Automation failed: {exc}")

        self.storage.save(profile, inventory, queue)

    def run_forever(self, *, interval: int = 300, dry_run: bool = False) -> None:
        while True:
            self.run_once(dry_run=dry_run)
            time.sleep(interval)

    def _ensure_documents(
        self,
        task: QueuedApplication,
        profile,
        assessment: MatchAssessment,
    ) -> tuple[Path, Path]:
        slug = _slugify(task.posting.title, task.posting.company, task.job_id)
        resume_path = Path(task.resume_path) if task.resume_path else self.documents_dir / f"{slug}_resume.md"
        cover_path = (
            Path(task.cover_letter_path)
            if task.cover_letter_path
            else self.documents_dir / f"{slug}_cover_letter.md"
        )

        resume_text = generate_resume(profile, task.posting, assessment)
        resume_path.write_text(resume_text, encoding="utf-8")
        task.resume_path = str(resume_path)

        cover_letter = generate_cover_letter(profile, task.posting, assessment)
        cover_path.write_text(cover_letter, encoding="utf-8")
        task.cover_letter_path = str(cover_path)

        return resume_path, cover_path

    def _load_state(self) -> tuple:
        profile, inventory, queue = self.storage.load()
        if profile is None:
            profile = CandidateProfile(name="Unknown", email="unknown@example.com")
        if inventory is None:
            inventory = SkillsInventory()
        if queue is None:
            queue = ApplicationQueue()
        return profile, inventory, queue
