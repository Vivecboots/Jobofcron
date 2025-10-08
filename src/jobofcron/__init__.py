"""Jobofcron – Indeed job application automation toolkit."""

from .profile import CandidateProfile, Experience, JobPreference
from .skills_inventory import SkillRecord, SkillsInventory
from .scheduler import ScheduledApplication, plan_schedule
from .storage import Storage

__all__ = [
    "CandidateProfile",
    "Experience",
    "JobPreference",
    "SkillRecord",
    "SkillsInventory",
    "ScheduledApplication",
    "Storage",
    "plan_schedule",
]
