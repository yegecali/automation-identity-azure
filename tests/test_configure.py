from __future__ import annotations

import pytest

import configure
from configure import (
    build_default_application_id_uri,
    build_manifest_restore_patch,
    resolve_app_type,
    resolve_runtime_values,
    validate_app_client_id,
    validate_redirect_uri,
)
from models.dto import ScopeChangeSummary, UpdateInputDTO

GUID = "12345678-1234-4234-8234-123456789012"


def _update_input_dto(**overrides) -> UpdateInputDTO:
    fields = {
        "operation": "update",
        "tennant": "persona",
        "env": "dev",
        "application_name": "b2c-nhbk-miapp-cc-client-id",
        "scopes": ["scope.a"],
        "app_type": None,
        "web_redirect_uri": None,
        "use_interactive_az_login": False,
    }
    fields.update(overrides)
    return UpdateInputDTO(**fields)


class TestValidateAppClientId:
    def test_valid_uuid_does_not_raise(self):
        validate_app_client_id(GUID)

    def test_empty_value_raises(self):
        with pytest.raises(RuntimeError, match="No se encontro client id"):
            validate_app_client_id("")

    def test_non_uuid_value_raises(self):
        with pytest.raises(RuntimeError, match="no tiene formato valido"):
            validate_app_client_id("not-a-guid")


class TestBuildDefaultApplicationIdUri:
    def test_plain_guid_without_tenant_domain_uses_api_scheme(self):
        assert build_default_application_id_uri(GUID) == f"api://{GUID}"

    def test_plain_guid_with_tenant_domain_uses_https(self):
        result = build_default_application_id_uri(GUID, "contoso.onmicrosoft.com")
        assert result == f"https://contoso.onmicrosoft.com/{GUID}"

    def test_tenant_domain_is_lowercased_and_stripped_of_leading_dot(self):
        result = build_default_application_id_uri(GUID, ".Contoso.OnMicrosoft.Com")
        assert result == f"https://contoso.onmicrosoft.com/{GUID}"

    def test_urn_spn_format_extracts_guid(self):
        result = build_default_application_id_uri(f"urn:spn:{GUID}")
        assert result == f"api://{GUID}"

    def test_api_scheme_format_extracts_guid(self):
        result = build_default_application_id_uri(f"api://{GUID}")
        assert result == f"api://{GUID}"

    def test_url_with_guid_tail_extracts_guid(self):
        result = build_default_application_id_uri(f"https://contoso.onmicrosoft.com/{GUID}")
        assert result == f"api://{GUID}"

    def test_non_guid_value_is_returned_unchanged(self):
        assert build_default_application_id_uri("api://custom-identifier") == "api://custom-identifier"

    def test_empty_value_raises(self):
        with pytest.raises(RuntimeError, match="No se encontro valor"):
            build_default_application_id_uri("")


class TestValidateRedirectUri:
    def test_valid_https_uri_does_not_raise(self):
        validate_redirect_uri("https://example.com/callback")

    def test_empty_value_raises(self):
        with pytest.raises(RuntimeError, match="no puede ser vacio"):
            validate_redirect_uri("")

    def test_missing_scheme_raises(self):
        with pytest.raises(RuntimeError, match="no es valida"):
            validate_redirect_uri("example.com/callback")

    def test_non_http_scheme_raises(self):
        with pytest.raises(RuntimeError, match="no es valida"):
            validate_redirect_uri("ftp://example.com/callback")


class TestResolveAppType:
    def test_explicit_type_is_used(self):
        dto = _update_input_dto(app_type="ac", application_name="anything")
        assert resolve_app_type(dto) == "ac"

    def test_explicit_invalid_type_raises(self):
        dto = _update_input_dto(app_type="oidc")
        with pytest.raises(RuntimeError, match="debe ser 'cc' o 'ac'"):
            resolve_app_type(dto)

    def test_infers_cc_from_standard_suffix(self):
        dto = _update_input_dto(app_type=None, application_name="b2c-nhbk-miapp-cc-client-id")
        assert resolve_app_type(dto) == "cc"

    def test_infers_ac_from_standard_suffix(self):
        dto = _update_input_dto(app_type=None, application_name="b2c-nhbk-miapp-ac-client-id")
        assert resolve_app_type(dto) == "ac"

    def test_infers_cc_from_legacy_pattern(self):
        dto = _update_input_dto(app_type=None, application_name="legacy-cc-app-name")
        assert resolve_app_type(dto) == "cc"

    def test_unresolvable_name_raises(self):
        dto = _update_input_dto(app_type=None, application_name="totally-unrelated-name")
        with pytest.raises(RuntimeError, match="No se pudo inferir el tipo"):
            resolve_app_type(dto)


class TestResolveRuntimeValues:
    def _set_dev_persona_env(self, monkeypatch):
        monkeypatch.setenv("B2CC_DEV_TENANT_ID", "tenant-dev")
        monkeypatch.setenv("B2CC_DEV_CLIENT_ID", "client-dev")
        monkeypatch.setenv("B2CC_DEV_CLIENT_SECRET", "secret-dev")

    def test_defaults_redirect_uri_when_missing(self, monkeypatch):
        self._set_dev_persona_env(monkeypatch)
        dto = _update_input_dto(web_redirect_uri=None, application_name="b2c-nhbk-miapp-cc-client-id")

        runtime = resolve_runtime_values(dto)

        assert runtime.redirect_uri == "https://jwt.ms"
        assert runtime.app_type == "cc"
        assert runtime.credentials.tenant_id == "tenant-dev"

    def test_uses_provided_redirect_uri(self, monkeypatch):
        self._set_dev_persona_env(monkeypatch)
        dto = _update_input_dto(web_redirect_uri="https://example.com/callback")

        runtime = resolve_runtime_values(dto)

        assert runtime.redirect_uri == "https://example.com/callback"

    def test_deduplicates_and_sorts_scopes(self, monkeypatch):
        self._set_dev_persona_env(monkeypatch)
        dto = _update_input_dto(scopes=["b.scope", "a.scope", "a.scope"])

        runtime = resolve_runtime_values(dto)

        assert runtime.scopes == ["a.scope", "b.scope"]

    def test_invalid_env_raises(self, monkeypatch):
        self._set_dev_persona_env(monkeypatch)
        dto = _update_input_dto(env="staging")

        with pytest.raises(RuntimeError, match="env en inputs-update.json"):
            resolve_runtime_values(dto)


class TestBuildManifestRestorePatch:
    def test_keeps_only_restorable_fields(self):
        manifest = {
            "id": "obj-1",
            "appId": "app-1",
            "createdDateTime": "2026-01-01T00:00:00Z",
            "publisherDomain": "contoso.onmicrosoft.com",
            "identifierUris": ["api://app-1"],
            "web": {"redirectUris": ["https://example.com/callback"]},
            "appRoles": [{"value": "role.a"}],
            "requiredResourceAccess": [{"resourceAppId": "graph", "resourceAccess": []}],
        }

        patch_body = build_manifest_restore_patch(manifest)

        assert patch_body == {
            "identifierUris": ["api://app-1"],
            "web": {"redirectUris": ["https://example.com/callback"]},
            "appRoles": [{"value": "role.a"}],
            "requiredResourceAccess": [{"resourceAppId": "graph", "resourceAccess": []}],
        }
        assert "id" not in patch_body
        assert "appId" not in patch_body
        assert "createdDateTime" not in patch_body
        assert "publisherDomain" not in patch_body

    def test_missing_fields_are_simply_omitted(self):
        patch_body = build_manifest_restore_patch({"identifierUris": ["api://app-1"]})
        assert patch_body == {"identifierUris": ["api://app-1"]}

    def test_non_dict_input_raises(self):
        with pytest.raises(RuntimeError, match="before_manifest debe ser un objeto JSON"):
            build_manifest_restore_patch(["not", "a", "dict"])

    def test_manifest_without_any_known_field_raises(self):
        with pytest.raises(RuntimeError, match="no contiene propiedades restaurables"):
            build_manifest_restore_patch({"displayName": "app"})


class TestAssignApplicationIdUriAndRedirect:
    def test_ac_flow_patches_identifier_and_web_redirect(self, monkeypatch):
        patch_calls = []
        monkeypatch.setattr(
            configure, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )
        responses = iter(
            [
                {"publisherDomain": "contoso.onmicrosoft.com"},
                {"identifierUris": [f"https://contoso.onmicrosoft.com/{GUID}"]},
            ]
        )
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: next(responses))
        monkeypatch.setattr(configure.time, "sleep", lambda seconds: None)

        result = configure.assign_application_id_uri_and_redirect(
            "obj-1", GUID, "https://example.com/callback", app_type="ac"
        )

        assert result == f"https://contoso.onmicrosoft.com/{GUID}"
        object_id, body = patch_calls[0]
        assert object_id == "obj-1"
        assert body["identifierUris"] == [f"https://contoso.onmicrosoft.com/{GUID}"]
        assert body["web"] == {"redirectUris": ["https://example.com/callback"]}
        assert "spa" not in body

    def test_cc_flow_patches_spa_redirect_and_implicit_grant(self, monkeypatch):
        patch_calls = []
        monkeypatch.setattr(
            configure, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )
        responses = iter([{"publisherDomain": ""}, {"identifierUris": [f"api://{GUID}"]}])
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: next(responses))
        monkeypatch.setattr(configure.time, "sleep", lambda seconds: None)

        configure.assign_application_id_uri_and_redirect(
            "obj-1", GUID, "https://example.com/callback", app_type="cc"
        )

        _, body = patch_calls[0]
        assert body["spa"] == {"redirectUris": ["https://example.com/callback"]}
        assert body["web"]["implicitGrantSettings"] == {
            "enableAccessTokenIssuance": True,
            "enableIdTokenIssuance": True,
        }

    def test_without_redirect_uri_only_identifier_uris_is_patched(self, monkeypatch):
        patch_calls = []
        monkeypatch.setattr(
            configure, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )
        responses = iter([{"publisherDomain": ""}, {"identifierUris": [f"api://{GUID}"]}])
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: next(responses))
        monkeypatch.setattr(configure.time, "sleep", lambda seconds: None)

        configure.assign_application_id_uri_and_redirect("obj-1", GUID, "", app_type="ac")

        _, body = patch_calls[0]
        assert body == {"identifierUris": [f"api://{GUID}"]}

    def test_retries_until_identifier_uri_becomes_visible(self, monkeypatch):
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: None)
        responses = iter(
            [
                {"publisherDomain": ""},
                {"identifierUris": []},
                {"identifierUris": []},
                {"identifierUris": [f"api://{GUID}"]},
            ]
        )
        sleep_calls = []
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: next(responses))
        monkeypatch.setattr(configure.time, "sleep", lambda seconds: sleep_calls.append(seconds))

        result = configure.assign_application_id_uri_and_redirect("obj-1", GUID, "", app_type="ac")
        assert result == f"api://{GUID}"
        assert len(sleep_calls) == 2

    def test_raises_when_identifier_uri_never_becomes_visible(self, monkeypatch):
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: None)
        monkeypatch.setattr(
            configure,
            "get_application_by_id_with_retry",
            lambda object_id: {"publisherDomain": "", "identifierUris": []},
        )
        monkeypatch.setattr(configure.time, "sleep", lambda seconds: None)

        with pytest.raises(RuntimeError, match="No se guardo correctamente"):
            configure.assign_application_id_uri_and_redirect("obj-1", GUID, "", app_type="ac")


class TestUpsertAppRolesForCc:
    def test_creates_new_roles_when_none_exist(self, monkeypatch):
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: {"appRoles": []})
        patch_calls = []
        monkeypatch.setattr(
            configure, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )

        target_roles = configure.upsert_app_roles_for_cc("obj-1", ["payments.write", "payments.read"])

        assert {role["value"] for role in target_roles} == {"payments.write", "payments.read"}
        assert len(patch_calls) == 1
        _, body = patch_calls[0]
        assert {role["value"] for role in body["appRoles"]} == {"payments.write", "payments.read"}

    def test_reuses_existing_roles_by_value(self, monkeypatch):
        existing_role = {"id": "role-existing", "value": "payments.write", "displayName": "payments.write"}
        monkeypatch.setattr(
            configure, "get_application_by_id_with_retry", lambda object_id: {"appRoles": [existing_role]}
        )
        patch_calls = []
        monkeypatch.setattr(
            configure, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )

        target_roles = configure.upsert_app_roles_for_cc("obj-1", ["payments.write"])

        assert target_roles == [existing_role]
        _, body = patch_calls[0]
        assert body["appRoles"] == [existing_role]

    def test_disables_then_removes_roles_no_longer_desired(self, monkeypatch):
        keep_role = {"id": "role-keep", "value": "payments.write", "isEnabled": True}
        drop_role = {"id": "role-drop", "value": "payments.legacy", "isEnabled": True}
        monkeypatch.setattr(
            configure, "get_application_by_id_with_retry", lambda object_id: {"appRoles": [keep_role, drop_role]}
        )
        patch_calls = []
        monkeypatch.setattr(
            configure, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )

        target_roles = configure.upsert_app_roles_for_cc("obj-1", ["payments.write"])

        assert target_roles == [keep_role]
        # 2 PATCHes: primero deshabilita el role a retirar, luego lo quita del todo.
        assert len(patch_calls) == 2
        _, disable_body = patch_calls[0]
        disabled = next(r for r in disable_body["appRoles"] if r["value"] == "payments.legacy")
        assert disabled["isEnabled"] is False
        still_enabled = next(r for r in disable_body["appRoles"] if r["value"] == "payments.write")
        assert still_enabled["isEnabled"] is True
        _, final_body = patch_calls[1]
        assert final_body["appRoles"] == [keep_role]


class TestConfigureAcScopes:
    def _base_app(self):
        return {"api": {"oauth2PermissionScopes": []}, "requiredResourceAccess": []}

    def test_adds_new_scopes_and_applies_admin_consent(self, monkeypatch):
        app_state = self._base_app()
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: app_state)
        patch_calls = []
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: patch_calls.append(body))
        monkeypatch.setattr(
            configure,
            "wait_for_configured_permissions",
            lambda app_object_id, app_id, expected_scope_ids: (expected_scope_ids, []),
        )
        monkeypatch.setattr(configure, "get_service_principal_by_app_id", lambda app_id: {"id": "sp-1"})
        grant_calls = []
        monkeypatch.setattr(
            configure,
            "upsert_oauth2_permission_grant_with_retry",
            lambda client_id, resource_id, scopes: grant_calls.append((client_id, resource_id, scopes)) or "created",
        )

        configure.configure_ac_scopes("obj-1", "api-app-id", ["orders.read"])

        assert any("api" in body for body in patch_calls)
        assert any("requiredResourceAccess" in body for body in patch_calls)
        assert grant_calls == [("sp-1", "sp-1", ["orders.read"])]

    def test_reuses_existing_scope_and_skips_service_principal_creation(self, monkeypatch):
        existing_scope = {"id": "scope-1", "value": "orders.read"}
        app_state = {
            "api": {"oauth2PermissionScopes": [existing_scope]},
            "requiredResourceAccess": [
                {"resourceAppId": "api-app-id", "resourceAccess": [{"id": "scope-1", "type": "Scope"}]}
            ],
        }
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: app_state)
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: None)
        monkeypatch.setattr(
            configure,
            "wait_for_configured_permissions",
            lambda app_object_id, app_id, expected_scope_ids: (expected_scope_ids, []),
        )
        monkeypatch.setattr(configure, "get_service_principal_by_app_id", lambda app_id: {"id": "sp-1"})

        def fail_create_sp(app_id):
            raise AssertionError("should not create a new SP when one already exists")

        monkeypatch.setattr(configure, "create_service_principal", fail_create_sp)
        monkeypatch.setattr(configure, "upsert_oauth2_permission_grant_with_retry", lambda **kwargs: "updated")

        configure.configure_ac_scopes("obj-1", "api-app-id", ["orders.read"])

    def test_creates_service_principal_when_missing(self, monkeypatch):
        app_state = self._base_app()
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: app_state)
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: None)
        monkeypatch.setattr(
            configure,
            "wait_for_configured_permissions",
            lambda app_object_id, app_id, expected_scope_ids: (expected_scope_ids, []),
        )
        monkeypatch.setattr(configure, "get_service_principal_by_app_id", lambda app_id: None)
        created = []
        monkeypatch.setattr(
            configure,
            "create_service_principal",
            lambda app_id: created.append(app_id) or {"id": "sp-new"},
        )
        monkeypatch.setattr(configure, "upsert_oauth2_permission_grant_with_retry", lambda **kwargs: "created")

        configure.configure_ac_scopes("obj-1", "api-app-id", ["orders.read"])
        assert created == ["api-app-id"]

    def test_skips_admin_consent_when_disabled(self, monkeypatch):
        app_state = self._base_app()
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: app_state)
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: None)
        monkeypatch.setattr(
            configure,
            "wait_for_configured_permissions",
            lambda app_object_id, app_id, expected_scope_ids: (expected_scope_ids, []),
        )

        def fail(*args, **kwargs):
            raise AssertionError("should not be called when apply_admin_consent=False")

        monkeypatch.setattr(configure, "get_service_principal_by_app_id", fail)
        monkeypatch.setattr(configure, "upsert_oauth2_permission_grant_with_retry", fail)

        configure.configure_ac_scopes("obj-1", "api-app-id", ["orders.read"], apply_admin_consent=False)

    def test_raises_when_scopes_do_not_fully_propagate(self, monkeypatch):
        app_state = self._base_app()
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: app_state)
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: None)
        monkeypatch.setattr(
            configure,
            "wait_for_configured_permissions",
            lambda app_object_id, app_id, expected_scope_ids: ([], expected_scope_ids),
        )

        with pytest.raises(RuntimeError, match="No quedaron todos los scopes"):
            configure.configure_ac_scopes("obj-1", "api-app-id", ["orders.read"])

    def test_raises_when_service_principal_has_no_id(self, monkeypatch):
        app_state = self._base_app()
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: app_state)
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: None)
        monkeypatch.setattr(
            configure,
            "wait_for_configured_permissions",
            lambda app_object_id, app_id, expected_scope_ids: (expected_scope_ids, []),
        )
        monkeypatch.setattr(configure, "get_service_principal_by_app_id", lambda app_id: {"id": ""})

        with pytest.raises(RuntimeError, match="No se pudo resolver service principal id"):
            configure.configure_ac_scopes("obj-1", "api-app-id", ["orders.read"])

    def test_replaces_scopes_disabling_then_removing_and_returns_diff(self, monkeypatch):
        keep_scope = {"id": "scope-keep", "value": "orders.read", "isEnabled": True}
        drop_scope = {"id": "scope-drop", "value": "orders.legacy", "isEnabled": True}
        app_state = {
            "api": {"oauth2PermissionScopes": [keep_scope, drop_scope]},
            "requiredResourceAccess": [
                {
                    "resourceAppId": "api-app-id",
                    "resourceAccess": [
                        {"id": "scope-keep", "type": "Scope"},
                        {"id": "scope-drop", "type": "Scope"},
                    ],
                }
            ],
        }
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: app_state)
        patch_calls = []
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: patch_calls.append(body))
        monkeypatch.setattr(
            configure,
            "wait_for_configured_permissions",
            lambda app_object_id, app_id, expected_scope_ids: (expected_scope_ids, []),
        )
        monkeypatch.setattr(configure, "get_service_principal_by_app_id", lambda app_id: {"id": "sp-1"})
        grant_calls = []
        monkeypatch.setattr(
            configure,
            "upsert_oauth2_permission_grant_with_retry",
            lambda client_id, resource_id, scopes: grant_calls.append(scopes) or "updated",
        )

        summary = configure.configure_ac_scopes("obj-1", "api-app-id", ["orders.read", "orders.new"])

        assert summary.added == ["orders.new"]
        assert summary.kept == ["orders.read"]
        assert summary.removed == ["orders.legacy"]

        api_patch_bodies = [body["api"] for body in patch_calls if "api" in body]
        assert len(api_patch_bodies) == 2
        disabled_scope = next(
            s for s in api_patch_bodies[0]["oauth2PermissionScopes"] if s["value"] == "orders.legacy"
        )
        assert disabled_scope["isEnabled"] is False
        final_scope_values = {s["value"] for s in api_patch_bodies[1]["oauth2PermissionScopes"]}
        assert final_scope_values == {"orders.read", "orders.new"}

        rra_patch = next(body for body in patch_calls if "requiredResourceAccess" in body)
        target_entry = next(
            e for e in rra_patch["requiredResourceAccess"] if e["resourceAppId"] == "api-app-id"
        )
        target_ids = {item["id"] for item in target_entry["resourceAccess"]}
        assert "scope-keep" in target_ids
        assert "scope-drop" not in target_ids
        assert len(target_ids) == 2  # scope-keep (reused) + el nuevo scope de orders.new

        assert grant_calls == [["orders.read", "orders.new"]]


class TestConfigureCcAppRoles:
    def test_creates_roles_and_assignments(self, monkeypatch):
        monkeypatch.setattr(
            configure,
            "upsert_app_roles_for_cc",
            lambda app_object_id, clean_scopes: [{"id": "role-1", "value": "payments.write"}],
        )
        monkeypatch.setattr(
            configure, "get_application_by_id_with_retry", lambda object_id: {"requiredResourceAccess": []}
        )
        patch_calls = []
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: patch_calls.append(body))
        assignment_calls = []
        monkeypatch.setattr(
            configure,
            "upsert_app_role_assignments_with_retry",
            lambda client_sp_id, resource_sp_id, app_role_ids: assignment_calls.append(
                (client_sp_id, resource_sp_id, app_role_ids)
            )
            or 1,
        )
        monkeypatch.setattr(
            configure,
            "remove_app_role_assignments",
            lambda **kwargs: pytest.fail("no deberia intentar remover nada, no hay roles a retirar"),
        )

        target_roles, summary = configure.configure_cc_app_roles("obj-1", "api-app-id", ["payments.write"], "sp-1")

        assert target_roles == [{"id": "role-1", "value": "payments.write"}]
        assert summary == ScopeChangeSummary(added=["payments.write"], kept=[], removed=[])
        assert patch_calls[0]["requiredResourceAccess"] == [
            {"resourceAppId": "api-app-id", "resourceAccess": [{"id": "role-1", "type": "Role"}]}
        ]
        assert assignment_calls == [("sp-1", "sp-1", ["role-1"])]

    def test_preserves_other_resource_apps_in_required_resource_access(self, monkeypatch):
        monkeypatch.setattr(
            configure,
            "upsert_app_roles_for_cc",
            lambda app_object_id, clean_scopes: [{"id": "role-1", "value": "payments.write"}],
        )
        monkeypatch.setattr(
            configure,
            "get_application_by_id_with_retry",
            lambda object_id: {
                "requiredResourceAccess": [
                    {
                        "resourceAppId": "00000003-0000-0000-c000-000000000000",
                        "resourceAccess": [{"id": "openid-id", "type": "Scope"}],
                    },
                ]
            },
        )
        patch_calls = []
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: patch_calls.append(body))
        monkeypatch.setattr(configure, "upsert_app_role_assignments_with_retry", lambda **kwargs: 1)

        configure.configure_cc_app_roles("obj-1", "api-app-id", ["payments.write"], "sp-1")

        resource_app_ids = {entry["resourceAppId"] for entry in patch_calls[0]["requiredResourceAccess"]}
        assert resource_app_ids == {"00000003-0000-0000-c000-000000000000", "api-app-id"}

    def test_removes_assignments_for_roles_no_longer_desired(self, monkeypatch):
        monkeypatch.setattr(
            configure,
            "get_application_by_id_with_retry",
            lambda object_id: {
                "appRoles": [
                    {"id": "role-keep", "value": "payments.write"},
                    {"id": "role-drop", "value": "payments.legacy"},
                ],
                "requiredResourceAccess": [],
            },
        )
        monkeypatch.setattr(
            configure,
            "upsert_app_roles_for_cc",
            lambda app_object_id, clean_scopes: [{"id": "role-keep", "value": "payments.write"}],
        )
        monkeypatch.setattr(configure, "patch_application", lambda object_id, body: None)
        monkeypatch.setattr(configure, "upsert_app_role_assignments_with_retry", lambda **kwargs: 0)
        removal_calls = []
        monkeypatch.setattr(
            configure,
            "remove_app_role_assignments",
            lambda client_sp_id, resource_sp_id, app_role_ids: removal_calls.append(
                (client_sp_id, resource_sp_id, app_role_ids)
            )
            or 1,
        )

        target_roles, summary = configure.configure_cc_app_roles(
            "obj-1", "api-app-id", ["payments.write"], "sp-1"
        )

        assert summary == ScopeChangeSummary(added=[], kept=["payments.write"], removed=["payments.legacy"])
        assert removal_calls == [("sp-1", "sp-1", ["role-drop"])]


class TestWaitForConfiguredPermissions:
    def test_returns_immediately_when_all_scopes_present(self, monkeypatch):
        monkeypatch.setattr(
            configure,
            "get_application_by_id_with_retry",
            lambda object_id: {
                "requiredResourceAccess": [{"resourceAppId": "api-1", "resourceAccess": [{"id": "s1", "type": "Scope"}]}]
            },
        )
        monkeypatch.setattr(configure.time, "sleep", lambda seconds: None)

        configured, missing = configure.wait_for_configured_permissions("obj-1", "api-1", ["s1"])
        assert configured == ["s1"]
        assert missing == []

    def test_retries_until_scopes_propagate(self, monkeypatch):
        responses = iter(
            [
                {"requiredResourceAccess": []},
                {
                    "requiredResourceAccess": [
                        {"resourceAppId": "api-1", "resourceAccess": [{"id": "s1", "type": "Scope"}]}
                    ]
                },
            ]
        )
        monkeypatch.setattr(configure, "get_application_by_id_with_retry", lambda object_id: next(responses))
        sleep_calls = []
        monkeypatch.setattr(configure.time, "sleep", lambda seconds: sleep_calls.append(seconds))

        configured, missing = configure.wait_for_configured_permissions(
            "obj-1", "api-1", ["s1"], max_attempts=3, delay_seconds=0
        )
        assert configured == ["s1"]
        assert missing == []
        assert len(sleep_calls) == 1

    def test_returns_missing_after_exhausting_attempts(self, monkeypatch):
        monkeypatch.setattr(
            configure, "get_application_by_id_with_retry", lambda object_id: {"requiredResourceAccess": []}
        )
        monkeypatch.setattr(configure.time, "sleep", lambda seconds: None)

        configured, missing = configure.wait_for_configured_permissions(
            "obj-1", "api-1", ["s1"], max_attempts=2, delay_seconds=0
        )
        assert configured == []
        assert missing == ["s1"]
