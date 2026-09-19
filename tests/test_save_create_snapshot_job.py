from __future__ import annotations

import sys

import pytest

import jobs.create.save_create_snapshot_job as snapshot_job


class TestBuildRunUrl:
    def test_builds_url_when_all_env_vars_present(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_RUN_ID", "12345")
        assert snapshot_job.build_run_url() == "https://github.com/org/repo/actions/runs/12345"

    def test_returns_empty_string_when_any_var_missing(self, monkeypatch):
        monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_RUN_ID", "12345")
        assert snapshot_job.build_run_url() == ""


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "conn-string")
        monkeypatch.setenv("AZURE_TABLE_STORAGE_TABLE_NAME_AUDIT", "history")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def test_skips_when_ticket_number_is_blank(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prog",
                "--ticket-number",
                "   ",
                "--app-id",
                "app-1",
                "--app-object-id",
                "obj-1",
                "--app-display-name",
                "my-app",
            ],
        )

        assert snapshot_job.main() == 0
        assert "snapshot_status=skipped" in output_file.read_text(encoding="utf-8")

    def test_saves_snapshot_and_sets_output(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        saved_entities = []
        monkeypatch.setattr(snapshot_job, "connect_table", lambda conn, table, create_if_missing: "fake-table")
        monkeypatch.setattr(
            snapshot_job, "save_snapshot", lambda table, entity: saved_entities.append((table, entity))
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prog",
                "--ticket-number",
                "itsm-123",
                "--app-id",
                "app-1",
                "--app-object-id",
                "obj-1",
                "--app-display-name",
                "my-app",
                "--sp-id",
                "sp-1",
                "--app-type",
                "cc",
            ],
        )

        assert snapshot_job.main() == 0
        assert "snapshot_status=saved" in output_file.read_text(encoding="utf-8")
        assert len(saved_entities) == 1
        table, entity = saved_entities[0]
        assert table == "fake-table"
        assert entity["PartitionKey"] == "itsm-123"
        assert entity["operation"] == "create"
        assert entity["appId"] == "app-1"
        assert entity["spId"] == "sp-1"

    def test_raises_when_table_storage_config_missing(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.delenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", raising=False)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prog",
                "--ticket-number",
                "itsm-123",
                "--app-id",
                "app-1",
                "--app-object-id",
                "obj-1",
                "--app-display-name",
                "my-app",
            ],
        )

        with pytest.raises(RuntimeError, match="Faltan AZURE_TABLE_STORAGE"):
            snapshot_job.main()
