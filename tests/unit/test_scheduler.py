"""Unit tests for SQLite persistent JobScheduler: scheduling, due job extraction, completion, cancellation, and isolation."""

from datetime import datetime, timedelta, timezone
import pytest
from src.infrastructure.scheduler.scheduler import JobScheduler, JobStatus, ScheduleType, ScheduledJob


@pytest.mark.asyncio
async def test_persistent_job_scheduling(temp_db):
    """Test creating and persisting scheduled jobs in SQLite."""
    scheduler = JobScheduler(db=temp_db)

    now = datetime.now(timezone.utc)
    future_time = now + timedelta(minutes=30)

    # 1. Schedule with datetime object
    job1 = await scheduler.schedule_job(
        user_id=1001,
        chat_id=2001,
        prompt="Check server metrics",
        due_at=future_time,
        job_type="task",
        schedule_type=ScheduleType.ONCE,
        is_ai_prompt=True,
        metadata={"priority": "high"}
    )

    assert job1.job_id is not None
    assert job1.user_id == 1001
    assert job1.chat_id == 2001
    assert job1.prompt == "Check server metrics"
    assert job1.status == JobStatus.ACTIVE
    assert job1.is_ai_prompt is True
    assert job1.metadata.get("priority") == "high"

    # 2. Verify persistence via get_job
    loaded_job = await scheduler.get_job(job1.job_id)
    assert loaded_job is not None
    assert loaded_job.job_id == job1.job_id
    assert loaded_job.prompt == "Check server metrics"
    assert loaded_job.status == JobStatus.ACTIVE


@pytest.mark.asyncio
async def test_extract_due_jobs(temp_db):
    """Test extracting only due jobs based on execution timestamp."""
    scheduler = JobScheduler(db=temp_db)
    now = datetime.now(timezone.utc)

    # Job 1: Due 10 minutes ago
    past_time = now - timedelta(minutes=10)
    job_past = await scheduler.schedule_job(
        user_id=1001,
        chat_id=2001,
        prompt="Past overdue task",
        due_at=past_time
    )

    # Job 2: Due right now
    job_now = await scheduler.schedule_job(
        user_id=1001,
        chat_id=2001,
        prompt="Current task",
        due_at=now
    )

    # Job 3: Due 2 hours in the future
    future_time = now + timedelta(hours=2)
    job_future = await scheduler.schedule_job(
        user_id=1001,
        chat_id=2001,
        prompt="Future task",
        due_at=future_time
    )

    # Extract due jobs as of now
    due_jobs = await scheduler.get_due_jobs(as_of=now)
    due_ids = [j.job_id for j in due_jobs]

    assert job_past.job_id in due_ids
    assert job_now.job_id in due_ids
    assert job_future.job_id not in due_ids


@pytest.mark.asyncio
async def test_job_completion(temp_db):
    """Test marking a due job as completed and verifying state updates."""
    scheduler = JobScheduler(db=temp_db)
    now = datetime.now(timezone.utc)

    job = await scheduler.schedule_job(
        user_id=1001,
        chat_id=2001,
        prompt="Send report",
        due_at=now - timedelta(seconds=1)
    )

    # Confirm it is due
    due_before = await scheduler.get_due_jobs()
    assert any(j.job_id == job.job_id for j in due_before)

    # Complete job
    success = await scheduler.complete_job(job.job_id)
    assert success is True

    # Verify no longer in due jobs
    due_after = await scheduler.get_due_jobs()
    assert not any(j.job_id == job.job_id for j in due_after)

    # Verify status in database
    completed_job = await scheduler.get_job(job.job_id)
    assert completed_job.status == JobStatus.COMPLETED
    assert completed_job.last_run_at is not None


@pytest.mark.asyncio
async def test_job_cancellation(temp_db):
    """Test cancelling scheduled jobs with authorization and status validation."""
    scheduler = JobScheduler(db=temp_db)
    now = datetime.now(timezone.utc)

    job = await scheduler.schedule_job(
        user_id=1001,
        chat_id=2001,
        prompt="Cancel me",
        due_at=now + timedelta(hours=1)
    )

    # 1. Attempt cancel with wrong user_id -> should fail
    wrong_user_cancel = await scheduler.cancel_job(job.job_id, user_id=9999)
    assert wrong_user_cancel is False

    # 2. Cancel with correct user_id -> should succeed
    success = await scheduler.cancel_job(job.job_id, user_id=1001)
    assert success is True

    # 3. Verify status changed to cancelled
    cancelled_job = await scheduler.get_job(job.job_id)
    assert cancelled_job.status == JobStatus.CANCELLED

    # 4. Cancelling an already cancelled job returns False
    second_cancel = await scheduler.cancel_job(job.job_id)
    assert second_cancel is False


@pytest.mark.asyncio
async def test_list_jobs_and_user_isolation(temp_db):
    """Test listing jobs with user isolation and status filters."""
    scheduler = JobScheduler(db=temp_db)
    now = datetime.now(timezone.utc)

    # User A has 2 active jobs and 1 completed job
    j_a1 = await scheduler.schedule_job(user_id=111, chat_id=10, prompt="Task A1", due_at=now + timedelta(minutes=5))
    j_a2 = await scheduler.schedule_job(user_id=111, chat_id=10, prompt="Task A2", due_at=now + timedelta(minutes=10))
    j_a3 = await scheduler.schedule_job(user_id=111, chat_id=10, prompt="Task A3", due_at=now + timedelta(minutes=15))
    await scheduler.complete_job(j_a3.job_id)

    # User B has 1 active job
    j_b1 = await scheduler.schedule_job(user_id=222, chat_id=20, prompt="Task B1", due_at=now + timedelta(minutes=5))

    # Test user isolation for User A
    user_a_active = await scheduler.list_jobs(user_id=111, status="active")
    assert len(user_a_active) == 2
    assert set(j.job_id for j in user_a_active) == {j_a1.job_id, j_a2.job_id}

    # Test all jobs for User A (active + completed)
    user_a_all = await scheduler.list_jobs(user_id=111)
    assert len(user_a_all) == 3

    # Test user isolation for User B
    user_b_jobs = await scheduler.list_jobs(user_id=222)
    assert len(user_b_jobs) == 1
    assert user_b_jobs[0].job_id == j_b1.job_id


def test_parse_time_delta_or_iso(temp_db):
    """Test natural language relative time deltas and ISO string parser."""
    scheduler = JobScheduler(db=temp_db)
    now = datetime.now(timezone.utc)

    # Relative expressions
    t_10s = scheduler.parse_time_delta_or_iso("10s")
    assert 9 <= (t_10s - now).total_seconds() <= 11

    t_5m = scheduler.parse_time_delta_or_iso("in 5m")
    assert 295 <= (t_5m - now).total_seconds() <= 305

    t_2h = scheduler.parse_time_delta_or_iso("2 hours")
    assert 7190 <= (t_2h - now).total_seconds() <= 7210

    t_1d = scheduler.parse_time_delta_or_iso("in 1 day")
    assert 86390 <= (t_1d - now).total_seconds() <= 86410

    # ISO format
    iso_str = "2026-08-30T15:00:00+00:00"
    t_iso = scheduler.parse_time_delta_or_iso(iso_str)
    assert t_iso == datetime(2026, 8, 30, 15, 0, 0, tzinfo=timezone.utc)

    # Invalid expression raises ValueError
    with pytest.raises(ValueError, match="Unable to parse time expression"):
        scheduler.parse_time_delta_or_iso("whenever you feel like it")


@pytest.mark.asyncio
async def test_run_due_jobs_callback_execution(temp_db):
    """Test batch execution runner of due jobs with async callback."""
    scheduler = JobScheduler(db=temp_db)
    now = datetime.now(timezone.utc)

    j1 = await scheduler.schedule_job(user_id=1, chat_id=1, prompt="Task 1", due_at=now - timedelta(seconds=5))
    j2 = await scheduler.schedule_job(user_id=1, chat_id=1, prompt="Task 2", due_at=now - timedelta(seconds=2))
    j3 = await scheduler.schedule_job(user_id=1, chat_id=1, prompt="Future Task", due_at=now + timedelta(hours=1))

    executed_prompts = []

    async def mock_executor(job: ScheduledJob):
        executed_prompts.append(job.prompt)

    executed_jobs = await scheduler.run_due_jobs(mock_executor)

    assert len(executed_jobs) == 2
    assert executed_prompts == ["Task 1", "Task 2"]

    # Verify executed jobs are marked completed
    assert (await scheduler.get_job(j1.job_id)).status == JobStatus.COMPLETED
    assert (await scheduler.get_job(j2.job_id)).status == JobStatus.COMPLETED
    # Future job remains active
    assert (await scheduler.get_job(j3.job_id)).status == JobStatus.ACTIVE
