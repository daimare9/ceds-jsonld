"""JSON serialization utilities — orjson with stdlib fallback.

orjson (Rust-backed) is ~10x faster than stdlib json for serialization.
This module provides a unified API regardless of which backend is available.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ceds_jsonld.exceptions import SerializationError


def _reject_non_finite(obj: Any) -> None:
    """Raise SerializationError if *obj* contains non-finite floats.

    JSON-LD is a strict subset of RFC 8259 JSON which does not permit
    bare ``NaN``, ``Infinity``, or ``-Infinity`` tokens.  This pre-check
    ensures consistent rejection regardless of the serialization backend.
    """
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        msg = (
            f"Cannot serialize non-finite float value {obj!r} to JSON. "
            f"NaN and Infinity are not valid JSON per RFC 8259. "
            f"Clean the data before serialization."
        )
        raise SerializationError(msg)
    if isinstance(obj, dict):
        for v in obj.values():
            _reject_non_finite(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _reject_non_finite(v)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

try:
    import orjson

    _BACKEND = "orjson"

    def dumps(obj: Any, *, pretty: bool = False) -> bytes:
        """Serialize a Python object to JSON bytes.

        Args:
            obj: The object to serialize.
            pretty: If True, indent with 2 spaces.

        Returns:
            UTF-8 encoded JSON bytes.

        Raises:
            SerializationError: If serialization fails.
        """
        try:
            _reject_non_finite(obj)
            option = orjson.OPT_INDENT_2 if pretty else 0
            return orjson.dumps(obj, option=option)
        except Exception as exc:
            msg = f"Failed to serialize object: {exc}"
            raise SerializationError(msg) from exc

    def loads(data: bytes | str) -> Any:
        """Deserialize JSON bytes or string to a Python object.

        Args:
            data: JSON bytes or string.

        Returns:
            Parsed Python object.

        Raises:
            SerializationError: If deserialization fails.
        """
        try:
            return orjson.loads(data)
        except Exception as exc:
            msg = f"Failed to deserialize JSON: {exc}"
            raise SerializationError(msg) from exc

except ImportError:
    import json as _json

    _BACKEND = "json"

    def dumps(obj: Any, *, pretty: bool = False) -> bytes:  # type: ignore[misc]
        """Serialize a Python object to JSON bytes (stdlib fallback).

        Raises:
            SerializationError: If serialization fails.
        """
        try:
            _reject_non_finite(obj)
            indent = 2 if pretty else None
            return _json.dumps(
                obj,
                indent=indent,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except Exception as exc:
            msg = f"Failed to serialize object: {exc}"
            raise SerializationError(msg) from exc

    def loads(data: bytes | str) -> Any:  # type: ignore[misc]
        """Deserialize JSON bytes or string (stdlib fallback).

        Raises:
            SerializationError: If deserialization fails.
        """
        try:
            return _json.loads(data)
        except Exception as exc:
            msg = f"Failed to deserialize JSON: {exc}"
            raise SerializationError(msg) from exc


def get_backend() -> str:
    """Return the name of the active JSON backend ('orjson' or 'json')."""
    return _BACKEND


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------


def write_json(obj: Any, path: str | Path, *, pretty: bool = True) -> int:
    """Serialize an object and write it to a JSON file.

    Args:
        obj: The object to serialize.
        path: Output file path.
        pretty: If True, indent with 2 spaces.

    Returns:
        Number of bytes written.

    Raises:
        SerializationError: If serialization or file writing fails.
    """
    try:
        data = dumps(obj, pretty=pretty)
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return len(data)
    except SerializationError:
        raise
    except Exception as exc:
        msg = f"Failed to write JSON to {path}: {exc}"
        raise SerializationError(msg) from exc


def read_json(path: str | Path) -> Any:
    """Read and parse a JSON file.

    Args:
        path: Input file path.

    Returns:
        Parsed Python object.

    Raises:
        SerializationError: If reading or parsing fails.
    """
    try:
        data = Path(path).read_bytes()
        return loads(data)
    except Exception as exc:
        msg = f"Failed to read JSON from {path}: {exc}"
        raise SerializationError(msg) from exc
