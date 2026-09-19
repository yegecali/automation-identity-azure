from __future__ import annotations

import pytest
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from services import table_storage_client as tsc


class FakePager:
    def __init__(self, raise_exc: Exception | None = None):
        self._raise_exc = raise_exc

    def by_page(self):
        if self._raise_exc:
            raise self._raise_exc
        return iter([])


class FakeTableClient:
    def __init__(self, name: str, raise_on_list: Exception | None = None):
        self.name = name
        self._raise_on_list = raise_on_list

    def list_entities(self, results_per_page: int = 1):
        return FakePager(self._raise_on_list)


class FakeTableServiceClient:
    def __init__(self, existing_raises: Exception | None = None):
        self._existing_raises = existing_raises
        self.created_tables: list[str] = []
        self._post_create_ok = False

    def get_table_client(self, table_name: str):
        if self._post_create_ok:
            return FakeTableClient(table_name)
        return FakeTableClient(table_name, raise_on_list=self._existing_raises)

    def create_table(self, table_name: str):
        self.created_tables.append(table_name)
        self._post_create_ok = True


VALID_SAS = "TableEndpoint=https://myacct.table.core.windows.net/;SharedAccessSignature=sv=1&sig=abc"


class TestBuildTableServiceClientFromSas:
    def test_builds_client_with_normalized_sas_token(self):
        client = tsc.build_table_service_client_from_sas(VALID_SAS)
        assert client is not None

    def test_strips_leading_question_mark_from_sas_token(self):
        conn = "TableEndpoint=https://myacct.table.core.windows.net/;SharedAccessSignature=?sv=1&sig=abc"
        # Should not raise; leading '?' is stripped before constructing the credential.
        tsc.build_table_service_client_from_sas(conn)

    def test_raises_when_endpoint_missing(self):
        with pytest.raises(RuntimeError, match="Falta TableEndpoint"):
            tsc.build_table_service_client_from_sas("SharedAccessSignature=sv=1&sig=abc")

    def test_raises_when_sas_token_missing(self):
        with pytest.raises(RuntimeError, match="Falta TableEndpoint"):
            tsc.build_table_service_client_from_sas("TableEndpoint=https://myacct.table.core.windows.net/")


class TestEnsureTableClient:
    def test_returns_existing_accessible_table(self):
        service = FakeTableServiceClient()
        table = tsc.ensure_table_client(service, "audit", create_if_missing=False)
        assert isinstance(table, FakeTableClient)
        assert table.name == "audit"

    def test_creates_table_when_missing_and_allowed(self):
        service = FakeTableServiceClient(existing_raises=ResourceNotFoundError("not found"))
        table = tsc.ensure_table_client(service, "audit", create_if_missing=True)
        assert service.created_tables == ["audit"]
        assert isinstance(table, FakeTableClient)

    def test_raises_when_missing_and_creation_not_allowed(self):
        service = FakeTableServiceClient(existing_raises=ResourceNotFoundError("not found"))
        with pytest.raises(RuntimeError, match="creacion automatica esta deshabilitada"):
            tsc.ensure_table_client(service, "audit", create_if_missing=False)

    def test_raises_friendly_error_on_http_response_error(self):
        service = FakeTableServiceClient(existing_raises=HttpResponseError("forbidden"))
        with pytest.raises(RuntimeError, match="No se pudo validar acceso"):
            tsc.ensure_table_client(service, "audit", create_if_missing=False)


class TestConnectTable:
    def test_connects_and_returns_table_client(self, monkeypatch):
        fake_service = FakeTableServiceClient()
        monkeypatch.setattr(tsc, "build_table_service_client_from_sas", lambda conn: fake_service)

        table = tsc.connect_table(VALID_SAS, "audit", create_if_missing=False)
        assert isinstance(table, FakeTableClient)
        assert table.name == "audit"

    def test_invalid_connection_string_raises_before_building_client(self, monkeypatch):
        def fail(conn):
            raise AssertionError("should not build a client with an invalid connection string")

        monkeypatch.setattr(tsc, "build_table_service_client_from_sas", fail)

        with pytest.raises(RuntimeError, match="no tiene formato valido"):
            tsc.connect_table("not-a-valid-connection-string", "audit")
