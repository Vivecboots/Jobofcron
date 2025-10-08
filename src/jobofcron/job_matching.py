"""Utilities for evaluating how well a profile matches a job posting.

The matching logic is deliberately heuristic driven so it can run without
external dependencies. It focuses on surfacing the questions the automation
should ask the user before submitting an application as well as the resume or
cover letter updates that would strengthen the submission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable, List, Optional, Tuple

from .profile import CandidateProfile


# Phrases that usually introduce skill requirements within a description.
SKILL_HINT_PATTERNS = (
    r"experience with ([^.;\n]+)",
    r"experience in ([^.;\n]+)",
    r"proficiency in ([^.;\n]+)",
    r"proficient in ([^.;\n]+)",
    r"skilled in ([^.;\n]+)",
    r"knowledge of ([^.;\n]+)",
    r"familiar(?:ity)? with ([^.;\n]+)",
    r"background in ([^.;\n]+)",
    r"skills?: ([^\n]+)",
    r"requirements?: ([^\n]+)",
)


SPLIT_PATTERN = re.compile(r",|;|\band\b|\bor\b|\bsuch as\b|\bincluding\b|\bfor example\b", re.IGNORECASE)


@dataclass
class JobPosting:
    """Minimal representation of a job posting."""

    title: str
    company: str
    id: Optional[str] = None
    location: Optional[str] = None
    salary_text: Optional[str] = None
    description: str = ""
    tags: List[str] = field(default_factory=list)
    felon_friendly: Optional[bool] = None


@dataclass
class MatchAssessment:
    """Result of comparing a profile against a job posting."""

    required_skills: List[str]
    matched_skills: List[str]
    missing_skills: List[str]
    match_score: float
    recommended_questions: List[str] = field(default_factory=list)
    recommended_profile_updates: List[str] = field(default_factory=list)
    salary_notes: List[str] = field(default_factory=list)
    meets_salary: Optional[bool] = None
    location_notes: List[str] = field(default_factory=list)
    meets_location: Optional[bool] = None
    felon_friendly: Optional[bool] = None


def _normalise_skill_name(skill: str) -> str:
    cleaned = skill.strip().strip("-•·:")
    cleaned = re.sub(
        r"^(?:experience|experiences|background|knowledge|familiarity|familiar|proficiency|proficient|skilled)\s+"
        r"(?:in|with|of)?\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(?:is\s+preferred|preferred|is\s+required|required|a\s+plus|plus)\b.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _split_skills(phrase: str) -> Iterable[str]:
    phrase = phrase.replace("/", ",")
    phrase = re.sub(r"\(.*?\)", "", phrase)
    for part in SPLIT_PATTERN.split(phrase):
        token = _normalise_skill_name(part)
        if not token:
            continue
        yield token


def _extract_skills_from_description(description: str) -> List[str]:
    skills: List[str] = []
    seen = set()
    for pattern in SKILL_HINT_PATTERNS:
        for match in re.finditer(pattern, description, flags=re.IGNORECASE):
            for skill in _split_skills(match.group(1)):
                key = skill.lower()
                if key not in seen:
                    seen.add(key)
                    skills.append(skill)

    for line in description.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("-", "*", "•")):
            bullet = stripped.lstrip("-*• ")
            if any(keyword in bullet.lower() for keyword in ("experience", "knowledge", "skill", "familiar")):
                for skill in _split_skills(bullet):
                    key = skill.lower()
                    if key not in seen:
                        seen.add(key)
                        skills.append(skill)

    return skills


def extract_required_skills(posting: JobPosting) -> List[str]:
    """Return a deduplicated ordered list of skills mentioned in the posting."""

    description_skills = _extract_skills_from_description(posting.description)
    skills: List[str] = []
    seen = set()
    for skill in list(posting.tags) + description_skills:
        token = _normalise_skill_name(skill)
        if not token:
            continue
        key = token.lower()
        if key not in seen:
            seen.add(key)
            skills.append(token)
    return skills


def _parse_salary_numbers(text: str) -> Tuple[Optional[int], Optional[int]]:
    numbers: List[int] = []
    for match in re.finditer(r"\$?\s*(\d[\d,]*)(?:\s*([kK]))?", text):
        raw_number = match.group(1).replace(",", "")
        try:
            value = int(raw_number)
        except ValueError:
            continue
        if match.group(2):
            value *= 1000
        numbers.append(value)

    if not numbers:
        return None, None

    low = min(numbers)
    high = max(numbers)
    return low, high


def _infer_felon_friendly(description: str) -> Optional[bool]:
    text = description.lower()
    positive = any(keyword in text for keyword in ("felon friendly", "felony friendly", "second chance", "justice-involved"))
    negative = any(keyword in text for keyword in ("must pass background", "no felonies", "no felony", "clean record required"))
    if positive and not negative:
        return True
    if negative and not positive:
        return False
    return None


def analyse_job_fit(profile: CandidateProfile, posting: JobPosting) -> MatchAssessment:
    """Compare the profile with the job posting and surface actionable gaps."""

    required_skills = extract_required_skills(posting)
    profile_skills = {skill.lower(): skill for skill in profile.skills}

    matched: List[str] = []
    missing: List[str] = []
    for skill in required_skills:
        key = skill.lower()
        if key in profile_skills:
            matched.append(profile_skills[key])
        else:
            missing.append(skill)

    total = len(required_skills) or 1
    score = len(matched) / total

    questions: List[str] = []
    updates: List[str] = []
    for skill in missing:
        questions.append(f"Do you have experience with {skill}? Provide anecdotes to include in the tailored resume/cover letter.")
    for skill in matched:
        updates.append(f"Highlight recent wins that showcase {skill} in the customised documents.")

    salary_notes: List[str] = []
    meets_salary: Optional[bool] = None
    min_required = profile.job_preferences.min_salary
    salary_source = posting.salary_text or posting.description
    if min_required is not None:
        if salary_source:
            low, high = _parse_salary_numbers(salary_source)
            if low is None and high is None:
                salary_notes.append("Posting does not advertise compensation; confirm it meets your minimum.")
            else:
                meets_salary = (high or low or 0) >= min_required
                if not meets_salary:
                    salary_notes.append(
                        f"Minimum salary preference ${min_required:,} may exceed the posting range ({low:,} - {high:,} if known)."
                    )
        else:
            salary_notes.append("No salary details were provided; verify against your minimum expectation.")
    elif posting.salary_text:
        salary_notes.append("Profile lacks a minimum salary preference; consider setting one based on this posting.")

    location_notes: List[str] = []
    meets_location: Optional[bool] = None
    preferred_locations = [loc.strip().casefold() for loc in profile.job_preferences.locations if loc.strip()]
    posting_location = posting.location.strip() if posting.location else None
    if preferred_locations:
        if posting_location:
            location_key = posting_location.casefold()
            matches = any(
                pref in location_key or location_key in pref or (pref == "remote" and "remote" in location_key)
                for pref in preferred_locations
            )
            meets_location = matches
            if not matches:
                location_notes.append(
                    "Posting location does not match saved preferences; decide if you want to expand your target areas."
                )
        else:
            location_notes.append("Posting omitted location details; confirm they align with your preferences.")
    elif posting_location:
        location_notes.append("Profile has no saved locations; record preferred markets if this posting is appealing.")

    felon_friendly = posting.felon_friendly
    if felon_friendly is None:
        felon_friendly = _infer_felon_friendly(posting.description)
    if profile.job_preferences.felon_friendly_only and felon_friendly is not True:
        questions.append(
            "Listing may not clearly state it is felon friendly; research or contact the employer before applying."
        )

    return MatchAssessment(
        required_skills=required_skills,
        matched_skills=matched,
        missing_skills=missing,
        match_score=score,
        recommended_questions=questions,
        recommended_profile_updates=updates,
        salary_notes=salary_notes,
        meets_salary=meets_salary,
        location_notes=location_notes,
        meets_location=meets_location,
        felon_friendly=felon_friendly,
    )

