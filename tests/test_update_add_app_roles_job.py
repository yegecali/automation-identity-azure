from __future__ import annotations

import sys

import pytest

import jobs.update.update_add_app_roles_job as roles_job
from models.dto import ScopeChangeSummary


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path, app_type="cc"):
        monkeypatch.setenv("B2CC_DEV_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("B2CC_INPUT_OPERATION", "update")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setenv("B2CC_INPUT_APPLICATION_NAME", f"b2c-nhbk-miapp-{app_type}-client-id")
        monkeypatch.setenv("B2CC_INPUT_SCOPES", "payments.write")
        monkeypatch.setattr(roles_job, "run_az", lambda args: None)
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def _mock_sp_resolution(self, monkeypatch, sp_id="app-sp-1"):
        monkeypatch.setattr(roles_job, "get_service_principal_by_app_id", lambda app_id: {"id": sp_id})
        monkeypatch.setattr(
            roles_job,
            "create_service_principal",
            lambda app_id: pytest.fail("create_service_principal no deberia llamarse si el SP ya existe"),
        )

    def test_applies_roles_for_cc_flow_with_consent(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        self._mock_sp_resolution(monkeypatch)
        configure_calls = []
        monkeypatch.setattr(
            roles_job,
            "configure_cc_app_roles",
            lambda app_object_id, app_id, clean_scopes, sp_id: (
                configure_calls.append((app_object_id, app_id, clean_scopes, sp_id))
                or (
                    [{"value": "payments.write", "id": "role-1"}],
                    ScopeChangeSummary(added=["payments.write"], kept=[], removed=["payments.old"]),
                )
            ),
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--app-id", "app-1"])

        assert roles_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "app_roles_status=updated" in content
        assert "app_roles_applied=payments.write" in content
        assert "scopes_applied=payments.write" in content
        assert "scopes_added=payments.write" in content
        assert "scopes_kept=" in content
        assert "scopes_removed=payments.old" in content
        assert configure_calls == [("obj-1", "app-1", ["payments.write"], "app-sp-1")]

    def test_creates_service_principal_when_missing(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(roles_job, "get_service_principal_by_app_id", lambda app_id: None)
        monkeypatch.setattr(roles_job, "create_service_principal", lambda app_id: {"id": "created-sp"})
        configure_calls = []
        monkeypatch.setattr(
            roles_job,
            "configure_cc_app_roles",
            lambda app_object_id, app_id, clean_scopes, sp_id: (
                configure_calls.append(sp_id)
                or ([{"value": "payments.write", "id": "role-1"}], ScopeChangeSummary(added=[], kept=["payments.write"], removed=[]))
            ),
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--app-id", "app-1"])

        assert roles_job.main() == 0
        assert configure_calls == ["created-sp"]

    def test_scopes_csv_overrides_dispatch_scopes(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        self._mock_sp_resolution(monkeypatch)
        monkeypatch.setattr(
            roles_job,
            "configure_cc_app_roles",
            lambda app_object_id, app_id, clean_scopes, sp_id: (
                [{"value": v, "id": f"role-{v}"} for v in clean_scopes],
                ScopeChangeSummary(added=list(clean_scopes), kept=[], removed=[]),
            ),
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
