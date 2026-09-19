from __future__ import annotations

import json

import pytest

import jobs.persist_table_storage as pts


class TestParseConnectionStringParts:
    def test_parses_key_value_pairs(self):
        conn = "TableEndpoint=https://acct.table.core.windows.net/;SharedAccessSignature=sv=1&sig=abc"
        parts = pts.parse_connection_string_parts(conn)
        assert parts["TableEndpoint"] == "https://acct.table.core.windows.net/"
        assert parts["SharedAccessSignature"] == "sv=1&sig=abc"

    def test_ignores_empty_and_malformed_tokens(self):
        conn = "TableEndpoint=https://acct.table.core.windows.net/;;NoEquals;SharedAccessSignature=sv=1"
        parts = pts.parse_connection_string_parts(conn)
        assert parts == {
            "TableEndpoint": "https://acct.table.core.windows.net/",
            "SharedAccessSignature": "sv=1",
        }


class TestValidateSasConnectionString:
    def test_valid_sas_string_does_not_raise(self):
        pts.validate_sas_connection_string(
            "TableEndpoint=https://acct.table.core.windows.net/;SharedAccessSignature=sv=1&sig=abc"
        )

    def test_missing_table_endpoint_raises(self):
        with pytest.raises(RuntimeError, match="no tiene formato valido"):
            pts.validate_sas_connection_string("SharedAccessSignature=sv=1&sig=abc")

    def test_missing_signature_raises(self):
        with pytest.raises(RuntimeError, match="no tiene formato valido"):
            pts.validate_sas_connection_string("TableEndpoint=https://acct.table.core.windows.net/")


class TestResolveConnectionTarget:
    def test_extracts_account_name_from_endpoint(self):
        conn = "TableEndpoint=https://myaccount.table.core.windows.net/;SharedAccessSignature=sv=1"
        account_name, endpoint = pts.resolve_connection_target(conn)
        assert account_name == "myaccount"
        assert endpoint == "https://myaccount.table.core.windows.net/"

    def test_unknown_account_when_endpoint_missing(self):
        account_name, endpoint = pts.resolve_connection_target("SharedAccessSignature=sv=1")
        assert account_name == "(desconocido)"
        assert endpoint == ""


class TestNormalizeScopes:
    def test_deduplicates_preserving_first_occurrence_order(self):
        assert pts._normalize_scopes("scope.b, scope.a, scope.b") == "scope.b,scope.a"

    def test_handles_none(self):
        assert pts._normalize_scopes(None) == ""

    def test_splits_on_whitespace_and_commas(self):
        assert pts._normalize_scopes("scope.a\nscope.b  scope.c") == "scope.a,scope.b,scope.c"


class TestResolvePartitionAndRowKey:
    def test_prefers_pascal_case_partition_key(self):
        event = {"PartitionKey": "app-display-name", "applicationName": "fallback"}
        assert pts._resolve_partition_key(event) == "app-display-name"

    def test_falls_back_to_legacy_application_name(self):
        event = {"applicationName": "legacy-app"}
        assert pts._resolve_partition_key(event) == "legacy-app"

    def test_prefers_pascal_case_row_key(self):
        event = {"RowKey": "persona", "tennant": "pyme"}
        assert pts._resolve_row_key(event) == "persona"

    def test_falls_back_to_legacy_tennant(self):
        event = {"tennant": "pyme"}
        assert pts._resolve_row_key(event) == "pyme"


class TestBuildEntity:
    def test_builds_entity_from_current_schema(self):
        event = {
            "operation": "create",
            "type": "cc",
            "Clientcode": "nhbk",
            "appcode": "ab",
            "clientid": "client-123",
            "scope": "scope.a,scope.b",
            "userApp": "juan.perez",
            "PartitionKey": "b2c-nhbk-miapp-cc-client-id",
            "RowKey": "persona",
            "createdAt": "2026-01-01T00:00:00Z",
        }

        entity = pts.build_entity(event)

        assert entity["PartitionKey"] == "b2c-nhbk-miapp-cc-client-id"
        assert entity["RowKey"] == "persona"
        assert entity["operation"] == "create"
        assert entity["type"] == "cc"
        assert entity["Clientcode"] == "nhbk"
        assert entity["appcode"] == "ab"
        assert entity["clientid"] == "client-123"
        assert entity["scope"] == "scope.a,scope.b"
        assert entity["userApp"] == "juan.perez"
        assert entity["createdAt"] == "2026-01-01T00:00:00Z"
        # Legacy aliases kept for existing consumers.
        assert entity["clientId"] == "client-123"
        assert entity["scopes"] == "scope.a,scope.b"

    def test_omits_created_at_when_absent(self):
        event = {"PartitionKey": "app", "RowKey": "persona"}
        entity = pts.build_entity(event)
        assert "createdAt" not in entity

    def test_builds_entity_from_legacy_field_names(self):
        event = {
            "applicationName": "legacy-app",
            "tennant": "pyme",
            "clientCode": "nhbk",
            "appCode": "ab",
            "clientId": "client-legacy",
            "scopes": "scope.a",
        }
        entity = pts.build_entity(event)
        assert entity["PartitionKey"] == "legacy-app"
        assert entity["RowKey"] == "pyme"
        assert entity["Clientcode"] == "nhbk"
        assert entity["appcode"] == "ab"
        assert entity["clientid"] == "client-legacy"
        assert entity["scope"] == "scope.a"


class TestToBool:
    @pytest.mark.parametrize("value", ["1", "true", "True", "yes", "y", "on"])
    def test_truthy_values(self, value):
        assert pts._to_bool(value) is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "", "maybe"])
    def test_falsy_values(self, value):
        assert pts._to_bool(value) is False


class TestLoadAuditEvents:
    def test_returns_empty_list_when_file_missing(self, tmp_path):
        assert pts.load_audit_events(str(tmp_path / "missing.jsonl")) == []

    def test_parses_each_non_empty_line_as_json(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        path.write_text(
            json.dumps({"a": 1}) + "\n\n" + json.dumps({"a": 2}) + "\n",
            encoding="utf-8",
        )
        events = pts.load_audit_events(str(path))
        assert events == [{"a": 1}, {"a": 2}]


class FakeUpsertTable:
    def __init__(self):
        self.upserts: list[dict] = []

    def upsert_entity(self, entity, mode="MERGE"):
        self.upserts.append(entity)


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path, audit_file):
        monkeypatch.setenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "conn-string")
        monkeypatch.setenv("AZURE_TABLE_STORAGE_TABLE_NAME", "audit")
        monkeypatch.setenv("B2CC_AUDIT_FILE", str(audit_file))

    def test_raises_when_connection_string_missing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", raising=False)
        monkeypatch.setenv("AZURE_TABLE_STORAGE_TABLE_NAME", "audit")
        with pytest.raises(RuntimeError, match="Falta AZURE_TABLE_STORAGE_CONNECTION_STRING"):
            pts.main()

    def test_raises_when_table_name_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "conn-string")
        monkeypatch.delenv("AZURE_TABLE_STORAGE_TABLE_NAME", raising=False)
        with pytest.raises(RuntimeError, match="Falta AZURE_TABLE_STORAGE_TABLE_NAME"):
            pts.main()

    def test_returns_early_when_no_events_to_persist(self, monkeypatch, tmp_path):
        audit_file = tmp_path / "missing.jsonl"
        self._set_common_env(monkeypatch, tmp_path, audit_file)

        def fail_connect(*args, **kwargs):
            raise AssertionError("should not connect to table storage when there are no events")

        monkeypatch.setattr(pts, "connect_table", fail_connect)

        assert pts.main() == 0

    def test_persists_events_and_skips_ones_without_keys(self, monkeypatch, tmp_path):
        audit_file = tmp_path / "audit.jsonl"
        audit_file.write_text(
            "\n".join(
                [
                    json.dumps({"PartitionKey": "app-1", "RowKey": "persona", "operation": "create"}),
                    json.dumps({"PartitionKey": "", "RowKey": "persona"}),
                    json.dumps({"PartitionKey": "app-2", "RowKey": ""}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self._set_common_env(monkeypatch, tmp_path, audit_file)
        fake_table = FakeUpsertTable()
        monkeypatch.setattr(pts, "connect_table", lambda conn, table, create_if_missing: fake_table)

        assert pts.main() == 0
        assert len(fake_table.upserts) == 1
        assert fake_table.upserts[0]["PartitionKey"] == "app-1"
