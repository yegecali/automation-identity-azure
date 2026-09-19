from __future__ import annotations

import sys

import pytest

import jobs.update.update_configure_redirect_uri_job as redirect_job


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path, app_type="ac"):
        monkeypatch.setenv("B2CC_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("B2CC_INPUT_OPERATION", "update")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setenv("B2CC_INPUT_APPLICATION_NAME", f"b2c-nhbk-miapp-{app_type}-client-id")
        monkeypatch.setenv("B2CC_INPUT_SCOPES", "orders.read")
        monkeypatch.setattr(redirect_job, "run_az", lambda args: None)
        monkeypatch.setattr(redirect_job.time, "sleep", lambda seconds: None)
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def test_configures_web_redirect_for_ac_flow(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path, app_type="ac")
        patch_calls = []
        monkeypatch.setattr(
            redirect_job, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )
        monkeypatch.setattr(
            redirect_job,
            "get_application_by_id_with_retry",
            lambda object_id: {"web": {"redirectUris": ["https://example.com/callback"]}},
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--app-object-id", "obj-1", "--redirect-uri", "https://example.com/callback"],
        )

        assert redirect_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "redirect_status=updated" in content
        assert "redirect_uri=https://example.com/callback" in content
        _, body = patch_calls[0]
        assert body == {"web": {"redirectUris": ["https://example.com/callback"]}}

    def test_configures_spa_redirect_and_implicit_grant_for_cc_flow(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path, app_type="cc")
        patch_calls = []
        monkeypatch.setattr(
            redirect_job, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )
        monkeypatch.setattr(
            redirect_job,
            "get_application_by_id_with_retry",
            lambda object_id: {"spa": {"redirectUris": ["https://example.com/callback"]}},
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--app-object-id", "obj-1", "--redirect-uri", "https://example.com/callback"],
        )

        assert redirect_job.main() == 0
        _, body = patch_calls[0]
        assert body["spa"] == {"redirectUris": ["https://example.com/callback"]}
        assert body["web"]["implicitGrantSettings"]["enableAccessTokenIssuance"] is True

    def test_falls_back_to_default_redirect_uri_when_not_overridden(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path, app_type="ac")
        monkeypatch.setattr(redirect_job, "patch_application", lambda object_id, body: None)
        monkeypatch.setattr(
            redirect_job,
            "get_application_by_id_with_retry",
            lambda object_id: {"web": {"redirectUris": ["https://jwt.ms"]}},
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1"])

        assert redirect_job.main() == 0

    def test_raises_when_redirect_uri_never_confirmed(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path, app_type="ac")
        monkeypatch.setattr(redirect_job, "patch_application", lambda object_id, body: None)
        monkeypatch.setattr(
            redirect_job, "get_application_by_id_with_retry", lambda object_id: {"web": {"redirectUris": []}}
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--app-object-id", "obj-1", "--redirect-uri", "https://example.com/callback"],
        )

        with pytest.raises(RuntimeError, match="No se pudo confirmar"):
            redirect_job.main()

    def test_raises_on_invalid_redirect_uri(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path, app_type="ac")
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--redirect-uri", "not-a-url"])

        with pytest.raises(RuntimeError, match="no es valida"):
            redirect_job.main()
