from __future__ import annotations

import pytest

from models.dto import CredentialsDTO
from utils.runtime_config import get_env_credentials


FIXED_CREDENTIAL_VARS = {
    "B2CC_TENANT_ID": "tenant-from-environment",
    "B2CC_CLIENT_ID": "client-from-environment",
    "B2CC_CLIENT_SECRET": "secret-from-environment",
}


def _set_env(monkeypatch, values: dict[str, str]) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)


class TestGetEnvCredentials:
    def test_reads_fixed_credential_vars_regardless_of_env_tennant(self, monkeypatch):
        _set_env(monkeypatch, FIXED_CREDENTIAL_VARS)

        creds = get_env_credentials("dev", "persona")

        assert creds == CredentialsDTO(
            tenant_id="tenant-from-environment",
            client_id="client-from-environment",
            client_secret="secret-from-environment",
        )

    def test_reads_same_vars_for_a_different_env_tennant_combo(self, monkeypatch):
        # The GitHub Environment selection (dev-persona, cer-pyme, ...) is what
        # picks the right secrets before this job even starts; this function
        # just reads whatever landed in the fixed-name env vars.
        _set_env(monkeypatch, FIXED_CREDENTIAL_VARS)

        creds = get_env_credentials("cer", "pyme")

        assert creds.tenant_id == "tenant-from-environment"

    def test_defaults_tennant_to_persona(self, monkeypatch):
        _set_env(monkeypatch, FIXED_CREDENTIAL_VARS)

        creds = get_env_credentials("dev")

        assert creds.tenant_id == "tenant-from-environment"

    def test_invalid_env_raises(self):
        with pytest.raises(RuntimeError, match="env debe ser uno de"):
            get_env_credentials("staging", "persona")

    def test_invalid_tennant_raises(self):
        with pytest.raises(RuntimeError, match="tennant debe ser"):
            get_env_credentials("dev", "empresa")

    def test_missing_variables_are_listed_in_error(self, monkeypatch):
        monkeypatch.delenv("B2CC_TENANT_ID", raising=False)
        monkeypatch.delenv("B2CC_CLIENT_ID", raising=False)
        monkeypatch.delenv("B2CC_CLIENT_SECRET", raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            get_env_credentials("pro", "persona")

        message = str(exc_info.value)
        assert "B2CC_TENANT_ID" in message
        assert "B2CC_CLIENT_ID" in message
        assert "B2CC_CLIENT_SECRET" in message
        assert "pro-persona" in message

    def test_error_names_the_github_environment(self, monkeypatch):
        monkeypatch.delenv("B2CC_TENANT_ID", raising=False)
        monkeypatch.delenv("B2CC_CLIENT_ID", raising=False)
        monkeypatch.delenv("B2CC_CLIENT_SECRET", raising=False)

        with pytest.raises(RuntimeError, match="cer-pyme"):
            get_env_credentials("cer", "pyme")
