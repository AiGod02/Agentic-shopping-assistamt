"""
Weaviate Search — hybrid semantic + keyword search for listings.

Combines BM25 keyword matching with vector similarity for best results.
Falls back to PostgreSQL full-text search when Weaviate is unavailable or empty.
"""

from __future__ import annotations

from typing import Any

import httpx

from agent_server.config import settings
from shared.middleware.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from shared.observability.logging import get_logger
from shared.observability.metrics import search_queries_total
from shared.observability.request_context import trace_log

logger = get_logger(__name__)

weaviate_breaker = CircuitBreaker("weaviate", CircuitBreakerConfig(failure_threshold=5, timeout_seconds=30))

LISTING_CLASS = "Listing"

# Weaviate search engine class definition
class WeaviateSearch:
    """Hybrid search using Weaviate — BM25 + vector similarity."""

    def __init__(self, url: str | None = None) -> None:
        import os
        raw_url = (url or os.getenv("WEAVIATE_URL") or getattr(settings, "weaviate_url", "") or "http://localhost:8080").strip('"\'')
        if raw_url and not raw_url.startswith("http://") and not raw_url.startswith("https://"):
            if "weaviate.cloud" in raw_url or "weaviate.network" in raw_url:
                raw_url = "https://" + raw_url
            else:
                raw_url = "http://" + raw_url
        self.base_url = raw_url.rstrip("/")
        self.api_key = os.getenv("WEAVIATE_API_KEY") or getattr(settings, "weaviate_api_key", "")
        self.headers = {}
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
            self.headers["X-Weaviate-Api-Key"] = self.api_key

    def _is_cloud(self) -> bool:
        return "weaviate.cloud" in self.base_url or "weaviate.network" in self.base_url

    def _build_v4_filter(
        self,
        listing_type: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        tags: list[str] | None = None,
        merchant_id: str | None = None,
    ):
        try:
            from weaviate.classes.query import Filter
            filters = []
            if listing_type:
                filters.append(Filter.by_property("listing_type").equal(listing_type))
            if min_price is not None:
                filters.append(Filter.by_property("base_price").greater_or_equal(float(min_price)))
            if max_price is not None:
                filters.append(Filter.by_property("base_price").less_or_equal(float(max_price)))
            if merchant_id:
                filters.append(Filter.by_property("merchant_id").equal(str(merchant_id)))
            if not filters:
                return None
            res = filters[0]
            for f in filters[1:]:
                res = res & f
            return res
        except Exception:
            return None

    async def hybrid_search(
        self,
        query: str,
        listing_type: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        location: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        alpha: float = 0.8,
        merchant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a hybrid search combining semantic and keyword matching."""
        trace_log("search.weaviate_start", backend="weaviate", query=query, url=self.base_url)
        logger.info("weaviate_search_started", query=query, base_url=self.base_url)

        try:
            # 1. Try modern weaviate-client v4 Collections API (gRPC supported, works on Weaviate Cloud)
            import weaviate
            from weaviate.classes.init import Auth
            from weaviate.classes.query import MetadataQuery

            v4_filters = self._build_v4_filter(listing_type, min_price, max_price, tags, merchant_id)

            if self._is_cloud():
                client_ctx = weaviate.use_async_with_weaviate_cloud(
                    cluster_url=self.base_url,
                    auth_credentials=Auth.api_key(self.api_key) if self.api_key else None,
                )
            else:
                import urllib.parse
                parsed = urllib.parse.urlparse(self.base_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 8080
                client_ctx = weaviate.use_async_with_local(
                    host=host,
                    port=port,
                    grpc_port=50051,
                )

            async with client_ctx as client:
                col = client.collections.get(LISTING_CLASS)
                response = await col.query.hybrid(
                    query=query,
                    filters=v4_filters,
                    limit=limit,
                    alpha=alpha,
                    return_metadata=MetadataQuery(score=True, distance=True),
                )

                listings = []
                for obj in response.objects:
                    p = obj.properties
                    meta = obj.metadata
                    distance = meta.distance if meta else None
                    if distance is not None and distance > 0.90:
                        continue
                    listings.append({
                        "id": str(p.get("listing_id") or obj.uuid),
                        "title": p.get("title", ""),
                        "description": p.get("description", ""),
                        "type": p.get("listing_type", ""),
                        "base_price": float(p.get("base_price") or 0),
                        "currency": p.get("currency", "USD"),
                        "rating_avg": float(p.get("rating_avg") or 0),
                        "tags": p.get("tags") or [],
                        "score": meta.score if meta else 0,
                        "distance": distance,
                        "source": "weaviate",
                    })

                search_queries_total.labels(search_type="hybrid", service="agent-server").inc()
                trace_log("search.weaviate_done", after_filter=len(listings))
                logger.info("weaviate_search_completed", query=query, base_url=self.base_url, result_count=len(listings))

                if listings:
                    trace_log("search.weaviate_success", returning=len(listings), source="weaviate")
                    return listings

        except Exception as v4_err:
            logger.warning("weaviate_v4_failed_trying_http", error=str(v4_err))

        # 2. Fallback to HTTP GraphQL (for local Weaviate instances where GraphQL is enabled)
        try:
            where_filter = self._build_filter(listing_type, min_price, max_price, tags, merchant_id)
            graphql_query = {
                "query": self._build_graphql(query, where_filter, limit, alpha),
            }

            @weaviate_breaker.protect
            async def _search():
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    response = await client.post(
                        f"{self.base_url}/v1/graphql",
                        json=graphql_query,
                        headers=self.headers,
                    )
                    response.raise_for_status()
                    return response.json()

            result = await _search()
            listings = []
            data = (result.get("data") or {}).get("Get", {}).get(LISTING_CLASS) or []
            for item in data:
                distance = item.get("_additional", {}).get("distance")
                if distance is not None and distance > 0.90:
                    continue
                listings.append({
                    "id": item.get("listing_id", ""),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "type": item.get("listing_type", ""),
                    "base_price": item.get("base_price", 0),
                    "currency": item.get("currency", "USD"),
                    "rating_avg": item.get("rating_avg", 0),
                    "tags": item.get("tags", []),
                    "score": item.get("_additional", {}).get("score", 0),
                    "distance": distance,
                    "source": "weaviate",
                })

            if listings:
                search_queries_total.labels(search_type="hybrid", service="agent-server").inc()
                return listings

        except Exception as e:
            trace_log("search.weaviate_failed_fallback_chroma", error=str(e))
            logger.error("weaviate_search_failed_falling_back_to_chroma", error=str(e), query=query, base_url=self.base_url)

        search_queries_total.labels(search_type="hybrid_fallback", service="agent-server").inc()
        return await self._chroma_fallback(
            query, listing_type, min_price, max_price, location, tags, limit, alpha, merchant_id
        )

    async def _chroma_fallback(
        self,
        query: str,
        listing_type: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        location: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        alpha: float = 0.8,
        merchant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fallback to local ChromaDB vector search if Weaviate is unavailable or empty."""
        trace_log("search.chroma_fallback_start", query=query)
        try:
            from agent_server.core.chroma_search import ChromaSearch
            chroma = ChromaSearch()
            res = await chroma.hybrid_search(
                query=query,
                listing_type=listing_type,
                min_price=min_price,
                max_price=max_price,
                location=location,
                tags=tags,
                limit=limit,
                alpha=alpha,
                merchant_id=merchant_id,
            )
            if res:
                trace_log("search.chroma_fallback_success", results=len(res), source="chromadb")
                logger.info("chroma_fallback_search_success", query=query, results=len(res))
                return res
            trace_log("search.chroma_fallback_empty_fallback_postgres")
        except Exception as e:
            trace_log("search.chroma_fallback_failed_fallback_postgres", error=str(e))
            logger.error("chroma_fallback_failed", error=str(e), query=query)


        return await self._postgres_fallback(
            query, listing_type, min_price, max_price, tags, limit, merchant_id
        )

    async def _postgres_fallback(
        self,
        query: str,
        listing_type: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        merchant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fallback to PostgreSQL full-text search via Merchant Server API."""
        trace_log("search.postgres_fallback_start", query=query)
        try:
            params: dict[str, Any] = {"q": query, "page_size": limit}
            if listing_type:
                params["type"] = listing_type
            if min_price is not None:
                params["min_price"] = min_price
            if max_price is not None:
                params["max_price"] = max_price
            if tags:
                params["tags"] = ",".join(tags)
            if merchant_id:
                params["merchant_id"] = merchant_id

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{settings.merchant_server_url}/api/v1/listings",
                    params=params,
                )
                response.raise_for_status()
                data = response.json()

            listings = []
            for item in data.get("items", []):
                listings.append({
                    "id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "type": item.get("type", ""),
                    "base_price": item.get("base_price", 0),
                    "currency": item.get("currency", "USD"),
                    "rating_avg": item.get("rating_avg", 0),
                    "tags": item.get("tags", []),
                    "score": 0,
                    "distance": None,
                    "source": "postgresql",
                })

            search_queries_total.labels(search_type="postgres_fallback", service="agent-server").inc()
            trace_log("search.postgres_fallback_done", results=len(listings), source="postgresql")
            logger.info("postgres_fallback_search", query=query, results=len(listings))
            return listings

        except Exception as e:
            trace_log("search.postgres_fallback_failed", error=str(e))
            logger.error("postgres_fallback_failed", error=str(e), query=query)
            return []

    async def semantic_search(
        self,
        query: str,
        merchant_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Pure vector similarity search."""
        if not merchant_id:
            raise ValueError("merchant_id is required for semantic_search")
        return await self.hybrid_search(query, limit=limit, alpha=1.0, merchant_id=merchant_id)

    async def keyword_search(
        self,
        query: str,
        merchant_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Pure BM25 keyword search."""
        if not merchant_id:
            raise ValueError("merchant_id is required for keyword_search")
        return await self.hybrid_search(query, limit=limit, alpha=0.0, merchant_id=merchant_id)

    async def create_listing_object(self, listing: dict[str, Any]) -> bool:
        """Index a listing in Weaviate."""
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.post(
                    f"{self.base_url}/v1/objects",
                    json={
                        "class": LISTING_CLASS,
                        "properties": {
                            "listing_id": listing.get("id", ""),
                            "title": listing.get("title", ""),
                            "description": listing.get("description", ""),
                            "listing_type": listing.get("type", ""),
                            "base_price": listing.get("base_price", 0),
                            "currency": listing.get("currency", "USD"),
                            "tags": listing.get("tags", []),
                            "rating_avg": listing.get("rating_avg", 0),
                            "merchant_id": listing.get("merchant_id", ""),
                            "status": listing.get("status", "draft"),
                        },
                    },
                    headers=self.headers,
                )
                return response.status_code in (200, 201)
        except Exception as e:
            logger.error("weaviate_index_failed", error=str(e))
            return False

    async def create_schema(self) -> bool:
        """Create classes in Weaviate (idempotent)."""
        schema = {
            "class": LISTING_CLASS,
            "description": "Commerce listing — products, hotels, rentals, services, etc.",
            "vectorizer": "text2vec-openai",
            "moduleConfig": {
                "text2vec-openai": {
                    "vectorizeClassName": False,
                    "model": "text-embedding-3-small",
                },
            },
            "properties": [
                {"name": "listing_id", "dataType": ["text"], "moduleConfig": {"text2vec-transformers": {"skip": True}}},
                {"name": "title", "dataType": ["text"], "moduleConfig": {"text2vec-transformers": {"skip": False, "vectorizePropertyName": False}}},
                {"name": "description", "dataType": ["text"], "moduleConfig": {"text2vec-transformers": {"skip": False, "vectorizePropertyName": False}}},
                {"name": "listing_type", "dataType": ["text"], "moduleConfig": {"text2vec-transformers": {"skip": False, "vectorizePropertyName": False}}},
                {"name": "base_price", "dataType": ["number"], "moduleConfig": {"text2vec-transformers": {"skip": True}}},
                {"name": "currency", "dataType": ["text"], "moduleConfig": {"text2vec-transformers": {"skip": True}}},
                {"name": "tags", "dataType": ["text[]"], "moduleConfig": {"text2vec-transformers": {"skip": False, "vectorizePropertyName": False}}},
                {"name": "rating_avg", "dataType": ["number"], "moduleConfig": {"text2vec-transformers": {"skip": True}}},
                {"name": "merchant_id", "dataType": ["text"], "moduleConfig": {"text2vec-transformers": {"skip": True}}},
                {"name": "status", "dataType": ["text"], "moduleConfig": {"text2vec-transformers": {"skip": True}}},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Create listing schema
                response = await client.post(
                    f"{self.base_url}/v1/schema", json=schema, headers=self.headers
                )
                listing_ok = response.status_code in (200, 201, 422)

                # Create UserMemory schema
                memory_schema = {
                    "class": "UserMemory",
                    "description": "User episodic long-term memories",
                    "vectorizer": "text2vec-transformers",
                    "properties": [
                        {"name": "user_id", "dataType": ["text"], "moduleConfig": {"text2vec-transformers": {"skip": True}}},
                        {"name": "memory_text", "dataType": ["text"], "moduleConfig": {"text2vec-transformers": {"skip": False}}},
                        {"name": "timestamp", "dataType": ["text"], "moduleConfig": {"text2vec-transformers": {"skip": True}}},
                    ]
                }
                response_mem = await client.post(
                    f"{self.base_url}/v1/schema", json=memory_schema, headers=self.headers
                )
                memory_ok = response_mem.status_code in (200, 201, 422)

                return listing_ok and memory_ok
        except Exception as e:
            logger.error("weaviate_schema_failed", error=str(e))
            return False

    def _build_filter(
        self,
        listing_type: str | None,
        min_price: float | None,
        max_price: float | None,
        tags: list[str] | None,
        merchant_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Build Weaviate where filter."""
        operands = []

        if listing_type:
            operands.append({
                "path": ["listing_type"],
                "operator": "Equal",
                "valueText": listing_type,
            })
        if min_price is not None:
            operands.append({
                "path": ["base_price"],
                "operator": "GreaterThanEqual",
                "valueNumber": min_price,
            })
        if max_price is not None:
            operands.append({
                "path": ["base_price"],
                "operator": "LessThanEqual",
                "valueNumber": max_price,
            })
        if merchant_id:
            operands.append({
                "path": ["merchant_id"],
                "operator": "Equal",
                "valueText": str(merchant_id),
            })

        if not operands:
            return None
        if len(operands) == 1:
            return operands[0]
        return {"operator": "And", "operands": operands}

    def _format_graphql_value(self, val: Any) -> str:
        """Recursively format Python values to GraphQL (unquoted Enums/Keys)."""
        if isinstance(val, str):
            if val in ("Equal", "NotEqual", "GreaterThan", "GreaterThanEqual", "LessThan", "LessThanEqual", "And", "Or"):
                return val
            return f'"{val}"'
        if isinstance(val, list):
            return "[" + ", ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in val) + "]"
        if isinstance(val, dict):
            items = []
            for k, v in val.items():
                items.append(f"{k}: {self._format_graphql_value(v)}")
            return "{" + ", ".join(items) + "}"
        return str(val)

    def _build_graphql(
        self,
        query: str,
        where_filter: dict[str, Any] | None,
        limit: int,
        alpha: float,
    ) -> str:
        """Build GraphQL query for hybrid search."""
        where_clause = ""
        if where_filter:
            where_clause = f", where: {self._format_graphql_value(where_filter)}"

        # Escape quotes in query to prevent GraphQL injection
        safe_query = query.replace('"', '\\"').replace("\n", " ")

        return f"""
        {{
            Get {{
                {LISTING_CLASS}(
                    hybrid: {{
                        query: "{safe_query}"
                        alpha: {alpha}
                    }}
                    limit: {limit}
                    {where_clause}
                ) {{
                    listing_id
                    title
                    description
                    listing_type
                    base_price
                    currency
                    tags
                    rating_avg
                    _additional {{
                        score
                        distance
                    }}
                }}
            }}
        }}
        """

    async def save_user_memory(self, user_id: str, memory_text: str) -> None:
        """Save a user fact to Weaviate and PostgreSQL."""
        import datetime
        import uuid

        # 1. Save to Weaviate
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/objects",
                    json={
                        "class": "UserMemory",
                        "properties": {
                            "user_id": user_id,
                            "memory_text": memory_text,
                            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        },
                    },
                    headers=self.headers,
                )
                logger.info("weaviate_saved_user_memory", user_id=user_id, status=response.status_code)
        except Exception as e:
            logger.error("weaviate_save_memory_failed", error=str(e))

        # 2. Save to PostgreSQL
        from shared.db.session import get_db_session
        from sqlalchemy import text
        try:
            async with get_db_session() as session:
                await session.execute(
                    text("INSERT INTO user_memories (id, user_id, memory_text, created_at) VALUES (:id, :uid, :text, NOW())"),
                    {"id": str(uuid.uuid4()), "uid": user_id, "text": memory_text}
                )
                await session.commit()
                logger.info("weaviate_sql_saved_user_memory", user_id=user_id)
        except Exception as e:
            logger.error("weaviate_sql_save_memory_failed", error=str(e))

    async def retrieve_user_memories(self, user_id: str, query: str | None = None, limit: int = 5) -> list[str]:
        """Retrieve user facts from Weaviate."""
        safe_query = query.replace('"', '\\"').replace("\n", " ") if query else "*"
        hybrid_args = ""
        if query and query != "*":
            hybrid_args = f'hybrid: {{ query: "{safe_query}", alpha: 0.7 }}'

        gql = f"""
        {{
            Get {{
                UserMemory(
                    limit: {limit}
                    where: {{
                        path: ["user_id"]
                        operator: Equal
                        valueText: "{user_id}"
                    }}
                    {hybrid_args}
                ) {{
                    memory_text
                }}
            }}
        }}
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/graphql",
                    json={"query": gql},
                    headers=self.headers,
                )
                response.raise_for_status()
                data = response.json()
                items = data.get("data", {}).get("Get", {}).get("UserMemory", [])
                memories = [item.get("memory_text") for item in items if item.get("memory_text")]
                if memories:
                    return memories
        except Exception as e:
            logger.error("weaviate_retrieve_memories_failed", error=str(e))

        # Fallback to ChromaDB user memory retrieval
        try:
            from agent_server.core.chroma_search import ChromaSearch
            chroma = ChromaSearch()
            return await chroma.retrieve_user_memories(user_id=user_id, query=query, limit=limit)
        except Exception as e:
            logger.error("chroma_retrieve_memories_fallback_failed", error=str(e))
            return []
