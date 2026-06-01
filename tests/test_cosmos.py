"""Tests for the Cosmos DB integration layer.

Tests the ``prepare_for_cosmos`` utility (pure logic — no mocks needed)
and the ``CosmosLoader`` class (mocked Azure SDK — true external service).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ceds_jsonld.cosmos.loader import (
    RECOMMENDED_INDEXING_POLICY,
    BulkResult,
    CosmosLoader,
    UpsertResult,
)
from ceds_jsonld.cosmos.prepare import prepare_for_cosmos, sanitize_cosmos_id
from ceds_jsonld.exceptions import CosmosError

# =====================================================================
# sanitize_cosmos_id — pure function, real tests
# =====================================================================


class TestSanitizeCosmosId:
    """Test the sanitize_cosmos_id utility function."""

    def test_replaces_slash_with_pipe(self) -> None:
        assert sanitize_cosmos_id("cepi:person/12345") == "cepi:person|12345"

    def test_replaces_multiple_slashes(self) -> None:
        assert sanitize_cosmos_id("https://cepi.org/person/12345") == "https:||cepi.org|person|12345"

    def test_no_slash_unchanged(self) -> None:
        assert sanitize_cosmos_id("plain-id-no-slash") == "plain-id-no-slash"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(CosmosError, match="Cannot derive Cosmos 'id'"):
            sanitize_cosmos_id("")

    def test_preserves_other_characters(self) -> None:
        assert sanitize_cosmos_id("cepi:person/ABC-123_test") == "cepi:person|ABC-123_test"

    def test_colon_preserved(self) -> None:
        assert sanitize_cosmos_id("urn:uuid:abc-123") == "urn:uuid:abc-123"


# =====================================================================
# prepare_for_cosmos — pure function, real tests
# =====================================================================


class TestPrepareForCosmos:
    """Test document preparation utility."""

    def test_injects_id_from_at_id(self) -> None:
        doc = {"@id": "cepi:person/12345", "@type": "Person"}
        result = prepare_for_cosmos(doc)
        assert result["id"] == "cepi:person|12345"

    def test_injects_partition_key_from_at_type(self) -> None:
        doc = {"@id": "cepi:person/12345", "@type": "Person"}
        result = prepare_for_cosmos(doc)
        assert result["partitionKey"] == "Person"

    def test_explicit_partition_value_overrides_type(self) -> None:
        doc = {"@id": "cepi:person/12345", "@type": "Person"}
        result = prepare_for_cosmos(doc, partition_value="collection_2026")
        assert result["partitionKey"] == "collection_2026"

    def test_does_not_mutate_original(self) -> None:
        doc = {"@id": "cepi:person/12345", "@type": "Person", "name": "Jane"}
        result = prepare_for_cosmos(doc)
        assert "id" not in doc
        assert "partitionKey" not in doc
        assert result["name"] == "Jane"

    def test_preserves_all_original_fields(self) -> None:
        doc = {
            "@id": "cepi:person/999",
            "@type": "Person",
            "@context": "https://example.com/context.json",
            "hasPersonName": {"FirstName": "Jane"},
        }
        result = prepare_for_cosmos(doc)
        assert result["@context"] == "https://example.com/context.json"
        assert result["hasPersonName"]["FirstName"] == "Jane"

    def test_strips_uri_prefix(self) -> None:
        doc = {"@id": "http://example.org/person/ABC-123", "@type": "Person"}
        result = prepare_for_cosmos(doc)
        assert result["id"] == "http:||example.org|person|ABC-123"

    def test_no_slash_in_id_uses_whole_value(self) -> None:
        doc = {"@id": "plain-id-no-slash", "@type": "Person"}
        result = prepare_for_cosmos(doc)
        assert result["id"] == "plain-id-no-slash"

    def test_missing_at_type_falls_back_to_id(self) -> None:
        doc = {"@id": "cepi:person/555"}
        result = prepare_for_cosmos(doc)
        assert result["partitionKey"] == "cepi:person|555"

    def test_missing_id_field_raises(self) -> None:
        doc = {"@type": "Person", "name": "No ID"}
        with pytest.raises(KeyError, match="@id"):
            prepare_for_cosmos(doc)

    def test_custom_id_field(self) -> None:
        doc = {"customId": "cepi:org/789", "@type": "Organization"}
        result = prepare_for_cosmos(doc, id_field="customId")
        assert result["id"] == "cepi:org|789"

    def test_deep_copy_isolates_nested_objects(self) -> None:
        """Regression: mutating result must not corrupt original (issue #12)."""
        doc = {"@id": "cepi:person/123", "@type": "Person", "hasPersonName": {"firstName": "Jane"}}
        result = prepare_for_cosmos(doc)
        result["hasPersonName"]["firstName"] = "MUTATED"
        assert doc["hasPersonName"]["firstName"] == "Jane"

    def test_empty_at_id_raises(self) -> None:
        """Regression: empty @id must raise CosmosError (issue #13)."""
        doc = {"@id": "", "@type": "Person"}
        with pytest.raises(CosmosError, match="Cannot derive Cosmos 'id'"):
            prepare_for_cosmos(doc)

    def test_slash_only_at_id_raises(self) -> None:
        """Regression: slash-only @id produces all-pipe string, not empty — no longer raises."""
        doc = {"@id": "////", "@type": "Person"}
        result = prepare_for_cosmos(doc)
        assert result["id"] == "||||"

    def test_trailing_slash_at_id_raises(self) -> None:
        """URI ending with slash sanitizes to trailing pipe — does not raise."""
        doc = {"@id": "cepi:person/", "@type": "Person"}
        result = prepare_for_cosmos(doc)
        assert result["id"] == "cepi:person|"


# =====================================================================
# CosmosLoader — mocked Azure SDK (true external service)
# =====================================================================


def _sample_doc(doc_id: str = "12345") -> dict[str, Any]:
    return {
        "@id": f"cepi:person/{doc_id}",
        "@type": "Person",
        "hasPersonName": {"FirstName": "Jane"},
    }


class TestCosmosLoaderInit:
    """Test CosmosLoader construction and configuration."""

    def test_default_attributes(self) -> None:
        loader = CosmosLoader(
            endpoint="https://fake.documents.azure.com:443/",
            credential="fake-key",
            database="ceds",
            container="person",
        )
        assert loader._endpoint == "https://fake.documents.azure.com:443/"
        assert loader._database_name == "ceds"
        assert loader._container_name == "person"
        assert loader._concurrency == 25
        assert loader._create_if_missing is True

    def test_custom_concurrency(self) -> None:
        loader = CosmosLoader(
            endpoint="https://fake.documents.azure.com:443/",
            credential="fake-key",
            database="ceds",
            container="person",
            concurrency=50,
        )
        assert loader._concurrency == 50


class TestCosmosLoaderPrepare:
    """Test the internal _prepare method."""

    def test_prepare_injects_fields(self) -> None:
        loader = CosmosLoader(
            endpoint="https://fake.documents.azure.com:443/",
            credential="fake-key",
            database="ceds",
            container="person",
        )
        doc = _sample_doc()
        result = loader._prepare(doc)
        assert "id" in result
        assert "partitionKey" in result

    def test_prepare_skips_if_already_present(self) -> None:
        loader = CosmosLoader(
            endpoint="https://fake.documents.azure.com:443/",
            credential="fake-key",
            database="ceds",
            container="person",
        )
        doc = {"id": "already-set", "partitionKey": "pk", "@type": "Person"}
        result = loader._prepare(doc)
        assert result["id"] == "already-set"
        assert result["partitionKey"] == "pk"

    def test_prepare_uses_explicit_partition_value(self) -> None:
        loader = CosmosLoader(
            endpoint="https://fake.documents.azure.com:443/",
            credential="fake-key",
            database="ceds",
            container="person",
            partition_value="collection_2026",
        )
        doc = _sample_doc()
        result = loader._prepare(doc)
        assert result["partitionKey"] == "collection_2026"


class TestCosmosLoaderUpsert:
    """Test upsert operations with mocked Azure SDK."""

    @pytest.fixture()
    def mock_container(self) -> AsyncMock:
        container = AsyncMock()
        # upsert_item returns the doc back (like the real SDK)
        container.upsert_item = AsyncMock(return_value=_sample_doc())
        return container

    @pytest.fixture()
    def loader_with_mock(self, mock_container: AsyncMock) -> CosmosLoader:
        loader = CosmosLoader(
            endpoint="https://fake.documents.azure.com:443/",
            credential="fake-key",
            database="ceds",
            container="person",
        )
        # Bypass SDK initialization — inject the mock container directly.
        loader._container = mock_container
        return loader

    def test_upsert_one_success(self, loader_with_mock: CosmosLoader, mock_container: AsyncMock) -> None:
        doc = _sample_doc()
        result = asyncio.run(loader_with_mock.upsert_one(doc))
        assert result.status == "success"
        assert result.document_id == "cepi:person|12345"
        mock_container.upsert_item.assert_awaited_once()

    def test_upsert_one_failure(self, loader_with_mock: CosmosLoader, mock_container: AsyncMock) -> None:
        mock_container.upsert_item.side_effect = Exception("Connection refused")
        doc = _sample_doc()
        result = asyncio.run(loader_with_mock.upsert_one(doc))
        assert result.status == "error"
        assert "Connection refused" in result.error

    def test_upsert_many_success(self, loader_with_mock: CosmosLoader, mock_container: AsyncMock) -> None:
        docs = [_sample_doc(str(i)) for i in range(5)]
        result = asyncio.run(loader_with_mock.upsert_many(docs))
        assert isinstance(result, BulkResult)
        assert result.total == 5
        assert result.succeeded == 5
        assert result.failed == 0
        assert mock_container.upsert_item.await_count == 5

    def test_upsert_many_partial_failure(self, loader_with_mock: CosmosLoader, mock_container: AsyncMock) -> None:
        call_count = 0

        async def _fail_on_third(body: dict) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                msg = "Throttled"
                raise Exception(msg)
            return body

        mock_container.upsert_item = _fail_on_third
        docs = [_sample_doc(str(i)) for i in range(5)]
        result = asyncio.run(loader_with_mock.upsert_many(docs))
        assert result.total == 5
        assert result.succeeded == 4
        assert result.failed == 1
        assert len(result.errors) == 1

    def test_upsert_many_custom_concurrency(self, loader_with_mock: CosmosLoader, mock_container: AsyncMock) -> None:
        docs = [_sample_doc(str(i)) for i in range(10)]
        result = asyncio.run(loader_with_mock.upsert_many(docs, concurrency=2))
        assert result.succeeded == 10


class TestCosmosLoaderContextManager:
    """Test async context manager behaviour."""

    def test_close_clears_state(self) -> None:
        loader = CosmosLoader(
            endpoint="https://fake.documents.azure.com:443/",
            credential="fake-key",
            database="ceds",
            container="person",
        )
        loader._client = MagicMock()
        loader._client.close = AsyncMock()
        loader._database = MagicMock()
        loader._container = MagicMock()

        asyncio.run(loader.close())
        assert loader._client is None
        assert loader._database is None
        assert loader._container is None


class TestUpsertResult:
    """Test result dataclasses."""

    def test_upsert_result_defaults(self) -> None:
        r = UpsertResult(document_id="123", status="success")
        assert r.ru_charge == 0.0
        assert r.error is None

    def test_bulk_result_defaults(self) -> None:
        r = BulkResult()
        assert r.total == 0
        assert r.succeeded == 0
        assert r.failed == 0
        assert r.total_ru == 0.0
        assert r.errors == []


class TestIndexingPolicy:
    """Verify the recommended indexing policy structure."""

    def test_policy_has_required_keys(self) -> None:
        assert "indexingMode" in RECOMMENDED_INDEXING_POLICY
        assert "includedPaths" in RECOMMENDED_INDEXING_POLICY
        assert "excludedPaths" in RECOMMENDED_INDEXING_POLICY

    def test_policy_indexes_id_and_partition_key(self) -> None:
        included = [p["path"] for p in RECOMMENDED_INDEXING_POLICY["includedPaths"]]
        assert "/id/?" in included
        assert "/partitionKey/?" in included


# =====================================================================
# Pipeline.to_cosmos() integration
# =====================================================================


class TestPipelineToCosmos:
    """Test that Pipeline.to_cosmos() wires through to CosmosLoader."""

    @pytest.fixture()
    def registry(self) -> Any:
        from ceds_jsonld.registry import ShapeRegistry

        reg = ShapeRegistry()
        reg.load_shape("person")
        return reg

    @pytest.fixture()
    def sample_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "FirstName": "Alice",
                "MiddleName": "",
                "LastName": "Smith",
                "GenerationCodeOrSuffix": "",
                "Birthdate": "1990-01-15",
                "Sex": "Female",
                "RaceEthnicity": "White",
                "PersonIdentifiers": "111222333",
                "IdentificationSystems": "PersonIdentificationSystem_SSN",
                "PersonIdentifierTypes": "PersonIdentifierType_PersonIdentifier",
            },
        ]

    def test_to_cosmos_calls_loader(self, registry: Any, sample_rows: list[dict]) -> None:
        from ceds_jsonld.adapters.dict_adapter import DictAdapter
        from ceds_jsonld.pipeline import Pipeline

        pipeline = Pipeline(source=DictAdapter(sample_rows), shape="person", registry=registry)

        mock_result = BulkResult(total=1, succeeded=1, failed=0, total_ru=5.0)

        with patch("ceds_jsonld.cosmos.loader.CosmosLoader") as MockLoader:
            mock_instance = AsyncMock()
            mock_instance.upsert_many = AsyncMock(return_value=mock_result)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            MockLoader.return_value = mock_instance

            result = pipeline.to_cosmos(
                endpoint="https://fake.documents.azure.com:443/",
                credential="fake-key",
                database="ceds",
            )
            assert result.succeeded == 1
            assert result.total_ru == 5.0
            MockLoader.assert_called_once()
            mock_instance.upsert_many.assert_awaited_once()

    def test_to_cosmos_uses_shape_name_as_container(self, registry: Any, sample_rows: list[dict]) -> None:
        from ceds_jsonld.adapters.dict_adapter import DictAdapter
        from ceds_jsonld.pipeline import Pipeline

        pipeline = Pipeline(source=DictAdapter(sample_rows), shape="person", registry=registry)

        with patch("ceds_jsonld.cosmos.loader.CosmosLoader") as MockLoader:
            mock_instance = AsyncMock()
            mock_instance.upsert_many = AsyncMock(return_value=BulkResult(total=1, succeeded=1))
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            MockLoader.return_value = mock_instance

            pipeline.to_cosmos(
                endpoint="https://fake.documents.azure.com:443/",
                credential="fake-key",
                database="ceds",
            )
            # Container should default to the shape name
            call_kwargs = MockLoader.call_args[1]
            assert call_kwargs["container"] == "person"

    def test_to_cosmos_custom_container(self, registry: Any, sample_rows: list[dict]) -> None:
        from ceds_jsonld.adapters.dict_adapter import DictAdapter
        from ceds_jsonld.pipeline import Pipeline

        pipeline = Pipeline(source=DictAdapter(sample_rows), shape="person", registry=registry)

        with patch("ceds_jsonld.cosmos.loader.CosmosLoader") as MockLoader:
            mock_instance = AsyncMock()
            mock_instance.upsert_many = AsyncMock(return_value=BulkResult(total=1, succeeded=1))
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            MockLoader.return_value = mock_instance

            pipeline.to_cosmos(
                endpoint="https://fake.documents.azure.com:443/",
                credential="fake-key",
                database="ceds",
                container="my_custom_container",
            )
            call_kwargs = MockLoader.call_args[1]
            assert call_kwargs["container"] == "my_custom_container"
