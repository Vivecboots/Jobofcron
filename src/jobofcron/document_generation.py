"""Helpers for generating tailored resume and cover letter drafts."""
from __future__ import annotations

import os
from datetime import datetime
from string import Template
from typing import Dict, Iterable, List, Optional

from .job_matching import JobPosting, MatchAssessment
from .profile import CandidateProfile, Experience


class DocumentGenerationDependencyError(RuntimeError):
    """Raised when optional AI dependencies are missing or misconfigured."""


class DocumentGenerationError(RuntimeError):
    """Raised when an AI provider fails to generate content."""


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


def _build_resume_context(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
) -> Dict[str, str]:
    remaining_skills = [
        skill
        for skill in profile.skills
        if skill.lower() not in {match.lower() for match in assessment.matched_skills}
    ]

    context: Dict[str, str] = {
        "name": profile.name,
        "email": profile.email,
        "phone": profile.phone or "",
        "summary": profile.summary or "",
        "target_title": posting.title,
        "target_company": posting.company,
        "contact_block": "\n".join(_format_contact_block(profile)),
        "matched_skills": "\n".join(f"- {skill}" for skill in assessment.matched_skills) or "",
        "additional_skills": "\n".join(f"- {skill}" for skill in remaining_skills) or "",
        "certifications": "\n".join(f"- {cert}" for cert in profile.certifications) or "",
        "experience": "\n".join(_format_experience(profile.experiences)) or "",
        "missing_skills": "\n".join(f"- {skill}" for skill in assessment.missing_skills) or "",
        "notes": "\n".join(f"- {topic}: {note}" for topic, note in profile.additional_notes.items())
        if profile.additional_notes
        else "",
    }
    return context


def _resume_traditional(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
) -> str:
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


def _resume_modern(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
) -> str:
    lines: List[str] = []
    lines.append(posting.title.upper())
    lines.append(profile.name.title())
    lines.append(" | ".join(bit for bit in [profile.email, profile.phone] if bit))
    if profile.summary:
        lines.extend(["", profile.summary.strip()])

    if assessment.matched_skills:
        lines.extend(["", "Impact Highlights"])
        for skill in assessment.matched_skills:
            lines.append(f"• Delivered measurable outcomes leveraging {skill}.")

    if profile.experiences:
        lines.extend(["", "Experience"])
        for exp in sorted(profile.experiences, key=lambda e: e.start_date, reverse=True):
            start = exp.start_date.strftime("%Y")
            end = exp.end_date.strftime("%Y") if exp.end_date else "Present"
            lines.append(f"{exp.role} — {exp.company} ({start}–{end})")
            for achievement in exp.achievements or []:
                lines.append(f"  · {achievement}")

    if profile.skills:
        lines.extend(["", "Core Skills", ", ".join(sorted(profile.skills))])

    if profile.certifications:
        lines.extend(["", "Certifications", ", ".join(profile.certifications)])

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def _resume_minimal(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
) -> str:
    lines: List[str] = []
    lines.append(profile.name)
    lines.append(posting.title)
    lines.append(profile.email)
    if profile.phone:
        lines.append(profile.phone)

    lines.append("")
    lines.append("Summary")
    summary = profile.summary or "Motivated professional ready to contribute immediately."
    lines.append(summary)

    if assessment.matched_skills:
        lines.append("")
        lines.append("Top Skills")
        lines.append(", ".join(assessment.matched_skills))

    experience_lines = _format_experience(profile.experiences)
    if experience_lines:
        lines.append("")
        lines.append("Experience")
        lines.extend(experience_lines[:8])

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


RESUME_TEMPLATES = {
    "traditional": _resume_traditional,
    "modern": _resume_modern,
    "minimal": _resume_minimal,
}


def generate_resume(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
    *,
    style: str = "traditional",
    custom_template: Optional[str] = None,
) -> str:
    """Create a resume draft using one of the built-in styles or a custom template."""

    template_key = style.lower()
    if template_key == "custom":
        if not custom_template:
            raise ValueError("Provide custom_template text when using the custom resume style.")
        context = _build_resume_context(profile, posting, assessment)
        rendered = Template(custom_template).safe_substitute(context)
        return rendered.strip() + "\n"

    builder = RESUME_TEMPLATES.get(template_key, RESUME_TEMPLATES["traditional"])
    return builder(profile, posting, assessment)


def _cover_letter_context(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
) -> Dict[str, str]:
    return {
        "name": profile.name,
        "email": profile.email,
        "phone": profile.phone or "",
        "company": posting.company,
        "title": posting.title,
        "today": datetime.now().strftime("%B %d, %Y"),
        "matched_skills": "\n".join(f"- {skill}" for skill in assessment.matched_skills) or "",
        "focus_points": "\n".join(
            f"- {update}" for update in assessment.recommended_profile_updates[:5]
        )
        if assessment.recommended_profile_updates
        else "",
        "missing_skills": "\n".join(f"- {skill}" for skill in assessment.missing_skills) or "",
    }


def _cover_letter_traditional(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
) -> str:
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
        lines.append(
            "I appreciate the transparency around compensation and would value a conversation to confirm mutual fit on salary expectations."
        )
        lines.append("")

    if assessment.location_notes:
        lines.append("Location logistics are workable on my end, and I am prepared for remote collaboration when needed.")
        lines.append("")

    closing = (
        "Thank you for your consideration. I welcome the chance to discuss how my experience can support your team and am happy to provide any additional information."
    )
    lines.extend([closing, "", "Sincerely,", profile.name])

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def _cover_letter_modern(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
) -> str:
    lines: List[str] = []
    lines.append(datetime.now().strftime("%d %B %Y"))
    lines.append("")
    lines.append(f"{posting.company} Hiring Team")
    lines.append("")
    lines.append(f"Hello {posting.company} team,")
    lines.append("")
    lines.append(
        f"Your {posting.title} opening stood out because it calls for professionals who build relationships and deliver measurable impact."
    )

    if assessment.matched_skills:
        lines.append("")
        lines.append("Highlights")
        for skill in assessment.matched_skills[:4]:
            lines.append(f"- Created wins leveraging {skill} across cross-functional teams.")

    if assessment.recommended_profile_updates:
        lines.append("")
        lines.append("What I'll bring next")
        for update in assessment.recommended_profile_updates[:3]:
            lines.append(f"- {update}")

    lines.append("")
    lines.append(
        "I'd welcome 20 minutes to explore how I can help the team hit its next set of goals."
    )
    lines.append("")
    lines.append("Best regards,")
    lines.append(profile.name)

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def _cover_letter_minimal(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
) -> str:
    lines: List[str] = []
    lines.append(datetime.now().strftime("%Y-%m-%d"))
    lines.append("")
    lines.append(f"To {posting.company},")
    lines.append("")
    lines.append(f"I am interested in the {posting.title} role.")
    if assessment.matched_skills:
        lines.append(
            "My background covers " + ", ".join(assessment.matched_skills[:5]) + "."
        )
    lines.append(
        "Let's connect to discuss how I can contribute immediately and learn where to focus first."
    )
    lines.append("")
    lines.append("Thank you,")
    lines.append(profile.name)

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


COVER_LETTER_TEMPLATES = {
    "traditional": _cover_letter_traditional,
    "modern": _cover_letter_modern,
    "minimal": _cover_letter_minimal,
}


def generate_cover_letter(
    profile: CandidateProfile,
    posting: JobPosting,
    assessment: MatchAssessment,
    *,
    style: str = "traditional",
    custom_template: Optional[str] = None,
) -> str:
    """Create a cover letter draft using built-in styles or user-provided text."""

    template_key = style.lower()
    if template_key == "custom":
        if not custom_template:
            raise ValueError("Provide custom_template text when using the custom cover letter style.")
        context = _cover_letter_context(profile, posting, assessment)
        rendered = Template(custom_template).safe_substitute(context)
        return rendered.strip() + "\n"

    builder = COVER_LETTER_TEMPLATES.get(template_key, COVER_LETTER_TEMPLATES["traditional"])
    return builder(profile, posting, assessment)


def available_resume_templates() -> List[str]:
    """Return the identifiers for bundled resume templates."""

    return sorted(RESUME_TEMPLATES.keys())


def available_cover_letter_templates() -> List[str]:
    """Return the identifiers for bundled cover letter templates."""

    return sorted(COVER_LETTER_TEMPLATES.keys())


class AIDocumentGenerator:
    """Use a chat-completion provider to craft tailored documents."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        system_prompt: Optional[str] = None,
    ) -> None:
        self._explicit_api_key = api_key
        self.model = model
        self.temperature = temperature
        self.system_prompt = system_prompt or (
            "You are an expert career coach who writes concise, accomplishment-focused job application materials. "
            "Always return valid Markdown and emphasise the candidate's demonstrable impact."
        )

    def _resolve_api_key(self) -> str:
        api_key = self._explicit_api_key or os.getenv("OPENAI_API_KEY") or os.getenv("JOBOFCRON_OPENAI_KEY")
        if not api_key:
            raise DocumentGenerationDependencyError(
                "Set OPENAI_API_KEY (or JOBOFCRON_OPENAI_KEY) or pass api_key to AIDocumentGenerator."
            )
        return api_key

    def _build_client(self):
        api_key = self._resolve_api_key()
        try:  # Preferred modern SDK path
            from openai import OpenAI  # type: ignore

            return OpenAI(api_key=api_key), True
        except ModuleNotFoundError:
            try:
                import openai  # type: ignore
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise DocumentGenerationDependencyError(
                    "Install the 'ai' optional dependency group (pip install jobofcron[ai])."
                ) from exc
            openai.api_key = api_key
            return openai, False

    def _profile_summary(self, profile: CandidateProfile) -> str:
        experiences = []
        for exp in profile.experiences:
            start = exp.start_date.strftime("%Y")
            end = exp.end_date.strftime("%Y") if exp.end_date else "Present"
            achievements = "; ".join(exp.achievements or [])
            experiences.append(
                f"- {exp.role} at {exp.company} ({start}-{end}): {achievements or 'Impact-driven responsibilities.'}"
            )
        notes = []
        if profile.additional_notes:
            for topic, note in profile.additional_notes.items():
                notes.append(f"- {topic}: {note}")
        return "\n".join(
            [
                f"Name: {profile.name}",
                f"Email: {profile.email}",
                f"Phone: {profile.phone or 'n/a'}",
                f"Summary: {profile.summary or 'n/a'}",
                f"Skills: {', '.join(profile.skills) or 'n/a'}",
                f"Certifications: {', '.join(profile.certifications) or 'n/a'}",
                "Experience:",
                *(experiences or ["- Not provided"]),
                "Notes:",
                *(notes or ["- None"]),
            ]
        )

    def _posting_summary(self, posting: JobPosting, assessment: MatchAssessment) -> str:
        return "\n".join(
            [
                f"Role: {posting.title}",
                f"Company: {posting.company}",
                f"Location: {posting.location or 'n/a'}",
                f"Salary: {posting.salary_text or 'n/a'}",
                f"Felon friendly: {posting.felon_friendly}",
                f"Apply URL: {posting.apply_url or 'n/a'}",
                "Description:",
                posting.description.strip() or "n/a",
                "Matched skills: " + ", ".join(assessment.matched_skills) if assessment.matched_skills else "Matched skills: n/a",
                "Missing skills: " + ", ".join(assessment.missing_skills) if assessment.missing_skills else "Missing skills: n/a",
                "Recommended focus: "
                + ", ".join(assessment.recommended_profile_updates)
                if assessment.recommended_profile_updates
                else "Recommended focus: n/a",
            ]
        )

    def _chat(self, prompt: str) -> str:
        client, is_modern = self._build_client()
        try:
            if is_modern:
                response = client.chat.completions.create(  # type: ignore[call-arg]
                    model=self.model,
                    temperature=self.temperature,
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                content = response.choices[0].message.content or ""
            else:  # Legacy SDK path
                response = client.ChatCompletion.create(  # type: ignore[attr-defined]
                    model=self.model,
                    temperature=self.temperature,
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                content = response["choices"][0]["message"]["content"]
        except Exception as exc:  # pragma: no cover - depends on network/service
            raise DocumentGenerationError(f"AI document generation failed: {exc}") from exc

        return content.strip()

    def generate_resume(
        self,
        profile: CandidateProfile,
        posting: JobPosting,
        assessment: MatchAssessment,
    ) -> str:
        prompt = (
            "Craft a targeted one-page resume in Markdown. Use concise bullet points and highlight quantifiable impact.\n\n"
            "Candidate details:\n"
            f"{self._profile_summary(profile)}\n\n"
            "Job posting details:\n"
            f"{self._posting_summary(posting, assessment)}"
        )
        content = self._chat(prompt)
        return content + ("\n" if not content.endswith("\n") else "")

    def generate_cover_letter(
        self,
        profile: CandidateProfile,
        posting: JobPosting,
        assessment: MatchAssessment,
    ) -> str:
        prompt = (
            "Write a persuasive cover letter in Markdown with greeting, two impact paragraphs, and a closing. "
            "Reference matched skills and address any development areas constructively.\n\n"
            "Candidate details:\n"
            f"{self._profile_summary(profile)}\n\n"
            "Job posting details:\n"
            f"{self._posting_summary(posting, assessment)}"
        )
        content = self._chat(prompt)
        return content + ("\n" if not content.endswith("\n") else "")
