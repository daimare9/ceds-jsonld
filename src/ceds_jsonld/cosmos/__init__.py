"""Cosmos DB integration for ceds-jsonld.

Provides :class:`CosmosLoader` for uploading JSON-LD documents to Azure
Cosmos DB NoSQL, plus the :func:`prepare_for_cosmos` utility for adapting
JSON-LD documents to Cosmos requirements.
"""

from __future__ import annotations

from ceds_jsonld.cosmos.loader import CosmosLoader
from ceds_jsonld.cosmos.prepare import prepare_for_cosmos, sanitize_cosmos_id

__all__ = [
    "CosmosLoader",
    "prepare_for_cosmos",
    "sanitize_cosmos_id",
]
