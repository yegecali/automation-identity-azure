from __future__ import annotations

import json

import pytest

from utils.common import (
    build_app_display_name,
    dedupe_resource_access,
    escape_odata,
    get_obfuscated_secret,
    load_dispatch_input_from_env,
    load_json_file,
    normalize_token,
    unique_scopes,
)


class TestGetObfuscatedSecret:
    def test_empty_value_returns_empty_string(self):
        assert get_obfuscated_secret("") == ""

    def test_short_value_is_fully_masked(self):
        assert get_obfuscated_secret("abcdef") == "******"

    def test_long_value_keeps_first_and_last_three_chars(self):
        result = get_obfuscated_secret("supersecretvalue")
        assert result.startswith("sup")
        assert result.endswith("lue")
        assert "*" in result
        assert len(result) == len("supersecretvalue")


class TestNormalizeToken:
    def test_lowercases_and_hyphenates_spaces(self):
        assert normalize_token("Canal Web") == "canal-web"

    def test_replaces_underscores_with_spaces_before_hyphenating(self):
        assert normalize_token("canal_web_prod") == "canal-web-prod"

    def test_collapses_repeated_whitespace(self):
        assert normalize_token("  canal   web  ") == "canal-web"


class TestBuildAppDisplayName:
    def test_builds_expected_pattern(self):
        name = build_app_display_name(name="MiApp", channel="NHBK", app_type="cc")
        assert name == "b2c-nhbk-miapp-cc-client-id"

    def test_normalizes_each_component_independently(self):
        name = build_app_display_name(name="Mi App Test", channel="Canal_Web", app_type="AC")
        assert name == "b2c-canal-web-mi-app-test-ac-client-id"


class TestUniqueScopes:
    def test_deduplicates_and_sorts(self):
        assert unique_scopes(["b", "a", "b", " a "]) == ["a", "b"]

    def test_strips_and_drops_blank_entries(self):
        assert unique_scopes([" scope1 ", "", "   ", "scope2"]) == ["scope1", "scope2"]

    def test_empty_input_returns_empty_list(self):
        assert unique_scopes([]) == []


class TestEscapeOdata:
    def test_escapes_single_quotes(self):
        assert escape_odata("O'Brien") == "O''Brien"

    def test_no_quotes_is_unchanged(self):
        assert escape_odata("plain-name") == "plain-name"


class TestLoadJsonFile:
    def test_raises_when_path_is_empty(self):
        with pytest.raises(RuntimeError, match="Debes especificar la ruta"):
            load_json_file("")

    def test_raises_when_file_missing(self, tmp_path):
        missing = tmp_path / "missing.json"
        with pytest.raises(RuntimeError, match="No existe el archivo"):
            load_json_file(str(missing))

    def test_raises_when_content_is_not_an_object(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(RuntimeError, match="debe contener un objeto JSON"):
            load_json_file(str(path))

    def test_loads_valid_object(self, tmp_path):
        path = tmp_path / "input.json"
        path.write_text(json.dumps({"operation": "create"}), encoding="utf-8")
        assert load_json_file(str(path)) == {"operation": "create"}


class TestDedupeResourceAccess:
    def test_deduplicates_by_id_and_type(self):
        values = [
            {"id": "1", "type": "Scope"},
            {"id": "1", "type": "Scope"},
            {"id": "1", "type": "Role"},
            {"id": "2", "type": "Scope"},
        ]
        result = dedupe_resource_access(values)
        assert len(result) == 3
        assert {"id": "1", "type": "Scope"} in result
        assert {"id": "1", "type": "Role"} in result
        assert {"id": "2", "type": "Scope"} in result

    def test_drops_entries_missing_id_or_type(self):
        values = [{"id": "1"}, {"type": "Scope"}, {"id": "", "type": "Scope"}]
        assert dedupe_resource_access(values) == []


class TestLoadDispatchInputFromEnv:
    def test_reads_only_the_defined_env_vars(self, monkeypatch):
        monkeypatch.setenv("B2CC_INPUT_OPERATION", "create")
        monkeypatch.setenv("B2CC_INPUT_CHANNEL", "nhbk")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setenv("B2CC_INPUT_TYPE", "cc")
        monkeypatch.setenv("B2CC_INPUT_NAME", "MiApp")
        for unset in ("B2CC_INPUT_APPLICATION_NAME", "B2CC_INPUT_WEB_REDIRECT_URI", "B2CC_INPUT_SCOPES"):
            monkeypatch.delenv(unset, raising=False)

        data = load_dispatch_input_from_env()

        assert data == {
            "operation": "create",
            "channel": "nhbk",
            "env": "dev",
            "tennant": "persona",
            "type": "cc",
            "name": "MiApp",
        }

    def test_omits_unset_optional_fields_entirely(self, monkeypatch):
        for env_name in [
            "B2CC_INPUT_OPERATION",
            "B2CC_INPUT_CHANNEL",
            "B2CC_INPUT_ENV",
            "B2CC_INPUT_TENNANT",
            "B2CC_INPUT_TYPE",
            "B2CC_INPUT_NAME",
            "B2CC_INPUT_APPLICATION_NAME",
            "B2CC_INPUT_WEB_REDIRECT_URI",
            "B2CC_INPUT_SCOPES",
        ]:
            monkeypatch.delenv(env_name, raising=False)

        assert load_dispatch_input_from_env() == {}

    def test_reads_update_flow_fields(self, monkeypatch):
        monkeypatch.setenv("B2CC_INPUT_OPERATION", "update")
        monkeypatch.setenv("B2CC_INPUT_ENV", "cer")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "pyme")
        monkeypatch.setenv("B2CC_INPUT_APPLICATION_NAME", "b2c-nhbk-miapp-ac-client-id")
        monkeypatch.setenv("B2CC_INPUT_SCOPES", "scope.a,scope.b")
        monkeypatch.setenv("B2CC_INPUT_WEB_REDIRECT_URI", "https://example.com/callback")
        for unset in ("B2CC_INPUT_CHANNEL", "B2CC_INPUT_TYPE", "B2CC_INPUT_NAME"):
            monkeypatch.delenv(unset, raising=False)

        data = load_dispatch_input_from_env()

        assert data == {
            "operation": "update",
            "env": "cer",
            "tennant": "pyme",
            "applicationName": "b2c-nhbk-miapp-ac-client-id",
            "webRedirectUri": "https://example.com/callback",
            "scopes": "scope.a,scope.b",
        }
