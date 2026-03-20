"""Fallback generators — pure-Python value generators for all XSD types.

These generators produce realistic-looking values without any LLM. They are
used as the default generation strategy for literal properties and as the
tier-3 fallback when LLM and cache both fail.

Generators are keyed by XSD datatype and optionally refined by property
label heuristics (e.g. ``rdfs:label == "First Name"`` → pick from a curated
US name list rather than random strings).
"""

from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ceds_jsonld.sdg.concept_resolver import PropertyMetadata

# ---------------------------------------------------------------------------
# Curated value pools for name-aware generation
# ---------------------------------------------------------------------------

_FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Christopher", "Karen",
    "Maria", "Carlos", "Wei", "Fatima", "Aiden", "Sophia", "DeShawn",
    "Yuki", "Mohammed", "Isabella", "Priya", "Liam", "Aaliyah", "Lucas",
    "Mei-Ling", "Connor", "Valentina", "Jayden", "Amara", "Emma",
    "Daniel", "Ashley", "Matthew", "Kimberly", "Anthony", "Emily",
    "Mark", "Donna", "Donald", "Michelle", "Steven", "Sandra",
    "Andrew", "Dorothy", "Joshua", "Lisa", "Kenneth", "Betty",
]

_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Chen", "Patel", "Kim", "Washington", "Okafor",
]

_MIDDLE_NAMES = [
    "A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M",
    "N", "P", "R", "S", "T", "W", "Ann", "Marie", "Lynn", "Rose",
    "Grace", "Lee", "James", "Michael", "Ray", "Allen", "Dean", "Paul",
]

_SUFFIXES = ["Jr", "Sr", "II", "III", "IV", "V", ""]

# Date ranges for education contexts
_STUDENT_BIRTH_START = date(2004, 1, 1)
_STUDENT_BIRTH_END = date(2019, 12, 31)
_STAFF_BIRTH_START = date(1955, 1, 1)
_STAFF_BIRTH_END = date(2003, 12, 31)


# ---------------------------------------------------------------------------
# Generator functions
# ---------------------------------------------------------------------------

def _generate_string(
    meta: PropertyMetadata,
    rng: random.Random,
) -> str:
    """Generate a string value based on property metadata."""
    label_lower = meta.label.lower()

    # Name-aware heuristics
    if "first name" in label_lower or "first_name" in meta.name.lower():
        return rng.choice(_FIRST_NAMES)
    if "middle name" in label_lower or "middle" in meta.name.lower():
        return rng.choice(_MIDDLE_NAMES)
    if "last" in label_lower or "surname" in label_lower:
        return rng.choice(_LAST_NAMES)
    if "generation" in label_lower or "suffix" in label_lower:
        return rng.choice(_SUFFIXES)

    # Default: random alphanumeric string
    max_len = min(meta.max_length or 20, 50)
    length = rng.randint(3, max_len)
    return "".join(rng.choices(string.ascii_letters, k=length))


def _generate_date(
    meta: PropertyMetadata,
    rng: random.Random,
) -> str:
    """Generate an ISO 8601 date (YYYY-MM-DD)."""
    label_lower = meta.label.lower()

    if "birth" in label_lower:
        # Mix of student and staff birthdates
        if rng.random() < 0.7:
            start, end = _STUDENT_BIRTH_START, _STUDENT_BIRTH_END
        else:
            start, end = _STAFF_BIRTH_START, _STAFF_BIRTH_END
    else:
        start = date(2000, 1, 1)
        end = date(2025, 12, 31)

    days_range = (end - start).days
    random_date = start + timedelta(days=rng.randint(0, days_range))
    return random_date.isoformat()


def _generate_datetime(
    meta: PropertyMetadata,
    rng: random.Random,
) -> str:
    """Generate an ISO 8601 datetime (YYYY-MM-DDTHH:MM:SS)."""
    date_str = _generate_date(meta, rng)
    hour = rng.randint(0, 23)
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return f"{date_str}T{hour:02d}:{minute:02d}:{second:02d}"


def _generate_token(
    meta: PropertyMetadata,
    rng: random.Random,
) -> str:
    """Generate a token value (typically an ID number)."""
    label_lower = meta.label.lower()

    if "identifier" in label_lower or "id" in meta.name.lower():
        # Generate a realistic ID number (9-10 digits)
        return str(rng.randint(100_000_000, 9_999_999_999))

    # Default: short alphanumeric token
    return "".join(rng.choices(string.ascii_uppercase + string.digits, k=10))


def _generate_integer(
    meta: PropertyMetadata,
    rng: random.Random,
) -> str:
    """Generate an integer value as a string."""
    return str(rng.randint(0, 9999))


def _generate_decimal(
    meta: PropertyMetadata,
    rng: random.Random,
) -> str:
    """Generate a decimal value as a string."""
    return f"{rng.uniform(0, 100):.2f}"


def _generate_boolean(
    meta: PropertyMetadata,
    rng: random.Random,
) -> str:
    """Generate a boolean value as a string."""
    return rng.choice(["true", "false"])


# ---------------------------------------------------------------------------
# XSD type → generator mapping
# ---------------------------------------------------------------------------

_XSD_NS = "http://www.w3.org/2001/XMLSchema#"

_GENERATORS: dict[str, Any] = {
    f"{_XSD_NS}string": _generate_string,
    f"{_XSD_NS}token": _generate_token,
    f"{_XSD_NS}date": _generate_date,
    f"{_XSD_NS}dateTime": _generate_datetime,
    f"{_XSD_NS}integer": _generate_integer,
    f"{_XSD_NS}int": _generate_integer,
    f"{_XSD_NS}long": _generate_integer,
    f"{_XSD_NS}decimal": _generate_decimal,
    f"{_XSD_NS}float": _generate_decimal,
    f"{_XSD_NS}double": _generate_decimal,
    f"{_XSD_NS}boolean": _generate_boolean,
    f"{_XSD_NS}nonNegativeInteger": _generate_integer,
    f"{_XSD_NS}positiveInteger": _generate_integer,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class FallbackGenerators:
    """Pure-Python generators for all XSD datatypes with name-aware heuristics.

    Example:
        >>> gen = FallbackGenerators(seed=42)
        >>> meta = PropertyMetadata("FirstName", "http://ceds.ed.gov/terms#P000115",
        ...     label="First Name", xsd_datatype="http://www.w3.org/2001/XMLSchema#string")
        >>> gen.generate_one(meta)
        'Valentina'
    """

    def __init__(self, *, seed: int | None = None) -> None:
        """Initialize with an optional random seed for reproducibility.

        Args:
            seed: Random seed. If ``None``, generation is non-deterministic.
        """
        self._rng = random.Random(seed)

    def generate_one(self, meta: PropertyMetadata) -> str:
        """Generate a single value for a property.

        Args:
            meta: Property metadata describing what to generate.

        Returns:
            A string value appropriate for the property's datatype and semantics.
        """
        datatype = meta.xsd_datatype or f"{_XSD_NS}string"
        generator_fn = _GENERATORS.get(datatype, _generate_string)
        return generator_fn(meta, self._rng)

    def generate_pool(self, meta: PropertyMetadata, count: int = 200) -> list[str]:
        """Generate a pool of values for a property.

        The pool can be sampled from repeatedly using ``random.choice()`` to
        create many records cheaply.

        Args:
            meta: Property metadata describing what to generate.
            count: Number of values to generate for the pool.

        Returns:
            List of generated string values.
        """
        return [self.generate_one(meta) for _ in range(count)]

    def sample_from_pool(self, pool: list[str]) -> str:
        """Randomly sample one value from a pre-generated pool.

        Args:
            pool: A list of pre-generated values.

        Returns:
            A randomly selected value.
        """
        return self._rng.choice(pool)
