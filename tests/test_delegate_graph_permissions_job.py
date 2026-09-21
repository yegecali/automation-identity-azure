from __future__ import annotations

import sys

import pytest

import jobs.delegate_graph_permissions_job as delegate_job


class TestResolvePermissions:
    def test_cc_returns_cc_permissions(self):
        assert delegate_job.resolve_permissions("cc") == delegate_job.CC_GRAPH_DELEGATED_PERMISSIONS

    def test_ac_returns_ac_permissions(self):
        assert delegate_job.resolve_permissions("AC") == delegate_job.AC_GRAPH_DELEGATED_PERMISSIONS

    def test_invalid_type_raises(self):
        with pytest.raises(RuntimeError, match="type debe ser 'cc' o 'ac'"):
            delegate_job.resolve_permissions("oidc")


class TestEnsureGraphRequiredResourceAccess:
    def _graph_sp(self):
        return {
            "oauth2PermissionScopes": [
                {"value": "openid", "id": "openid-id"},
                {"value": "offline_access", "id": "offline-id"},
            ],
            "appRoles": [
                {"value": "User.Read.All", "id": "user-read-all-role-id"},
            ],
        }

    def test_raises_when_app_not_found(self, monkeypatch):
        monkeypatch.setattr(delegate_job, "get_application_by_app_id", lambda app_id: None)
        with pytest.raises(RuntimeError, match="No se encontro la App Registration"):
            delegate_job.ensure_graph_required_resource_access("app-1", "graph-app-id", ["openid"])

    def test_raises_when_app_has_no_object_id(self, monkeypatch):
        monkeypatch.setattr(delegate_job, "get_application_by_app_id", lambda app_id: {"appId": "app-1"})
        with pytest.raises(RuntimeError, match="no tiene object id valido"):
            delegate_job.ensure_graph_required_resource_access("app-1", "graph-app-id", ["openid"])

    def test_raises_when_graph_sp_not_found(self, monkeypatch):
        monkeypatch.setattr(delegate_job, "get_application_by_app_id", lambda app_id: {"id": "obj-1"})
        monkeypatch.setattr(delegate_job, "get_service_principal_by_app_id", lambda app_id: None)
        with pytest.raises(RuntimeError, match="No se encontro service principal de Microsoft Graph"):
            delegate_job.ensure_graph_required_resource_access("app-1", "graph-app-id", ["openid"])

    def test_raises_when_permission_id_cannot_be_resolved(self, monkeypatch):
        monkeypatch.setattr(delegate_job, "get_application_by_app_id", lambda app_id: {"id": "obj-1"})
        monkeypatch.setattr(
            delegate_job, "get_service_principal_by_app_id", lambda app_id: {"oauth2PermissionScopes": []}
        )
        with pytest.raises(RuntimeError, match="No se pudieron resolver IDs"):
            delegate_job.ensure_graph_required_resource_access("app-1", "graph-app-id", ["openid"])

    def test_patches_merged_resource_access_and_returns_count(self, monkeypatch):
        monkeypatch.setattr(
            delegate_job,
            "get_application_by_app_id",
            lambda app_id: {"id": "obj-1", "requiredResourceAccess": []},
        )
        monkeypatch.setattr(delegate_job, "get_service_principal_by_app_id", lambda app_id: self._graph_sp())
        patch_calls = []
        monkeypatch.setattr(
            delegate_job, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )

        count, delegated_permissions, application_role_ids = delegate_job.ensure_graph_required_resource_access(
            "app-1", "graph-app-id", ["openid", "offline_access"]
        )

        assert count == 2
        assert delegated_permissions == ["openid", "offline_access"]
        assert application_role_ids == []
        object_id, body = patch_calls[0]
        assert object_id == "obj-1"
        graph_entry = next(
            e for e in body["requiredResourceAccess"] if e["resourceAppId"] == "graph-app-id"
        )
        assert {item["id"] for item in graph_entry["resourceAccess"]} == {"openid-id", "offline-id"}
        assert all(item["type"] == "Scope" for item in graph_entry["resourceAccess"])

    def test_user_read_all_is_declared_as_application_role(self, monkeypatch):
        monkeypatch.setattr(
            delegate_job,
            "get_application_by_app_id",
            lambda app_id: {"id": "obj-1", "requiredResourceAccess": []},
        )
        monkeypatch.setattr(delegate_job, "get_service_principal_by_app_id", lambda app_id: self._graph_sp())
        patch_calls = []
        monkeypatch.setattr(
            delegate_job, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )

        count, delegated_permissions, application_role_ids = delegate_job.ensure_graph_required_resource_access(
            "app-1", "graph-app-id", ["openid", "User.Read.All"]
        )

        assert count == 2
        assert delegated_permissions == ["openid"]
        assert application_role_ids == ["user-read-all-role-id"]
        _, body = patch_calls[0]
        graph_entry = next(
            e for e in body["requiredResourceAccess"] if e["resourceAppId"] == "graph-app-id"
        )
        access_by_id = {item["id"]: item["type"] for item in graph_entry["resourceAccess"]}
        assert access_by_id["openid-id"] == "Scope"
        assert access_by_id["user-read-all-role-id"] == "Role"

    def test_raises_when_application_role_id_cannot_be_resolved(self, monkeypatch):
        monkeypatch.setattr(delegate_job, "get_application_by_app_id", lambda app_id: {"id": "obj-1"})
        monkeypatch.setattr(
            delegate_job, "get_service_principal_by_app_id", lambda app_id: {"oauth2PermissionScopes": [], "appRoles": []}
        )
        with pytest.raises(RuntimeError, match="No se pudieron resolver IDs de permisos de aplicacion"):
            delegate_job.ensure_graph_required_resource_access("app-1", "graph-app-id", ["User.Read.All"])

    def test_preserves_other_resource_apps(self, monkeypatch):
        monkeypatch.setattr(
            delegate_job,
            "get_application_by_app_id",
            lambda app_id: {
                "id": "obj-1",
                "requiredResourceAccess": [
                    {"resourceAppId": "some-other-api", "resourceAccess": [{"id": "x", "type": "Scope"}]}
                ],
            },
        )
        monkeypatch.setattr(delegate_job, "get_service_principal_by_app_id", lambda app_id: self._graph_sp())
        patch_calls = []
        monkeypatch.setattr(
            delegate_job, "patch_application", lambda object_id, body: patch_calls.append((object_id, body))
        )

        delegate_job.ensure_graph_required_resource_access("app-1", "graph-app-id", ["openid"])

        _, body = patch_calls[0]
        resource_app_ids = {e["resourceAppId"] for e in body["requiredResourceAccess"]}
        assert resource_app_ids == {"some-other-api", "graph-app-id"}


class TestMain:
    def _set_common_env(self, monkeypatch, tmp_path, app_type="cc"):
        monkeypatch.setenv("B2CC_DEV_TENANT_ID", "tenant-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_ID", "client-1")
        monkeypatch.setenv("B2CC_DEV_CLIENT_SECRET", "secret-1")
        monkeypatch.setenv("B2CC_INPUT_ENV", "dev")
        monkeypatch.setenv("B2CC_INPUT_TENNANT", "persona")
        monkeypatch.setenv("B2CC_INPUT_TYPE", app_type)
        monkeypatch.setattr(delegate_job, "run_az", lambda args: None)
        output_file = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        return output_file

    def test_full_flow_with_provided_app_sp_id(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            delegate_job,
            "get_service_principal_by_app_id",
            lambda app_id: {"id": "graph-sp-1"},
        )
        monkeypatch.setattr(
            delegate_job, "ensure_graph_required_resource_access", lambda app_id, graph_app_id, permissions: (2, permissions, [])
        )
        monkeypatch.setattr(
            delegate_job,
            "upsert_oauth2_permission_grant_with_retry",
            lambda client_id, resource_id, scopes: "created",
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1", "--app-sp-id", "app-sp-1"])

        assert delegate_job.main() == 0
        content = output_file.read_text(encoding="utf-8")
        assert "grant_status=created" in content
        assert "app_sp_id=app-sp-1" in content

    def test_user_read_all_creates_app_role_assignment_not_oauth2_grant(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path, app_type="ac")
        monkeypatch.setattr(
            delegate_job,
            "get_service_principal_by_app_id",
            lambda app_id: {"id": "graph-sp-1"},
        )
        monkeypatch.setattr(
            delegate_job,
            "ensure_graph_required_resource_access",
            lambda app_id, graph_app_id, permissions: (3, ["openid", "offline_access"], ["user-read-all-role-id"]),
        )
        oauth2_calls = []
        monkeypatch.setattr(
            delegate_job,
            "upsert_oauth2_permission_grant_with_retry",
            lambda client_id, resource_id, scopes: oauth2_calls.append(scopes) or "created",
        )
        role_assignment_calls = []
        monkeypatch.setattr(
            delegate_job,
            "upsert_app_role_assignments_with_retry",
            lambda client_sp_id, resource_sp_id, app_role_ids: role_assignment_calls.append(app_role_ids) or 1,
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1", "--app-sp-id", "app-sp-1"])

        assert delegate_job.main() == 0
        assert oauth2_calls == [["openid", "offline_access"]]
        assert role_assignment_calls == [["user-read-all-role-id"]]
        content = output_file.read_text(encoding="utf-8")
        assert "granted_scopes=User.Read.All offline_access openid" in content

    def test_resolves_app_sp_id_when_not_provided(self, monkeypatch, tmp_path):
        output_file = self._set_common_env(monkeypatch, tmp_path)

        def fake_get_sp(app_id):
            if app_id == "app-1":
                return {"id": "resolved-sp"}
            return {"id": "graph-sp-1"}

        monkeypatch.setattr(delegate_job, "get_service_principal_by_app_id", fake_get_sp)
        monkeypatch.setattr(
            delegate_job, "ensure_graph_required_resource_access", lambda app_id, graph_app_id, permissions: (2, permissions, [])
        )
        monkeypatch.setattr(
            delegate_job,
            "upsert_oauth2_permission_grant_with_retry",
            lambda client_id, resource_id, scopes: "created",
        )
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1"])

        assert delegate_job.main() == 0
        assert "app_sp_id=resolved-sp" in output_file.read_text(encoding="utf-8")

    def test_raises_when_app_service_principal_not_found(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(delegate_job, "get_service_principal_by_app_id", lambda app_id: None)
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1"])

        with pytest.raises(RuntimeError, match="No se encontro service principal de la aplicacion"):
            delegate_job.main()

    def test_raises_when_graph_service_principal_not_found(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(delegate_job, "get_service_principal_by_app_id", lambda app_id: None)
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1", "--app-sp-id", "app-sp-1"])

        with pytest.raises(RuntimeError, match="No se encontro service principal de Microsoft Graph"):
            delegate_job.main()

    def test_raises_when_graph_service_principal_missing_id(self, monkeypatch, tmp_path):
        self._set_common_env(monkeypatch, tmp_path)
        monkeypatch.setattr(delegate_job, "get_service_principal_by_app_id", lambda app_id: {"displayName": "x"})
        monkeypatch.setattr(sys, "argv", ["prog", "--app-id", "app-1", "--app-sp-id", "app-sp-1"])

        with pytest.raises(RuntimeError, match="Service principal de Graph no tiene id"):
            delegate_job.main()
