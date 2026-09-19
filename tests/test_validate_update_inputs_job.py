from __future__ import annotations

import sys

import jobs.validate.validate_update_inputs_job as validate_job


class TestExtractCurrentScopes:
    def test_extracts_delegated_scopes_for_ac(self):
        app = {"api": {"oauth2PermissionScopes": [{"value": "orders.read"}, {"value": "orders.write"}]}}
        assert validate_job.extract_current_scopes(app, "ac") == ["orders.read", "orders.write"]

    def test_extracts_app_roles_for_cc(self):
        app = {"appRoles": [{"value": "payments.write"}, {"value": "payments.read"}]}
        assert validate_job.extract_current_scopes(app, "cc") == ["payments.read", "payments.write"]

    def test_missing_api_or_app_roles_returns_empty(self):
        assert validate_job.extract_current_scopes({}, "ac") == []
        assert validate_job.extract_current_scopes({}, "cc") == []


class TestDiffScopes:
    def test_added_are_requested_not_in_current(self):
        added, missing = validate_job.diff_scopes(current=["a", "b"], requested=["b", "c"])
        assert added == ["c"]
        assert missing == ["a"]

    def test_no_difference_returns_empty_lists(self):
        added, missing = validate_job.diff_scopes(current=["a"], requested=["a"])
        assert added == []
        assert missing == []

    def test_results_are_sorted(self):
        added, missing = validate_job.diff_scopes(current=["z", "y"], requested=["b", "a"])
        assert added == ["a", "b"]
        assert missing == ["y", "z"]


class TestFormatUpdateValidationComment:
    def test_reports_added_and_missing_scopes(self):
        comment = validate_job.format_update_validation_comment(
            application_name="b2c-nhbk-miapp-ac-client-id",
            app_type="ac",
            current_scopes=["a", "b"],
            requested_scopes=["b", "c"],
            added=["c"],
            missing=["a"],
        )
        assert "Se **agregarían**: `c`" in comment
        assert "no incluidos** en este request: `a`" in comment
        assert "no elimina de Graph" in comment

    def test_no_added_or_missing_scopes(self):
        comment = validate_job.format_update_validation_comment(
            application_name="b2c-nhbk-miapp-cc-client-id",
            app_type="cc",
            current_scopes=["a"],
            requested_scopes=["a"],
            added=[],
            missing=[],
        )
        assert "Se agregarían: _(ninguno)_" in comment
        assert "No hay scopes/app roles configurados hoy que falten en el request." in comment

    def test_empty_current_scopes_render_placeholder(self):
        comment = validate_job.format_update_validation_comment(
            application_name="app",
            app_type="ac",
            current_scopes=[],
            requested_scopes=["a"],
            added=["a"],
            missing=[],
        )
        assert "Configurados actualmente: _(ninguno)_" in comment


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path, app_type="ac"):
        monkeypatch.setenv("B2CC_DEV_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("B2CC_INPUT_OPERATION", "update")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setenv("B2CC_INPUT_APPLICATION_NAME", f"b2c-nhbk-miapp-{app_type}-client-id")
        monkeypatch.setenv("B2CC_INPUT_SCOPES", "orders.read,orders.write")
        monkeypatch.setattr(validate_job, "run_az", lambda args: None)
        comment_path = tmp_path / "comment.md"
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return comment_path, output_file

    def test_writes_not_found_comment_when_app_missing(self, monkeypatch, tmp_path):
        comment_path, output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(validate_job, "get_application_by_display_name", lambda name: None)
        monkeypatch.setattr(sys, "argv", ["prog", "--comment-output", str(comment_path)])

        assert validate_job.main() == 0
        assert "app_found=false" in output_file.read_text(encoding="utf-8")
        assert "No se encontró ninguna aplicación" in comment_path.read_text(encoding="utf-8")

    def test_writes_scope_diff_comment_when_app_found(self, monkeypatch, tmp_path):
        comment_path, output_file = self._set_common_env(monkeypatch, tmp_path, app_type="ac")
        monkeypatch.setattr(
            validate_job,
            "get_application_by_display_name",
            lambda name: {"api": {"oauth2PermissionScopes": [{"value": "orders.read"}]}},
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--comment-output", str(comment_path)])

        assert validate_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "app_found=true" in content
        assert "scopes_added=orders.write" in content
        comment_text = comment_path.read_text(encoding="utf-8")
        assert "Se **agregarían**: `orders.write`" in comment_text
