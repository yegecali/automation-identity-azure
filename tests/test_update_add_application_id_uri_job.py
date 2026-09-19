from __future__ import annotations

import sys

import pytest

import jobs.update.update_add_application_id_uri_job as appid_job

GUID = "12345678-1234-4234-8234-123456789012"


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("B2CC_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("B2CC_INPUT_OPERATION", "update")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setenv("B2CC_INPUT_APPLICATION_NAME", "b2c-nhbk-miapp-ac-client-id")
        monkeypatch.setenv("B2CC_INPUT_SCOPES", "orders.read")
        monkeypatch.setattr(appid_job, "run_az", lambda args: None)
        monkeypatch.setattr(appid_job.time, "sleep", lambda seconds: None)
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def test_sets_application_id_uri_after_confirmation(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        expected_uri = f"api://{GUID}"
        patch_calls = []
        monkeypatch.setattr(
            appid_job, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )
        responses = iter(
            [
                {"publisherDomain": ""},
                {"identifierUris": [expected_uri]},
            ]
        )
        monkeypatch.setattr(appid_job, "get_application_by_id_with_retry", lambda object_id: next(responses))
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--app-id", GUID])

        assert appid_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert f"application_id_uri={expected_uri}" in content
        assert "application_id_uri_status=updated" in content
        _, body = patch_calls[0]
        assert body == {"identifierUris": [expected_uri]}

    def test_uses_publisher_domain_when_available(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        expected_uri = f"https://contoso.onmicrosoft.com/{GUID}"
        monkeypatch.setattr(appid_job, "patch_application", lambda object_id, body: None)
        responses = iter(
            [
                {"publisherDomain": "contoso.onmicrosoft.com"},
                {"identifierUris": [expected_uri]},
            ]
        )
        monkeypatch.setattr(appid_job, "get_application_by_id_with_retry", lambda object_id: next(responses))
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--app-id", GUID])

        assert appid_job.main() == 0

    def test_raises_when_never_confirmed(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(appid_job, "patch_application", lambda object_id, body: None)
        monkeypatch.setattr(
            appid_job,
            "get_application_by_id_with_retry",
            lambda object_id: {"publisherDomain": "", "identifierUris": []},
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--app-object-id", "obj-1", "--app-id", GUID])

        with pytest.raises(RuntimeError, match="No se pudo confirmar Application ID URI"):
            appid_job.main()
