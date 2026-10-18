"""
Kafka Producer — async event producer with in-memory fallback.

When Kafka is unavailable, events are logged to stdout instead of being
published to a topic. This allows the platform to function without Kafka.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from shared.middleware.request_id import get_request_id
from shared.observability.logging import get_logger

logger = get_logger(__name__)

_producer: Any = None
_using_fallback = False


async def init_kafka_producer(bootstrap_servers: str) -> Any:
    """Initialize Kafka producer — falls back to log-only if Kafka is unavailable."""
    global _producer, _using_fallback

    try:
        from aiokafka import AIOKafkaProducer

        import os
        
        producer_kwargs = {
            "bootstrap_servers": bootstrap_servers,
            "value_serializer": lambda v: json.dumps(v, default=str).encode("utf-8"),
            "key_serializer": lambda k: k.encode("utf-8") if k else None,
            "acks": "all",
            "retries": 5,
            "retry_backoff_ms": 100,
            "max_request_size": 1048576,
            "enable_idempotence": True,
        }

        sasl_mechanism = os.getenv("KAFKA_SASL_MECHANISM")
        security_protocol = os.getenv("KAFKA_SECURITY_PROTOCOL")
        sasl_username = os.getenv("KAFKA_SASL_USERNAME")
        sasl_password = os.getenv("KAFKA_SASL_PASSWORD")

        if security_protocol:
            producer_kwargs["security_protocol"] = security_protocol
        if sasl_mechanism:
            producer_kwargs["sasl_mechanism"] = sasl_mechanism
        if sasl_username:
            producer_kwargs["sasl_plain_username"] = sasl_username
        if sasl_password:
            producer_kwargs["sasl_plain_password"] = sasl_password

        _producer = AIOKafkaProducer(**producer_kwargs)
        await _producer.start()
        _using_fallback = False
        logger.info("kafka_producer_started", servers=bootstrap_servers)
    except Exception as e:
        logger.warning("kafka_unavailable_using_log_fallback", error=str(e))
        _producer = None
        _using_fallback = True

    return _producer


async def close_kafka_producer() -> None:
    """Gracefully close the Kafka producer."""
    global _producer, _using_fallback
    if _producer and not _using_fallback:
        await _producer.stop()
        _producer = None
        logger.info("kafka_producer_stopped")
    _using_fallback = False


def _build_envelope(
    event_type: str,
    payload: dict[str, Any],
    source: str,
    aggregate_id: str | None = None,
) -> dict[str, Any]:
    """Build a structured event envelope."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "source": source,
        "aggregate_id": aggregate_id,
        "correlation_id": get_request_id() or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0",
        "payload": payload,
    }


async def publish_event(
    topic: str,
    event_type: str,
    payload: dict[str, Any],
    source: str,
    key: str | None = None,
    aggregate_id: str | None = None,
) -> None:
    """Publish a structured event to Kafka, or log it if Kafka is unavailable.

    Args:
        topic: Kafka topic name
        event_type: Event type identifier (e.g., 'order.created')
        payload: Event payload data
        source: Source service name
        key: Partition key for ordering guarantees
        aggregate_id: Aggregate root ID for event sourcing
    """
    envelope = _build_envelope(event_type, payload, source, aggregate_id)

    if _using_fallback or _producer is None:
        # Log-only fallback — events are printed but not lost
        logger.info(
            "event_logged_fallback",
            topic=topic,
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload_keys=list(payload.keys()),
        )
        return

    try:
        record = await _producer.send_and_wait(
            topic=topic,
            value=envelope,
            key=key or aggregate_id,
        )
        logger.info(
            "event_published",
            topic=topic,
            event_type=event_type,
            partition=record.partition,
            offset=record.offset,
            aggregate_id=aggregate_id,
        )
    except Exception:
        logger.exception(
            "event_publish_failed_logging_instead",
            topic=topic,
            event_type=event_type,
            aggregate_id=aggregate_id,
        )
        # Don't raise — log and continue so the request isn't broken


async def save_outbox_event(
    db_session: Any,
    topic: str,
    event_type: str,
    payload: dict[str, Any],
    source: str,
    key: str | None = None,
) -> None:
    """Save an event to the outbox database table inside a database transaction."""
    from sqlalchemy import text
    import uuid

    event_id = str(uuid.uuid4())
    await db_session.execute(
        text("""
            INSERT INTO outbox_events (id, topic, event_type, payload, source, key, status)
            VALUES (:id, :topic, :event_type, :payload, :source, :key, 'pending')
        """),
        {
            "id": event_id,
            "topic": topic,
            "event_type": event_type,
            "payload": json.dumps(payload, default=str),
            "source": source,
            "key": key,
        }
    )
    logger.info("outbox_event_saved", event_id=event_id, event_type=event_type)


async def process_outbox_events(db_session: Any) -> int:
    """Fetch pending outbox events, publish to Kafka, and mark as sent."""
    from sqlalchemy import text
    import datetime

    # Lock and fetch pending events to avoid multi-worker processing races
    result = await db_session.execute(
        text("""
            SELECT id, topic, event_type, payload, source, key 
            FROM outbox_events 
            WHERE status = 'pending' 
            ORDER BY created_at 
            LIMIT 50 
            FOR UPDATE SKIP LOCKED
        """)
    )
    rows = result.all()
    if not rows:
        return 0

    processed_count = 0
    for row in rows:
        event_id, topic, event_type, payload_raw, source, key = row
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
        
        try:
            # Attempt to publish to Kafka
            await publish_event(
                topic=topic,
                event_type=event_type,
                payload=payload,
                source=source,
                key=key,
                aggregate_id=key,
            )
            
            # Update status to sent
            await db_session.execute(
                text("""
                    UPDATE outbox_events 
                    SET status = 'sent', processed_at = :now 
                    WHERE id = :id
                """),
                {"id": event_id, "now": datetime.datetime.now(datetime.timezone.utc)}
            )
            processed_count += 1
        except Exception as e:
            logger.error("outbox_event_publish_failed", event_id=str(event_id), error=str(e))
            await db_session.execute(
                text("UPDATE outbox_events SET status = 'failed' WHERE id = :id"),
                {"id": event_id}
            )

    await db_session.commit()
    return processed_count
