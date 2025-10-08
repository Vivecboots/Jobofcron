"""Jobofcron – Indeed job application automation toolkit."""

from .application_automation import AutomationDependencyError, DirectApplyAutomation
from .application_queue import ApplicationQueue, QueuedApplication
from .document_generation import (
    AIDocumentGenerator,
    DocumentGenerationDependencyError,
    DocumentGenerationError,
    generate_cover_letter,
    generate_resume,
)
from .job_matching import JobPosting, MatchAssessment, analyse_job_fit, extract_required_skills
from .job_search import CraigslistSearch, GoogleJobSearch, SearchResult
from .profile import CandidateProfile, Experience, JobPreference
from .scheduler import ScheduledApplication, plan_schedule
from .skills_inventory import SkillRecord, SkillsInventory
from .storage import Storage
from .worker import JobAutomationWorker

__all__ = [
    "JobPosting",
    "MatchAssessment",
    "analyse_job_fit",
    "extract_required_skills",
    "GoogleJobSearch",
    "CraigslistSearch",
    "SearchResult",
    "CandidateProfile",
    "Experience",
    "JobPreference",
    "SkillRecord",
    "SkillsInventory",
    "ScheduledApplication",
    "Storage",
    "plan_schedule",
    "ApplicationQueue",
    "QueuedApplication",
    "generate_resume",
    "generate_cover_letter",
    "AIDocumentGenerator",
    "DocumentGenerationDependencyError",
    "DocumentGenerationError",
    "DirectApplyAutomation",
    "AutomationDependencyError",
    "JobAutomationWorker",
]
