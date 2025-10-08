"""Jobofcron – Indeed job application automation toolkit."""

from .application_automation import AutomationDependencyError, DirectApplyAutomation, EmailApplicationSender
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
from .job_history import AppliedJobRegistry
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
    "AppliedJobRegistry",
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
    "available_resume_templates",
    "available_cover_letter_templates",
    "AIDocumentGenerator",
    "DocumentGenerationDependencyError",
    "DocumentGenerationError",
    "DirectApplyAutomation",
    "EmailApplicationSender",
    "AutomationDependencyError",
    "JobAutomationWorker",
]
