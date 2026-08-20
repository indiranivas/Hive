"""Proactive messaging support.

Storage lives here and is exercised in Phase 2 (every turn records where the
person can be reached). The actual outbound send is a thin adapter call, wired up
by the dependency router in Phase 5.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from api.models.orm import BotConversation

logger = logging.getLogger(__name__)


def remember_conversation(session: Session, person_id: uuid.UUID,
                          reference: dict[str, Any]) -> BotConversation:
    """Upsert the conversation reference for a person."""
    record = session.get(BotConversation, person_id)
    service_url = reference.get("serviceUrl") or reference.get("service_url")
    if record is None:
        record = BotConversation(
            person_id=person_id,
            service_url=service_url,
            conversation_reference=reference,
        )
        session.add(record)
    else:
        record.conversation_reference = reference
        record.service_url = service_url or record.service_url
    session.flush()
    return record


def get_conversation(session: Session, person_id: uuid.UUID) -> dict[str, Any] | None:
    record = session.get(BotConversation, person_id)
    return dict(record.conversation_reference) if record else None


def serialize_reference(reference: Any) -> dict[str, Any]:
    """Convert a Bot Framework ConversationReference into a plain dict.

    The SDK's models are msrest-based; which serializer exists has varied across
    versions, so try each and fall back to __dict__ rather than raising.
    """
    if reference is None:
        return {}
    if isinstance(reference, dict):
        return reference
    for method in ("serialize", "as_dict"):
        serializer = getattr(reference, method, None)
        if callable(serializer):
            try:
                return dict(serializer())
            except Exception:  # noqa: BLE001 - fall through to the next strategy
                logger.debug("reference.%s() failed", method, exc_info=True)
    return {
        key: value
        for key, value in vars(reference).items()
        if not key.startswith("_") and isinstance(value, (str, int, float, bool, dict, list))
    }
