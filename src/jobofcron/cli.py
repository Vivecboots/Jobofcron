"""Lightweight command line interface for interacting with Jobofcron."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List

from .job_matching import JobPosting, analyse_job_fit
from .job_search import GoogleJobSearch
from .profile import CandidateProfile
from .scheduler import plan_schedule
from .skills_inventory import SkillsInventory
from .storage import Storage

DEFAULT_STORAGE = Path("jobofcron_data.json")


def load_or_init(storage_path: Path) -> tuple[CandidateProfile, SkillsInventory, Storage]:
    storage = Storage(storage_path)
    profile, inventory = storage.load()

    if profile is None:
        profile = CandidateProfile(name="Unknown", email="unknown@example.com")
    if inventory is None:
        inventory = SkillsInventory()
    return profile, inventory, storage


def save_and_exit(profile: CandidateProfile, inventory: SkillsInventory, storage: Storage) -> None:
    storage.save(profile, inventory)


def cmd_show_profile(args: argparse.Namespace) -> None:
    profile, inventory, _ = load_or_init(Path(args.storage))
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


def cmd_update_preferences(args: argparse.Namespace) -> None:
    profile, inventory, storage = load_or_init(Path(args.storage))
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
    save_and_exit(profile, inventory, storage)
    print("Preferences updated.")


def cmd_add_skill(args: argparse.Namespace) -> None:
    profile, inventory, storage = load_or_init(Path(args.storage))
    profile.add_skill(args.skill)
    inventory.observe_skills([args.skill])
    save_and_exit(profile, inventory, storage)
    print(f"Skill '{args.skill}' added.")


def cmd_plan(args: argparse.Namespace) -> None:
    profile, inventory, _ = load_or_init(Path(args.storage))
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
    profile, inventory, storage = load_or_init(Path(args.storage))

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
    )

    assessment = analyse_job_fit(profile, posting)
    inventory.observe_skills(assessment.required_skills)
    save_and_exit(profile, inventory, storage)

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


def cmd_search(args: argparse.Namespace) -> None:
    profile, _, _ = load_or_init(Path(args.storage))

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
    analyze.set_defaults(func=cmd_analyze)

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

    return parser


def main(argv: List[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
