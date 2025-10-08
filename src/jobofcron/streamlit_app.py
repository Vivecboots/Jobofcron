"""Streamlit interface for the Jobofcron automation toolkit.

The UI focuses on helping users manage their profile, discover roles via the
Google search helper, analyse job descriptions, review skill trends, and plan
their application queue. The goal is to provide a human-in-the-loop cockpit
that sits on top of the existing CLI building blocks.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Iterable, List, Optional

import streamlit as st

PACKAGE_DIR = Path(__file__).resolve().parent

if __package__ in {None, ""}:
    sys.path.append(str(PACKAGE_DIR.parent))
    from jobofcron.application_queue import ApplicationQueue, QueuedApplication  # type: ignore[attr-defined]
    from jobofcron.document_generation import (  # type: ignore[attr-defined]
        AIDocumentGenerator,
        DocumentGenerationDependencyError,
        DocumentGenerationError,
        available_cover_letter_templates,
        available_resume_templates,
        generate_cover_letter,
        generate_resume,
    )
    from jobofcron.job_matching import JobPosting, analyse_job_fit  # type: ignore[attr-defined]
    from jobofcron.job_search import CraigslistSearch, GoogleJobSearch, SearchResult  # type: ignore[attr-defined]
    from jobofcron.profile import CandidateProfile  # type: ignore[attr-defined]
    from jobofcron.skills_inventory import SkillsInventory  # type: ignore[attr-defined]
    from jobofcron.storage import Storage  # type: ignore[attr-defined]
else:
    from .application_queue import ApplicationQueue, QueuedApplication
    from .document_generation import (
        AIDocumentGenerator,
        DocumentGenerationDependencyError,
        DocumentGenerationError,
        available_cover_letter_templates,
        available_resume_templates,
        generate_cover_letter,
        generate_resume,
    )
    from .job_matching import JobPosting, analyse_job_fit
    from .job_search import CraigslistSearch, GoogleJobSearch, SearchResult
    from .profile import CandidateProfile
    from .skills_inventory import SkillsInventory
    from .storage import Storage

DEFAULT_STORAGE = Path(os.getenv("JOBOFCRON_STORAGE", "jobofcron_data.json"))

DEFAULT_CUSTOM_RESUME_TEMPLATE = """$contact_block

Target Role: $target_title at $target_company

Key Highlights
$matched_skills

Professional Experience
$experience

Additional Skills
$additional_skills
"""

DEFAULT_CUSTOM_COVER_TEMPLATE = """$today

$company Hiring Team,

I am excited to apply for the $title role and share how my background aligns with your needs.

Highlights
$matched_skills

Focus Areas
$focus_points

Thank you for your consideration.

Sincerely,
$name
"""


def _slugify(*parts: str) -> str:
    token = "-".join(part.strip().lower().replace(" ", "-") for part in parts if part)
    cleaned = [ch for ch in token if ch.isalnum() or ch in {"-", "_"}]
    return "".join(cleaned) or "document"


def _load_state(path: Path) -> tuple[CandidateProfile, SkillsInventory, ApplicationQueue, Storage]:
    storage = Storage(path)
    profile, inventory, queue = storage.load()

    if profile is None:
        profile = CandidateProfile(name="Unknown", email="unknown@example.com")
    if inventory is None:
        inventory = SkillsInventory()
    if queue is None:
        queue = ApplicationQueue()

    return profile, inventory, queue, storage


def _initialise_session_state() -> None:
    if "storage_path" not in st.session_state:
        st.session_state.storage_path = str(DEFAULT_STORAGE)
    if "loaded_storage_path" not in st.session_state:
        profile, inventory, queue, storage = _load_state(Path(st.session_state.storage_path))
        st.session_state.profile = profile
        st.session_state.inventory = inventory
        st.session_state.queue = queue
        st.session_state.storage = storage
        st.session_state.loaded_storage_path = st.session_state.storage_path
    if "search_results" not in st.session_state:
        st.session_state.search_results = []
    if "search_selected" not in st.session_state:
        st.session_state.search_selected = []
    if "search_min_match" not in st.session_state:
        st.session_state.search_min_match = 0
    if "custom_resume_template" not in st.session_state:
        st.session_state.custom_resume_template = DEFAULT_CUSTOM_RESUME_TEMPLATE
    if "custom_cover_template" not in st.session_state:
        st.session_state.custom_cover_template = DEFAULT_CUSTOM_COVER_TEMPLATE
    if "resume_template_choice" not in st.session_state:
        st.session_state.resume_template_choice = "traditional"
    if "cover_template_choice" not in st.session_state:
        st.session_state.cover_template_choice = "traditional"


def _reload_state_if_needed(path_text: str) -> None:
    if path_text != st.session_state.get("loaded_storage_path"):
        profile, inventory, queue, storage = _load_state(Path(path_text))
        st.session_state.profile = profile
        st.session_state.inventory = inventory
        st.session_state.queue = queue
        st.session_state.storage = storage
        st.session_state.loaded_storage_path = path_text


def _save_state() -> None:
    storage: Storage = st.session_state.storage
    storage.save(st.session_state.profile, st.session_state.inventory, st.session_state.queue)


def _export_results_to_csv(results: Iterable[SearchResult]) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["title", "link", "snippet", "source", "is_company_site", "match_score", "contact_email"])
    for result in results:
        score = f"{result.match_score * 100:.0f}%" if result.match_score is not None else ""
        writer.writerow(
            [
                result.title,
                result.link,
                result.snippet,
                result.source,
                "yes" if result.is_company_site else "no",
                score,
                result.contact_email or "",
            ]
        )
    return buffer.getvalue().encode("utf-8")


def _score_search_results(profile: CandidateProfile, results: List[SearchResult]) -> List[SearchResult]:
    for result in results:
        description = result.description or result.snippet or ""
        posting = JobPosting(
            title=result.title,
            company=result.source or "Unknown",
            description=description,
            apply_url=result.link,
            contact_email=result.contact_email,
        )
        assessment = analyse_job_fit(profile, posting)
        result.match_score = assessment.match_score
        if not result.description:
            result.description = description
    return results


def _queue_search_result(
    result: SearchResult,
    schedule_time: datetime,
    *,
    resume_template: str,
    cover_template: str,
    custom_resume_template: Optional[str] = None,
    custom_cover_template: Optional[str] = None,
) -> QueuedApplication:
    posting = JobPosting(
        title=result.title,
        company=result.source or "Unknown",
        description=result.description or result.snippet or "",
        apply_url=result.link,
        contact_email=result.contact_email,
    )
    queued = QueuedApplication(
        posting=posting,
        apply_at=schedule_time,
        resume_template=resume_template,
        cover_letter_template=cover_template,
        custom_resume_template=custom_resume_template,
        custom_cover_letter_template=custom_cover_template,
    )
    st.session_state.queue.add(queued)
    _save_state()
    return queued


def _template_label(name: str) -> str:
    return name.replace("_", " ").title()


def _render_profile_tab() -> None:
    profile: CandidateProfile = st.session_state.profile

    st.subheader("Contact & Preferences")
    with st.form("profile_form", clear_on_submit=False):
        name = st.text_input("Name", value=profile.name)
        email = st.text_input("Email", value=profile.email)
        phone = st.text_input("Phone", value=profile.phone or "")
        summary = st.text_area("Professional summary", value=profile.summary or "", height=120)

        prefs = profile.job_preferences
        min_salary = st.text_input(
            "Minimum salary (USD)",
            value=str(prefs.min_salary or ""),
            help="Leave blank if you are flexible. Use annual salary in USD.",
        )
        locations_text = st.text_area(
            "Preferred locations",
            value="\n".join(prefs.locations),
            help="Enter one location per line. Include 'Remote' if applicable.",
        )
        domains_text = st.text_area(
            "Focus domains",
            value="\n".join(prefs.focus_domains),
            help="Industries or domains to prioritise during searches.",
        )
        felon_friendly = st.checkbox(
            "Require felon friendly roles",
            value=prefs.felon_friendly_only,
            help="When enabled, highlight postings that explicitly welcome justice-involved candidates.",
        )

        submitted = st.form_submit_button("Save profile")
        if submitted:
            profile.name = name.strip() or "Unknown"
            profile.email = email.strip() or "unknown@example.com"
            profile.phone = phone.strip() or None
            profile.summary = summary.strip() or None

            if min_salary.strip():
                try:
                    prefs.min_salary = int(min_salary.replace(",", "").strip())
                except ValueError:
                    st.error("Minimum salary must be a whole number.")
                    return
            else:
                prefs.min_salary = None

            prefs.locations = [loc.strip() for loc in locations_text.splitlines() if loc.strip()]
            prefs.focus_domains = [domain.strip() for domain in domains_text.splitlines() if domain.strip()]
            prefs.felon_friendly_only = felon_friendly

            st.session_state.profile = profile
            _save_state()
            st.success("Profile updated.")

    st.markdown("---")
    st.subheader("Skills")
    skill_input = st.text_input("Add a skill", key="add_skill_input")
    if st.button("Add skill", key="add_skill_button"):
        if skill_input.strip():
            profile.add_skill(skill_input.strip())
            st.session_state.inventory.observe_skills([skill_input.strip()])
            _save_state()
            st.success(f"Added skill '{skill_input.strip()}'.")
            st.session_state["add_skill_input"] = ""
        else:
            st.warning("Enter a skill name before adding.")

    if profile.skills:
        st.write(sorted(profile.skills))
    else:
        st.info("No skills recorded yet. Use the field above to add them.")


def _render_dashboard_tab() -> None:
    profile: CandidateProfile = st.session_state.profile
    inventory: SkillsInventory = st.session_state.inventory
    queue: ApplicationQueue = st.session_state.queue

    st.subheader(f"Welcome back, {profile.name.split(' ')[0] if profile.name else 'job seeker'}")

    pending = queue.pending()
    outcomes = {}
    for application in queue.items:
        if application.outcome:
            outcomes[application.outcome] = outcomes.get(application.outcome, 0) + 1

    cols = st.columns(3)
    cols[0].metric("Pending applications", len(pending))
    cols[1].metric("Total queued", len(queue.items))
    cols[2].metric("Skills tracked", len(inventory.sorted_by_opportunity()))

    if pending:
        upcoming = sorted(pending, key=lambda app: app.apply_at)[:5]
        st.markdown("### Upcoming applications")
        st.table(
            [
                {
                    "Job": f"{app.posting.title} @ {app.posting.company}",
                    "Apply at": app.apply_at.isoformat(timespec="minutes"),
                }
                for app in upcoming
            ]
        )
    else:
        st.info("No pending applications scheduled. Use the search or documents tab to queue new opportunities.")

    if outcomes:
        st.markdown("### Outcomes so far")
        st.table(
            [
                {"Outcome": outcome.title(), "Count": count}
                for outcome, count in sorted(outcomes.items())
            ]
        )
    else:
        st.info("Log interview or offer outcomes from the queue tab to start building performance insights.")

    top_skills = inventory.sorted_by_opportunity()[:5]
    if top_skills:
        st.markdown("### High-impact skills")
        st.table(
            [
                {
                    "Skill": record.name,
                    "Seen": record.occurrences,
                    "Interviews": record.interviews,
                    "Offers": record.offers,
                }
                for record in top_skills
            ]
        )


def _run_search(
    *,
    provider: str,
    title: str,
    location: str,
    limit: int,
    remote: bool,
    direct_only: bool,
    extra_terms: Iterable[str],
    serpapi_key: Optional[str],
    sample_payload: Optional[dict],
    craigslist_site: Optional[str],
) -> List[SearchResult]:
    if provider == "google":
        if sample_payload is not None:
            results = GoogleJobSearch.parse_results(sample_payload)
        else:
            if not serpapi_key:
                raise ValueError("Provide a SerpAPI key or sample response for Google searches.")
            searcher = GoogleJobSearch(serpapi_key)
            results = searcher.search_jobs(
                title=title,
                location=location,
                max_results=limit,
                remote=remote,
                extra_terms=[term for term in extra_terms if term],
            )
        if direct_only:
            results = GoogleJobSearch.filter_direct_apply(results)
        return results[:limit]

    searcher = CraigslistSearch(location=location, site_hint=craigslist_site)
    return searcher.search_jobs(
        title=title,
        max_results=limit,
        remote=remote,
        extra_terms=[term for term in extra_terms if term],
    )


def _render_search_tab() -> None:
    profile: CandidateProfile = st.session_state.profile

    with st.form("search_form"):
        title = st.text_input("Job title or keywords", value="")
        location = st.text_input(
            "Location",
            value=profile.job_preferences.locations[0] if profile.job_preferences.locations else "",
        )
        limit = st.slider("Result limit", min_value=1, max_value=20, value=10)
        remote = st.checkbox("Prefer remote roles", value="Remote" in profile.job_preferences.locations)
        provider_label = st.selectbox("Provider", ["Google (SerpAPI)", "Craigslist"], index=0)
        provider = "google" if provider_label.startswith("Google") else "craigslist"
        direct_only = st.checkbox(
            "Company sites only",
            value=True,
            disabled=provider != "google",
            help="Craigslist results already point directly to employers.",
        )
        extra_terms_text = st.text_input(
            "Extra search terms",
            value=" ".join(profile.job_preferences.focus_domains),
            help="Optional additional keywords (e.g. industry, company).",
        )
        serpapi_key = ""
        sample_response: Optional[dict] = None
        craigslist_site = None
        uploaded_file = None
        if provider == "google":
            serpapi_key = st.text_input(
                "SerpAPI key",
                value=os.getenv("SERPAPI_KEY", ""),
                type="password",
                help="Provide an API key for live Google searches or upload a saved response below.",
            )
            uploaded_file = st.file_uploader("Sample SerpAPI response (JSON)", type="json")
        else:
            craigslist_site = st.text_input(
                "Craigslist site", value=location.split(",")[0].lower() if location else "", help="e.g. 'austin'"
            )

        submitted = st.form_submit_button("Search")

    if submitted:
        if not title.strip():
            st.error("Enter a job title or keyword to search.")
            return
        if not location.strip() and not remote:
            st.warning("Provide a location or enable remote roles for best results.")

        if provider == "google":
            if uploaded_file is not None:
                try:
                    sample_response = json.load(uploaded_file)
                except json.JSONDecodeError as exc:  # pragma: no cover - user input
                    st.error(f"Could not parse uploaded JSON: {exc}")
                    return
            elif not serpapi_key.strip():
                st.error("Provide either a SerpAPI key or a sample response.")
                return

        try:
            results = _run_search(
                provider=provider,
                title=title.strip(),
                location=location.strip(),
                limit=limit,
                remote=remote,
                direct_only=direct_only,
                extra_terms=extra_terms_text.split(),
                serpapi_key=serpapi_key.strip() or None,
                sample_payload=sample_response,
                craigslist_site=craigslist_site,
            )
        except Exception as exc:  # pragma: no cover - network errors
            st.error(f"Search failed: {exc}")
            return

        st.session_state.search_results = results
        st.session_state.search_provider = provider
        if results:
            st.success(f"Found {len(results)} results.")
        else:
            st.info("No results matched the filters. Try broadening your query.")

    results = st.session_state.get("search_results", [])
    if results:
        scored_results = _score_search_results(profile, list(results))
        st.session_state.search_results = scored_results

        min_match = st.slider(
            "Minimum match score",
            min_value=0,
            max_value=100,
            value=int(st.session_state.search_min_match),
        )
        st.session_state.search_min_match = min_match

        filtered_results = [
            result for result in scored_results if int(round((result.match_score or 0) * 100)) >= min_match
        ]

        st.caption(f"Showing {len(filtered_results)} of {len(scored_results)} results above the match threshold.")

        csv_bytes = _export_results_to_csv(filtered_results)
        st.download_button(
            "Export results to CSV",
            data=csv_bytes,
            file_name="jobofcron_search_results.csv",
            mime="text/csv",
        )

        json_payload = []
        for result in filtered_results:
            json_payload.append(
                {
                    "title": result.title,
                    "link": result.link,
                    "snippet": result.snippet,
                    "description": result.description,
                    "source": result.source,
                    "is_company_site": result.is_company_site,
                    "match_score": result.match_score,
                    "contact_email": result.contact_email,
                }
            )
        st.download_button(
            "Export results to JSON",
            data=json.dumps(json_payload, indent=2).encode("utf-8"),
            file_name="jobofcron_search_results.json",
            mime="application/json",
        )

        resume_options = available_resume_templates()
        if "custom" not in resume_options:
            resume_options.append("custom")
        resume_options = sorted(resume_options, key=lambda name: {"traditional": 0, "modern": 1, "minimal": 2, "custom": 3}.get(name, 99))
        cover_options = available_cover_letter_templates()
        if "custom" not in cover_options:
            cover_options.append("custom")
        cover_options = sorted(cover_options, key=lambda name: {"traditional": 0, "modern": 1, "minimal": 2, "custom": 3}.get(name, 99))

        with st.expander("Batch queue options", expanded=False):
            start_time = st.datetime_input(
                "Start scheduling from",
                value=datetime.now().replace(second=0, microsecond=0),
                key="batch_start_time",
            )
            interval_minutes = st.number_input(
                "Minutes between applications",
                min_value=1,
                max_value=180,
                value=15,
                step=1,
            )
            resume_choice = st.selectbox(
                "Resume template",
                resume_options,
                index=resume_options.index(st.session_state.resume_template_choice)
                if st.session_state.resume_template_choice in resume_options
                else 0,
                format_func=_template_label,
            )
            st.session_state.resume_template_choice = resume_choice
            custom_resume_text = None
            if resume_choice == "custom":
                custom_resume_text = st.text_area(
                    "Custom resume template",
                    value=st.session_state.custom_resume_template,
                    height=220,
                    help="Use $placeholders such as $name, $matched_skills, $experience, $additional_skills.",
                )
                st.session_state.custom_resume_template = custom_resume_text

            cover_choice = st.selectbox(
                "Cover letter template",
                cover_options,
                index=cover_options.index(st.session_state.cover_template_choice)
                if st.session_state.cover_template_choice in cover_options
                else 0,
                format_func=_template_label,
            )
            st.session_state.cover_template_choice = cover_choice
            custom_cover_text = None
            if cover_choice == "custom":
                custom_cover_text = st.text_area(
                    "Custom cover letter template",
                    value=st.session_state.custom_cover_template,
                    height=220,
                    help="Use $placeholders such as $today, $company, $title, $matched_skills, $focus_points.",
                )
                st.session_state.custom_cover_template = custom_cover_text

        selected_keys = set(st.session_state.search_selected or [])
        resume_custom_for_actions = (
            st.session_state.custom_resume_template if resume_choice == "custom" else custom_resume_text
        )
        cover_custom_for_actions = (
            st.session_state.custom_cover_template if cover_choice == "custom" else custom_cover_text
        )

        for idx, result in enumerate(filtered_results):
            score_pct = int(round((result.match_score or 0) * 100))
            header = f"{result.title} — {score_pct}% match"
            with st.expander(header, expanded=False):
                st.caption(f"Source: {result.source}")
                if result.contact_email:
                    st.info(f"Contact email: {result.contact_email}")
                st.markdown(f"[Open apply link]({result.link})")
                if result.description:
                    st.markdown("### Preview")
                    st.write(result.description)
                elif result.snippet:
                    st.write(result.snippet)

                selection_key = result.link or result.title
                selected = st.checkbox(
                    "Select for batch queue",
                    value=selection_key in selected_keys,
                    key=f"search_select_{idx}",
                )
                if selected and selection_key not in selected_keys:
                    st.session_state.search_selected.append(selection_key)
                    selected_keys.add(selection_key)
                elif not selected and selection_key in selected_keys:
                    st.session_state.search_selected.remove(selection_key)
                    selected_keys.remove(selection_key)

                action_cols = st.columns(3)
                if action_cols[0].button("Queue now", key=f"queue_now_{idx}"):
                    queued = _queue_search_result(
                        result,
                        datetime.now(),
                        resume_template=resume_choice,
                        cover_template=cover_choice,
                        custom_resume_template=resume_custom_for_actions if resume_choice == "custom" else None,
                        custom_cover_template=cover_custom_for_actions if cover_choice == "custom" else None,
                    )
                    st.success(f"Queued {queued.job_id} for immediate processing.")
                    st.experimental_rerun()
                if action_cols[1].button("Save for later", key=f"queue_later_{idx}"):
                    scheduled_time = datetime.now() + timedelta(hours=12)
                    _queue_search_result(
                        result,
                        scheduled_time,
                        resume_template=resume_choice,
                        cover_template=cover_choice,
                        custom_resume_template=resume_custom_for_actions if resume_choice == "custom" else None,
                        custom_cover_template=cover_custom_for_actions if cover_choice == "custom" else None,
                    )
                    st.success(f"Queued for {scheduled_time.isoformat(timespec='minutes')}.")
                if action_cols[2].button("Skip", key=f"queue_skip_{idx}"):
                    st.session_state.search_results = [
                        existing
                        for existing in st.session_state.search_results
                        if not (
                            existing.link == result.link and existing.title == result.title
                        )
                    ]
                    if selection_key in selected_keys:
                        st.session_state.search_selected.remove(selection_key)
                    st.experimental_rerun()

        if st.button(
            "Queue selected jobs",
            disabled=not st.session_state.search_selected,
        ):
            apply_time = start_time
            queued_count = 0
            selection_set = set(st.session_state.search_selected)
            for result in scored_results:
                key = result.link or result.title
                if key in selection_set:
                    _queue_search_result(
                        result,
                        apply_time,
                        resume_template=resume_choice,
                        cover_template=cover_choice,
                        custom_resume_template=st.session_state.custom_resume_template if resume_choice == "custom" else None,
                        custom_cover_template=st.session_state.custom_cover_template if cover_choice == "custom" else None,
                    )
                    apply_time += timedelta(minutes=interval_minutes)
                    queued_count += 1
            st.session_state.search_selected = []
            st.success(f"Queued {queued_count} jobs starting {start_time.isoformat(timespec='minutes')}.")
    else:
        st.info("Run a search to see direct-apply opportunities.")


def _render_analysis_tab() -> None:
    profile: CandidateProfile = st.session_state.profile
    inventory: SkillsInventory = st.session_state.inventory

    results = st.session_state.get("search_results", [])
    default_title = results[0].title if results else ""
    options = ["Manual entry"] + [f"{res.title} ({res.source})" for res in results]
    choice = st.selectbox("Select a job to analyse", options)

    selected: Optional[SearchResult] = None
    if choice != "Manual entry":
        selected = results[options.index(choice) - 1]

    with st.form("analysis_form"):
        title = st.text_input("Job title", value=selected.title if selected else default_title)
        company = st.text_input("Company", value="")
        location = st.text_input("Location", value="")
        salary_text = st.text_input("Salary info", value="")
        apply_url = st.text_input("Apply URL", value=selected.link if selected else "")
        description = st.text_area(
            "Job description",
            value=selected.snippet if selected else "",
            height=220,
            help="Paste the full job description for the best assessment.",
        )
        tags_text = st.text_input("Tags", value="")
        felon_friendly = st.selectbox(
            "Felon friendly?",
            options=["Unknown", "Yes", "No"],
            index=0,
            help="Use when the posting explicitly mentions justice-involved candidates.",
        )
        submitted = st.form_submit_button("Analyse job match")

    if submitted:
        if not title.strip() or not company.strip():
            st.error("Provide both a job title and company name.")
            return
        posting = JobPosting(
            title=title.strip(),
            company=company.strip(),
            location=location.strip() or None,
            salary_text=salary_text.strip() or None,
            description=description,
            tags=[tag.strip() for tag in tags_text.split(",") if tag.strip()],
            felon_friendly=None
            if felon_friendly == "Unknown"
            else felon_friendly == "Yes",
            apply_url=apply_url.strip() or (selected.link if selected else None),
        )
        assessment = analyse_job_fit(profile, posting)
        inventory.observe_skills(assessment.required_skills)
        _save_state()

        score_pct = int(round(assessment.match_score * 100))
        st.success(f"Match score: {score_pct}%")
        st.progress(assessment.match_score)

        cols = st.columns(2)
        cols[0].metric("Skills matched", len(assessment.matched_skills))
        cols[1].metric("Skills missing", len(assessment.missing_skills))

        if assessment.required_skills:
            st.markdown("### Required skills")
            st.write(
                {
                    "Matched": assessment.matched_skills,
                    "Missing": assessment.missing_skills,
                }
            )

        if assessment.recommended_questions:
            st.markdown("### Follow-up questions")
            for question in assessment.recommended_questions:
                st.write(f"- {question}")

        if assessment.recommended_profile_updates:
            st.markdown("### Resume & cover letter focus")
            for update in assessment.recommended_profile_updates:
                st.write(f"- {update}")

        if assessment.salary_notes:
            st.markdown("### Salary notes")
            for note in assessment.salary_notes:
                st.write(f"- {note}")
        elif assessment.meets_salary is True:
            st.info("Posting appears to meet your minimum salary preference.")

        if assessment.location_notes:
            st.markdown("### Location notes")
            for note in assessment.location_notes:
                st.write(f"- {note}")
        elif assessment.meets_location is True:
            st.info("Posting aligns with your saved location preferences.")

        if assessment.felon_friendly is True:
            st.success("Posting explicitly welcomes justice-involved candidates.")
        elif assessment.felon_friendly is False:
            st.warning("Posting may require a clean record; investigate further before applying.")
        else:
            st.info("No clear felon-friendly signals detected.")

        with st.expander("Add to application queue"):
            schedule_time = st.datetime_input(
                "Schedule application for",
                value=datetime.now(),
                key="queue_schedule_time",
            )
            resume_path = st.text_input("Resume path", value="", key="queue_resume_path")
            cover_path = st.text_input("Cover letter path", value="", key="queue_cover_path")
            if st.button("Queue application", key="queue_submit_button"):
                queued = QueuedApplication(
                    posting=posting,
                    apply_at=schedule_time,
                    resume_path=resume_path or None,
                    cover_letter_path=cover_path or None,
                )
                st.session_state.queue.add(queued)
                _save_state()
                st.success(f"Queued {queued.job_id} for {schedule_time.isoformat(timespec='minutes')}.")


def _render_documents_tab() -> None:
    profile: CandidateProfile = st.session_state.profile
    inventory: SkillsInventory = st.session_state.inventory
    queue: ApplicationQueue = st.session_state.queue

    results = st.session_state.get("search_results", [])
    options = ["Manual entry"] + [f"{res.title} ({res.source})" for res in results]
    selection = st.selectbox("Source", options)
    selected: Optional[SearchResult] = None
    if selection != "Manual entry":
        selected = results[options.index(selection) - 1]

    with st.form("documents_form"):
        title = st.text_input("Job title", value=selected.title if selected else "")
        company = st.text_input("Company", value="")
        location = st.text_input("Location", value="")
        salary = st.text_input("Salary info", value="")
        apply_url = st.text_input("Apply URL", value=selected.link if selected else "")
        contact_email = st.text_input("Contact email", value=selected.contact_email if selected else "")
        description = st.text_area(
            "Job description",
            value=selected.snippet if selected else "",
            height=220,
        )
        tags_text = st.text_input("Tags", value="")
        use_ai = st.checkbox(
            "Use AI generator",
            value=bool(os.getenv("OPENAI_API_KEY")),
            help="Requires the openai package and an API key.",
        )
        ai_model = st.text_input("AI model", value="gpt-4o-mini", disabled=not use_ai)
        ai_temperature = st.slider("AI creativity", min_value=0.0, max_value=1.0, value=0.3, step=0.05, disabled=not use_ai)
        ai_key = st.text_input(
            "AI API key",
            value=os.getenv("OPENAI_API_KEY", ""),
            type="password",
            disabled=not use_ai,
        )
        output_dir = st.text_input("Output directory", value="generated_documents")
        enqueue = st.checkbox("Add to queue", value=False)
        schedule_time = datetime.now()
        if enqueue:
            schedule_time = st.datetime_input(
                "Schedule application for",
                value=datetime.now(),
                key="documents_schedule_time",
            )
        resume_options = available_resume_templates()
        if "custom" not in resume_options:
            resume_options.append("custom")
        resume_options = sorted(resume_options, key=lambda name: {"traditional": 0, "modern": 1, "minimal": 2, "custom": 3}.get(name, 99))
        cover_options = available_cover_letter_templates()
        if "custom" not in cover_options:
            cover_options.append("custom")
        cover_options = sorted(cover_options, key=lambda name: {"traditional": 0, "modern": 1, "minimal": 2, "custom": 3}.get(name, 99))

        resume_choice = st.selectbox(
            "Resume template",
            resume_options,
            index=resume_options.index(st.session_state.resume_template_choice)
            if st.session_state.resume_template_choice in resume_options
            else 0,
            format_func=_template_label,
        )
        st.session_state.resume_template_choice = resume_choice
        resume_custom_text = None
        if resume_choice == "custom":
            resume_custom_text = st.text_area(
                "Custom resume template",
                value=st.session_state.custom_resume_template,
                height=220,
                help="Use $placeholders such as $name, $matched_skills, $experience, $additional_skills.",
            )
            st.session_state.custom_resume_template = resume_custom_text

        cover_choice = st.selectbox(
            "Cover letter template",
            cover_options,
            index=cover_options.index(st.session_state.cover_template_choice)
            if st.session_state.cover_template_choice in cover_options
            else 0,
            format_func=_template_label,
        )
        st.session_state.cover_template_choice = cover_choice
        cover_custom_text = None
        if cover_choice == "custom":
            cover_custom_text = st.text_area(
                "Custom cover letter template",
                value=st.session_state.custom_cover_template,
                height=220,
                help="Use $placeholders such as $today, $company, $title, $matched_skills, $focus_points.",
            )
            st.session_state.custom_cover_template = cover_custom_text
        submitted = st.form_submit_button("Generate documents")

    if not submitted:
        return

    if not title.strip() or not company.strip():
        st.error("Provide both a job title and company name.")
        return
    if not description.strip():
        st.error("Paste the job description for better tailoring.")
        return
    if enqueue and not apply_url.strip():
        st.error("Provide an apply URL when adding the job to the queue.")
        return

    posting = JobPosting(
        title=title.strip(),
        company=company.strip(),
        location=location.strip() or None,
        salary_text=salary.strip() or None,
        description=description,
        tags=[tag.strip() for tag in tags_text.split(",") if tag.strip()],
        apply_url=apply_url.strip() or (selected.link if selected else None),
        contact_email=contact_email.strip() or (selected.contact_email if selected else None),
    )
    assessment = analyse_job_fit(profile, posting)
    inventory.observe_skills(assessment.required_skills)

    generator: Optional[AIDocumentGenerator] = None
    resume_text: str
    cover_text: str
    if use_ai:
        try:
            generator = AIDocumentGenerator(api_key=ai_key or None, model=ai_model, temperature=ai_temperature)
        except DocumentGenerationDependencyError as exc:
            st.error(str(exc))
            return
        try:
            resume_text = generator.generate_resume(profile, posting, assessment)
            cover_text = generator.generate_cover_letter(profile, posting, assessment)
        except DocumentGenerationError as exc:
            st.error(str(exc))
            return
    else:
        resume_text = generate_resume(
            profile,
            posting,
            assessment,
            style=resume_choice,
            custom_template=resume_custom_text if resume_choice == "custom" else None,
        )
        cover_text = generate_cover_letter(
            profile,
            posting,
            assessment,
            style=cover_choice,
            custom_template=cover_custom_text if cover_choice == "custom" else None,
        )

    directory = Path(output_dir.strip() or "generated_documents")
    directory.mkdir(parents=True, exist_ok=True)
    slug = _slugify(posting.title, posting.company)
    resume_path = directory / f"{slug}_resume.md"
    cover_path = directory / f"{slug}_cover_letter.md"
    resume_path.write_text(resume_text, encoding="utf-8")
    cover_path.write_text(cover_text, encoding="utf-8")

    st.success("Documents generated.")
    st.write(f"Resume saved to {resume_path}")
    st.write(f"Cover letter saved to {cover_path}")

    st.download_button("Download resume", data=resume_text.encode("utf-8"), file_name=resume_path.name)
    st.download_button("Download cover letter", data=cover_text.encode("utf-8"), file_name=cover_path.name)

    if enqueue:
        queued = QueuedApplication(
            posting=posting,
            apply_at=schedule_time,
            resume_path=str(resume_path),
            cover_letter_path=str(cover_path),
            resume_template=resume_choice,
            cover_letter_template=cover_choice,
            custom_resume_template=resume_custom_text if resume_choice == "custom" else None,
            custom_cover_letter_template=cover_custom_text if cover_choice == "custom" else None,
        )
        if use_ai and generator:
            queued.notes.append(f"Documents generated with AI model {generator.model}.")
        queue.add(queued)
        st.success(f"Queued {queued.job_id} for {schedule_time.isoformat(timespec='minutes')}.")

    st.session_state.profile = profile
    st.session_state.inventory = inventory
    st.session_state.queue = queue
    _save_state()

def _render_skills_tab() -> None:
    inventory: SkillsInventory = st.session_state.inventory

    records = inventory.sorted_by_opportunity()
    if not records:
        st.info("No skill observations yet. Analyse job descriptions to populate this dashboard.")
        return

    table = [
        {
            "Skill": record.name,
            "Demand": record.occurrences,
            "Interviews": record.interviews,
            "Offers": record.offers,
            "Notes": " | ".join(record.notes),
        }
        for record in records
    ]
    st.dataframe(table, hide_index=True, use_container_width=True)

    with st.form("skill_notes_form"):
        skill_names = [record.name for record in records]
        selection = st.selectbox("Select a skill", skill_names)
        interviews = st.number_input("Interviews", min_value=0, value=0, step=1)
        offers = st.number_input("Offers", min_value=0, value=0, step=1)
        note = st.text_input("Add note", value="")
        submitted = st.form_submit_button("Update skill")

    if submitted:
        record = inventory.ensure(selection)
        for _ in range(interviews):
            record.record_interview()
        for _ in range(offers):
            record.record_offer()
        if note.strip():
            record.add_note(note)
        _save_state()
        st.success(f"Updated skill '{selection}'.")


def _render_queue_tab() -> None:
    queue: ApplicationQueue = st.session_state.queue
    inventory: SkillsInventory = st.session_state.inventory

    pending = queue.items
    if not pending:
        st.info("No applications scheduled. Use the analysis tab to add new ones.")
        return

    for idx, application in enumerate(list(pending)):
        header = f"{application.posting.title} @ {application.posting.company}"
        with st.expander(header, expanded=False):
            st.write(f"Scheduled for: {application.apply_at.isoformat(timespec='minutes')}")
            st.write(f"Status: {application.status}")
            if application.posting.apply_url:
                st.write(f"Apply URL: {application.posting.apply_url}")
            if application.posting.contact_email:
                st.write(f"Contact email: {application.posting.contact_email}")
            if application.resume_path:
                st.write(f"Resume: {application.resume_path}")
            if application.cover_letter_path:
                st.write(f"Cover letter: {application.cover_letter_path}")
            if application.notes:
                st.markdown("### Notes")
                for note in application.notes:
                    st.write(f"- {note}")
            if application.last_error:
                st.error(f"Last error: {application.last_error}")
            if application.outcome:
                recorded = (
                    application.outcome_recorded_at.isoformat(timespec="minutes")
                    if application.outcome_recorded_at
                    else "unknown"
                )
                st.info(f"Outcome: {application.outcome} (recorded {recorded})")

            col1, col2, col3 = st.columns(3)
            if col1.button("Mark applied", key=f"queue_apply_{idx}"):
                application.mark_success()
                _save_state()
                st.experimental_rerun()
            if col2.button("Reschedule", key=f"queue_reschedule_{idx}"):
                new_time = datetime.now().replace(second=0, microsecond=0)
                application.defer(new_time)
                _save_state()
                st.success(f"Rescheduled for {new_time.isoformat(timespec='minutes')}.")
            if col3.button("Remove", key=f"queue_remove_{idx}"):
                queue.items.pop(idx)
                _save_state()
                st.experimental_rerun()

            outcome_cols = st.columns(4)
            if outcome_cols[0].button("Interview", key=f"queue_outcome_interview_{idx}"):
                application.record_outcome("interview")
                for skill in application.posting.tags:
                    inventory.record_interview(skill)
                _save_state()
                st.experimental_rerun()
            if outcome_cols[1].button("Offer", key=f"queue_outcome_offer_{idx}"):
                application.record_outcome("offer")
                for skill in application.posting.tags:
                    inventory.record_offer(skill)
                _save_state()
                st.experimental_rerun()
            if outcome_cols[2].button("Rejected", key=f"queue_outcome_rejected_{idx}"):
                application.record_outcome("rejected")
                _save_state()
                st.experimental_rerun()
            if outcome_cols[3].button("Ghosted", key=f"queue_outcome_ghosted_{idx}"):
                application.record_outcome("ghosted")
                _save_state()
                st.experimental_rerun()


def main() -> None:
    st.set_page_config(page_title="Jobofcron Control Centre", layout="wide")
    _initialise_session_state()

    st.sidebar.title("Settings")
    storage_path = st.sidebar.text_input("Storage file", value=st.session_state.storage_path)
    if storage_path != st.session_state.storage_path:
        st.session_state.storage_path = storage_path
    _reload_state_if_needed(storage_path)

    st.title("Jobofcron Control Centre")
    st.caption("Plan direct applications, tailor documents, and track job hunt progress.")

    tabs = st.tabs(
        [
            "Dashboard",
            "Profile",
            "Job search",
            "Job analysis",
            "Documents",
            "Skills dashboard",
            "Application queue",
        ]
    )

    with tabs[0]:
        _render_dashboard_tab()
    with tabs[1]:
        _render_profile_tab()
    with tabs[2]:
        _render_search_tab()
    with tabs[3]:
        _render_analysis_tab()
    with tabs[4]:
        _render_documents_tab()
    with tabs[5]:
        _render_skills_tab()
    with tabs[6]:
        _render_queue_tab()


if __name__ == "__main__":  # pragma: no cover - Streamlit entry point
    main()
