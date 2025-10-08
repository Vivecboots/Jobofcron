"""Jobofcron – Indeed job application automation toolkit."""

from .job_matching import JobPosting, MatchAssessment, analyse_job_fit, extract_required_skills
from .profile import CandidateProfile, Experience, JobPreference
from .scheduler import ScheduledApplication, plan_schedule
from .skills_inventory import SkillRecord, SkillsInventory
from .storage import Storage

__all__ = [
    "JobPosting",
    "MatchAssessment",
    "analyse_job_fit",
    "extract_required_skills",
    "CandidateProfile",
    "Experience",
    "JobPreference",
    "SkillRecord",
    "SkillsInventory",
    "ScheduledApplication",
    "Storage",
    "plan_schedule",
]
