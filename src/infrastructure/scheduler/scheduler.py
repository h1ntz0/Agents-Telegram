"""Compatibility alias for job_scheduler."""

from src.infrastructure.scheduler.job_scheduler import (
    JobScheduler,
    JobStatus,
    JobType,
    ScheduledJob,
    ScheduleType,
    compute_next_cron_run,
    parse_relative_duration,
    parse_schedule_expression,
)

Scheduler = JobScheduler

__all__ = [
    "JobScheduler",
    "Scheduler",
    "ScheduledJob",
    "JobType",
    "ScheduleType",
    "JobStatus",
    "compute_next_cron_run",
    "parse_relative_duration",
    "parse_schedule_expression",
]
