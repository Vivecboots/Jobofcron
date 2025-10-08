"""Lightweight command line interface for interacting with Jobofcron."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from .application_automation import AutomationDependencyError, DirectApplyAutomation
from .application_queue import ApplicationQueue, QueuedApplication
from .document_generation import generate_cover_letter, generate_resume
from .job_matching import JobPosting, analyse_job_fit
from .job_search import GoogleJobSearch
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


def parse_iso_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - defensive conversion
        raise SystemExit("Use ISO 8601 format for timestamps, e.g. 2024-05-01T09:30") from exc


def load_or_init(
    storage_path: Path,
) -> tuple[CandidateProfile, SkillsInventory, ApplicationQueue, Storage]:
    storage = Storage(storage_path)
    profile, inventory, queue = storage.load()

    if profile is None:
        profile = CandidateProfile(name="Unknown", email="unknown@example.com")
    if inventory is None:
        inventory = SkillsInventory()
    if queue is None:
        queue = ApplicationQueue()
    return profile, inventory, queue, storage


def save_and_exit(
    profile: CandidateProfile,
    inventory: SkillsInventory,
    queue: ApplicationQueue,
    storage: Storage,
) -> None:
    storage.save(profile, inventory, queue)


def cmd_show_profile(args: argparse.Namespace) -> None:
    profile, inventory, queue, _ = load_or_init(Path(args.storage))
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
    profile, inventory, queue, storage = load_or_init(Path(args.storage))
    profile.job_preferences.update(
        min_salary=args.min_salary,
        locations=args.locations,
        focus_domains=args.domains,
        felon_friendly_only=args.felon_friendly,
    )
    if args.name:
        profile.name = args.name
    if args.email:
        profile.email = args.email
    if args.phone:
        profile.phone = args.phone
    save_and_exit(profile, inventory, queue, storage)
    print("Preferences updated.")


def cmd_add_skill(args: argparse.Namespace) -> None:
    profile, inventory, queue, storage = load_or_init(Path(args.storage))
    profile.add_skill(args.skill)
    inventory.observe_skills([args.skill])
    save_and_exit(profile, inventory, queue, storage)
    print(f"Skill '{args.skill}' added.")


def cmd_plan(args: argparse.Namespace) -> None:
    profile, inventory, queue, _ = load_or_init(Path(args.storage))
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
    profile, inventory, queue, storage = load_or_init(Path(args.storage))

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
    save_and_exit(profile, inventory, queue, storage)

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
    profile, inventory, queue, storage = load_or_init(Path(args.storage))

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

    resume_path.write_text(generate_resume(profile, posting, assessment), encoding="utf-8")
    cover_path.write_text(generate_cover_letter(profile, posting, assessment), encoding="utf-8")

    print(f"Resume saved to {resume_path}")
    print(f"Cover letter saved to {cover_path}")

    if args.enqueue:
        if not posting.apply_url:
            raise SystemExit("--apply-url is required when enqueueing an application")
        apply_at = parse_iso_datetime(args.apply_at) if args.apply_at else datetime.now()
        task = QueuedApplication(
            posting=posting,
            apply_at=apply_at,
            resume_path=str(resume_path),
            cover_letter_path=str(cover_path),
        )
        queue.add(task)
        print(f"Queued application {task.job_id} for {apply_at.isoformat(timespec='minutes')}")

    save_and_exit(profile, inventory, queue, storage)


def _load_description(args: argparse.Namespace) -> str:
    if args.description is None and args.description_file is None:
        raise SystemExit("Provide either --description or --description-file")
    return args.description or Path(args.description_file).read_text(encoding="utf-8")


def cmd_apply(args: argparse.Namespace) -> None:
    profile, inventory, queue, storage = load_or_init(Path(args.storage))
    automation = DirectApplyAutomation(headless=not args.no_headless, timeout=args.timeout)
    task: Optional[QueuedApplication] = None
    now = datetime.now()
    resume_path: Optional[Path] = None
    cover_path: Optional[Path] = None

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
            resume_path.write_text(generate_resume(profile, posting, assessment), encoding="utf-8")
            cover_path.write_text(generate_cover_letter(profile, posting, assessment), encoding="utf-8")
            print(f"Generated resume at {resume_path}")
            print(f"Generated cover letter at {cover_path}")

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
        save_and_exit(profile, inventory, queue, storage)


def cmd_worker(args: argparse.Namespace) -> None:
    documents_dir = Path(args.documents_dir)
    documents_dir.mkdir(parents=True, exist_ok=True)
    worker = JobAutomationWorker(
        Path(args.storage),
        documents_dir=documents_dir,
        headless=not args.no_headless,
        timeout=args.timeout,
        retry_delay=timedelta(minutes=args.retry_minutes),
    )

    if args.loop:
        worker.run_forever(interval=args.interval, dry_run=args.dry_run)
    else:
        worker.run_once(dry_run=args.dry_run)


def cmd_search(args: argparse.Namespace) -> None:
    profile, _, _, _ = load_or_init(Path(args.storage))

    location = args.location
    if not location:
        preferences = profile.job_preferences.locations
        if preferences:
            location = preferences[0]
    if not location:
        raise SystemExit("Provide --location or save a default location via prefs.")

    results = []

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

    if not results:
        print("No search results found.")
        return

    print(f"Top {len(results)} results for '{args.title}' near {location}:")
    for idx, result in enumerate(results, start=1):
        badge = "DIRECT" if result.is_company_site else "AGGREGATOR"
        print(f"{idx:>2}. [{badge}] {result.title}")
        print(f"    Source: {result.source}")
        print(f"    Link:   {result.link}")
        if args.verbose and result.snippet:
            print(f"    Snippet: {result.snippet}")


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
    documents.add_argument("--output-dir", default="generated_documents")
    documents.add_argument("--enqueue", action="store_true")
    documents.add_argument(
        "--apply-at",
        help="ISO 8601 timestamp for when the worker should submit the queued application",
    )
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
    apply_cmd.add_argument("--resume")
    apply_cmd.add_argument("--cover-letter")
    apply_cmd.add_argument("--auto-documents", action="store_true")
    apply_cmd.add_argument("--output-dir", default="generated_documents")
    apply_cmd.add_argument("--no-headless", action="store_true")
    apply_cmd.add_argument("--timeout", type=int, default=90)
    apply_cmd.add_argument("--dry-run", action="store_true")
    apply_cmd.add_argument("--retry-minutes", type=int, default=60)
    apply_cmd.set_defaults(func=cmd_apply)

    search = subparsers.add_parser(
        "search",
        help="Search Google (via SerpAPI) for jobs and highlight direct-apply links",
    )
    search.add_argument("--title", required=True, help="Job title or keywords to search for")
    search.add_argument("--location", help="Location to focus on; defaults to saved prefs")
    search.add_argument("--remote", action="store_true", help="Hint the search to favour remote roles")
    search.add_argument("--limit", type=int, default=10, help="Maximum number of search results to show")
    search.add_argument("--extra", nargs="*", help="Additional search terms to append")
    search.add_argument("--direct-only", action="store_true", help="Only show company-owned domains")
    search.add_argument("--serpapi-key", help="Override the SERPAPI_KEY environment variable")
    search.add_argument(
        "--engine",
        default="google",
        help="SerpAPI engine to use (defaults to 'google')",
    )
    search.add_argument(
        "--sample-response",
        help="Load a saved SerpAPI response JSON file instead of making a live request",
    )
    search.add_argument("--verbose", action="store_true", help="Print search result snippets")
    search.set_defaults(func=cmd_search)

    worker = subparsers.add_parser("worker", help="Process queued applications on a schedule")
    worker.add_argument("--documents-dir", default="generated_documents")
    worker.add_argument("--loop", action="store_true", help="Keep running instead of exiting after one pass")
    worker.add_argument("--interval", type=int, default=300, help="Seconds to wait between polling runs")
    worker.add_argument("--dry-run", action="store_true", help="Skip browser automation and only refresh documents")
    worker.add_argument("--no-headless", action="store_true", help="Run the browser with a visible window")
    worker.add_argument("--timeout", type=int, default=90, help="Playwright navigation timeout in seconds")
    worker.add_argument("--retry-minutes", type=int, default=45, help="Minutes to wait before retrying failures")
    worker.set_defaults(func=cmd_worker)

    return parser


def main(argv: List[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
