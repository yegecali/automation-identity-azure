from __future__ import annotations

import sys

import pytest

import jobs.revert.find_snapshot_env_job as find_job


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "conn-string")
        monkeypatch.setenv("AZURE_TABLE_STORAGE_HISTORY_TABLE_NAME", "history")
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def test_sets_env_and_tennant_from_snapshot(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(find_job, "connect_table", lambda conn, table, create_if_missing: "fake-table")
        monkeypatch.setattr(
            find_job,
            "find_latest_snapshot",
            lambda table, ticket_number, operation: {"env": "DEV", "tennant": "PERSONA"},
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--ticket-number", "itsm-123", "--operation", "create"])

        assert find_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "env=dev" in content
        assert "tennant=persona" in content

    def test_raises_when_ticket_number_is_blank(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "--ticket-number", "   ", "--operation", "create"])

        with pytest.raises(RuntimeError, match="Debes indicar --ticket-number"):
            find_job.main()

    def test_raises_when_table_storage_config_missing(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.delenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", raising=False)
        monkeypatch.setattr(sys, "argv", ["prog", "--ticket-number", "itsm-123", "--operation", "create"])

        with pytest.raises(RuntimeError, match="Faltan AZURE_TABLE_STORAGE"):
            find_job.main()

    def test_raises_when_no_snapshot_found(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(find_job, "connect_table", lambda conn, table, create_if_missing: "fake-table")
        monkeypatch.setattr(find_job, "find_latest_snapshot", lambda table, ticket_number, operation: None)
        monkeypatch.setattr(sys, "argv", ["prog", "--ticket-number", "itsm-123", "--operation", "update"])

        with pytest.raises(RuntimeError, match="No se encontro un snapshot de update"):
            find_job.main()

    def test_raises_when_snapshot_missing_env_or_tennant(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(find_job, "connect_table", lambda conn, table, create_if_missing: "fake-table")
        monkeypatch.setattr(
            find_job, "find_latest_snapshot", lambda table, ticket_number, operation: {"env": "", "tennant": ""}
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--ticket-number", "itsm-123", "--operation", "create"])

        with pytest.raises(RuntimeError, match="no tiene env/tennant validos"):
            find_job.main()

    def test_rejects_invalid_operation_choice(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "--ticket-number", "itsm-123", "--operation", "delete"])

        with pytest.raises(SystemExit):
            find_job.main()
