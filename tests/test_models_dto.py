from __future__ import annotations

import pytest

from models.dto import AppRoleDTO, CreateInputDTO, ScopeDTO, UpdateInputDTO


def _valid_create_payload(**overrides):
    payload = {
        "operation": "create",
        "name": "MiApp",
        "tennant": "persona",
        "env": "dev",
        "channel": "nhbk",
        "type": "cc",
    }
    payload.update(overrides)
    return payload


def _valid_update_payload(**overrides):
    payload = {
        "operation": "update",
        "tennant": "persona",
        "env": "dev",
        "applicationName": "b2c-nhbk-miapp-cc-client-id",
        "scopes": ["scope.a", "scope.b"],
    }
    payload.update(overrides)
    return payload


class TestCreateInputDTO:
    def test_valid_payload_is_parsed(self):
        dto = CreateInputDTO.from_dict(_valid_create_payload())

        assert dto.operation == "create"
        assert dto.name == "MiApp"
        assert dto.tennant == "persona"
        assert dto.env == "dev"
        assert dto.channel == "nhbk"
        assert dto.app_type == "cc"
        assert dto.use_interactive_az_login is False

    def test_values_are_lowercased_and_trimmed(self):
        dto = CreateInputDTO.from_dict(
            _valid_create_payload(tennant=" PERSONA ", env=" DEV ", type=" CC ")
        )
        assert dto.tennant == "persona"
        assert dto.env == "dev"
        assert dto.app_type == "cc"

    def test_accepts_tenant_alias(self):
        payload = _valid_create_payload()
        del payload["tennant"]
        payload["tenant"] = "pyme"
        dto = CreateInputDTO.from_dict(payload)
        assert dto.tennant == "pyme"

    @pytest.mark.parametrize("missing_field", ["operation", "name", "tennant", "env", "channel", "type"])
    def test_missing_required_field_raises(self, missing_field):
        payload = _valid_create_payload()
        del payload[missing_field]
        with pytest.raises(RuntimeError, match="Faltan campos obligatorios"):
            CreateInputDTO.from_dict(payload)

    def test_operation_must_be_create(self):
        payload = _valid_create_payload(operation="update")
        with pytest.raises(RuntimeError, match="operation para CreateInputDTO debe ser 'create'"):
            CreateInputDTO.from_dict(payload)

    def test_invalid_tennant_raises(self):
        payload = _valid_create_payload(tennant="empresa")
        with pytest.raises(RuntimeError, match="tennant en input.json debe ser"):
            CreateInputDTO.from_dict(payload)

    def test_invalid_env_raises(self):
        payload = _valid_create_payload(env="staging")
        with pytest.raises(RuntimeError, match="env debe ser uno de"):
            CreateInputDTO.from_dict(payload)

    def test_invalid_type_raises(self):
        payload = _valid_create_payload(type="oidc")
        with pytest.raises(RuntimeError, match="type en input.json debe ser 'cc' o 'ac'"):
            CreateInputDTO.from_dict(payload)


class TestUpdateInputDTO:
    def test_valid_payload_with_scope_list(self):
        dto = UpdateInputDTO.from_dict(_valid_update_payload())

        assert dto.operation == "update"
        assert dto.application_name == "b2c-nhbk-miapp-cc-client-id"
        assert dto.scopes == ["scope.a", "scope.b"]
        assert dto.web_redirect_uri is None
        assert dto.app_type is None

    def test_scopes_as_comma_separated_string_are_split_and_sorted(self):
        dto = UpdateInputDTO.from_dict(_valid_update_payload(scopes="scope.b, scope.a ,scope.a"))
        assert dto.scopes == ["scope.a", "scope.b"]

    def test_scopes_list_items_may_contain_embedded_separators(self):
        dto = UpdateInputDTO.from_dict(_valid_update_payload(scopes=["scope.a,scope.b", "scope.c"]))
        assert dto.scopes == ["scope.a", "scope.b", "scope.c"]

    def test_application_name_falls_back_to_name(self):
        payload = _valid_update_payload()
        del payload["applicationName"]
        payload["name"] = "b2c-nhbk-miapp-cc-client-id"
        dto = UpdateInputDTO.from_dict(payload)
        assert dto.application_name == "b2c-nhbk-miapp-cc-client-id"

    def test_web_redirect_uri_is_optional(self):
        dto = UpdateInputDTO.from_dict(_valid_update_payload(webRedirectUri="https://example.com/callback"))
        assert dto.web_redirect_uri == "https://example.com/callback"

    def test_operation_must_be_update(self):
        with pytest.raises(RuntimeError, match="operation para UpdateInputDTO debe ser 'update'"):
            UpdateInputDTO.from_dict(_valid_update_payload(operation="create"))

    def test_missing_application_name_raises(self):
        payload = _valid_update_payload()
        del payload["applicationName"]
        with pytest.raises(RuntimeError, match="applicationName o name"):
            UpdateInputDTO.from_dict(payload)

    def test_empty_scopes_raises(self):
        with pytest.raises(RuntimeError, match="al menos un scope"):
            UpdateInputDTO.from_dict(_valid_update_payload(scopes=[]))

    def test_scopes_wrong_type_raises(self):
        with pytest.raises(RuntimeError, match="scopes en input.json debe ser"):
            UpdateInputDTO.from_dict(_valid_update_payload(scopes=123))

    def test_invalid_type_raises(self):
        with pytest.raises(RuntimeError, match="type en input.json debe ser 'cc' o 'ac'"):
            UpdateInputDTO.from_dict(_valid_update_payload(type="oidc"))

    def test_type_is_optional(self):
        dto = UpdateInputDTO.from_dict(_valid_update_payload())
        assert dto.app_type is None


class TestAppRoleDTO:
    def test_from_role_value_builds_expected_shape(self):
        role = AppRoleDTO.from_role_value("payments.write")

        assert role.value == "payments.write"
        assert role.display_name == "payments.write"
        assert role.description == "payments.write"
        assert role.allowed_member_types == ["Application"]
        assert role.is_enabled is True
        assert role.id

    def test_empty_value_raises(self):
        with pytest.raises(RuntimeError, match="app role no puede ser vacio"):
            AppRoleDTO.from_role_value("   ")

    def test_to_graph_dict_matches_graph_schema(self):
        role = AppRoleDTO.from_role_value("payments.write")
        graph_dict = role.to_graph_dict()

        assert graph_dict == {
            "id": role.id,
            "allowedMemberTypes": ["Application"],
            "description": "payments.write",
            "displayName": "payments.write",
            "isEnabled": True,
            "value": "payments.write",
        }


class TestScopeDTO:
    def test_from_scope_name_builds_expected_shape(self):
        scope = ScopeDTO.from_scope_name("orders.read")

        assert scope.value == "orders.read"
        assert scope.scope_type == "Admin"
        assert scope.is_enabled is True
        assert scope.id

    def test_empty_value_raises(self):
        with pytest.raises(RuntimeError, match="scope no puede ser vacio"):
            ScopeDTO.from_scope_name("")

    def test_to_graph_dict_matches_graph_schema(self):
        scope = ScopeDTO.from_scope_name("orders.read")
        graph_dict = scope.to_graph_dict()

        assert graph_dict == {
            "id": scope.id,
            "value": "orders.read",
            "type": "Admin",
            "isEnabled": True,
            "adminConsentDisplayName": "orders.read",
            "adminConsentDescription": "orders.read",
            "userConsentDisplayName": "orders.read",
            "userConsentDescription": "orders.read",
        }
