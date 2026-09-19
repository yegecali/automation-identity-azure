from __future__ import annotations

import sys

import pytest

import jobs.update.update_add_app_roles_job as roles_job


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path, app_type="cc"):
        monkeypatch.setenv("B2CC_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("B2CC_INPUT_OPERATION", "update")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setenv("B2CC_INPUT_APPLICATION_NAME", f"b2c-nhbk-miapp-{app_type}-client-id")
        monkeypatch.setenv("B2CC_INPUT_SCOPES", "payments.write")
        monkeypatch.setattr(roles_job, "run_az", lambda args: None)
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def test_applies_roles_and_scopes_for_cc_flow(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            roles_job,
            "upsert_app_roles_for_cc",
            lambda app_object_id, clean_scopes: [{"value": "payments.write", "id": "role-1"}],
        )
        ac_scope_calls = []
        monkeypatch.setattr(
            roles_job,
            "configure_ac_scopes",
            lambda app_object_id, app_id, clean_scopes, apply_admin_consent: ac_scope_calls.append(
                apply_admin_consent
            ),
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--app-id", "app-1"])

        assert roles_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "app_roles_status=updated" in content
        assert "app_roles_applied=payments.write" in content
        assert "scopes_applied=payments.write" in content
        assert ac_scope_calls == [False]

    def test_scopes_csv_overrides_dispatch_scopes(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            roles_job,
            "upsert_app_roles_for_cc",
            lambda app_object_id, clean_scopes: [{"value": v, "id": f"role-{v}"} for v in clean_scopes],
        )
        monkeypatch.setattr(
            roles_job,
            "configure_ac_scopes",
            lambda app_object_id, app_id, clean_scopes, apply_admin_consent: None,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--app-object-id", "obj-1", "--app-id", "app-1", "--scopes-csv", "custom.role"],
        )

        assert roles_job.main() == 0
        assert "app_roles_applied=custom.role" in output_file.read_text(encoding="utf-8")

    def test_raises_when_flow_is_not_cc(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path, app_type="ac")
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--app-id", "app-1"])

        with pytest.raises(RuntimeError, match="solo aplica para flujo CC"):
            roles_job.main()
