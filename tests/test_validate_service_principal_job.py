from __future__ import annotations

import sys

import pytest

import jobs.create.validate_service_principal_job as sp_job


class TestResolveAppId:
    def test_returns_provided_app_id_directly(self):
        app_id, app_name = sp_job.resolve_app_id({}, "app-id-1")
        assert (app_id, app_name) == ("app-id-1", "")

    def test_resolves_from_application_name(self, monkeypatch):
        monkeypatch.setattr(
            sp_job, "get_application_by_display_name", lambda name: {"appId": "resolved-app-id"}
        )
        app_id, app_name = sp_job.resolve_app_id({"applicationName": "my-app"}, "")
        assert (app_id, app_name) == ("resolved-app-id", "my-app")

    def test_builds_name_from_create_fields(self, monkeypatch):
        monkeypatch.setattr(
            sp_job, "get_application_by_display_name", lambda name: {"appId": "resolved-app-id"}
        )
        input_data = {"operation": "create", "name": "MiApp", "channel": "nhbk", "type": "ac"}
        app_id, app_name = sp_job.resolve_app_id(input_data, "")
        assert app_name == "b2c-nhbk-miapp-ac-client-id"
        assert app_id == "resolved-app-id"

    def test_raises_when_no_app_identification_available(self):
        with pytest.raises(RuntimeError, match="Envia --app-id o applicationName"):
            sp_job.resolve_app_id({}, "")

    def test_raises_when_application_not_found(self, monkeypatch):
        monkeypatch.setattr(sp_job, "get_application_by_display_name", lambda name: None)
        with pytest.raises(RuntimeError, match="No se encontro aplicacion"):
            sp_job.resolve_app_id({"applicationName": "my-app"}, "")

    def test_raises_when_app_has_no_app_id(self, monkeypatch):
        monkeypatch.setattr(
            sp_job, "get_application_by_display_name", lambda name: {"displayName": "my-app"}
        )
        with pytest.raises(RuntimeError, match="no tiene appId"):
            sp_job.resolve_app_id({"applicationName": "my-app"}, "")


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("B2CC_DEV_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        monkeypatch.setattr(sp_job, "run_az", lambda args: None)
        return output_file

    def test_creates_service_principal_when_none_exists(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(sp_job, "get_service_principal_by_app_id", lambda app_id: None)
        monkeypatch.setattr(sp_job, "create_service_principal", lambda app_id: {"id": "sp-new"})
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1"])

        assert sp_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "sp_status=created" in content
        assert "sp_id=sp-new" in content
        assert "app_id=app-1" in content

    def test_reuses_existing_service_principal(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(sp_job, "get_service_principal_by_app_id", lambda app_id: {"id": "sp-existing"})

        def fail_create(app_id):
            raise AssertionError("should not create when one already exists")

        monkeypatch.setattr(sp_job, "create_service_principal", fail_create)
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1"])

        assert sp_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "sp_status=existing" in content
        assert "sp_id=sp-existing" in content

    def test_sets_app_name_output_when_resolved(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            sp_job, "get_application_by_display_name", lambda name: {"appId": "app-1"}
        )
        monkeypatch.setattr(sp_job, "get_service_principal_by_app_id", lambda app_id: {"id": "sp-1"})
        monkeypatch.setattr(sys, "argv", ["prog"])

        # No applicationName in env means resolve_app_id needs it from B2CC_INPUT_APPLICATION_NAME.
        monkeypatch.setenv("B2CC_INPUT_APPLICATION_NAME", "my-app")

        assert sp_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "app_name=my-app" in content

    def test_raises_when_service_principal_has_no_id(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(sp_job, "get_service_principal_by_app_id", lambda app_id: {})
        monkeypatch.setattr(sp_job, "create_service_principal", lambda app_id: {"displayName": "no-id"})
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1"])

        with pytest.raises(RuntimeError, match="No se pudo resolver id del service principal"):
            sp_job.main()
