"""IRI sanitization — protect against injection in ``@id`` construction.

Ensures values used as IRI components in ``@id`` fields cannot contain
characters that would break the IRI structure or allow injection attacks.
"""

from __future__ import annotations

import re
import unicodedata

#: Pattern matching path traversal sequences (``../``, ``..\\``, leading ``./``).
_PATH_TRAVERSAL_RE = re.compile(r"\.\.[/\\]|[/\\]\.\.|^\.\.|\.\.%|%2[eE]%2[eE]")

#: Characters allowed in the local part of an IRI (after the base URI prefix).
#: Alphanumerics, hyphens, underscores, dots, and tildes are safe.
#: Note: ``/`` is intentionally EXCLUDED — a component value (e.g. a person
#: identifier) should never contain path separators.  Slashes in user input
#: would allow path traversal when the IRI is resolved against a base.
_SAFE_IRI_RE = re.compile(r"^[A-Za-z0-9._~:@!$&'()*+,;=-]+$")

#: Characters that MUST be percent-encoded in an IRI local part.
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._~:@!$&'()*+,;=-]")


def sanitize_iri_component(value: str) -> str:
    """Sanitize a string for use as an IRI local component.

    Percent-encodes any characters that are not safe in an IRI reference.
    Also strips leading/trailing whitespace and normalises Unicode to NFC.
    Forward slashes are always percent-encoded since they should not appear
    in identifier components.  Path traversal sequences (``../``) are
    detected and their dots are also encoded.

    Args:
        value: The raw value to embed in an IRI (e.g. a person identifier).

    Returns:
        A safe string suitable for use in ``@id`` values.

    Raises:
        ValueError: If the value is empty after sanitization.

    Example:
        >>> sanitize_iri_component("989897099")
        '989897099'
        >>> sanitize_iri_component("hello world/<script>")
        'hello%20world%2F%3Cscript%3E'
        >>> sanitize_iri_component("../../../etc/passwd")
        '%2E%2E%2F%2E%2E%2F%2E%2E%2Fetc%2Fpasswd'
    """
    # Normalise Unicode and strip whitespace
    value = unicodedata.normalize("NFC", value.strip())

    if not value:
        msg = "IRI component cannot be empty"
        raise ValueError(msg)

    # Detect path traversal BEFORE the fast path — traversal sequences use
    # characters that would otherwise be individually "safe".
    if _PATH_TRAVERSAL_RE.search(value):
        return _encode_all(value)

    # Fast path: value is already safe (no slashes, no unsafe chars)
    if _SAFE_IRI_RE.match(value):
        return value

    # Percent-encode unsafe characters (includes / now)
    def _encode_char(match: re.Match[str]) -> str:
        char = match.group(0)
        return "".join(f"%{b:02X}" for b in char.encode("utf-8"))

    return _UNSAFE_CHARS.sub(_encode_char, value)


def _encode_all(value: str) -> str:
    """Percent-encode every character that is not alphanumeric or ``-_~``.

    Used for values that contain path traversal sequences where dots and
    slashes must all be encoded to neutralise the traversal.
    """
    safe = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_~")
    parts: list[str] = []
    for ch in value:
        if ch in safe:
            parts.append(ch)
        else:
            parts.extend(f"%{b:02X}" for b in ch.encode("utf-8"))
    return "".join(parts)


def sanitize_string_value(value: str) -> str:
    """Strip null bytes and other control characters from a field value.

    Removes all Unicode control characters — C0 (U+0000–U+001F), DEL
    (U+007F), and C1 (U+0080–U+009F) — except tab (U+0009), newline
    (U+000A), and carriage return (U+000D).  These have no legitimate use
    in education data and can cause problems in downstream systems (XML/RDF
    serialization, HTML rendering, data interchange).

    Args:
        value: The raw string value from a mapped field.

    Returns:
        The cleaned string with control characters removed.

    Example:
        >>> sanitize_string_value("Jane\\x00Doe")
        'JaneDoe'
        >>> sanitize_string_value("Jane\\x7fDoe")
        'JaneDoe'
    """
    return value.translate(_CONTROL_CHAR_TABLE)


#: Translation table that maps dangerous control characters to None (removal).
#: Covers C0 (0x00–0x1F), DEL (0x7F), and C1 (0x80–0x9F).
#: Keeps tab (0x09), newline (0x0A), and carriage return (0x0D).
_CONTROL_CHAR_TABLE: dict[int, None] = {
    c: None for c in (*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0)) if c not in (0x09, 0x0A, 0x0D)
}


def validate_base_uri(base_uri: str) -> str:
    """Validate that a base URI is well-formed.

    Checks for common injection patterns and ensures the URI ends with
    a separator character (``/`` or ``#``).

    Args:
        base_uri: The base URI prefix (e.g. ``"cepi:person/"``).

    Returns:
        The validated base URI.

    Raises:
        ValueError: If the base URI is malformed or contains suspicious content.
    """
    if not base_uri:
        msg = "Base URI cannot be empty"
        raise ValueError(msg)

    # Block obvious injection attempts
    suspicious = ["<script", "javascript:", "data:", "\x00", "\n", "\r"]
    lower = base_uri.lower()
    for pattern in suspicious:
        if pattern in lower:
            msg = f"Base URI contains suspicious content: {base_uri!r}"
            raise ValueError(msg)

    # Reject whitespace characters (space, tab, vertical tab, form feed).
    # These are invalid in URIs per RFC 3986.
    if re.search(r"[\s]", base_uri):
        msg = (
            f"Base URI contains whitespace characters: {base_uri!r}. "
            "URIs must not contain spaces, tabs, or other whitespace."
        )
        raise ValueError(msg)

    # Reject dangerous URI schemes that could enable local file access or
    # other unintended resolution.
    _dangerous_schemes = ("file:", "ftp:")
    if lower.startswith(_dangerous_schemes):
        msg = (
            f"Base URI uses a disallowed scheme: {base_uri!r}. "
            "Only http:, https:, urn:, and compact-IRI prefixes are permitted."
        )
        raise ValueError(msg)

    # Reject percent-encoded path traversal (e.g. %2E%2E/ which decodes
    # to ../).  This catches double-encoding attacks.
    if (
        re.search(r"%2[eE]%2[eE][/\\#]", base_uri)
        or re.search(r"%2[eE]\.", base_uri)
        or re.search(r"\.%2[eE]", base_uri)
    ):
        msg = (
            f"Base URI contains percent-encoded path traversal: {base_uri!r}. "
            "Encoded dot sequences (e.g. %2E%2E/) are not allowed."
        )
        raise ValueError(msg)

    # Ensure the URI ends with a separator so @id values are well-formed.
    # Without a trailing '/' or '#', the ID component merges into the
    # namespace (e.g. "cepi:person" + "123" → "cepi:person123").
    if not base_uri.endswith(("/", "#")):
        msg = f"Base URI must end with '/' or '#', got {base_uri!r}. Example: '{base_uri}/' or '{base_uri}#'"
        raise ValueError(msg)

    return base_uri
