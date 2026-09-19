from __future__ import annotations

import pytest

import jobs.create.create_app_registration_job as create_job
from models.dto import CreateInputDTO
from utils.common import DISPATCH_INPUT_ENV_KEYS


def _create_input_dto(**overrides) -> CreateInputDTO:
    fields = {
        "operation": "create",
        "name": "MiApp",
        "tennant": "persona",
        "env": "dev",
        "channel": "nhbk",
        "app_type": "cc",
        "use_interactive_az_login": False,
    }
    fields.update(overrides)
    return CreateInputDTO(**fields)


class TestResolveRuntimeValues:
    def _set_dev_persona_env(self, monkeypatch):
        monkeypatch.setenv("B2CC_DEV_TENANT_ID", "tenant-dev")
        monkeypatch.setenv("B2CC_DEV_CLIENT_ID", "client-dev")
        monkeypatch.setenv("B2CC_DEV_CLIENT_SECRET", "secret-dev")

    def test_builds_display_name_and_credentials(self, monkeypatch):
        self._set_dev_persona_env(monkeypatch)
        dto = _create_input_dto()

        runtime = create_job.resolve_runtime_values(dto)

        assert runtime.app_display_name == "b2c-nhbk-miapp-cc-client-id"
        assert runtime.app_type == "cc"
        assert runtime.credentials.tenant_id == "tenant-dev"
        assert runtime.env == "dev"

    def test_cc_flow_uses_cc_graph_permissions(self, monkeypatch):
        self._set_dev_persona_env(monkeypatch)
        dto = _create_input_dto(app_type="cc")

        runtime = create_job.resolve_runtime_values(dto)

        assert runtime.graph_permissions == create_job.CC_GRAPH_DELEGATED_PERMISSIONS

    def test_ac_flow_uses_ac_graph_permissions(self, monkeypatch):
        self._set_dev_persona_env(monkeypatch)
        dto = _create_input_dto(app_type="ac")

        runtime = create_job.resolve_runtime_values(dto)

        assert runtime.graph_permissions == create_job.AC_GRAPH_DELEGATED_PERMISSIONS


class TestBuildParser:
    def test_defaults(self):
        parser = create_job.build_parser()
        args = parser.parse_args([])
        assert args.use_interactive_az_login is False

    def test_parses_provided_arguments(self):
        parser = create_job.build_parser()
        args = parser.parse_args(["--use-interactive-az-login"])
        assert args.use_interactive_az_login is True


class TestSetOutput:
    def test_writes_key_value_line_to_github_output(self, tmp_path, monkeypatch):
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        create_job.set_output("app_id", "app-123")
        create_job.set_output("app_type", "cc")

        content = output_file.read_text(encoding="utf-8")
        assert content == "app_id=app-123\napp_type=cc\n"

    def test_noop_when_github_output_not_set(self, monkeypatch):
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        create_job.set_output("app_id", "app-123")  # must not raise


class TestRunCreateFromInputReadsEnv:
    def test_missing_dispatch_env_vars_raise_via_create_input_dto(self, monkeypatch):
        for env_name in DISPATCH_INPUT_ENV_KEYS.values():
            monkeypatch.delenv(env_name, raising=False)

        with pytest.raises(RuntimeError, match="Faltan campos obligatorios"):
            create_job.run_create_from_input()


class TestRunCreateFromInput:
    def _set_common_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("B2CC_DEV_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("B2CC_INPUT_OPERATION", "create")
        monkeypatch.setenv("B2CC_INPUT_CHANNEL", "nhbk")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setenv("B2CC_INPUT_TYPE", "cc")
        monkeypatch.setenv("B2CC_INPUT_NAME", "MiApp")
        monkeypatch.setattr(create_job, "run_az", lambda args: None)
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def test_creates_new_app_when_none_exists(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(create_job, "get_application_by_display_name", lambda name: None)
        monkeypatch.setattr(
            create_job, "create_application", lambda display_name: {"appId": "new-app-id", "id": "new-obj-id"}
        )
        monkeypatch.setattr(
            create_job,
            "get_application_with_fallback_by_app_id",
            lambda app_object_id, app_id, max_attempts, delay_seconds: {
                "id": "new-obj-id",
                "displayName": "b2c-nhbk-miapp-cc-client-id",
            },
        )

        assert create_job.run_create_from_input() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "app_id=new-app-id" in content
        assert "app_object_id=new-obj-id" in content
        assert "app_display_name=b2c-nhbk-miapp-cc-client-id" in content
        assert "app_type=cc" in content

    def test_reuses_existing_app(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            create_job,
            "get_application_by_display_name",
            lambda name: {"appId": "existing-app-id", "id": "existing-obj-id"},
        )

        def fail_create(display_name):
            raise AssertionError("should not create a new app when one already exists")

        monkeypatch.setattr(create_job, "create_application", fail_create)
        monkeypatch.setattr(
            create_job,
            "get_application_with_fallback_by_app_id",
            lambda app_object_id, app_id, max_attempts, delay_seconds: {"id": "existing-obj-id"},
        )

        assert create_job.run_create_from_input() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "app_id=existing-app-id" in content
        assert "app_object_id=existing-obj-id" in content

    def test_runs_interactive_login_when_requested(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            create_job,
            "get_application_by_display_name",
            lambda name: {"appId": "existing-app-id", "id": "existing-obj-id"},
        )
        monkeypatch.setattr(
            create_job,
            "get_application_with_fallback_by_app_id",
            lambda app_object_id, app_id, max_attempts, delay_seconds: {"id": "existing-obj-id"},
        )
        az_calls = []
        monkeypatch.setattr(create_job, "run_az", lambda args: az_calls.append(args))

        assert create_job.run_create_from_input(use_interactive_az_login=True) == 0
        assert len(az_calls) == 2
        assert "--service-principal" in az_calls[0]
        assert "--service-principal" not in az_calls[1]

    def test_raises_when_existing_app_missing_ids(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            create_job, "get_application_by_display_name", lambda name: {"displayName": "incomplete"}
        )

        with pytest.raises(RuntimeError, match="no tiene appId/id validos"):
            create_job.run_create_from_input()

    def test_raises_when_graph_create_response_missing_ids(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(create_job, "get_application_by_display_name", lambda name: None)
        monkeypatch.setattr(create_job, "create_application", lambda display_name: {})

        with pytest.raises(RuntimeError, match="did not include appId/id"):
            create_job.run_create_from_input()

    def test_raises_when_created_app_cannot_be_validated(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(create_job, "get_application_by_display_name", lambda name: None)
        monkeypatch.setattr(
            create_job, "create_application", lambda display_name: {"appId": "new-app-id", "id": "new-obj-id"}
        )
        monkeypatch.setattr(
            create_job,
            "get_application_with_fallback_by_app_id",
            lambda app_object_id, app_id, max_attempts, delay_seconds: None,
        )

        with pytest.raises(RuntimeError, match="No se pudo validar la App Registration"):
            create_job.run_create_from_input()

    def test_output_json_path_argument_is_no_longer_accepted(self):
        # Historical regression guard: --output-json/--input were removed when this
        # job switched from a JSON handoff file to GITHUB_OUTPUT + env vars.
        with pytest.raises(SystemExit):
            create_job.build_parser().parse_args(["--output-json", "out.json"])
