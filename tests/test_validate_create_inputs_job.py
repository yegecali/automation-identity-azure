from __future__ import annotations

import sys

import jobs.validate.validate_create_inputs_job as validate_job


class TestBuildCreateValidationReport:
    def test_app_does_not_exist(self):
        report = validate_job.build_create_validation_report(
            None, app_display_name="b2c-nhbk-miapp-cc-client-id", app_type="cc"
        )
        assert report["client_id_exists"] is False
        assert report["app_id"] == ""
        assert report["secret_alias_exists"] is False
        assert report["secret_alias"] == "b2c-nhbk-miapp-cc-client-id-secret"

    def test_app_exists_ac_flow_skips_secret_check(self):
        app = {"appId": "app-1", "passwordCredentials": []}
        report = validate_job.build_create_validation_report(
            app, app_display_name="b2c-nhbk-miapp-ac-client-id", app_type="ac"
        )
        assert report["client_id_exists"] is True
        assert report["app_id"] == "app-1"
        assert report["secret_alias_exists"] is False

    def test_app_exists_cc_flow_with_existing_secret_alias(self):
        app = {
            "appId": "app-1",
            "passwordCredentials": [{"displayName": "b2c-nhbk-miapp-cc-client-id-secret"}],
        }
        report = validate_job.build_create_validation_report(
            app, app_display_name="b2c-nhbk-miapp-cc-client-id", app_type="cc"
        )
        assert report["client_id_exists"] is True
        assert report["secret_alias_exists"] is True

    def test_app_exists_cc_flow_with_no_matching_secret_alias(self):
        app = {
            "appId": "app-1",
            "passwordCredentials": [{"displayName": "some-other-secret"}],
        }
        report = validate_job.build_create_validation_report(
            app, app_display_name="b2c-nhbk-miapp-cc-client-id", app_type="cc"
        )
        assert report["secret_alias_exists"] is False


class TestFormatCreateValidationComment:
    def test_reports_client_id_does_not_exist(self):
        report = validate_job.build_create_validation_report(
            None, app_display_name="b2c-nhbk-miapp-ac-client-id", app_type="ac"
        )
        comment = validate_job.format_create_validation_comment(report)
        assert "Client ID ya existe: **NO**" in comment
        assert "Alias de client secret" not in comment

    def test_reports_client_id_exists_and_secret_alias_for_cc(self):
        app = {
            "appId": "app-1",
            "passwordCredentials": [{"displayName": "b2c-nhbk-miapp-cc-client-id-secret"}],
        }
        report = validate_job.build_create_validation_report(
            app, app_display_name="b2c-nhbk-miapp-cc-client-id", app_type="cc"
        )
        comment = validate_job.format_create_validation_comment(report)
        assert "Client ID ya existe: **SI**" in comment
        assert "appId: `app-1`" in comment
        assert "Alias de client secret `b2c-nhbk-miapp-cc-client-id-secret` ya existe: **SI**" in comment


class TestMain:
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
        monkeypatch.setattr(validate_job, "run_az", lambda args: None)
        comment_path = tmp_path / "comment.md"
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return comment_path, output_file

    def test_writes_comment_and_outputs_when_app_does_not_exist(self, monkeypatch, tmp_path):
        comment_path, output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(validate_job, "get_application_by_display_name", lambda name: None)
        monkeypatch.setattr(sys, "argv", ["prog", "--comment-output", str(comment_path)])

        assert validate_job.main() == 0
        assert "client_id_exists=false" in output_file.read_text(encoding="utf-8")
        assert "secret_alias_exists=false" in output_file.read_text(encoding="utf-8")
        assert "**NO**" in comment_path.read_text(encoding="utf-8")

    def test_writes_comment_when_app_and_secret_alias_exist(self, monkeypatch, tmp_path):
        comment_path, output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            validate_job,
            "get_application_by_display_name",
            lambda name: {
                "appId": "app-1",
                "passwordCredentials": [{"displayName": "b2c-nhbk-miapp-cc-client-id-secret"}],
            },
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--comment-output", str(comment_path)])

        assert validate_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "client_id_exists=true" in content
        assert "secret_alias_exists=true" in content
