"""Document preparation utilities for Cosmos DB.

Transforms JSON-LD documents into Cosmos-ready format by injecting the
required ``id`` and ``partitionKey`` fields.
"""

from __future__ import annotations

import copy
from typing import Any

from ceds_jsonld.exceptions import CosmosError


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

    Args:
        doc: A JSON-LD document dict (must contain *id_field*).
        partition_value: Value for the ``partitionKey`` field.  Defaults to
            the document's ``@type`` if not provided.
        id_field: The key in *doc* that holds the document identifier.
            Defaults to ``"@id"``.  The URI prefix is stripped automatically
            (everything up to and including the last ``/`` or ``#``).

    Returns:
        A deep copy of *doc* with ``id`` and ``partitionKey`` injected.

    Raises:
        KeyError: If *id_field* is missing from *doc*.
        CosmosError: If the derived ``id`` is empty.

    Example::

        >>> from ceds_jsonld.cosmos import prepare_for_cosmos
        >>> doc = {"@id": "cepi:person/12345", "@type": "Person", ...}
        >>> cosmos_doc = prepare_for_cosmos(doc)
        >>> cosmos_doc["id"]
        '12345'
        >>> cosmos_doc["partitionKey"]
        'Person'
    """
    if id_field not in doc:
        msg = f"Document is missing '{id_field}'. Cannot prepare for Cosmos DB. Available keys: {sorted(doc.keys())}"
        raise KeyError(msg)

    cosmos_doc = copy.deepcopy(doc)

    # Extract the trailing identifier from the URI.
    # Split on both '/' and '#' separators — URIs may use either as the
    # namespace delimiter (e.g. "cepi:person/12345" or "cepi:person#12345").
    raw_id = str(doc[id_field])
    # First split on '#' (fragment), then on '/' (path), taking the last segment.
    last_segment = raw_id.rsplit("#", 1)[-1] if "#" in raw_id else raw_id
    derived_id = last_segment.rsplit("/", 1)[-1] if "/" in last_segment else last_segment

    if not derived_id:
        msg = (
            f"Cannot derive Cosmos 'id' from {id_field}={raw_id!r}. "
            "The value is empty or ends with '/' yielding an empty identifier. "
            "Ensure every document has a non-empty @id with a meaningful trailing segment."
        )
        raise CosmosError(msg)

    cosmos_doc["id"] = derived_id

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
