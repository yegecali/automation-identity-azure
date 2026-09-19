from __future__ import annotations

import pytest

from models.dto import CredentialsDTO
from utils.runtime_config import get_env_credentials


DEV_PERSONA_VARS = {
    "B2CC_DEV_TENANT_ID": "tenant-dev-persona",
    "B2CC_DEV_CLIENT_ID": "client-dev-persona",
    "B2CC_DEV_CLIENT_SECRET": "secret-dev-persona",
}

CER_PYME_VARS = {
    "B2CC_CER_PYME_TENANT_ID": "tenant-cer-pyme",
    "B2CC_CER_PYME_CLIENT_ID": "client-cer-pyme",
    "B2CC_CER_PYME_CLIENT_SECRET": "secret-cer-pyme",
}


def _set_env(monkeypatch, values: dict[str, str]) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)


class TestGetEnvCredentials:
    def test_reads_persona_vars_for_the_given_env(self, monkeypatch):
        _set_env(monkeypatch, DEV_PERSONA_VARS)

        creds = get_env_credentials("dev", "persona")

        assert creds == CredentialsDTO(
            tenant_id="tenant-dev-persona",
            client_id="client-dev-persona",
            client_secret="secret-dev-persona",
        )

    def test_reads_pyme_vars_with_pyme_suffix(self, monkeypatch):
        _set_env(monkeypatch, CER_PYME_VARS)

        creds = get_env_credentials("cer", "pyme")

        assert creds == CredentialsDTO(
            tenant_id="tenant-cer-pyme",
            client_id="client-cer-pyme",
            client_secret="secret-cer-pyme",
        )

    def test_does_not_mix_up_different_env_tennant_combos(self, monkeypatch):
        _set_env(monkeypatch, DEV_PERSONA_VARS)
        _set_env(monkeypatch, CER_PYME_VARS)

        creds = get_env_credentials("dev", "persona")

        assert creds.tenant_id == "tenant-dev-persona"

    def test_defaults_tennant_to_persona(self, monkeypatch):
        _set_env(monkeypatch, DEV_PERSONA_VARS)

        creds = get_env_credentials("dev")

        assert creds.tenant_id == "tenant-dev-persona"

    def test_invalid_env_raises(self):
        with pytest.raises(RuntimeError, match="env debe ser uno de"):
            get_env_credentials("staging", "persona")

    def test_invalid_tennant_raises(self):
        with pytest.raises(RuntimeError, match="tennant debe ser"):
            get_env_credentials("dev", "empresa")

    def test_missing_variables_are_listed_in_error(self, monkeypatch):
        monkeypatch.delenv("B2CC_PRO_TENANT_ID", raising=False)
        monkeypatch.delenv("B2CC_PRO_CLIENT_ID", raising=False)
        monkeypatch.delenv("B2CC_PRO_CLIENT_SECRET", raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            get_env_credentials("pro", "persona")

        message = str(exc_info.value)
        assert "B2CC_PRO_TENANT_ID" in message
        assert "B2CC_PRO_CLIENT_ID" in message
        assert "B2CC_PRO_CLIENT_SECRET" in message

    def test_error_names_the_env(self, monkeypatch):
        monkeypatch.delenv("B2CC_CER_PYME_TENANT_ID", raising=False)
        monkeypatch.delenv("B2CC_CER_PYME_CLIENT_ID", raising=False)
        monkeypatch.delenv("B2CC_CER_PYME_CLIENT_SECRET", raising=False)

        with pytest.raises(RuntimeError, match="'cer'"):
            get_env_credentials("cer", "pyme")
