"""
Kafka Consumer — async event consumer with error handling.

Supports consumer groups, offset management, and dead-letter processing.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Coroutine

from aiokafka import AIOKafkaConsumer, ConsumerRecord

from shared.observability.logging import get_logger

logger = get_logger(__name__)

EventHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class EventConsumer:
    """Async Kafka consumer with robust error handling.

    Usage:
        consumer = EventConsumer(
            topics=["orders", "payments"],
            bootstrap_servers="kafka:9092",
            group_id="merchant-server",
        )
        consumer.register_handler("order.created", handle_order_created)
        consumer.register_handler("payment.captured", handle_payment_captured)
        await consumer.start()
    """

    def __init__(
        self,
        topics: list[str],
        bootstrap_servers: str,
        group_id: str,
        max_retries: int = 3,
        dead_letter_topic: str | None = None,
    ) -> None:
        self.topics = topics
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.max_retries = max_retries
        self.dead_letter_topic = dead_letter_topic or f"{group_id}.dead-letter"
        self._handlers: dict[str, EventHandler] = {}
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False

    def register_handler(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._handlers[event_type] = handler
        logger.info("handler_registered", event_type=event_type, handler=handler.__name__)

    async def start(self) -> None:
        """Start consuming events."""
        import os
        
        consumer_kwargs = {
            "bootstrap_servers": self.bootstrap_servers,
            "group_id": self.group_id,
            "value_deserializer": lambda v: json.loads(v.decode("utf-8")),
            "auto_offset_reset": "earliest",
            "enable_auto_commit": False,
            "max_poll_interval_ms": 300000,
        }

        sasl_mechanism = os.getenv("KAFKA_SASL_MECHANISM")
        security_protocol = os.getenv("KAFKA_SECURITY_PROTOCOL")
        sasl_username = os.getenv("KAFKA_SASL_USERNAME")
        sasl_password = os.getenv("KAFKA_SASL_PASSWORD")

        if security_protocol:
            consumer_kwargs["security_protocol"] = security_protocol
        if sasl_mechanism:
            consumer_kwargs["sasl_mechanism"] = sasl_mechanism
        if sasl_username:
            consumer_kwargs["sasl_plain_username"] = sasl_username
        if sasl_password:
            consumer_kwargs["sasl_plain_password"] = sasl_password

        self._consumer = AIOKafkaConsumer(*self.topics, **consumer_kwargs)
        await self._consumer.start()
        self._running = True
        logger.info("consumer_started", topics=self.topics, group=self.group_id)

        try:
            async for record in self._consumer:
                await self._process_record(record)
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop consuming events."""
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None
            logger.info("consumer_stopped", group=self.group_id)

    async def _process_record(self, record: ConsumerRecord) -> None:
        """Process a single Kafka record with retry logic."""
        try:
            envelope = record.value
            event_type = envelope.get("event_type", "unknown")

            handler = self._handlers.get(event_type)
            if handler is None:
                logger.warning(
                    "no_handler_for_event",
                    event_type=event_type,
                    topic=record.topic,
                )
                await self._consumer.commit()
                return

            retries = 0
            while retries <= self.max_retries:
                try:
                    await handler(envelope)
                    await self._consumer.commit()
                    logger.info(
                        "event_processed",
                        event_type=event_type,
                        event_id=envelope.get("event_id"),
                        topic=record.topic,
                        partition=record.partition,
                        offset=record.offset,
                    )
                    return
                except Exception:
                    retries += 1
                    if retries > self.max_retries:
                        logger.exception(
                            "event_processing_failed_max_retries",
                            event_type=event_type,
                            event_id=envelope.get("event_id"),
                            retries=retries,
                        )
                        await self._send_to_dead_letter(record, envelope)
                        await self._consumer.commit()
                        return
                    logger.warning(
                        "event_processing_retry",
                        event_type=event_type,
                        retry=retries,
                    )

        except Exception:
            logger.exception("record_processing_error", topic=record.topic)
            await self._consumer.commit()

    async def _send_to_dead_letter(
        self, record: ConsumerRecord, envelope: dict[str, Any]
    ) -> None:
        """Send failed event to dead-letter topic."""
        from shared.events.kafka_producer import publish_event

        try:
            await publish_event(
                topic=self.dead_letter_topic,
                event_type="dead_letter",
                payload={
                    "original_topic": record.topic,
                    "original_event": envelope,
                    "error": "Max retries exceeded",
                },
                source=self.group_id,
            )
            logger.info(
                "sent_to_dead_letter",
                event_id=envelope.get("event_id"),
                dead_letter_topic=self.dead_letter_topic,
            )
        except Exception:
            logger.exception("dead_letter_send_failed")
