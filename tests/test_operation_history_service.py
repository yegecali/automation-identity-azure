from __future__ import annotations

import json

import pytest

from services.operation_history_service import (
    CREATE_OPERATION,
    UPDATE_OPERATION,
    build_snapshot_entity,
    find_latest_snapshot,
    mark_snapshot_reverted,
    parse_before_manifest,
    query_snapshots_for_ticket,
    save_snapshot,
    select_latest_snapshot,
)


class FakeTable:
    """In-memory stand-in for azure.data.tables.TableClient used by the tests."""

    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    def upsert_entity(self, entity, mode="MERGE"):
        key = (entity["PartitionKey"], entity["RowKey"])
        existing = self.rows.get(key, {})
        merged = {**existing, **entity}
        self.rows[key] = merged

    def update_entity(self, entity, mode="MERGE"):
        key = (entity["PartitionKey"], entity["RowKey"])
        if key not in self.rows:
            raise KeyError(key)
        self.rows[key] = {**self.rows[key], **entity}

    def query_entities(self, query_filter):
        # Only supports "PartitionKey eq '<value>'", which is all the service uses.
        assert query_filter.startswith("PartitionKey eq '")
        partition_key = query_filter[len("PartitionKey eq '") : -1]
        return [dict(row) for (pk, _rk), row in self.rows.items() if pk == partition_key]


class TestBuildSnapshotEntity:
    def test_builds_create_snapshot_with_expected_fields(self):
        entity = build_snapshot_entity(
            ticket_number="itsm-12345",
            operation="create",
            env="dev",
            tennant="persona",
            application_name="b2c-nhbk-miapp-cc-client-id",
            app_id="app-id-1",
            app_object_id="obj-id-1",
            sp_id="sp-id-1",
            run_id="42",
            created_at="2026-01-01T10:00:00Z",
        )

        assert entity["PartitionKey"] == "itsm-12345"
        assert entity["RowKey"] == "2026-01-01T10:00:00Z_42"
        assert entity["operation"] == "create"
        assert entity["env"] == "dev"
        assert entity["tennant"] == "persona"
        assert entity["appId"] == "app-id-1"
        assert entity["appObjectId"] == "obj-id-1"
        assert entity["spId"] == "sp-id-1"
        assert entity["reverted"] is False
        assert "beforeManifestJson" not in entity

    def test_serializes_before_manifest_as_json_string(self):
        manifest = {"identifierUris": ["api://guid"], "appRoles": []}
        entity = build_snapshot_entity(
            ticket_number="itsm-1",
            operation="update",
            env="dev",
            tennant="persona",
            application_name="app",
            before_manifest=manifest,
            created_at="2026-01-01T10:00:00Z",
        )
        assert json.loads(entity["beforeManifestJson"]) == manifest

    def test_empty_ticket_number_raises(self):
        with pytest.raises(RuntimeError, match="ticket_number no puede ser vacio"):
            build_snapshot_entity(
                ticket_number="  ",
                operation="create",
                env="dev",
                tennant="persona",
                application_name="app",
            )

    def test_invalid_operation_raises(self):
        with pytest.raises(RuntimeError, match="operation debe ser uno de"):
            build_snapshot_entity(
                ticket_number="itsm-1",
                operation="delete",
                env="dev",
                tennant="persona",
                application_name="app",
            )

    def test_defaults_created_at_when_not_provided(self):
        entity = build_snapshot_entity(
            ticket_number="itsm-1",
            operation="create",
            env="dev",
            tennant="persona",
            application_name="app",
        )
        assert entity["createdAt"].endswith("Z")


class TestSelectLatestSnapshot:
    def _snapshot(self, row_key: str, operation: str, reverted: bool = False):
        return {"RowKey": row_key, "operation": operation, "reverted": reverted}

    def test_picks_the_lexicographically_greatest_row_key(self):
        entities = [
            self._snapshot("2026-01-01T10:00:00Z_1", "update"),
            self._snapshot("2026-01-03T10:00:00Z_3", "update"),
            self._snapshot("2026-01-02T10:00:00Z_2", "update"),
        ]
        latest = select_latest_snapshot(entities, "update")
        assert latest["RowKey"] == "2026-01-03T10:00:00Z_3"

    def test_ignores_other_operations(self):
        entities = [
            self._snapshot("2026-01-05T10:00:00Z_9", "create"),
            self._snapshot("2026-01-01T10:00:00Z_1", "update"),
        ]
        latest = select_latest_snapshot(entities, "update")
        assert latest["RowKey"] == "2026-01-01T10:00:00Z_1"

    def test_ignores_already_reverted_snapshots(self):
        entities = [
            self._snapshot("2026-01-02T10:00:00Z_2", "update", reverted=True),
            self._snapshot("2026-01-01T10:00:00Z_1", "update", reverted=False),
        ]
        latest = select_latest_snapshot(entities, "update")
        assert latest["RowKey"] == "2026-01-01T10:00:00Z_1"

    def test_returns_none_when_no_candidates(self):
        assert select_latest_snapshot([], "update") is None
        assert select_latest_snapshot([self._snapshot("x", "create", reverted=True)], "create") is None


class TestParseBeforeManifest:
    def test_parses_stored_json(self):
        entity = {"beforeManifestJson": json.dumps({"identifierUris": ["api://guid"]})}
        assert parse_before_manifest(entity) == {"identifierUris": ["api://guid"]}

    def test_missing_field_raises(self):
        with pytest.raises(RuntimeError, match="no contiene beforeManifestJson"):
            parse_before_manifest({})


class TestTableRoundTrip:
    def test_save_then_find_latest_snapshot(self):
        table = FakeTable()
        entity = build_snapshot_entity(
            ticket_number="itsm-round-trip",
            operation=CREATE_OPERATION,
            env="dev",
            tennant="persona",
            application_name="app",
            app_id="app-1",
            sp_id="sp-1",
            created_at="2026-01-01T10:00:00Z",
            run_id="1",
        )
        save_snapshot(table, entity)

        found = find_latest_snapshot(table, "itsm-round-trip", CREATE_OPERATION)
        assert found is not None
        assert found["appId"] == "app-1"

        assert find_latest_snapshot(table, "itsm-round-trip", UPDATE_OPERATION) is None
        assert find_latest_snapshot(table, "unknown-ticket", CREATE_OPERATION) is None

    def test_mark_snapshot_reverted_prevents_it_being_selected_again(self):
        table = FakeTable()
        entity = build_snapshot_entity(
            ticket_number="itsm-revert",
            operation=UPDATE_OPERATION,
            env="dev",
            tennant="persona",
            application_name="app",
            before_manifest={"identifierUris": []},
            created_at="2026-01-01T10:00:00Z",
            run_id="1",
        )
        save_snapshot(table, entity)

        snapshot = find_latest_snapshot(table, "itsm-revert", UPDATE_OPERATION)
        mark_snapshot_reverted(table, snapshot, reverted_run_id="99")

        assert find_latest_snapshot(table, "itsm-revert", UPDATE_OPERATION) is None

        all_rows = query_snapshots_for_ticket(table, "itsm-revert")
        assert len(all_rows) == 1
        assert all_rows[0]["reverted"] is True
        assert all_rows[0]["revertedRunId"] == "99"

    def test_query_snapshots_for_ticket_requires_non_empty_ticket(self):
        table = FakeTable()
        with pytest.raises(RuntimeError, match="ticket_number no puede ser vacio"):
            query_snapshots_for_ticket(table, "")
