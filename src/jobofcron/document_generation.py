"""Helpers for generating tailored resume and cover letter drafts."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List

from .job_matching import JobPosting, MatchAssessment
from .profile import CandidateProfile, Experience


def _format_contact_block(profile: CandidateProfile) -> List[str]:
    lines = [profile.name]
    contact_bits: List[str] = [profile.email]
    if profile.phone:
        contact_bits.append(profile.phone)
    lines.append(" | ".join(bit for bit in contact_bits if bit))
    if profile.summary:
        lines.append(profile.summary.strip())
    return lines


def _format_experience(experiences: Iterable[Experience]) -> List[str]:
    lines: List[str] = []
    sorted_experiences = sorted(experiences, key=lambda exp: exp.start_date, reverse=True)
    for exp in sorted_experiences:
        start = exp.start_date.strftime("%b %Y")
        end = exp.end_date.strftime("%b %Y") if exp.end_date else "Present"
        lines.append(f"{exp.role} — {exp.company} ({start} – {end})")
        for achievement in exp.achievements or []:
            lines.append(f"  • {achievement}")
    return lines


def generate_resume(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
) -> str:
    """Create a lightweight resume draft emphasising the matched skills."""

    lines: List[str] = []
    lines.extend(_format_contact_block(profile))
    lines.append("")

    lines.append(f"Target Role: {posting.title} at {posting.company}")
    lines.append("")

    if assessment.matched_skills:
        lines.append("Key Qualifications")
        for skill in assessment.matched_skills:
            lines.append(f"  • Demonstrated expertise in {skill}")
        lines.append("")

    remaining_skills = [
        skill
        for skill in profile.skills
        if skill.lower() not in {match.lower() for match in assessment.matched_skills}
    ]
    if remaining_skills:
        lines.append("Additional Skills")
        for skill in remaining_skills:
            lines.append(f"  • {skill}")
        lines.append("")

    if profile.certifications:
        lines.append("Certifications")
        for cert in profile.certifications:
            lines.append(f"  • {cert}")
        lines.append("")

    experience_lines = _format_experience(profile.experiences)
    if experience_lines:
        lines.append("Professional Experience")
        lines.extend(experience_lines)
        lines.append("")

    if assessment.missing_skills:
        lines.append("Development Targets")
        for skill in assessment.missing_skills:
            lines.append(f"  • Gather supporting stories for {skill} or pursue training")
        lines.append("")

    if profile.additional_notes:
        lines.append("Additional Notes")
        for topic, note in profile.additional_notes.items():
            lines.append(f"  • {topic}: {note}")
        lines.append("")

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def generate_cover_letter(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
) -> str:
    """Create a conversational cover letter referencing the match assessment."""

    today = datetime.now().strftime("%B %d, %Y")
    lines: List[str] = [today, "", posting.company, "", "Dear Hiring Manager,"]

    intro = (
        f"I am excited to apply for the {posting.title} role with {posting.company}. "
        "My background and focus areas align with the responsibilities highlighted in the description."
    )
    lines.extend(["", intro, ""])

    if assessment.matched_skills:
        lines.append("In my recent work I have:")
        for skill in assessment.matched_skills[:5]:
            lines.append(f"  • Delivered results that showcase {skill}.")
        lines.append("")

    if assessment.recommended_profile_updates:
        lines.append("I have also prepared supporting materials that emphasise:")
        for update in assessment.recommended_profile_updates[:5]:
            lines.append(f"  • {update}")
        lines.append("")

    if assessment.missing_skills:
        lines.append(
            "Where the posting calls for emerging skills, I am proactively filling those gaps through research, mentorship, and hands-on projects."
        )
        lines.append("")

    if assessment.salary_notes:
        lines.append("I appreciate the transparency around compensation and would value a conversation to confirm mutual fit on salary expectations.")
        lines.append("")

    if assessment.location_notes:
        lines.append("Location logistics are workable on my end, and I am prepared for remote collaboration when needed.")
        lines.append("")

    closing = (
        "Thank you for your consideration. I welcome the chance to discuss how my experience can support your team and am happy to provide any additional information."
    )
    lines.extend([closing, "", "Sincerely,", profile.name])

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"
