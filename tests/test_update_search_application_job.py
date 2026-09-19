from __future__ import annotations

import sys

import pytest

import jobs.update.update_search_application_job as search_job

APP_ID = "12345678-1234-1234-1234-123456789012"


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("B2CC_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("B2CC_INPUT_OPERATION", "update")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setenv("B2CC_INPUT_APPLICATION_NAME", "b2c-nhbk-miapp-cc-client-id")
        monkeypatch.setenv("B2CC_INPUT_SCOPES", "payments.write,payments.read")
        monkeypatch.setattr(search_job, "run_az", lambda args: None)
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        monkeypatch.setattr(sys, "argv", ["prog"])
        return output_file

    def test_finds_app_and_sets_outputs(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            search_job,
            "get_application_by_display_name",
            lambda name: {"appId": APP_ID, "id": "obj-1"},
        )

        assert search_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert f"app_id={APP_ID}" in content
        assert "app_object_id=obj-1" in content
        assert "app_type=cc" in content
        assert "scopes_csv=payments.read,payments.write" in content

    def test_raises_when_application_not_found(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(search_job, "get_application_by_display_name", lambda name: None)

        with pytest.raises(RuntimeError, match="No se encontro ninguna aplicacion"):
            search_job.main()

    def test_raises_when_app_missing_id_fields(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            search_job, "get_application_by_display_name", lambda name: {"displayName": "incomplete"}
        )

        with pytest.raises(RuntimeError, match="no tiene appId/id valido"):
            search_job.main()

    def test_raises_when_app_id_is_not_a_valid_uuid(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            search_job,
            "get_application_by_display_name",
            lambda name: {"appId": "not-a-guid", "id": "obj-1"},
        )

        with pytest.raises(RuntimeError, match="no tiene formato valido"):
            search_job.main()
