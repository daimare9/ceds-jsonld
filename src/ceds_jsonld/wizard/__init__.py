"""AI-Assisted Mapping Wizard — auto-map source columns to CEDS shapes.

Three-phase matching pipeline:
1. Concept-value matching (deterministic, <1ms)
2. Heuristic name matching (deterministic, <1ms)
3. LLM-assisted resolution (optional, 30-75s)

Example:
    >>> from ceds_jsonld.wizard import MappingWizard
    >>> wizard = MappingWizard()
    >>> result = wizard.suggest("students.csv", shape="person")
    >>> result.save("person_mapping.yaml")
"""

from __future__ import annotations

__all__: list[str] = []
