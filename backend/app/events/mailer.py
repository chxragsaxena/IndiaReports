"""Sends queued emails, retrying failures with growing delays.

Safe on many instances at once (rows are claimed with SKIP LOCKED). An email is marked sent
only after the provider accepted it, so a crash between the two re-sends rather than loses it:
at-least-once delivery, which for a status notice is the right side to err on."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.mailer import SendError, email_enabled, send_email
from app.db.session import AsyncSessionLocal
from app.models.email import EmailJob

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
IDLE_SECONDS = 5.0
KEEP_SENT_DAYS = 7
PRUNE_EVERY_SECONDS = 3600

Sender = Callable[[str, str, str], Awaitable[None]]


def retry_delay(attempts: int) -> timedelta:
    """1 min, 2, 4, 8, ... capped at 6 hours."""
    return timedelta(seconds=min(60 * 2 ** max(attempts - 1, 0), 6 * 3600))


async def send_pending_once(sender: Sender = send_email) -> int:
    """Send one batch of due emails. Returns how many were sent."""
    sent = 0
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        jobs = (
            await db.execute(
                select(EmailJob)
                .where(
                    EmailJob.sent_at.is_(None),
                    EmailJob.attempts < settings.EMAIL_MAX_ATTEMPTS,
                    EmailJob.next_attempt_at <= now,
                )
                .order_by(EmailJob.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        for job in jobs:
            try:
                await sender(job.to_email, job.subject, job.body)
            except SendError as e:
                job.attempts += 1
                job.next_attempt_at = now + retry_delay(job.attempts)
                job.last_error = str(e)[:500]
                if job.attempts >= settings.EMAIL_MAX_ATTEMPTS:
                    logger.error("giving up on email %s after %d attempts: %s", job.id, job.attempts, e)
                else:
                    logger.warning("email %s failed (attempt %d), will retry: %s", job.id, job.attempts, e)
            else:
                job.sent_at = now
                job.last_error = None
                sent += 1
        await db.commit()
    return sent


async def prune_sent() -> int:
    async with AsyncSessionLocal() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_SENT_DAYS)
        result = await db.execute(delete(EmailJob).where(EmailJob.sent_at < cutoff))
        await db.commit()
        return result.rowcount or 0


async def run_mailer(stop: asyncio.Event) -> None:
    """Background loop. A provider or database error only delays email; it never raises."""
    if not email_enabled():
        logger.info("email is not configured: citizen and officer emails are off")
        return
    since_prune = 0.0
    while not stop.is_set():
        try:
            if await send_pending_once() == BATCH_SIZE:
                continue
            since_prune += IDLE_SECONDS
            if since_prune >= PRUNE_EVERY_SECONDS:
                since_prune = 0.0
                await prune_sent()
        except Exception:
            logger.warning("mailer run failed, retrying", exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=IDLE_SECONDS)
        except asyncio.TimeoutError:
            pass
