"""
ChromaDB Search — lightweight vector search for local development.

Replaces the 8GB Weaviate+Transformers Docker setup with a pure Python
solution that runs in-process. Provides the same interface as WeaviateSearch.

Install: pip install chromadb
Model: all-MiniLM-L6-v2 (~90MB, auto-downloaded on first use)
"""

from __future__ import annotations

import re
from typing import Any
import httpx

from agent_server.config import settings
from shared.observability.logging import get_logger
from shared.observability.metrics import search_queries_total

logger = get_logger(__name__)

_chroma_client = None
_collection = None

COLLECTION_NAME = "listings"


def _get_collection():
    """Lazy-init ChromaDB client and collection."""
    global _chroma_client, _collection

    if _collection is not None:
        return _collection

    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        raise ImportError(
            "chromadb not installed. Run: pip install chromadb"
        )

    embedding_fn = None
    if settings.openai_api_key:
        try:
            embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
                api_key=settings.openai_api_key,
                model_name="text-embedding-3-small"
            )
            logger.info("using_openai_embeddings", model="text-embedding-3-small")
        except Exception as e:
            logger.error("openai_embedding_init_failed_falling_back", error=str(e))

    if embedding_fn is None:
        try:
            # Use DefaultEmbeddingFunction (local ONNX, fast, no external network hang)
            embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        except Exception:
            logger.warning("default_embedding_not_available")


    import pathlib
    project_root = pathlib.Path(__file__).resolve().parent.parent.parent.parent
    chroma_path = str(project_root / "chroma_data")

    _chroma_client = chromadb.PersistentClient(path=chroma_path)
    _collection = _chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
        embedding_function=embedding_fn
    )
    logger.info("chromadb_initialized", path=chroma_path, count=_collection.count(), model="openai" if settings.openai_api_key and embedding_fn else ("multilingual" if embedding_fn else "default"))
    return _collection


def prewarm_model() -> None:
    """Pre-warm sentence-transformer embedding model at application startup to avoid live cold-start latency."""
    try:
        logger.info("prewarming_embedding_model_starting")
        coll = _get_collection()
        logger.info("prewarming_embedding_model_complete", document_count=coll.count() if coll else 0)
    except Exception as e:
        logger.error("prewarm_embedding_model_failed", error=str(e))


class ChromaSearch:
    """Local vector search using ChromaDB — no Docker required.

    Provides the same interface as WeaviateSearch so the rest of the
    codebase doesn't need to know which backend is active.
    """

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
            logger.info("chromadb_postgres_fallback_search", query=query, results=len(listings))
            return listings

        except Exception as e:
            logger.error("chromadb_postgres_fallback_failed", error=str(e), query=query)
            return []

    async def hybrid_search(
        self,
        query: str,
        listing_type: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        location: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        alpha: float = 0.5,
        merchant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search listings using ChromaDB vector similarity."""
        try:
            collection = _get_collection()

            if collection.count() == 0:
                logger.info("chromadb_empty_collection_falling_back")
                return await self._postgres_fallback(
                    query, listing_type, min_price, max_price, tags, limit, merchant_id
                )

            # 1. Category/Keyword inference
            category_keyword = None
            q_lower = query.lower().strip()
            if re.search(r"\b(?:laptop|laptops|notebook|macbook)\b", q_lower):
                category_keyword = "laptop"
            elif re.search(r"\b(?:phone|phones|smartphone|galaxy|iphone)\b", q_lower):
                category_keyword = "phone"
            elif re.search(r"\b(?:tv|tvs|television|oled)\b", q_lower):
                category_keyword = "tv"
            elif re.search(r"\b(?:tablet|tablets|ipad)\b", q_lower):
                category_keyword = "tablet"
            elif re.search(r"\b(?:hotel|hotels|room|stay)\b", q_lower):
                category_keyword = "hotel"
            elif re.search(r"\b(?:villa|rental|resort)\b", q_lower):
                category_keyword = "rental"

            # Build where filter for ChromaDB
            where_filter = self._build_filter(listing_type, min_price, max_price, tags, merchant_id)

            query_params: dict[str, Any] = {
                "query_texts": [query],
                "n_results": min(max(limit * 3, 20), collection.count()),  # Fetch all candidates for filtering
            }
            if where_filter:
                query_params["where"] = where_filter

            results = collection.query(**query_params)

            raw_listings = []
            seen_ids = set()
            if results and results["metadatas"]:
                for i, metadata in enumerate(results["metadatas"][0]):
                    listing_id = metadata.get("listing_id", "")
                    # Deduplicate by listing_id
                    if not listing_id or listing_id in seen_ids:
                        continue
                    seen_ids.add(listing_id)

                    title = metadata.get("title", "")
                    tags_str = metadata.get("tags", "")
                    item_type = metadata.get("listing_type", "")
                    doc_text = (results["documents"][0][i] if results.get("documents") else "").lower()

                    # Hard category boundary filter when category_keyword is inferable
                    if category_keyword:
                        matches_cat = (
                            category_keyword in title.lower() or
                            category_keyword in tags_str.lower() or
                            category_keyword in item_type.lower() or
                            category_keyword in doc_text
                        )
                        if not matches_cat:
                            continue

                    distance = results["distances"][0][i] if results.get("distances") else None
                    score = 1 - (distance or 0)  # Convert distance to similarity
                    
                    # Boost score if category match
                    boost = 0.0
                    if category_keyword and (category_keyword in title.lower() or category_keyword in tags_str.lower()):
                        boost += 0.5

                    final_relevance = score + boost

                    raw_listings.append({
                        "id": listing_id,
                        "title": title,
                        "description": (results["documents"][0][i] if results.get("documents") else ""),
                        "type": item_type,
                        "base_price": metadata.get("base_price", 0),
                        "currency": metadata.get("currency", "USD"),
                        "rating_avg": metadata.get("rating_avg", 0),
                        "tags": tags_str.split(",") if tags_str else [],
                        "score": max(0.0, final_relevance),
                        "distance": distance,
                        "source": "chromadb",
                    })

            # Sort primarily by relevance score, with rating as tie-breaker
            sorted_listings = sorted(
                raw_listings,
                key=lambda x: (x["score"], x.get("rating_avg", 0)),
                reverse=True
            )
            listings = sorted_listings[:limit]

            search_queries_total.labels(search_type="chromadb", service="agent-server").inc()
            logger.info("chromadb_search_completed", query=query, result_count=len(listings), item_ids=[x.get("id") for x in listings])

            if not listings:
                logger.info("chromadb_empty_results_falling_back", query=query)
                return await self._postgres_fallback(
                    query, listing_type, min_price, max_price, tags, limit, merchant_id
                )


            return listings

        except Exception as e:
            logger.error("chromadb_search_failed_falling_back", error=str(e), query=query)
            return await self._postgres_fallback(
                query, listing_type, min_price, max_price, tags, limit, merchant_id
            )

    async def semantic_search(self, query: str, merchant_id: str, limit: int = 10) -> list[dict[str, Any]]:
        if not merchant_id:
            raise ValueError("merchant_id is required for semantic_search")
        return await self.hybrid_search(query, limit=limit, alpha=1.0, merchant_id=merchant_id)

    async def keyword_search(self, query: str, merchant_id: str, limit: int = 10) -> list[dict[str, Any]]:
        if not merchant_id:
            raise ValueError("merchant_id is required for keyword_search")
        return await self.hybrid_search(query, limit=limit, alpha=0.0, merchant_id=merchant_id)

    async def create_listing_object(self, listing: dict[str, Any]) -> bool:
        """Index a listing in ChromaDB."""
        try:
            collection = _get_collection()
            listing_id = listing.get("id", "")

            # ChromaDB document = text we want to make searchable
            document = f"{listing.get('title', '')} {listing.get('description', '')} {listing.get('type', '')}"
            tags = listing.get("tags", [])
            if tags:
                document += " " + " ".join(tags)

            # Store metadata for filtering
            metadata = {
                "listing_id": listing_id,
                "title": listing.get("title", ""),
                "listing_type": listing.get("type", ""),
                "base_price": float(listing.get("base_price", 0)),
                "currency": listing.get("currency", "USD"),
                "rating_avg": float(listing.get("rating_avg", 0)),
                "merchant_id": listing.get("merchant_id", ""),
                "status": listing.get("status", "draft"),
                "tags": ",".join(tags) if tags else "",
            }

            collection.upsert(
                ids=[listing_id],
                documents=[document],
                metadatas=[metadata],
            )
            logger.info("chromadb_indexed", listing_id=listing_id, title=listing.get("title"))
            return True

        except Exception as e:
            logger.error("chromadb_index_failed", error=str(e))
            return False

    async def create_schema(self) -> bool:
        """ChromaDB doesn't need explicit schema — collection is auto-created."""
        try:
            _get_collection()
            return True
        except Exception as e:
            logger.error("chromadb_schema_failed", error=str(e))
            return False

    def _build_filter(
        self,
        listing_type: str | None,
        min_price: float | None,
        max_price: float | None,
        tags: list[str] | None = None,
        merchant_id: str | None = None,
        category_keyword: str | None = None,
    ) -> dict[str, Any] | None:
        """Build ChromaDB where filter."""
        conditions = []

        if listing_type:
            conditions.append({"listing_type": {"$eq": listing_type}})
        if min_price is not None:
            conditions.append({"base_price": {"$gte": min_price}})
        if max_price is not None:
            conditions.append({"base_price": {"$lte": max_price}})
        if merchant_id:
            conditions.append({"merchant_id": {"$eq": str(merchant_id)}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    async def save_user_memory(self, user_id: str, memory_text: str) -> None:
        """Save a user-specific episodic preference/fact to long-term memory (both Vector and SQL DB)."""
        import uuid
        from datetime import datetime, timezone
        from shared.db.session import get_db_session
        from sqlalchemy import text

        # 1. Save to Vector Store (ChromaDB)
        try:
            collection = _get_memory_collection()
            memory_id = str(uuid.uuid4())
            collection.add(
                ids=[memory_id],
                documents=[memory_text],
                metadatas=[{"user_id": user_id, "timestamp": datetime.now(timezone.utc).isoformat()}]
            )
            logger.info("saved_user_episodic_memory_vector", user_id=user_id, memory_id=memory_id)
        except Exception as e:
            logger.error("failed_to_save_user_episodic_memory_vector", error=str(e))

        # 2. Save to Relational Database (PostgreSQL)
        try:
            async with get_db_session() as session:
                await session.execute(
                    text("""
                        INSERT INTO user_memories (id, user_id, memory_text, created_at)
                        VALUES (:id, :uid, :text, NOW())
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "uid": user_id,
                        "text": memory_text,
                    }
                )
                await session.commit()
                logger.info("saved_user_episodic_memory_sql", user_id=user_id)
        except Exception as e:
            logger.error("failed_to_save_user_episodic_memory_sql", error=str(e))

    async def retrieve_user_memories(self, user_id: str, query: str | None = None, limit: int = 5) -> list[str]:
        """Retrieve user-specific long-term preferences matching a concept, or the latest ones."""
        try:
            collection = _get_memory_collection()
            if collection.count() == 0:
                return []

            # Filter by user_id
            query_params: dict[str, Any] = {
                "where": {"user_id": user_id},
                "n_results": min(limit, collection.count())
            }
            if query:
                query_params["query_texts"] = [query]
            else:
                # If no specific semantic search query, query anything but filter by user
                query_params["query_texts"] = ["*"]

            results = collection.query(**query_params)
            memories = []
            if results and results["documents"]:
                for document_list in results["documents"]:
                    for doc in document_list:
                        memories.append(doc)
            return memories
        except Exception as e:
            logger.error("failed_to_retrieve_user_memories", error=str(e))
            return []


_memory_collection = None

def _get_memory_collection():
    """Lazy-init ChromaDB client and collection for user long-term episodic memory."""
    global _chroma_client, _memory_collection

    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        raise ImportError("chromadb not installed")

    if _memory_collection is not None:
        return _memory_collection

    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path="./chroma_data")

    # Use same embedding function
    embedding_fn = None
    if settings.openai_api_key:
        try:
            embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
                api_key=settings.openai_api_key,
                model_name="text-embedding-3-small"
            )
        except Exception:
            pass

    if embedding_fn is None:
        try:
            embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="paraphrase-multilingual-MiniLM-L12-v2"
            )
        except Exception:
            pass

    _memory_collection = _chroma_client.get_or_create_collection(
        name="agent_memories",
        metadata={"hnsw:space": "cosine"},
        embedding_function=embedding_fn
    )
    return _memory_collection
