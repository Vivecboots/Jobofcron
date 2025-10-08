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
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Iterable, List, Optional

import streamlit as st

PACKAGE_DIR = Path(__file__).resolve().parent

if __package__ in {None, ""}:
    sys.path.append(str(PACKAGE_DIR.parent))
    from jobofcron.application_queue import ApplicationQueue, QueuedApplication  # type: ignore[attr-defined]
    from jobofcron.job_matching import JobPosting, analyse_job_fit  # type: ignore[attr-defined]
    from jobofcron.job_search import GoogleJobSearch, SearchResult  # type: ignore[attr-defined]
    from jobofcron.profile import CandidateProfile  # type: ignore[attr-defined]
    from jobofcron.skills_inventory import SkillsInventory  # type: ignore[attr-defined]
    from jobofcron.storage import Storage  # type: ignore[attr-defined]
else:
    from .application_queue import ApplicationQueue, QueuedApplication
    from .job_matching import JobPosting, analyse_job_fit
    from .job_search import GoogleJobSearch, SearchResult
    from .profile import CandidateProfile
    from .skills_inventory import SkillsInventory
    from .storage import Storage

DEFAULT_STORAGE = Path(os.getenv("JOBOFCRON_STORAGE", "jobofcron_data.json"))


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
    writer.writerow(["title", "link", "snippet", "source", "is_company_site"])
    for result in results:
        writer.writerow([result.title, result.link, result.snippet, result.source, "yes" if result.is_company_site else "no"])
    return buffer.getvalue().encode("utf-8")


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


def _run_search(
    title: str,
    location: str,
    limit: int,
    remote: bool,
    direct_only: bool,
    extra_terms: Iterable[str],
    serpapi_key: str,
    sample_payload: Optional[dict],
) -> List[SearchResult]:
    if sample_payload is not None:
        results = GoogleJobSearch.parse_results(sample_payload)
    else:
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
        direct_only = st.checkbox("Company sites only", value=True)
        extra_terms_text = st.text_input(
            "Extra search terms",
            value=" ".join(profile.job_preferences.focus_domains),
            help="Optional additional keywords (e.g. industry, company).",
        )
        serpapi_key = st.text_input(
            "SerpAPI key",
            value=os.getenv("SERPAPI_KEY", ""),
            type="password",
            help="Provide an API key for live Google searches or upload a saved response below.",
        )
        sample_response = st.file_uploader("Sample SerpAPI response (JSON)", type="json")

        submitted = st.form_submit_button("Search")

    if submitted:
        if not title.strip():
            st.error("Enter a job title or keyword to search.")
            return
        if not location.strip() and not remote:
            st.warning("Provide a location or enable remote roles for best results.")

        payload: Optional[dict] = None
        if sample_response is not None:
            try:
                payload = json.load(sample_response)
            except json.JSONDecodeError as exc:  # pragma: no cover - user input
                st.error(f"Could not parse uploaded JSON: {exc}")
                return
        elif not serpapi_key.strip():
            st.error("Provide either a SerpAPI key or a sample response.")
            return

        try:
            results = _run_search(
                title=title.strip(),
                location=location.strip(),
                limit=limit,
                remote=remote,
                direct_only=direct_only,
                extra_terms=extra_terms_text.split(),
                serpapi_key=serpapi_key.strip(),
                sample_payload=payload,
            )
        except Exception as exc:  # pragma: no cover - network errors
            st.error(f"Search failed: {exc}")
            return

        st.session_state.search_results = results
        if results:
            st.success(f"Found {len(results)} results.")
        else:
            st.info("No results matched the filters. Try broadening your query.")

    results = st.session_state.get("search_results", [])
    if results:
        table_data = [
            {
                "Title": result.title,
                "Source": result.source,
                "Company site?": "Yes" if result.is_company_site else "No",
                "Link": result.link,
                "Snippet": result.snippet,
            }
            for result in results
        ]
        st.dataframe(table_data, use_container_width=True, hide_index=True)

        csv_bytes = _export_results_to_csv(results)
        st.download_button(
            "Export results to CSV",
            data=csv_bytes,
            file_name="jobofcron_search_results.csv",
            mime="text/csv",
        )
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

    pending = queue.items
    if not pending:
        st.info("No applications scheduled. Use the analysis tab to add new ones.")
        return

    for idx, application in enumerate(list(pending)):
        header = f"{application.posting.title} @ {application.posting.company}"
        with st.expander(header, expanded=False):
            st.write(f"Scheduled for: {application.apply_at.isoformat(timespec='minutes')}")
            st.write(f"Status: {application.status}")
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
            "Profile",
            "Job search",
            "Job analysis",
            "Skills dashboard",
            "Application queue",
        ]
    )

    with tabs[0]:
        _render_profile_tab()
    with tabs[1]:
        _render_search_tab()
    with tabs[2]:
        _render_analysis_tab()
    with tabs[3]:
        _render_skills_tab()
    with tabs[4]:
        _render_queue_tab()


if __name__ == "__main__":  # pragma: no cover - Streamlit entry point
    main()
