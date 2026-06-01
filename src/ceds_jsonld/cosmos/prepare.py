"""Document preparation utilities for Cosmos DB.

Transforms JSON-LD documents into Cosmos-ready format by injecting the
required ``id`` and ``partitionKey`` fields.
"""

from __future__ import annotations

import copy
from typing import Any

from ceds_jsonld.exceptions import CosmosError

# Characters that Cosmos DB does not permit in the ``id`` field.
_COSMOS_INVALID_CHARS = "/\\?#"
_COSMOS_REPLACEMENT = "|"


def sanitize_cosmos_id(uri: str) -> str:
    """Derive a Cosmos DB-safe ``id`` from a URI or IRI string.

    Replaces every ``/`` character with ``|``, preserving the full URI so
    that the resulting ``id`` is unique across entity types.

    Args:
        uri: The source URI (typically the JSON-LD ``@id`` value).

    Returns:
        The sanitized string with ``/`` replaced by ``|``.

    Raises:
        CosmosError: If the resulting ``id`` is empty.

    Example::

        >>> from ceds_jsonld.cosmos import sanitize_cosmos_id
        >>> sanitize_cosmos_id("cepi:person/12345")
        'cepi:person|12345'
        >>> sanitize_cosmos_id("https://cepi.org/person/12345")
        'https:|cepi.org|person|12345'
        >>> sanitize_cosmos_id("plain-id-no-slash")
        'plain-id-no-slash'
    """
    result = uri.replace("/", _COSMOS_REPLACEMENT)
    if not result:
        msg = (
            f"Cannot derive Cosmos 'id' from URI {uri!r}. "
            "The value is empty. Ensure every document has a non-empty @id."
        )
        raise CosmosError(msg)
    return result


def prepare_for_cosmos(
    doc: dict[str, Any],
    *,
    partition_value: str | None = None,
    id_field: str = "@id",
) -> dict[str, Any]:
    """Prepare a JSON-LD document for Cosmos DB upsert.

    Cosmos DB requires a string ``id`` at the document root and benefits
    from an explicit ``partitionKey`` field.  This function copies the
    original document (no mutation) and injects both fields.

    The ``id`` is derived from the full value of *id_field* with ``/``
    replaced by ``|`` via :func:`sanitize_cosmos_id`.  This preserves
    the complete URI (avoiding ID collisions between entity types) while
    producing a Cosmos-safe string.

    Args:
        doc: A JSON-LD document dict (must contain *id_field*).
        partition_value: Value for the ``partitionKey`` field.  Defaults to
            the document's ``@type`` if not provided.
        id_field: The key in *doc* that holds the document identifier.
            Defaults to ``"@id"``.

    Returns:
        A deep copy of *doc* with ``id`` and ``partitionKey`` injected.

    Raises:
        KeyError: If *id_field* is missing from *doc*.
        CosmosError: If the sanitized ``id`` is empty.

    Example::

        >>> from ceds_jsonld.cosmos import prepare_for_cosmos
        >>> doc = {"@id": "cepi:person/12345", "@type": "Person"}
        >>> cosmos_doc = prepare_for_cosmos(doc)
        >>> cosmos_doc["id"]
        'cepi:person|12345'
        >>> cosmos_doc["partitionKey"]
        'Person'
    """
    if id_field not in doc:
        msg = f"Document is missing '{id_field}'. Cannot prepare for Cosmos DB. Available keys: {sorted(doc.keys())}"
        raise KeyError(msg)

    raw_id = str(doc[id_field])

    if not raw_id:
        msg = (
            f"Cannot derive Cosmos 'id' from {id_field}={raw_id!r}. "
            "The value is empty. Ensure every document has a non-empty @id."
        )
        raise CosmosError(msg)

    cosmos_doc = copy.deepcopy(doc)
    cosmos_doc["id"] = sanitize_cosmos_id(raw_id)

    # Partition key: explicit value, or fall back to @type.
    if partition_value is not None:
        cosmos_doc["partitionKey"] = partition_value
    elif "@type" in doc:
        doc_type = doc["@type"]
        # When @type is a list (e.g. ["Organization", "K12School"]),
        # use the first element as the partition key.
        if isinstance(doc_type, list):
            cosmos_doc["partitionKey"] = str(doc_type[0])
        else:
            cosmos_doc["partitionKey"] = str(doc_type)
    else:
        cosmos_doc["partitionKey"] = cosmos_doc["id"]

    return cosmos_doc
