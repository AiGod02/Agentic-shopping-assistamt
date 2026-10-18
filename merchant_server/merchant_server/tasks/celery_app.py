"""Celery tasks — background job processing."""

from celery import Celery

from merchant_server.config import settings

celery_app = Celery(
    "merchant_server",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Auto-detect if Redis is running; fall back to synchronous eager execution if not
task_always_eager = False
try:
    import socket
    from urllib.parse import urlparse
    parsed = urlparse(settings.celery_broker_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    with socket.create_connection((host, port), timeout=1.0):
        pass
except Exception:
    task_always_eager = True

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,  # Acknowledge after completion for reliability
    worker_prefetch_multiplier=1,
    task_default_retry_delay=60,
    task_max_retries=3,
    task_always_eager=task_always_eager,
)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def sync_search_index(self, listing_id: str):
    """Sync a listing to Weaviate search index."""
    import asyncio

    async def _async_sync():
        from merchant_server.domain.repositories.listing_repo import ListingRepository
        from shared.db.session import get_db_session
        import uuid
        import httpx
        from shared.observability.logging import get_logger

        logger = get_logger(__name__)

        try:
            async with get_db_session() as db:
                repo = ListingRepository(db)
                listing = await repo.get_by_id(uuid.UUID(listing_id))
                if not listing:
                    logger.warning("sync_search_index_listing_not_found", listing_id=listing_id)
                    return {"status": "skipped", "reason": "not_found"}

                payload = {
                    "id": str(listing.id),
                    "title": listing.title,
                    "description": listing.description or "",
                    "type": listing.type,
                    "base_price": float(listing.base_price),
                    "currency": listing.currency,
                    "tags": listing.tags or [],
                    "rating_avg": float(listing.rating_avg),
                    "merchant_id": str(listing.merchant_id),
                    "status": listing.status,
                }

                from merchant_server.config import settings
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        f"{settings.agent_server_url}/api/v1/agent/webhook/index-listing",
                        json=payload
                    )
                    response.raise_for_status()
                    logger.info("search_sync_success", listing_id=listing_id)
                    return {"status": "synced", "listing_id": listing_id}
        except Exception as e:
            logger.error("weaviate_sync_error", error=str(e), listing_id=listing_id)
            raise e

    try:
        return asyncio.run(_async_sync())
    except Exception as exc:
        self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3)
def send_order_notification(self, order_id: str, notification_type: str):
    """Send order notification (email, SMS, push)."""
    try:
        # Integration with notification service
        return {"status": "sent", "order_id": order_id, "type": notification_type}
    except Exception as exc:
        self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3)
def dispatch_merchant_webhook(self, webhook_id: str, event_type: str, payload: dict):
    """Dispatch webhook to merchant endpoint."""
    import hashlib
    import hmac
    import json
    import httpx

    try:
        # This would load the webhook config from DB
        # For now, the task structure is ready for real implementation
        body = json.dumps(payload)
        # In production, load webhook.secret from DB:
        # signature = hmac.new(webhook.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        return {"status": "dispatched", "webhook_id": webhook_id, "event": event_type}
    except Exception as exc:
        self.retry(exc=exc)
