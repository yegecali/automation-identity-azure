from __future__ import annotations

import sys

import pytest

import jobs.create.create_cc_client_secret_job as secret_job


class TestResolveAppContext:
    def test_returns_provided_object_id_and_name_directly(self):
        object_id, name = secret_job.resolve_app_context({}, "obj-1", "my-app")
        assert (object_id, name) == ("obj-1", "my-app")

    def test_resolves_name_from_input_data_when_arg_missing(self, monkeypatch):
        monkeypatch.setattr(secret_job, "get_application_by_display_name", lambda name: {"id": "obj-found"})
        object_id, name = secret_job.resolve_app_context({"applicationName": "my-app"}, "", "")
        assert (object_id, name) == ("obj-found", "my-app")

    def test_builds_name_from_create_fields_when_operation_is_create(self, monkeypatch):
        monkeypatch.setattr(secret_job, "get_application_by_display_name", lambda name: {"id": "obj-found"})
        input_data = {"operation": "create", "name": "MiApp", "channel": "nhbk", "type": "cc"}
        object_id, name = secret_job.resolve_app_context(input_data, "", "")
        assert name == "b2c-nhbk-miapp-cc-client-id"
        assert object_id == "obj-found"

    def test_raises_when_name_cannot_be_resolved(self):
        with pytest.raises(RuntimeError, match="No se pudo resolver nombre"):
            secret_job.resolve_app_context({}, "", "")

    def test_raises_when_application_not_found(self, monkeypatch):
        monkeypatch.setattr(secret_job, "get_application_by_display_name", lambda name: None)
        with pytest.raises(RuntimeError, match="No se encontro aplicacion"):
            secret_job.resolve_app_context({"applicationName": "my-app"}, "", "")

    def test_raises_when_app_has_no_object_id(self, monkeypatch):
        monkeypatch.setattr(
            secret_job, "get_application_by_display_name", lambda name: {"displayName": "my-app"}
        )
        with pytest.raises(RuntimeError, match="no tiene object id"):
            secret_job.resolve_app_context({"applicationName": "my-app"}, "", "")

    def test_keeps_given_object_id_over_graph_result(self, monkeypatch):
        monkeypatch.setattr(secret_job, "get_application_by_display_name", lambda name: {"id": "obj-graph"})
        object_id, name = secret_job.resolve_app_context({"applicationName": "my-app"}, "obj-given", "")
        assert object_id == "obj-given"
        assert name == "my-app"


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("B2CC_DEV_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_SECRET", "secret-1")
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def test_skips_when_not_cc_flow(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setenv("B2CC_INPUT_TYPE", "ac")
        monkeypatch.setattr(sys, "argv", ["prog"])

        assert secret_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "secret_status=skipped" in content
        assert "client_secret_obfuscated=" in content
        assert "client_secret_alias=" in content
        assert "client_secret_expires_at=" in content

    def test_creates_secret_for_cc_flow(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setenv("B2CC_INPUT_TYPE", "cc")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setattr(secret_job, "run_az", lambda args: None)
        monkeypatch.setattr(
            secret_job,
            "add_application_password",
            lambda app_object_id, display_name: {
                "secretText": "super-secret-value",
                "endDateTime": "2027-09-19T12:34:56Z",
            },
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--app-name", "my-app"])

        assert secret_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "secret_status=created" in content
        assert "client_secret_obfuscated=sup" in content
        assert "client_secret_alias=my-app-secret" in content
        assert "client_secret_expires_at=2027-09-19T12:34:56Z" in content

    def test_raises_when_graph_does_not_return_secret_text(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setenv("B2CC_INPUT_TYPE", "cc")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setattr(secret_job, "run_az", lambda args: None)
        monkeypatch.setattr(secret_job, "add_application_password", lambda app_object_id, display_name: {})
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--app-name", "my-app"])

        with pytest.raises(RuntimeError, match="no devolvio secretText"):
            secret_job.main()
