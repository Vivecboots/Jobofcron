"""Application scheduler utilities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Sequence


@dataclass
class ScheduledApplication:
    job_id: str
    job_title: str
    company: str
    apply_at: datetime


def plan_schedule(
    jobs: Sequence[dict],
    *,
    start: datetime,
    min_interval_minutes: int = 10,
    break_every: int = 5,
    break_duration: timedelta = timedelta(minutes=30),
) -> List[ScheduledApplication]:
    """Create a paced schedule for applying to jobs.

    Args:
        jobs: Iterable of job dictionaries with ``id``, ``title`` and ``company``.
        start: When to begin applying.
        min_interval_minutes: Minimum spacing between applications.
        break_every: After how many applications to insert a break.
        break_duration: Duration of the break.
    """

    if min_interval_minutes <= 0:
        raise ValueError("min_interval_minutes must be positive")
    if break_every <= 0:
        raise ValueError("break_every must be positive")

    schedule: List[ScheduledApplication] = []
    current_time = start
    interval = timedelta(minutes=min_interval_minutes)

    for index, job in enumerate(jobs, start=1):
        schedule.append(
            ScheduledApplication(
                job_id=str(job.get("id")),
                job_title=job.get("title", ""),
                company=job.get("company", ""),
                apply_at=current_time,
            )
        )
        current_time += interval
        if index % break_every == 0:
            current_time += break_duration

    return schedule
