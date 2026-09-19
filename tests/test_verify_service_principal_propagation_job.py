from __future__ import annotations

import sys

import pytest

import jobs.create.verify_service_principal_propagation_job as verify_job


class TestMain:
    def _set_common_env(self, monkeypatch):
        monkeypatch.setenv("B2CC_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setattr(verify_job, "run_az", lambda args: None)

    def test_succeeds_when_sp_found_and_matches_expected(self, monkeypatch):
        self._set_common_env(monkeypatch)
        monkeypatch.setattr(verify_job, "get_service_principal_by_app_id", lambda app_id: {"id": "sp-1"})
        monkeypatch.setattr(
            sys, "argv", ["prog", "--app-id", "app-1", "--expected-sp-id", "sp-1"]
        )

        assert verify_job.main() == 0

    def test_succeeds_without_expected_sp_id_check(self, monkeypatch):
        self._set_common_env(monkeypatch)
        monkeypatch.setattr(verify_job, "get_service_principal_by_app_id", lambda app_id: {"id": "sp-1"})
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1"])

        assert verify_job.main() == 0

    def test_raises_when_sp_not_found(self, monkeypatch):
        self._set_common_env(monkeypatch)
        monkeypatch.setattr(verify_job, "get_service_principal_by_app_id", lambda app_id: None)
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1"])

        with pytest.raises(RuntimeError, match="Aun no existe service principal"):
            verify_job.main()

    def test_raises_when_sp_has_no_id(self, monkeypatch):
        self._set_common_env(monkeypatch)
        monkeypatch.setattr(
            verify_job, "get_service_principal_by_app_id", lambda app_id: {"displayName": "no-id"}
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1"])

        with pytest.raises(RuntimeError, match="no contiene id"):
            verify_job.main()

    def test_raises_when_found_sp_id_does_not_match_expected(self, monkeypatch):
        self._set_common_env(monkeypatch)
        monkeypatch.setattr(verify_job, "get_service_principal_by_app_id", lambda app_id: {"id": "sp-other"})
        monkeypatch.setattr(
            sys, "argv", ["prog", "--app-id", "app-1", "--expected-sp-id", "sp-expected"]
        )

        with pytest.raises(RuntimeError, match="SP propagado con id distinto"):
            verify_job.main()
