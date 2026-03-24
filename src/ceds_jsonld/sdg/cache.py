"""File-based value cache for LLM-generated synthetic data.

Caches LLM-generated value pools to disk so they can be reused across runs
without re-invoking the LLM. Cache files are stored per-shape and per-property,
keyed by model name (different model = different cache).

Default cache location: ``~/.ceds_jsonld/cache/synthetic_values/{shape}/``

Each cache file is a JSON document::

    {
        "property_iri": "http://ceds.ed.gov/terms#P000115",
        "property_label": "First Name",
        "model": "Qwen/Qwen3-4B",
        "generated_at": "2026-02-08T14:30:00",
        "count": 200,
        "values": ["Maria", "James", ...]
    }
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ceds_jsonld.logging import get_logger

_log = get_logger(__name__)

_DEFAULT_CACHE_DIR = Path.home() / ".ceds_jsonld" / "cache" / "synthetic_values"


def _safe_filename(name: str) -> str:
    """Convert a property name/IRI to a safe filename component."""
    # Use the fragment (after #) or last path component
    if "#" in name:
        name = name.rsplit("#", 1)[-1]
    elif "/" in name:
        name = name.rsplit("/", 1)[-1]
    # Replace any remaining unsafe chars
    return "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)


class ValueCache:
    """Disk-backed cache for LLM-generated value pools.

    Example:
        >>> cache = ValueCache()
        >>> cache.put("person", "http://ceds.ed.gov/terms#P000115",
        ...           "First Name", "Qwen/Qwen3-4B",
        ...           ["Maria", "James", "Sophia"])
        >>> cache.get("person", "http://ceds.ed.gov/terms#P000115",
        ...           "Qwen/Qwen3-4B")
        ['Maria', 'James', 'Sophia']
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        """Initialize the cache.

        Args:
            cache_dir: Root directory for cache files. Defaults to
                ``~/.ceds_jsonld/cache/synthetic_values/``.
        """
        self._cache_dir = cache_dir or _DEFAULT_CACHE_DIR

    def _cache_path(
        self,
        shape_name: str,
        property_iri: str,
        model: str,
    ) -> Path:
        """Build the file path for a cached property."""
        prop_name = _safe_filename(property_iri)
        model_safe = _safe_filename(model)
        return self._cache_dir / shape_name / f"{prop_name}_{model_safe}.json"

    def get(
        self,
        shape_name: str,
        property_iri: str,
        model: str,
    ) -> list[str] | None:
        """Retrieve cached values for a property.

        Args:
            shape_name: Shape name (e.g. "person").
            property_iri: Full IRI of the property.
            model: Model identifier used for generation.

        Returns:
            List of cached string values, or ``None`` on cache miss.
        """
        path = self._cache_path(shape_name, property_iri, model)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            values = data.get("values")
            if isinstance(values, list) and len(values) > 0:
                _log.debug(
                    "Cache hit",
                    shape=shape_name,
                    property=property_iri,
                    count=len(values),
                )
                return values
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("Cache read failed, treating as miss", error=str(exc))
        return None

    def put(
        self,
        shape_name: str,
        property_iri: str,
        property_label: str,
        model: str,
        values: list[str],
    ) -> Path:
        """Store generated values in the cache.

        Args:
            shape_name: Shape name (e.g. "person").
            property_iri: Full IRI of the property.
            property_label: Human-readable label for the cache file.
            model: Model identifier used for generation.
            values: List of generated string values.

        Returns:
            The path where the cache file was written.
        """
        path = self._cache_path(shape_name, property_iri, model)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "property_iri": property_iri,
            "property_label": property_label,
            "model": model,
            "generated_at": datetime.now(UTC).isoformat(),
            "count": len(values),
            "values": values,
        }

        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _log.debug(
            "Cache written",
            shape=shape_name,
            property=property_iri,
            count=len(values),
            path=str(path),
        )
        return path

    def has(
        self,
        shape_name: str,
        property_iri: str,
        model: str,
    ) -> bool:
        """Check if a cache entry exists without reading it.

        Args:
            shape_name: Shape name.
            property_iri: Full IRI of the property.
            model: Model identifier.

        Returns:
            ``True`` if the cache file exists and is non-empty.
        """
        path = self._cache_path(shape_name, property_iri, model)
        return path.exists() and path.stat().st_size > 0

    def clear(self, shape_name: str | None = None) -> int:
        """Remove cached files.

        Args:
            shape_name: If given, clear only cache for this shape.
                If ``None``, clear the entire cache.

        Returns:
            Number of files removed.
        """
        target = self._cache_dir / shape_name if shape_name else self._cache_dir
        if not target.exists():
            return 0

        count = 0
        for f in target.rglob("*.json"):
            f.unlink()
            count += 1

        # Clean up empty directories
        if shape_name:
            try:
                target.rmdir()
            except OSError:
                pass  # Directory not empty or doesn't exist

        _log.info("Cache cleared", shape=shape_name or "all", files_removed=count)
        return count
