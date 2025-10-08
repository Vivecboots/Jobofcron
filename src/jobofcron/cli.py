"""Lightweight command line interface for interacting with Jobofcron."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import List

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

    return parser


def main(argv: List[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
