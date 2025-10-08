"""Background worker for orchestrating scheduled applications."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .application_automation import AutomationDependencyError, DirectApplyAutomation, EmailApplicationSender
from .application_queue import ApplicationQueue, QueuedApplication
from .document_generation import (
    AIDocumentGenerator,
    DocumentGenerationError,
    generate_cover_letter,
    generate_resume,
)
from .job_history import AppliedJobRegistry
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
        ai_generator: Optional[AIDocumentGenerator] = None,
        email_sender: Optional[EmailApplicationSender] = None,
    ) -> None:
        self.storage = Storage(storage_path)
        self.documents_dir = documents_dir or Path("generated_documents")
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.retry_delay = retry_delay
        self.automation = DirectApplyAutomation(headless=headless, timeout=timeout)
        self.ai_generator = ai_generator
        self.email_sender = email_sender

    def run_once(self, *, dry_run: bool = False) -> None:
        profile, inventory, queue, history = self._load_state()
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
                email_target = bool(
                    task.posting.contact_email
                    or (task.posting.apply_url and task.posting.apply_url.startswith("mailto:"))
                )
                if email_target and self.email_sender is not None:
                    try:
                        sent = self.email_sender.send(
                            profile,
                            task.posting,
                            resume_path=resume_path,
                            cover_letter_path=cover_path,
                            dry_run=dry_run,
                        )
                    except Exception as exc:  # pragma: no cover - SMTP integration
                        task.mark_failure(f"Email send failed: {exc}")
                        task.defer(now + self.retry_delay)
                        print(f"Email submission failed: {exc}")
                        continue

                    if dry_run:
                        task.notes.append("Dry run executed; email send simulated.")
                        task.defer(now + self.retry_delay)
                        continue

                    if sent:
                        task.mark_success()
                        history.record(task.posting, status=task.status)
                        continue
                elif email_target and self.email_sender is None:
                    task.notes.append(
                        "Email application detected but SMTP settings were not provided; falling back to browser automation."
                    )

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
                        history.record(task.posting, status=task.status)
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

        self.storage.save(profile, inventory, queue, history)

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

        if self.ai_generator is not None:
            try:
                resume_text = self.ai_generator.generate_resume(profile, task.posting, assessment)
            except DocumentGenerationError as exc:
                task.notes.append(f"AI resume generation failed: {exc}")
                resume_text = generate_resume(
                    profile,
                    task.posting,
                    assessment,
                    style=task.resume_template,
                    custom_template=task.custom_resume_template,
                )
        else:
            resume_text = generate_resume(
                profile,
                task.posting,
                assessment,
                style=task.resume_template,
                custom_template=task.custom_resume_template,
            )
        resume_path.write_text(resume_text, encoding="utf-8")
        task.resume_path = str(resume_path)

        if self.ai_generator is not None:
            try:
                cover_letter = self.ai_generator.generate_cover_letter(profile, task.posting, assessment)
            except DocumentGenerationError as exc:
                task.notes.append(f"AI cover letter generation failed: {exc}")
                cover_letter = generate_cover_letter(
                    profile,
                    task.posting,
                    assessment,
                    style=task.cover_letter_template,
                    custom_template=task.custom_cover_letter_template,
                )
        else:
            cover_letter = generate_cover_letter(
                profile,
                task.posting,
                assessment,
                style=task.cover_letter_template,
                custom_template=task.custom_cover_letter_template,
            )
        cover_path.write_text(cover_letter, encoding="utf-8")
        task.cover_letter_path = str(cover_path)

        return resume_path, cover_path

    def _load_state(self) -> tuple:
        profile, inventory, queue, history = self.storage.load()
        if profile is None:
            profile = CandidateProfile(name="Unknown", email="unknown@example.com")
        if inventory is None:
            inventory = SkillsInventory()
        if queue is None:
            queue = ApplicationQueue()
        if history is None:
            history = AppliedJobRegistry()
        return profile, inventory, queue, history
