"""Tests for issues #50 and #51: sanitize DEL/C1 chars and write_json double-wrap."""

from __future__ import annotations

import datetime
import os
import tempfile

import pytest

from ceds_jsonld import sanitize_string_value
from ceds_jsonld.exceptions import SerializationError
from ceds_jsonld.serializer import write_json


# ---------------------------------------------------------------------------
# Issue #50 — sanitize_string_value must strip DEL and C1 control characters
# ---------------------------------------------------------------------------


class TestSanitizeDELAndC1:
    """sanitize_string_value must strip DEL (U+007F) and C1 (U+0080–U+009F)."""

    def test_del_character_stripped(self):
        assert sanitize_string_value("Jane\x7fDoe") == "JaneDoe"

    def test_del_only_string(self):
        assert sanitize_string_value("\x7f\x7f\x7f") == ""

    def test_c1_next_line_stripped(self):
        """U+0085 NEXT LINE should be removed."""
        assert sanitize_string_value("Hello\x85World") == "HelloWorld"

    def test_c1_csi_stripped(self):
        """U+009B CSI should be removed."""
        assert sanitize_string_value("data\x9bvalue") == "datavalue"

    def test_c1_range_fully_stripped(self):
        """Every character in U+0080–U+009F should be removed."""
        c1_chars = "".join(chr(c) for c in range(0x80, 0xA0))
        assert sanitize_string_value(f"A{c1_chars}B") == "AB"

    def test_mixed_c0_del_c1_stripped(self):
        """Mix of C0, DEL, and C1 characters all stripped."""
        assert sanitize_string_value("\x00Hello\x7f\x85World\x9b") == "HelloWorld"

    def test_tab_newline_cr_still_preserved(self):
        """Tab, newline, and carriage return must survive."""
        assert sanitize_string_value("a\tb\nc\r\nd") == "a\tb\nc\r\nd"

    def test_normal_unicode_unaffected(self):
        """Non-ASCII printable characters above U+009F are untouched."""
        assert sanitize_string_value("Ñoño Ü — café") == "Ñoño Ü — café"

    def test_empty_string(self):
        assert sanitize_string_value("") == ""

    def test_legacy_paste_artifact(self):
        """Simulates copy-paste artifact from legacy student records."""
        raw = "Smith\x7f, John\x85 Q.\x90"
        assert sanitize_string_value(raw) == "Smith, John Q."


# ---------------------------------------------------------------------------
# Issue #51 — write_json must not double-wrap SerializationError
# ---------------------------------------------------------------------------


class TestWriteJsonNoDoubleWrap:
    """write_json must re-raise SerializationError without wrapping it again."""

    def test_circular_ref_single_failed_to(self, tmp_path):
        """Circular reference: error message should contain 'Failed to' only once."""
        d: dict = {}
        d["self"] = d
        with pytest.raises(SerializationError) as exc_info:
            write_json(d, tmp_path / "out.json")
        msg = str(exc_info.value)
        assert msg.count("Failed to") == 1

    def test_non_serializable_type_single_failed_to(self, tmp_path):
        """Non-serializable type: error message should contain 'Failed to' only once."""
        obj = {"bad": object()}
        with pytest.raises(SerializationError) as exc_info:
            write_json(obj, tmp_path / "out.json")
        msg = str(exc_info.value)
        assert msg.count("Failed to") == 1

    def test_set_type_single_failed_to(self, tmp_path):
        """Set type: error message should contain 'Failed to' only once."""
        obj = {"tags": {1, 2, 3}}
        with pytest.raises(SerializationError) as exc_info:
            write_json(obj, tmp_path / "out.json")
        msg = str(exc_info.value)
        assert msg.count("Failed to") == 1

    def test_write_json_still_works_for_valid_data(self, tmp_path):
        """Regression: valid data should still write and round-trip fine."""
        from ceds_jsonld.serializer import read_json

        path = tmp_path / "valid.json"
        obj = {"@type": "Person", "name": "Jane"}
        write_json(obj, path)
        assert read_json(path) == obj
