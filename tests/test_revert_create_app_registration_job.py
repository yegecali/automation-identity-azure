from __future__ import annotations

import sys

import pytest

import jobs.revert.revert_create_app_registration_job as revert_job


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "conn-string")
        monkeypatch.setenv("AZURE_TABLE_STORAGE_TABLE_NAME_AUDIT", "history")
        monkeypatch.setenv("B2CC_DEV_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_SECRET", "secret-1")
        monkeypatch.setattr(revert_job, "run_az", lambda args: None)
        monkeypatch.setattr(revert_job, "connect_table", lambda conn, table, create_if_missing: "fake-table")
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def _fake_snapshot(self, **overrides):
        snapshot = {
            "env": "dev",
            "tennant": "persona",
            "appId": "app-1",
            "spId": "sp-1",
            "applicationName": "b2c-nhbk-miapp-cc-client-id",
        }
        snapshot.update(overrides)
        return snapshot

    def test_disables_service_principal_and_marks_reverted(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        snapshot = self._fake_snapshot()
        monkeypatch.setattr(
            revert_job, "find_latest_snapshot", lambda table, ticket_number, operation: snapshot
        )
        patch_calls = []
        monkeypatch.setattr(
            revert_job, "patch_service_principal", lambda sp_id, body: patch_calls.append((sp_id, body))
        )
        marked = []
        monkeypatch.setattr(
            revert_job,
            "mark_snapshot_reverted",
            lambda table, snap, reverted_run_id: marked.append((table, snap, reverted_run_id)),
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--ticket-number", "itsm-123"])

        assert revert_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "revert_status=disabled" in content
        assert "app_id=app-1" in content
        assert "env=dev" in content
        assert "tennant=persona" in content
        assert patch_calls == [("sp-1", {"accountEnabled": False})]
        assert len(marked) == 1
        assert marked[0][1] == snapshot

    def test_raises_when_ticket_number_blank(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "--ticket-number", "   "])

        with pytest.raises(RuntimeError, match="Debes indicar --ticket-number"):
            revert_job.main()

    def test_raises_when_table_storage_config_missing(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.delenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", raising=False)
        monkeypatch.setattr(sys, "argv", ["prog", "--ticket-number", "itsm-123"])

        with pytest.raises(RuntimeError, match="Faltan AZURE_TABLE_STORAGE"):
            revert_job.main()

    def test_raises_when_no_snapshot_found(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(revert_job, "find_latest_snapshot", lambda table, ticket_number, operation: None)
        monkeypatch.setattr(sys, "argv", ["prog", "--ticket-number", "itsm-123"])

        with pytest.raises(RuntimeError, match="No se encontro un snapshot de creacion"):
            revert_job.main()

    def test_raises_when_snapshot_has_no_sp_id(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        snapshot = self._fake_snapshot(spId="")
        monkeypatch.setattr(
            revert_job, "find_latest_snapshot", lambda table, ticket_number, operation: snapshot
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--ticket-number", "itsm-123"])

        with pytest.raises(RuntimeError, match="no tiene spId"):
            revert_job.main()
