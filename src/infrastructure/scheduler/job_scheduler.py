"""SQLite-backed persistent scheduler for one-time reminders and recurring cron jobs."""

from __future__ import annotations
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple, Union
from src.infrastructure.database.sqlite_db import SqliteDatabase

logger = logging.getLogger(__name__)


class JobType(str, Enum):
    TASK = "task"
    REMINDER = "reminder"
    CRON = "cron"
    AI_PROMPT = "ai_prompt"


class ScheduleType(str, Enum):
    ONCE = "once"
    INTERVAL = "interval"
    CRON = "cron"


class JobStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class ScheduledJob:
    job_id: str
    user_id: int
    chat_id: int
    job_type: str
    schedule_type: str
    schedule_value: str
    prompt: str
    is_ai_prompt: bool
    next_run_at: datetime
    last_run_at: Optional[datetime] = None
    status: str = JobStatus.ACTIVE.value
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


def _parse_cron_field(field_str: str, min_val: int, max_val: int) -> Set[int]:
    """Parse a single cron field into allowed integer values."""
    field_str = field_str.strip()
    result: Set[int] = set()

    for part in field_str.split(","):
        part = part.strip()
        if not part:
            continue

        if "/" in part:
            subparts = part.split("/", 1)
            range_part = subparts[0]
            step = int(subparts[1])
            if range_part == "*" or range_part == "":
                start_val, end_val = min_val, max_val
            elif "-" in range_part:
                s_str, e_str = range_part.split("-", 1)
                start_val, end_val = int(s_str), int(e_str)
            else:
                start_val, end_val = int(range_part), max_val
            for v in range(start_val, end_val + 1, step):
                if min_val <= v <= max_val:
                    result.add(v)
        elif "-" in part:
            s_str, e_str = part.split("-", 1)
            start_val, end_val = int(s_str), int(e_str)
            for v in range(start_val, end_val + 1):
                if min_val <= v <= max_val:
                    result.add(v)
        elif part == "*":
            result.update(range(min_val, max_val + 1))
        else:
            v = int(part)
            if min_val <= v <= max_val:
                result.add(v)

    if not result:
        raise ValueError(f"Invalid cron field format: '{field_str}'")
    return result


def compute_next_cron_run(cron_expr: str, base_dt: Optional[datetime] = None) -> datetime:
    """Calculate the next occurrence of a standard 5-part cron expression."""
    if base_dt is None:
        base_dt = datetime.now(timezone.utc)
    elif base_dt.tzinfo is None:
        base_dt = base_dt.replace(tzinfo=timezone.utc)

    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must contain exactly 5 fields, got {len(parts)}: '{cron_expr}'")

    minute_set = _parse_cron_field(parts[0], 0, 59)
    hour_set = _parse_cron_field(parts[1], 0, 23)
    dom_set = _parse_cron_field(parts[2], 1, 31)
    month_set = _parse_cron_field(parts[3], 1, 12)
    raw_dow = _parse_cron_field(parts[4], 0, 7)
    dow_set: Set[int] = set()
    for d in raw_dow:
        if d in (0, 7):
            dow_set.add(6)  # Sunday
        else:
            dow_set.add(d - 1)

    current = base_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(525600):
        if current.month not in month_set:
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1, day=1, hour=0, minute=0)
            else:
                current = current.replace(month=current.month + 1, day=1, hour=0, minute=0)
            continue

        if current.day not in dom_set or current.weekday() not in dow_set:
            current = (current + timedelta(days=1)).replace(hour=0, minute=0)
            continue

        if current.hour not in hour_set:
            current = (current + timedelta(hours=1)).replace(minute=0)
            continue

        if current.minute in minute_set:
            return current

        current += timedelta(minutes=1)

    raise ValueError(f"Could not find next run time within 1 year for cron '{cron_expr}'")


def parse_relative_duration(duration_str: str) -> timedelta:
    """Parse relative duration string like '10s', '5m', '2 hours', '1 day'."""
    pattern = r"(\d+)\s*(s(?:ec(?:ond)?s?)?|m(?:in(?:ute)?s?)?|h(?:(?:ou)?rs?)?|d(?:ays?)?|w(?:eeks?)?)"
    match = re.search(pattern, duration_str.strip().lower())
    if not match:
        raise ValueError(f"Cannot parse relative duration: '{duration_str}'")

    val = int(match.group(1))
    unit = match.group(2)

    if unit.startswith("s"):
        return timedelta(seconds=val)
    elif unit.startswith("m"):
        return timedelta(minutes=val)
    elif unit.startswith("h"):
        return timedelta(hours=val)
    elif unit.startswith("d"):
        return timedelta(days=val)
    elif unit.startswith("w"):
        return timedelta(weeks=val)

    raise ValueError(f"Unknown duration unit '{unit}' in '{duration_str}'")


def parse_schedule_expression(schedule_input: str, base_dt: Optional[datetime] = None) -> Tuple[ScheduleType, datetime, str]:
    """Parse relative duration, cron, or ISO timestamp."""
    if base_dt is None:
        base_dt = datetime.now(timezone.utc)
    elif base_dt.tzinfo is None:
        base_dt = base_dt.replace(tzinfo=timezone.utc)

    raw = schedule_input.strip()

    # 1. Check if cron format (5 tokens)
    tokens = raw.split()
    if len(tokens) == 5 and all(any(c in t for c in "0123456789*,-/") for t in tokens):
        try:
            next_dt = compute_next_cron_run(raw, base_dt)
            return ScheduleType.CRON, next_dt, raw
        except Exception as e:
            raise ValueError(f"Invalid cron expression '{raw}': {str(e)}")

    # 2. Check for recurring interval: 'every ...'
    if raw.lower().startswith("every "):
        interval_str = raw[6:].strip()
        delta = parse_relative_duration(interval_str)
        next_dt = base_dt + delta
        return ScheduleType.INTERVAL, next_dt, interval_str

    # 3. Check for relative delay: 'in ...' or single token
    clean_delay = raw[3:].strip() if raw.lower().startswith("in ") else raw
    try:
        delta = parse_relative_duration(clean_delay)
        next_dt = base_dt + delta
        return ScheduleType.ONCE, next_dt, clean_delay
    except ValueError:
        pass

    # 4. Check for ISO datetime
    iso_candidates = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
    ]
    for fmt in iso_candidates:
        try:
            parsed = datetime.strptime(raw, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return ScheduleType.ONCE, parsed, parsed.isoformat()
        except ValueError:
            continue

    # 5. Check for clock time: 'HH:MM'
    time_match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", raw)
    if time_match:
        h = int(time_match.group(1))
        m = int(time_match.group(2))
        s = int(time_match.group(3) or 0)
        target = base_dt.replace(hour=h, minute=m, second=s, microsecond=0)
        if target <= base_dt:
            target += timedelta(days=1)
        return ScheduleType.ONCE, target, target.isoformat()

    raise ValueError(f"Unable to parse time expression '{schedule_input}'")


class JobScheduler:
    """Async SQLite-backed persistent scheduler for managing one-off reminders and recurring cron jobs."""

    def __init__(self, db: SqliteDatabase):
        self.db = db

    def parse_time_delta_or_iso(self, time_str: str, base_dt: Optional[datetime] = None) -> datetime:
        """Parse natural language time expression or ISO format into future datetime."""
        _, next_dt, _ = parse_schedule_expression(time_str, base_dt=base_dt)
        return next_dt

    async def schedule_job(
        self,
        user_id: int,
        chat_id: int,
        prompt: str,
        due_at: Optional[Union[datetime, str]] = None,
        schedule_expr: Optional[str] = None,
        job_type: Union[JobType, str] = JobType.TASK,
        schedule_type: Optional[Union[ScheduleType, str]] = None,
        is_ai_prompt: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ScheduledJob:
        """Parse schedule and persist a new scheduled job."""
        now = datetime.now(timezone.utc)
        raw_expr = schedule_expr or due_at

        if raw_expr is None:
            raise ValueError("Either 'due_at' or 'schedule_expr' must be provided.")

        if isinstance(raw_expr, datetime):
            sched_type_val = ScheduleType.ONCE.value if schedule_type is None else (schedule_type.value if isinstance(schedule_type, Enum) else str(schedule_type))
            next_run = raw_expr if raw_expr.tzinfo else raw_expr.replace(tzinfo=timezone.utc)
            norm_value = next_run.isoformat()
        else:
            sched_enum, next_run, norm_value = parse_schedule_expression(str(raw_expr), base_dt=now)
            sched_type_val = sched_enum.value if schedule_type is None else (schedule_type.value if isinstance(schedule_type, Enum) else str(schedule_type))

        job_type_val = job_type.value if isinstance(job_type, Enum) else str(job_type)
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        job = ScheduledJob(
            job_id=job_id,
            user_id=user_id,
            chat_id=chat_id,
            job_type=job_type_val,
            schedule_type=sched_type_val,
            schedule_value=norm_value,
            prompt=prompt.strip(),
            is_ai_prompt=is_ai_prompt,
            next_run_at=next_run,
            status=JobStatus.ACTIVE.value,
            created_at=now,
            metadata=metadata or {},
        )

        assert self.db._db is not None
        await self.db._db.execute(
            """
            INSERT INTO scheduled_jobs (
                job_id, user_id, chat_id, job_type, schedule_type, schedule_value,
                prompt, is_ai_prompt, next_run_at, last_run_at, status, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.user_id,
                job.chat_id,
                job.job_type,
                job.schedule_type,
                job.schedule_value,
                job.prompt,
                1 if job.is_ai_prompt else 0,
                job.next_run_at.isoformat(),
                None,
                job.status,
                job.created_at.isoformat(),
                json.dumps(job.metadata),
            )
        )
        await self.db._db.commit()
        return job

    async def schedule_reminder(
        self,
        user_id: int,
        chat_id: int,
        time_expr: str,
        text: str,
    ) -> ScheduledJob:
        """Schedule a one-off plain text reminder."""
        return await self.schedule_job(
            user_id=user_id,
            chat_id=chat_id,
            prompt=text,
            due_at=time_expr,
            job_type=JobType.REMINDER,
            is_ai_prompt=False,
        )

    async def schedule_cron(
        self,
        user_id: int,
        chat_id: int,
        schedule_expr: str,
        prompt: str,
        is_ai_prompt: bool = True,
    ) -> ScheduledJob:
        """Schedule a recurring cron / interval AI task."""
        return await self.schedule_job(
            user_id=user_id,
            chat_id=chat_id,
            prompt=prompt,
            schedule_expr=schedule_expr,
            job_type=JobType.CRON,
            is_ai_prompt=is_ai_prompt,
        )

    async def get_due_jobs(self, as_of: Optional[datetime] = None, now: Optional[datetime] = None) -> List[ScheduledJob]:
        """Fetch all active jobs that are due for execution."""
        ref_time = as_of or now or datetime.now(timezone.utc)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        ref_iso = ref_time.isoformat()
        assert self.db._db is not None
        cursor = await self.db._db.execute(
            """
            SELECT job_id, user_id, chat_id, job_type, schedule_type, schedule_value,
                   prompt, is_ai_prompt, next_run_at, last_run_at, status, created_at, metadata_json
            FROM scheduled_jobs
            WHERE status = 'active' AND next_run_at <= ?
            ORDER BY next_run_at ASC
            """,
            (ref_iso,)
        )
        rows = await cursor.fetchall()
        jobs: List[ScheduledJob] = []
        for r in rows:
            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    pass
            jobs.append(ScheduledJob(
                job_id=r["job_id"],
                user_id=r["user_id"],
                chat_id=r["chat_id"],
                job_type=r["job_type"],
                schedule_type=r["schedule_type"],
                schedule_value=r["schedule_value"],
                prompt=r["prompt"],
                is_ai_prompt=bool(r["is_ai_prompt"]),
                next_run_at=datetime.fromisoformat(r["next_run_at"]),
                last_run_at=datetime.fromisoformat(r["last_run_at"]) if r["last_run_at"] else None,
                status=r["status"],
                created_at=datetime.fromisoformat(r["created_at"]),
                metadata=meta,
            ))
        return jobs

    async def complete_job(self, job_id: str, completed_at: Optional[datetime] = None) -> bool:
        """Mark a job as completed."""
        if completed_at is None:
            completed_at = datetime.now(timezone.utc)
        elif completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)

        assert self.db._db is not None
        cursor = await self.db._db.execute(
            """
            UPDATE scheduled_jobs
            SET status = 'completed', last_run_at = ?
            WHERE job_id = ?
            """,
            (completed_at.isoformat(), job_id)
        )
        await self.db._db.commit()
        return cursor.rowcount > 0

    async def record_job_completion(self, job: ScheduledJob, executed_at: Optional[datetime] = None) -> None:
        """Mark job executed, calculating next trigger time or completing one-off jobs."""
        if executed_at is None:
            executed_at = datetime.now(timezone.utc)
        elif executed_at.tzinfo is None:
            executed_at = executed_at.replace(tzinfo=timezone.utc)

        assert self.db._db is not None

        if job.schedule_type == ScheduleType.ONCE.value:
            await self.complete_job(job.job_id, completed_at=executed_at)
        elif job.schedule_type == ScheduleType.INTERVAL.value:
            delta = parse_relative_duration(job.schedule_value)
            next_run = executed_at + delta
            await self.db._db.execute(
                """
                UPDATE scheduled_jobs
                SET last_run_at = ?, next_run_at = ?
                WHERE job_id = ?
                """,
                (executed_at.isoformat(), next_run.isoformat(), job.job_id)
            )
            await self.db._db.commit()
        elif job.schedule_type == ScheduleType.CRON.value:
            next_run = compute_next_cron_run(job.schedule_value, executed_at)
            await self.db._db.execute(
                """
                UPDATE scheduled_jobs
                SET last_run_at = ?, next_run_at = ?
                WHERE job_id = ?
                """,
                (executed_at.isoformat(), next_run.isoformat(), job.job_id)
            )
            await self.db._db.commit()

    async def run_due_jobs(self, executor_callback: Callable[[ScheduledJob], Coroutine[Any, Any, None]]) -> List[ScheduledJob]:
        """Fetch and execute due jobs with async callback."""
        due_jobs = await self.get_due_jobs()
        executed: List[ScheduledJob] = []
        for job in due_jobs:
            try:
                await executor_callback(job)
                await self.record_job_completion(job)
                executed.append(job)
            except Exception as e:
                logger.error(f"Error executing due job {job.job_id}: {str(e)}")
        return executed

    async def cancel_job(self, job_id: str, user_id: Optional[int] = None) -> bool:
        """Cancel an active scheduled job."""
        assert self.db._db is not None
        if user_id is not None:
            cursor = await self.db._db.execute(
                "UPDATE scheduled_jobs SET status = 'cancelled' WHERE job_id = ? AND user_id = ? AND status = 'active'",
                (job_id, user_id)
            )
        else:
            cursor = await self.db._db.execute(
                "UPDATE scheduled_jobs SET status = 'cancelled' WHERE job_id = ? AND status = 'active'",
                (job_id,)
            )
        await self.db._db.commit()
        return cursor.rowcount > 0

    async def list_jobs(self, user_id: Optional[int] = None, status: Optional[str] = None, active_only: bool = False) -> List[ScheduledJob]:
        """List scheduled jobs for a user or globally."""
        assert self.db._db is not None
        query = "SELECT * FROM scheduled_jobs WHERE 1=1"
        params: List[Any] = []
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        elif active_only:
            query += " AND status = 'active'"
        query += " ORDER BY next_run_at ASC"

        cursor = await self.db._db.execute(query, tuple(params))
        rows = await cursor.fetchall()
        jobs: List[ScheduledJob] = []
        for r in rows:
            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    pass
            jobs.append(ScheduledJob(
                job_id=r["job_id"],
                user_id=r["user_id"],
                chat_id=r["chat_id"],
                job_type=r["job_type"],
                schedule_type=r["schedule_type"],
                schedule_value=r["schedule_value"],
                prompt=r["prompt"],
                is_ai_prompt=bool(r["is_ai_prompt"]),
                next_run_at=datetime.fromisoformat(r["next_run_at"]),
                last_run_at=datetime.fromisoformat(r["last_run_at"]) if r["last_run_at"] else None,
                status=r["status"],
                created_at=datetime.fromisoformat(r["created_at"]),
                metadata=meta,
            ))
        return jobs

    async def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        """Retrieve a specific job by ID."""
        assert self.db._db is not None
        cursor = await self.db._db.execute("SELECT * FROM scheduled_jobs WHERE job_id = ?", (job_id,))
        r = await cursor.fetchone()
        if not r:
            return None
        meta = {}
        if r["metadata_json"]:
            try:
                meta = json.loads(r["metadata_json"])
            except Exception:
                pass
        return ScheduledJob(
            job_id=r["job_id"],
            user_id=r["user_id"],
            chat_id=r["chat_id"],
            job_type=r["job_type"],
            schedule_type=r["schedule_type"],
            schedule_value=r["schedule_value"],
            prompt=r["prompt"],
            is_ai_prompt=bool(r["is_ai_prompt"]),
            next_run_at=datetime.fromisoformat(r["next_run_at"]),
            last_run_at=datetime.fromisoformat(r["last_run_at"]) if r["last_run_at"] else None,
            status=r["status"],
            created_at=datetime.fromisoformat(r["created_at"]),
            metadata=meta,
        )
