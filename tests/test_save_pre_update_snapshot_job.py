from __future__ import annotations

import sys

import pytest

import jobs.update.save_pre_update_snapshot_job as snapshot_job


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("B2CC_DEV_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "conn-string")
        monkeypatch.setenv("AZURE_TABLE_STORAGE_HISTORY_TABLE_NAME", "history")
        monkeypatch.setenv("B2CC_INPUT_OPERATION", "update")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setenv("B2CC_INPUT_APPLICATION_NAME", "b2c-nhbk-miapp-ac-client-id")
        monkeypatch.setenv("B2CC_INPUT_SCOPES", "orders.read")
        monkeypatch.setattr(snapshot_job, "run_az", lambda args: None)
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def test_skips_when_ticket_number_is_blank(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--ticket-number", "  ", "--app-object-id", "obj-1", "--app-id", "app-1"],
        )

        assert snapshot_job.main() == 0
        assert "snapshot_status=skipped" in output_file.read_text(encoding="utf-8")

    def test_saves_current_manifest_before_any_change(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        current_manifest = {"identifierUris": ["api://app-1"], "appRoles": []}
        monkeypatch.setattr(
            snapshot_job, "get_application_by_id_with_retry", lambda object_id: current_manifest
        )
        monkeypatch.setattr(snapshot_job, "connect_table", lambda conn, table, create_if_missing: "fake-table")
        saved = []
        monkeypatch.setattr(snapshot_job, "save_snapshot", lambda table, entity: saved.append((table, entity)))
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--ticket-number", "itsm-123", "--app-object-id", "obj-1", "--app-id", "app-1"],
        )

        assert snapshot_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "snapshot_status=saved" in content
        assert len(saved) == 1
        table, entity = saved[0]
        assert table == "fake-table"
        assert entity["operation"] == "update"
        assert entity["PartitionKey"] == "itsm-123"
        assert entity["appObjectId"] == "obj-1"
        import json

        assert json.loads(entity["beforeManifestJson"]) == current_manifest

    def test_raises_when_table_storage_config_missing(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.delenv("AZURE_TABLE_STORAGE_HISTORY_TABLE_NAME", raising=False)
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--ticket-number", "itsm-123", "--app-object-id", "obj-1", "--app-id", "app-1"],
        )

        with pytest.raises(RuntimeError, match="Faltan AZURE_TABLE_STORAGE"):
            snapshot_job.main()
