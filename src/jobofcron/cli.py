"""Lightweight command line interface for interacting with Jobofcron."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from .application_automation import AutomationDependencyError, DirectApplyAutomation, EmailApplicationSender
from .application_queue import ApplicationQueue, QueuedApplication
from .document_generation import (
    AIDocumentGenerator,
    DocumentGenerationDependencyError,
    DocumentGenerationError,
    generate_cover_letter,
    generate_resume,
)
from .job_history import AppliedJobRegistry
from .job_matching import JobPosting, analyse_job_fit
from .job_search import CraigslistSearch, GoogleJobSearch
from .profile import CandidateProfile
from .scheduler import plan_schedule
from .skills_inventory import SkillsInventory
from .storage import Storage
from .worker import JobAutomationWorker

DEFAULT_STORAGE = Path("jobofcron_data.json")


def slugify(*parts: str) -> str:
    token = "-".join(part.strip().lower().replace(" ", "-") for part in parts if part)
    cleaned = [ch for ch in token if ch.isalnum() or ch in {"-", "_"}]
    return "".join(cleaned) or "application"


def _normalise_term(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def _matches_blacklist(value: Optional[str], blacklist: List[str]) -> bool:
    target = _normalise_term(value)
    if not target:
        return False
    for entry in blacklist:
        token = _normalise_term(entry)
        if token and token in target:
            return True
    return False


def parse_iso_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - defensive conversion
        raise SystemExit("Use ISO 8601 format for timestamps, e.g. 2024-05-01T09:30") from exc


def load_or_init(
    storage_path: Path,
) -> tuple[CandidateProfile, SkillsInventory, ApplicationQueue, AppliedJobRegistry, Storage]:
    storage = Storage(storage_path)
    profile, inventory, queue, history = storage.load()

    if profile is None:
        profile = CandidateProfile(name="Unknown", email="unknown@example.com")
    if inventory is None:
        inventory = SkillsInventory()
    if queue is None:
        queue = ApplicationQueue()
    if history is None:
        history = AppliedJobRegistry()
    return profile, inventory, queue, history, storage


def save_and_exit(
    profile: CandidateProfile,
    inventory: SkillsInventory,
    queue: ApplicationQueue,
    history: AppliedJobRegistry,
    storage: Storage,
) -> None:
    storage.save(profile, inventory, queue, history)


def build_email_sender_from_args(args: argparse.Namespace) -> Optional[EmailApplicationSender]:
    host = getattr(args, "email_host", None) or os.getenv("JOBOFCRON_SMTP_HOST")
    if not host:
        return None

    port = getattr(args, "email_port", None) or os.getenv("JOBOFCRON_SMTP_PORT")
    port_int = int(port) if port else 587

    username = getattr(args, "email_username", None) or os.getenv("JOBOFCRON_SMTP_USERNAME")
    password = getattr(args, "email_password", None) or os.getenv("JOBOFCRON_SMTP_PASSWORD")
    from_address = getattr(args, "email_from", None) or os.getenv("JOBOFCRON_SMTP_FROM")

    use_ssl = bool(getattr(args, "email_use_ssl", False) or os.getenv("JOBOFCRON_SMTP_USE_SSL", "").lower() in {"1", "true", "yes"})
    disable_tls = bool(getattr(args, "email_disable_tls", False) or os.getenv("JOBOFCRON_SMTP_DISABLE_TLS", "").lower() in {"1", "true", "yes"})
    use_tls = not use_ssl and not disable_tls

    return EmailApplicationSender(
        host=host,
        port=port_int,
        username=username,
        password=password,
        from_address=from_address,
        use_tls=use_tls,
        use_ssl=use_ssl,
    )


def _build_ai_generator(
    *, api_key: Optional[str], model: str, temperature: float
) -> AIDocumentGenerator:
    try:
        return AIDocumentGenerator(api_key=api_key, model=model, temperature=temperature)
    except DocumentGenerationDependencyError as exc:
        raise SystemExit(str(exc)) from exc


def cmd_show_profile(args: argparse.Namespace) -> None:
    profile, inventory, queue, history, _ = load_or_init(Path(args.storage))
    print("Profile:")
    print(f"  Name: {profile.name}")
    print(f"  Email: {profile.email}")
    if profile.phone:
        print(f"  Phone: {profile.phone}")
    if profile.summary:
        print(f"  Summary: {profile.summary}")
    print("  Skills:")
    for skill in profile.skills:
        print(f"    - {skill}")
    print("  Preferences:")
    prefs = profile.job_preferences
    print(f"    Min salary: {prefs.min_salary}")
    print(f"    Locations: {', '.join(prefs.locations) if prefs.locations else 'None set'}")
    print(f"    Domains: {', '.join(prefs.focus_domains) if prefs.focus_domains else 'None set'}")
    print(f"    Felon friendly only: {'Yes' if prefs.felon_friendly_only else 'No'}")
    print(
        "    Blacklist: "
        + (", ".join(prefs.blacklisted_companies) if prefs.blacklisted_companies else "None set")
    )

    print("\nTracked skills (demand vs. success):")
    for record in inventory.sorted_by_opportunity():
        print(
            f"  {record.name}: seen {record.occurrences}x, interviews {record.interviews}, offers {record.offers}"
        )

    pending = queue.pending()
    print("\nQueued applications:")
    if not pending:
        print("  None pending.")
    else:
        for task in pending:
            print(
                f"  - {task.job_id} => {task.posting.title} at {task.posting.company} scheduled for {task.apply_at.isoformat(timespec='minutes')}"
            )


def cmd_update_preferences(args: argparse.Namespace) -> None:
    profile, inventory, queue, history, storage = load_or_init(Path(args.storage))
    profile.job_preferences.update(
        min_salary=args.min_salary,
        locations=args.locations,
        focus_domains=args.domains,
        felon_friendly_only=args.felon_friendly,
        blacklisted_companies=args.blacklist,
    )
    if args.name:
        profile.name = args.name
    if args.email:
        profile.email = args.email
    if args.phone:
        profile.phone = args.phone
    save_and_exit(profile, inventory, queue, history, storage)
    print("Preferences updated.")


def cmd_add_skill(args: argparse.Namespace) -> None:
    profile, inventory, queue, history, storage = load_or_init(Path(args.storage))
    profile.add_skill(args.skill)
    inventory.observe_skills([args.skill])
    save_and_exit(profile, inventory, queue, history, storage)
    print(f"Skill '{args.skill}' added.")


def cmd_plan(args: argparse.Namespace) -> None:
    profile, inventory, queue, _, _ = load_or_init(Path(args.storage))
    if len(args.titles) != len(args.companies):
        raise SystemExit("--titles and --companies must have the same length")
    jobs = [
        {"id": idx + 1, "title": title, "company": company}
        for idx, (title, company) in enumerate(zip(args.titles, args.companies))
    ]
    schedule = plan_schedule(
        jobs,
        start=datetime.now(),
        min_interval_minutes=args.interval,
        break_every=args.break_every,
    )
    print("Planned application times:")
    for entry in schedule:
        print(f"  {entry.apply_at.isoformat(timespec='minutes')} - {entry.job_title} @ {entry.company}")


def cmd_analyze(args: argparse.Namespace) -> None:
    profile, inventory, queue, history, storage = load_or_init(Path(args.storage))

    if args.description is None and args.description_file is None:
        raise SystemExit("Provide either --description or --description-file")

    description = args.description or Path(args.description_file).read_text(encoding="utf-8")
    posting = JobPosting(
        id=args.job_id,
        title=args.title,
        company=args.company,
        location=args.location,
        salary_text=args.salary,
        description=description,
        tags=args.tags or [],
        felon_friendly=args.felon_friendly,
        apply_url=args.apply_url,
        contact_email=args.contact_email,
    )

    assessment = analyse_job_fit(profile, posting)
    inventory.observe_skills(assessment.required_skills)
    save_and_exit(profile, inventory, queue, history, storage)

    total_skills = len(assessment.required_skills)
    matched = len(assessment.matched_skills)
    score_pct = assessment.match_score * 100
    print(f"Match score: {score_pct:.0f}% ({matched}/{total_skills or 1} skills covered)")

    if assessment.required_skills:
        print("Required skills detected:")
        for skill in assessment.required_skills:
            marker = "✔" if skill.lower() in {s.lower() for s in assessment.matched_skills} else "✖"
            print(f"  {marker} {skill}")

    if assessment.recommended_questions:
        print("\nQuestions to clarify:")
        for question in assessment.recommended_questions:
            print(f"  - {question}")

    if assessment.recommended_profile_updates:
        print("\nResume/Cover letter focus:")
        for update in assessment.recommended_profile_updates:
            print(f"  - {update}")

    if assessment.salary_notes:
        print("\nSalary notes:")
        for note in assessment.salary_notes:
            print(f"  - {note}")
    elif assessment.meets_salary is True:
        print("\nSalary notes:")
        print("  - Posting appears to meet your minimum salary preference.")

    if assessment.location_notes:
        print("\nLocation notes:")
        for note in assessment.location_notes:
            print(f"  - {note}")
    elif assessment.meets_location is True:
        print("\nLocation notes:")
        print("  - Posting aligns with your saved location preferences.")

    if assessment.felon_friendly is True:
        print("\nFelon-friendly signal: Posting explicitly welcomes justice-impacted candidates.")
    elif assessment.felon_friendly is False:
        print("\nFelon-friendly signal: Posting may require a clean record; investigate further before applying.")
    else:
        print("\nFelon-friendly signal: No clear information provided; follow up if this is a requirement.")


def cmd_generate_documents(args: argparse.Namespace) -> None:
    profile, inventory, queue, history, storage = load_or_init(Path(args.storage))

    if args.description is None and args.description_file is None:
        raise SystemExit("Provide either --description or --description-file")

    description = args.description or Path(args.description_file).read_text(encoding="utf-8")
    posting = JobPosting(
        id=args.job_id,
        title=args.title,
        company=args.company,
        location=args.location,
        salary_text=args.salary,
        description=description,
        tags=args.tags or [],
        felon_friendly=args.felon_friendly,
        apply_url=args.apply_url,
    )

    assessment = analyse_job_fit(profile, posting)
    inventory.observe_skills(assessment.required_skills)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(args.job_id or posting.id or posting.title, posting.company)

    resume_path = output_dir / f"{slug}_resume.md"
    cover_path = output_dir / f"{slug}_cover_letter.md"

    resume_text: str
    cover_text: str

    resume_template_text = (
        Path(args.resume_template_file).read_text(encoding="utf-8")
        if args.resume_template_file
        else None
    )
    cover_template_text = (
        Path(args.cover_template_file).read_text(encoding="utf-8")
        if args.cover_template_file
        else None
    )

    if args.resume_template == "custom" and not resume_template_text:
        raise SystemExit("--resume-template-file is required when using the custom resume template")
    if args.cover_template == "custom" and not cover_template_text:
        raise SystemExit("--cover-template-file is required when using the custom cover letter template")

    if args.use_ai:
        generator = _build_ai_generator(
            api_key=args.ai_api_key,
            model=args.ai_model,
            temperature=args.ai_temperature,
        )
        try:
            resume_text = generator.generate_resume(profile, posting, assessment)
            cover_text = generator.generate_cover_letter(profile, posting, assessment)
        except DocumentGenerationError as exc:
            raise SystemExit(str(exc))
    else:
        resume_text = generate_resume(
            profile,
            posting,
            assessment,
            style=args.resume_template,
            custom_template=resume_template_text,
        )
        cover_text = generate_cover_letter(
            profile,
            posting,
            assessment,
            style=args.cover_template,
            custom_template=cover_template_text,
        )

    resume_path.write_text(resume_text, encoding="utf-8")
    cover_path.write_text(cover_text, encoding="utf-8")

    print(f"Resume saved to {resume_path}")
    print(f"Cover letter saved to {cover_path}")

    if args.enqueue:
        if not posting.apply_url:
            raise SystemExit("--apply-url is required when enqueueing an application")
        apply_at = parse_iso_datetime(args.apply_at) if args.apply_at else datetime.now()
        blacklist = profile.job_preferences.blacklisted_companies
        if blacklist and (
            _matches_blacklist(posting.company, blacklist)
            or _matches_blacklist(args.company, blacklist)
        ):
            print(
                f"Skipping queue: {posting.company} is currently blacklisted in your preferences."
            )
            save_and_exit(profile, inventory, queue, history, storage)
            return
        task = QueuedApplication(
            posting=posting,
            apply_at=apply_at,
            resume_path=str(resume_path),
            cover_letter_path=str(cover_path),
            resume_template=args.resume_template,
            cover_letter_template=args.cover_template,
            custom_resume_template=resume_template_text,
            custom_cover_letter_template=cover_template_text,
        )
        if args.use_ai:
            task.notes.append(f"Documents generated with AI model {args.ai_model}.")
        existing = queue.find_matching(task.posting)
        history_record = history.find(task.posting)
        if existing:
            print(
                f"Skipping queue for {task.posting.title} at {task.posting.company}: already queued for"
                f" {existing.apply_at.isoformat(timespec='minutes')} (status: {existing.status})."
            )
        elif history_record:
            print(
                f"Skipping queue for {task.posting.title} at {task.posting.company}: applied previously on"
                f" {history_record.last_seen_at.isoformat(timespec='minutes')} (status: {history_record.last_status or 'unknown'})."
            )
        else:
            queue.add(task)
            print(f"Queued application {task.job_id} for {apply_at.isoformat(timespec='minutes')}")

    save_and_exit(profile, inventory, queue, history, storage)


def _load_description(args: argparse.Namespace) -> str:
    if args.description is None and args.description_file is None:
        raise SystemExit("Provide either --description or --description-file")
    return args.description or Path(args.description_file).read_text(encoding="utf-8")


def cmd_apply(args: argparse.Namespace) -> None:
    profile, inventory, queue, history, storage = load_or_init(Path(args.storage))
    automation = DirectApplyAutomation(headless=not args.no_headless, timeout=args.timeout)
    task: Optional[QueuedApplication] = None
    now = datetime.now()
    resume_path: Optional[Path] = None
    cover_path: Optional[Path] = None
    email_sender = build_email_sender_from_args(args)

    if args.queue_id:
        task = queue.get(args.queue_id)
        if not task:
            raise SystemExit(f"No queued application found with id {args.queue_id}")
        posting = task.posting
        resume_path = Path(task.resume_path) if task.resume_path else None
        cover_path = Path(task.cover_letter_path) if task.cover_letter_path else None
        assessment = analyse_job_fit(profile, posting)
    else:
        if not args.apply_url:
            raise SystemExit("--apply-url is required when applying directly")
        if not args.title or not args.company:
            raise SystemExit("--title and --company are required when applying directly")
        description = _load_description(args)
        posting = JobPosting(
            id=args.job_id,
            title=args.title,
            company=args.company,
            location=args.location,
            salary_text=args.salary,
            description=description,
            tags=args.tags or [],
            felon_friendly=args.felon_friendly,
            apply_url=args.apply_url,
            contact_email=args.contact_email,
        )
        assessment = analyse_job_fit(profile, posting)
        inventory.observe_skills(assessment.required_skills)
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        resume_path = Path(args.resume) if args.resume else None
        cover_path = Path(args.cover_letter) if args.cover_letter else None
        if args.auto_documents:
            slug = slugify(args.job_id or posting.id or posting.title, posting.company)
            resume_path = output_dir / f"{slug}_resume.md"
            cover_path = output_dir / f"{slug}_cover_letter.md"
            if args.ai_docs:
                generator = _build_ai_generator(
                    api_key=args.ai_api_key,
                    model=args.ai_model,
                    temperature=args.ai_temperature,
                )
                try:
                    resume_text = generator.generate_resume(profile, posting, assessment)
                    cover_text = generator.generate_cover_letter(profile, posting, assessment)
                except DocumentGenerationError as exc:
                    raise SystemExit(str(exc))
            else:
                resume_template_text = (
                    Path(args.resume_template_file).read_text(encoding="utf-8")
                    if args.resume_template_file
                    else None
                )
                cover_template_text = (
                    Path(args.cover_template_file).read_text(encoding="utf-8")
                    if args.cover_template_file
                    else None
                )
                if args.resume_template == "custom" and not resume_template_text:
                    raise SystemExit("--resume-template-file is required when using the custom resume template")
                if args.cover_template == "custom" and not cover_template_text:
                    raise SystemExit("--cover-template-file is required when using the custom cover letter template")
                resume_text = generate_resume(
                    profile,
                    posting,
                    assessment,
                    style=args.resume_template,
                    custom_template=resume_template_text,
                )
                cover_text = generate_cover_letter(
                    profile,
                    posting,
                    assessment,
                    style=args.cover_template,
                    custom_template=cover_template_text,
                )
            resume_path.write_text(resume_text, encoding="utf-8")
            cover_path.write_text(cover_text, encoding="utf-8")
            print(f"Generated resume at {resume_path}")
            print(f"Generated cover letter at {cover_path}")

    blacklist = profile.job_preferences.blacklisted_companies
    if blacklist and (
        _matches_blacklist(posting.company, blacklist)
        or _matches_blacklist(posting.title, blacklist)
    ):
        print(
            f"Warning: {posting.company} appears in your blacklist preferences."
            " Remove it via 'prefs --blacklist' to stop seeing this warning."
        )

    existing = queue.find_matching(posting)
    if existing and (task is None or existing.job_id != task.job_id):
        print(
            f"Warning: {posting.title} at {posting.company} is already queued for"
            f" {existing.apply_at.isoformat(timespec='minutes')} (status: {existing.status})."
        )
    history_record = history.find(posting)
    if history_record:
        print(
            "Warning: this job was previously actioned on "
            f"{history_record.last_seen_at.isoformat(timespec='minutes')}"
            f" (status: {history_record.last_status or 'unknown'})."
        )

    email_handled = False
    email_target = bool(
        posting.contact_email or (posting.apply_url and posting.apply_url.startswith("mailto:"))
    )
    if email_target and email_sender is not None:
        try:
            sent = email_sender.send(
                profile,
                posting,
                resume_path=resume_path,
                cover_letter_path=cover_path,
                dry_run=args.dry_run,
            )
        except Exception as exc:  # pragma: no cover - SMTP integration
            print(f"Email submission failed: {exc}")
            if task:
                task.mark_failure(str(exc))
                task.defer(now + timedelta(minutes=args.retry_minutes))
            email_handled = True
        else:
            if args.dry_run:
                print("[dry-run] Would send an application email instead of using the browser automation.")
                if task:
                    task.notes.append("Dry run executed; email send simulated.")
                    task.defer(now + timedelta(minutes=args.retry_minutes))
                email_handled = True
            elif sent:
                print("Application email sent successfully.")
                if task:
                    task.mark_success()
                history.record(posting, status="applied")
                email_handled = True
    elif email_target and email_sender is None:
        print("Email contact detected but SMTP settings are missing; cannot send email automation.")
        if not posting.apply_url or posting.apply_url.startswith("mailto:"):
            if task:
                task.defer(now + timedelta(minutes=args.retry_minutes))
                task.notes.append("SMTP configuration missing; email-only application deferred.")
            else:
                print("Provide SMTP credentials or specify a direct apply URL to continue.")
            email_handled = True

    if email_handled:
        save_and_exit(profile, inventory, queue, history, storage)
        return

    if posting.apply_url and posting.apply_url.startswith("mailto:"):
        print("Mailto apply link requires SMTP settings; aborting automation run.")
        if task:
            task.defer(now + timedelta(minutes=args.retry_minutes))
        save_and_exit(profile, inventory, queue, history, storage)
        return

    try:
        submitted = automation.apply(
            profile,
            posting,
            resume_path=resume_path,
            cover_letter_path=cover_path,
            dry_run=args.dry_run,
        )
        if submitted:
            if args.dry_run:
                print("Dry run complete; documents prepared without submitting the form.")
                if task:
                    task.notes.append(
                        "Dry run executed via CLI; manual review/submission still pending."
                    )
            else:
                print("Application submission routine completed.")
                if task:
                    task.mark_success()
                if not args.dry_run:
                    history.record(posting, status=task.status if task else "applied")
        else:
            print("Submission sequence executed but no submit control was triggered.")
            if task:
                task.mark_failure("No submit button detected")
                task.defer(now + timedelta(minutes=args.retry_minutes))
    except AutomationDependencyError as exc:
        print(f"Automation dependency missing: {exc}")
        if task:
            task.mark_failure(str(exc))
            task.defer(now + timedelta(minutes=args.retry_minutes))
    except Exception as exc:  # pragma: no cover - automation side effects
        print(f"Automation failed: {exc}")
        if task:
            task.mark_failure(str(exc))
            task.defer(now + timedelta(minutes=args.retry_minutes))
    finally:
        save_and_exit(profile, inventory, queue, history, storage)


def cmd_record_outcome(args: argparse.Namespace) -> None:
    profile, inventory, queue, history, storage = load_or_init(Path(args.storage))
    job_id = args.queue_id
    task = queue.get(job_id)
    if not task:
        raise SystemExit(f"No queued application found with id {job_id}")

    task.record_outcome(args.outcome, note=args.note)
    history.record(task.posting, status=task.status)

    target_skills: List[str] = args.skills or list(task.posting.tags or [])
    if args.outcome.lower() == "interview":
        for skill in target_skills:
            inventory.record_interview(skill)
    elif args.outcome.lower() == "offer":
        for skill in target_skills:
            inventory.record_offer(skill)

    save_and_exit(profile, inventory, queue, history, storage)
    print(f"Recorded outcome '{args.outcome}' for {job_id}.")


def cmd_worker(args: argparse.Namespace) -> None:
    documents_dir = Path(args.documents_dir)
    documents_dir.mkdir(parents=True, exist_ok=True)
    ai_generator: Optional[AIDocumentGenerator] = None
    if args.ai_docs:
        ai_generator = _build_ai_generator(
            api_key=args.ai_api_key,
            model=args.ai_model,
            temperature=args.ai_temperature,
        )
    email_sender = build_email_sender_from_args(args)
    worker = JobAutomationWorker(
        Path(args.storage),
        documents_dir=documents_dir,
        headless=not args.no_headless,
        timeout=args.timeout,
        retry_delay=timedelta(minutes=args.retry_minutes),
        ai_generator=ai_generator,
        email_sender=email_sender,
    )

    if args.loop:
        worker.run_forever(interval=args.interval, dry_run=args.dry_run)
    else:
        worker.run_once(dry_run=args.dry_run)


def cmd_search(args: argparse.Namespace) -> None:
    profile, inventory, queue, history, _ = load_or_init(Path(args.storage))

    location = args.location
    if not location:
        preferences = profile.job_preferences.locations
        if preferences:
            location = preferences[0]
    if not location:
        raise SystemExit("Provide --location or save a default location via prefs.")

    if args.min_match_score < 0 or args.min_match_score > 100:
        raise SystemExit("--min-match-score must be between 0 and 100")

    if args.provider != "google" and args.sample_response:
        raise SystemExit("--sample-response is only supported with the Google provider.")

    results = []

    if args.provider == "google":
        if args.sample_response:
            payload = json.loads(Path(args.sample_response).read_text(encoding="utf-8"))
            results = GoogleJobSearch.parse_results(payload)
        else:
            api_key = args.serpapi_key or os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY")
            if not api_key:
                raise SystemExit("Set SERPAPI_KEY or pass --serpapi-key to run live searches.")
            searcher = GoogleJobSearch(api_key=api_key, engine=args.engine)
            results = searcher.search_jobs(
                title=args.title,
                location=location,
                max_results=args.limit,
                remote=args.remote,
                extra_terms=args.extra or None,
            )

        if args.direct_only:
            results = GoogleJobSearch.filter_direct_apply(results)
    else:
        searcher = CraigslistSearch(
            location=location,
            site_hint=args.craigslist_site,
        )
        results = searcher.search_jobs(
            title=args.title,
            max_results=args.limit,
            remote=args.remote,
            extra_terms=args.extra or None,
        )

    scored_results = []
    blacklist = [entry for entry in profile.job_preferences.blacklisted_companies if entry.strip()]
    skipped_blacklisted: List[str] = []
    min_score_fraction = (args.min_match_score or 0) / 100
    for result in results:
        description = result.description or result.snippet
        posting = JobPosting(
            title=result.title,
            company=result.source or "Unknown",
            description=description or "",
            apply_url=result.link,
            contact_email=result.contact_email,
        )
        if blacklist and (
            _matches_blacklist(posting.company, blacklist)
            or _matches_blacklist(result.source, blacklist)
            or _matches_blacklist(result.title, blacklist)
        ):
            skipped_blacklisted.append(posting.company or result.source or result.title)
            continue
        assessment = analyse_job_fit(profile, posting)
        result.match_score = assessment.match_score
        duplicate_note = None
        queue_match = queue.find_matching(posting)
        history_match = history.find(posting)
        if queue_match:
            result.is_duplicate = True
            duplicate_note = (
                f"Queued for {queue_match.apply_at.isoformat(timespec='minutes')} (status: {queue_match.status})"
            )
        elif history_match:
            result.is_duplicate = True
            duplicate_note = (
                "Applied "
                f"{history_match.last_seen_at.isoformat(timespec='minutes')}"
                f" (status: {history_match.last_status or 'unknown'})"
            )
        result.duplicate_reason = duplicate_note
        if assessment.match_score >= min_score_fraction:
            scored_results.append(result)

    results = scored_results

    if args.sort_by == "match":
        results.sort(key=lambda res: res.match_score or 0.0, reverse=True)
    elif args.sort_by == "company":
        results.sort(key=lambda res: (res.source or "").lower())
    elif args.sort_by == "date":
        results.sort(key=lambda res: res.published_at or datetime.min, reverse=True)

    if skipped_blacklisted:
        skipped_preview = ", ".join(sorted({name or "Unknown" for name in skipped_blacklisted})[:5])
        print(
            f"Filtered {len(skipped_blacklisted)} result(s) due to blacklist settings: {skipped_preview}"
            + ("..." if len(set(skipped_blacklisted)) > 5 else "")
        )

    if not results:
        print("No search results found.")
        return

    print(f"Top {len(results)} results for '{args.title}' near {location} ({args.provider}):")
    for idx, result in enumerate(results, start=1):
        if args.provider == "google":
            badge = "DIRECT" if result.is_company_site else "AGGREGATOR"
        else:
            badge = "DIRECT"
        print(f"{idx:>2}. [{badge}] {result.title}")
        print(f"    Source: {result.source}")
        print(f"    Link:   {result.link}")
        if result.match_score is not None:
            print(f"    Match:  {int(round(result.match_score * 100))}%")
        if result.is_duplicate and result.duplicate_reason:
            print(f"    Duplicate: {result.duplicate_reason}")
        if result.contact_email:
            print(f"    Email:  {result.contact_email}")
        if args.verbose and result.snippet:
            print(f"    Snippet: {result.snippet}")

    if args.output:
        payload = []
        for result in results:
            data = asdict(result)
            if result.match_score is not None:
                data["match_score"] = result.match_score
                data["match_score_percent"] = round(result.match_score * 100, 2)
            data["provider"] = args.provider
            data["searched_location"] = location
            data["is_duplicate"] = result.is_duplicate
            data["duplicate_reason"] = result.duplicate_reason
            payload.append(data)
        Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Saved filtered results to {args.output}")


def cmd_batch_queue(args: argparse.Namespace) -> None:
    profile, inventory, queue, history, storage = load_or_init(Path(args.storage))

    payload = json.loads(Path(args.results).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("Results file must contain a JSON array of search results")

    if args.min_match_score < 0 or args.min_match_score > 100:
        raise SystemExit("--min-match-score must be between 0 and 100")

    resume_template_text = None
    cover_template_text = None
    if args.resume_template == "custom":
        if not args.resume_template_file:
            raise SystemExit("--resume-template-file is required when resume template is 'custom'")
        resume_template_text = Path(args.resume_template_file).read_text(encoding="utf-8")
    elif args.resume_template_file:
        resume_template_text = Path(args.resume_template_file).read_text(encoding="utf-8")

    if args.cover_template == "custom":
        if not args.cover_template_file:
            raise SystemExit("--cover-template-file is required when cover template is 'custom'")
        cover_template_text = Path(args.cover_template_file).read_text(encoding="utf-8")
    elif args.cover_template_file:
        cover_template_text = Path(args.cover_template_file).read_text(encoding="utf-8")

    start_time = parse_iso_datetime(args.start) if args.start else datetime.now()
    interval = timedelta(minutes=args.interval_minutes)
    min_score_fraction = args.min_match_score / 100

    queued = 0
    apply_at = start_time
    for item in payload:
        if not isinstance(item, dict):
            continue
        score = item.get("match_score")
        if score is None and item.get("match_score_percent") is not None:
            try:
                score = float(item.get("match_score_percent")) / 100
            except (TypeError, ValueError):
                score = None
        if score is not None and score < min_score_fraction:
            continue

        description = item.get("description") or item.get("snippet") or ""
        posting = JobPosting(
            id=item.get("id") or item.get("job_id"),
            title=item.get("title", "Unknown role"),
            company=item.get("company") or item.get("source", "Unknown company"),
            location=item.get("location"),
            salary_text=item.get("salary_text"),
            description=description,
            tags=list(item.get("tags", [])),
            felon_friendly=item.get("felon_friendly"),
            apply_url=item.get("link") or item.get("apply_url"),
            contact_email=item.get("contact_email"),
        )

        if not posting.apply_url and not posting.contact_email:
            continue

        blacklist = profile.job_preferences.blacklisted_companies
        if blacklist and (
            _matches_blacklist(posting.company, blacklist)
            or _matches_blacklist(item.get("source"), blacklist)
            or _matches_blacklist(posting.title, blacklist)
        ):
            print(
                f"Skipping {posting.title} at {posting.company}: company matches blacklist settings."
            )
            continue

        if queue.find_matching(posting):
            print(
                f"Skipping {posting.title} at {posting.company}: already queued."
            )
            continue
        history_record = history.find(posting)
        if history_record:
            print(
                f"Skipping {posting.title} at {posting.company}: previously applied on"
                f" {history_record.last_seen_at.isoformat(timespec='minutes')} (status: {history_record.last_status or 'unknown'})."
            )
            continue

        task = QueuedApplication(
            posting=posting,
            apply_at=apply_at,
            resume_template=args.resume_template,
            cover_letter_template=args.cover_template,
            custom_resume_template=resume_template_text,
            custom_cover_letter_template=cover_template_text,
        )
        queue.add(task)
        queued += 1
        apply_at += interval

    save_and_exit(profile, inventory, queue, history, storage)

    if queued:
        print(
            f"Queued {queued} jobs starting {start_time.isoformat(timespec='minutes')}"
            f" with {args.interval_minutes}-minute intervals."
        )
    else:
        print("No jobs met the filtering criteria; nothing was queued.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jobofcron CLI")
    parser.add_argument("--storage", default=str(DEFAULT_STORAGE))

    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show", help="Display the stored profile and skill stats")
    show.set_defaults(func=cmd_show_profile)

    prefs = subparsers.add_parser("prefs", help="Update profile and job preferences")
    prefs.add_argument("--name")
    prefs.add_argument("--email")
    prefs.add_argument("--phone")
    prefs.add_argument("--min-salary", dest="min_salary", type=int)
    prefs.add_argument("--locations", nargs="*", default=None)
    prefs.add_argument("--domains", nargs="*", default=None)
    prefs.add_argument("--felon-friendly", dest="felon_friendly", action="store_true")
    prefs.add_argument("--no-felon-friendly", dest="felon_friendly", action="store_false")
    prefs.add_argument("--blacklist", nargs="*", default=None, help="Companies to avoid during search and queueing")
    prefs.set_defaults(felon_friendly=None)
    prefs.set_defaults(func=cmd_update_preferences)

    add_skill = subparsers.add_parser("add-skill", help="Register a new skill")
    add_skill.add_argument("skill")
    add_skill.set_defaults(func=cmd_add_skill)

    plan = subparsers.add_parser("plan", help="Plan application pacing for a batch of jobs")
    plan.add_argument("--titles", nargs="+", required=True)
    plan.add_argument("--companies", nargs="+", required=True)
    plan.add_argument("--interval", type=int, default=10)
    plan.add_argument("--break-every", dest="break_every", type=int, default=5)
    plan.set_defaults(func=cmd_plan)

    analyze = subparsers.add_parser("analyze", help="Assess how well a job posting fits the saved profile")
    analyze.add_argument("--job-id")
    analyze.add_argument("--title", required=True)
    analyze.add_argument("--company", required=True)
    analyze.add_argument("--location")
    analyze.add_argument("--salary")
    analyze.add_argument("--tags", nargs="*")
    analyze.add_argument("--felon-friendly", dest="felon_friendly", action="store_true")
    analyze.add_argument("--no-felon-friendly", dest="felon_friendly", action="store_false")
    analyze.set_defaults(felon_friendly=None)
    analyze.add_argument("--description")
    analyze.add_argument("--description-file")
    analyze.add_argument("--apply-url")
    analyze.set_defaults(func=cmd_analyze)

    documents = subparsers.add_parser(
        "generate-docs",
        help="Generate resume and cover letter drafts tailored to a posting",
    )
    documents.add_argument("--job-id")
    documents.add_argument("--title", required=True)
    documents.add_argument("--company", required=True)
    documents.add_argument("--location")
    documents.add_argument("--salary")
    documents.add_argument("--tags", nargs="*")
    documents.add_argument("--felon-friendly", dest="felon_friendly", action="store_true")
    documents.add_argument("--no-felon-friendly", dest="felon_friendly", action="store_false")
    documents.set_defaults(felon_friendly=None)
    documents.add_argument("--description")
    documents.add_argument("--description-file")
    documents.add_argument("--apply-url")
    documents.add_argument("--contact-email")
    documents.add_argument("--output-dir", default="generated_documents")
    documents.add_argument("--enqueue", action="store_true")
    documents.add_argument(
        "--apply-at",
        help="ISO 8601 timestamp for when the worker should submit the queued application",
    )
    documents.add_argument("--use-ai", action="store_true", help="Use the AI generator instead of templates")
    documents.add_argument("--ai-model", default="gpt-4o-mini")
    documents.add_argument("--ai-api-key")
    documents.add_argument("--ai-temperature", type=float, default=0.3)
    documents.add_argument(
        "--resume-template",
        choices=["traditional", "modern", "minimal", "custom"],
        default="traditional",
    )
    documents.add_argument("--resume-template-file")
    documents.add_argument(
        "--cover-template",
        choices=["traditional", "modern", "minimal", "custom"],
        default="traditional",
    )
    documents.add_argument("--cover-template-file")
    documents.set_defaults(func=cmd_generate_documents)

    apply_cmd = subparsers.add_parser("apply", help="Submit an application immediately")
    apply_cmd.add_argument("--queue-id", help="Use a queued application id instead of providing job details")
    apply_cmd.add_argument("--job-id")
    apply_cmd.add_argument("--title")
    apply_cmd.add_argument("--company")
    apply_cmd.add_argument("--location")
    apply_cmd.add_argument("--salary")
    apply_cmd.add_argument("--tags", nargs="*")
    apply_cmd.add_argument("--felon-friendly", dest="felon_friendly", action="store_true")
    apply_cmd.add_argument("--no-felon-friendly", dest="felon_friendly", action="store_false")
    apply_cmd.set_defaults(felon_friendly=None)
    apply_cmd.add_argument("--description")
    apply_cmd.add_argument("--description-file")
    apply_cmd.add_argument("--apply-url")
    apply_cmd.add_argument("--contact-email")
    apply_cmd.add_argument("--resume")
    apply_cmd.add_argument("--cover-letter")
    apply_cmd.add_argument("--auto-documents", action="store_true")
    apply_cmd.add_argument("--ai-docs", action="store_true", help="Use the AI generator when auto-creating documents")
    apply_cmd.add_argument("--ai-model", default="gpt-4o-mini")
    apply_cmd.add_argument("--ai-api-key")
    apply_cmd.add_argument("--ai-temperature", type=float, default=0.3)
    apply_cmd.add_argument("--output-dir", default="generated_documents")
    apply_cmd.add_argument(
        "--resume-template",
        choices=["traditional", "modern", "minimal", "custom"],
        default="traditional",
    )
    apply_cmd.add_argument("--resume-template-file")
    apply_cmd.add_argument(
        "--cover-template",
        choices=["traditional", "modern", "minimal", "custom"],
        default="traditional",
    )
    apply_cmd.add_argument("--cover-template-file")
    apply_cmd.add_argument("--email-host")
    apply_cmd.add_argument("--email-port", type=int)
    apply_cmd.add_argument("--email-username")
    apply_cmd.add_argument("--email-password")
    apply_cmd.add_argument("--email-from")
    apply_cmd.add_argument("--email-use-ssl", action="store_true")
    apply_cmd.add_argument("--email-disable-tls", action="store_true")
    apply_cmd.add_argument("--no-headless", action="store_true")
    apply_cmd.add_argument("--timeout", type=int, default=90)
    apply_cmd.add_argument("--dry-run", action="store_true")
    apply_cmd.add_argument("--retry-minutes", type=int, default=60)
    apply_cmd.set_defaults(func=cmd_apply)

    search = subparsers.add_parser(
        "search",
        help="Discover roles via Google (SerpAPI) or Craigslist",
    )
    search.add_argument("--title", required=True, help="Job title or keywords to search for")
    search.add_argument("--location", help="Location to focus on; defaults to saved prefs")
    search.add_argument("--remote", action="store_true", help="Hint the search to favour remote roles")
    search.add_argument("--limit", type=int, default=10, help="Maximum number of search results to show")
    search.add_argument("--extra", nargs="*", help="Additional search terms to append")
    search.add_argument("--provider", choices=["google", "craigslist"], default="google")
    search.add_argument("--direct-only", action="store_true", help="Only show company-owned domains (Google only)")
    search.add_argument("--serpapi-key", help="Override the SERPAPI_KEY environment variable (Google only)")
    search.add_argument(
        "--engine",
        default="google",
        help="SerpAPI engine to use (defaults to 'google')",
    )
    search.add_argument(
        "--sample-response",
        help="Load a saved SerpAPI response JSON file instead of making a live request",
    )
    search.add_argument(
        "--craigslist-site",
        help="Craigslist site slug or hostname (e.g. 'austin' or 'sfbay.craigslist.org')",
    )
    search.add_argument("--verbose", action="store_true", help="Print search result snippets")
    search.add_argument("--min-match-score", type=int, default=0, help="Only show results scoring at or above this percent")
    search.add_argument(
        "--sort-by",
        choices=["match", "date", "company"],
        default="match",
        help="Sort results by match score, published date, or company",
    )
    search.add_argument("--output", help="Write the filtered results to a JSON file for later processing")
    search.set_defaults(func=cmd_search)

    batch = subparsers.add_parser(
        "batch-queue",
        help="Queue multiple jobs from a saved search results JSON file",
    )
    batch.add_argument("--results", required=True, help="Path to the JSON results file produced by the search command")
    batch.add_argument("--start", help="ISO 8601 timestamp for the first scheduled application")
    batch.add_argument("--interval-minutes", type=int, default=15, help="Minutes between each queued application")
    batch.add_argument("--min-match-score", type=int, default=0, help="Only queue jobs at or above this match score")
    batch.add_argument(
        "--resume-template",
        choices=["traditional", "modern", "minimal", "custom"],
        default="traditional",
    )
    batch.add_argument("--resume-template-file")
    batch.add_argument(
        "--cover-template",
        choices=["traditional", "modern", "minimal", "custom"],
        default="traditional",
    )
    batch.add_argument("--cover-template-file")
    batch.set_defaults(func=cmd_batch_queue)

    record = subparsers.add_parser(
        "record-outcome",
        help="Log interviews/offers for queued applications and update skill stats",
    )
    record.add_argument("--queue-id", required=True)
    record.add_argument(
        "--outcome",
        required=True,
        choices=["applied", "interview", "offer", "rejected", "ghosted"],
    )
    record.add_argument("--skills", nargs="*", help="Override which skills should be credited")
    record.add_argument("--note", help="Optional note to attach to the queue entry")
    record.set_defaults(func=cmd_record_outcome)

    worker = subparsers.add_parser("worker", help="Process queued applications on a schedule")
    worker.add_argument("--documents-dir", default="generated_documents")
    worker.add_argument("--loop", action="store_true", help="Keep running instead of exiting after one pass")
    worker.add_argument("--interval", type=int, default=300, help="Seconds to wait between polling runs")
    worker.add_argument("--dry-run", action="store_true", help="Skip browser automation and only refresh documents")
    worker.add_argument("--no-headless", action="store_true", help="Run the browser with a visible window")
    worker.add_argument("--timeout", type=int, default=90, help="Playwright navigation timeout in seconds")
    worker.add_argument("--retry-minutes", type=int, default=45, help="Minutes to wait before retrying failures")
    worker.add_argument("--ai-docs", action="store_true", help="Use the AI generator when refreshing documents")
    worker.add_argument("--ai-model", default="gpt-4o-mini")
    worker.add_argument("--ai-api-key")
    worker.add_argument("--ai-temperature", type=float, default=0.3)
    worker.add_argument("--email-host")
    worker.add_argument("--email-port", type=int)
    worker.add_argument("--email-username")
    worker.add_argument("--email-password")
    worker.add_argument("--email-from")
    worker.add_argument("--email-use-ssl", action="store_true")
    worker.add_argument("--email-disable-tls", action="store_true")
    worker.set_defaults(func=cmd_worker)

    return parser


def main(argv: List[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
