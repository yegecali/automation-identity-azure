from __future__ import annotations

import sys

import pytest

import jobs.update.update_add_scopes_job as scopes_job


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
        monkeypatch.setattr(scopes_job, "run_az", lambda args: None)
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def test_applies_scopes_from_dispatch_input(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        calls = []
        monkeypatch.setattr(
            scopes_job,
            "configure_ac_scopes",
            lambda app_object_id, app_id, clean_scopes: calls.append((app_object_id, app_id, clean_scopes)),
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--app-id", "app-1"])

        assert scopes_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "scopes_status=updated" in content
        assert "scopes_applied=orders.read,orders.write" in content
        assert calls == [("obj-1", "app-1", ["orders.read", "orders.write"])]

    def test_scopes_csv_overrides_dispatch_scopes(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        calls = []
        monkeypatch.setattr(
            scopes_job,
            "configure_ac_scopes",
            lambda app_object_id, app_id, clean_scopes: calls.append(clean_scopes),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--app-object-id", "obj-1", "--app-id", "app-1", "--scopes-csv", "custom.scope"],
        )

        assert scopes_job.main() == 0
        assert calls == [["custom.scope"]]
        assert "scopes_applied=custom.scope" in output_file.read_text(encoding="utf-8")

    def test_raises_when_flow_is_not_ac(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path, app_type="cc")
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--app-id", "app-1"])

        with pytest.raises(RuntimeError, match="solo aplica para flujo AC"):
            scopes_job.main()
