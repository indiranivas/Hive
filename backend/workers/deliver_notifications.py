"""Drain the notification outbox.

Delivery needs the Bot Framework SDK and a stored conversation reference, so this
task is the seam between "Hive decided to tell someone" and "Teams delivered it".
Rows it cannot deliver stay pending with the reason recorded -- nothing is lost.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from api.core.db import session_scope
from api.services.kr_routing_graph import pending_notifications
from bot.proactive import get_conversation
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


@celery_app.task(name="workers.deliver_notifications.deliver", bind=True)
def deliver(self) -> dict:
    sent = skipped = failed = 0
    with session_scope() as session:
        for notification in pending_notifications(session):
            notification.attempts += 1

            if notification.person_id is None:
                # Channel-wide posts need a team conversation reference, which only
                # exists once the app is installed in a Teams channel.
                notification.last_error = "no channel conversation reference"
                skipped += 1
                continue

            reference = get_conversation(session, notification.person_id)
            if not reference:
                notification.last_error = "person has never messaged @Hive"
                skipped += 1
                continue

            try:
                from bot.sender import send_notification

                send_notification(reference, notification)
            except Exception as exc:  # noqa: BLE001 - keep draining the rest
                notification.last_error = str(exc)[:500]
                if notification.attempts >= MAX_ATTEMPTS:
                    notification.status = "failed"
                failed += 1
                logger.warning("notification %s not delivered: %s", notification.id, exc)
                continue

            notification.status = "sent"
            notification.sent_at = datetime.now(UTC)
            notification.last_error = None
            sent += 1

    summary = {"sent": sent, "skipped": skipped, "failed": failed}
    logger.info("notification drain: %s", summary)
    return summary
