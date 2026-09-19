from __future__ import annotations

import io
import subprocess
from urllib.error import HTTPError, URLError

import pytest

from services import graph_service
from services.graph_service import GraphHttpClient, get_first_value


class FakeHTTPResponse:
    def __init__(self, status: int, body: str):
        self._status = status
        self._body = body.encode("utf-8")

    def getcode(self):
        return self._status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class TestGetFirstValue:
    def test_returns_first_item_when_list_is_non_empty(self):
        assert get_first_value({"value": [{"id": "1"}, {"id": "2"}]}) == {"id": "1"}

    def test_returns_none_when_list_is_empty(self):
        assert get_first_value({"value": []}) is None

    def test_returns_none_when_value_key_missing(self):
        assert get_first_value({}) is None


class TestNormalizeGraphUrl:
    def setup_method(self):
        self.client = GraphHttpClient()

    def test_relative_path_is_prefixed_with_graph_host(self):
        result = self.client._normalize_graph_url("/v1.0/applications")
        assert result == "https://graph.microsoft.com/v1.0/applications"

    def test_absolute_url_is_kept_as_is_host(self):
        result = self.client._normalize_graph_url("https://graph.microsoft.com/v1.0/applications")
        assert result.startswith("https://graph.microsoft.com/v1.0/applications")

    def test_query_with_odata_filter_is_preserved(self):
        url = "https://graph.microsoft.com/v1.0/applications?$filter=displayName eq 'my-app'"
        result = self.client._normalize_graph_url(url)
        assert "$filter=displayName" in result
        assert "my-app" in result

    def test_strips_surrounding_whitespace(self):
        result = self.client._normalize_graph_url("  /v1.0/applications  ")
        assert result == "https://graph.microsoft.com/v1.0/applications"


class TestResolveAzExecutable:
    def test_returns_first_candidate_found_in_path(self, monkeypatch):
        def fake_which(candidate):
            return "/usr/bin/az" if candidate == "az" else None

        monkeypatch.setattr(graph_service.shutil, "which", fake_which)
        assert graph_service.resolve_az_executable() == "/usr/bin/az"

    def test_falls_back_to_az_cmd_on_windows_style_path(self, monkeypatch):
        def fake_which(candidate):
            return r"C:\az.cmd" if candidate == "az.cmd" else None

        monkeypatch.setattr(graph_service.shutil, "which", fake_which)
        assert graph_service.resolve_az_executable() == r"C:\az.cmd"

    def test_raises_when_az_is_nowhere_in_path(self, monkeypatch):
        monkeypatch.setattr(graph_service.shutil, "which", lambda candidate: None)
        with pytest.raises(RuntimeError, match="No se encontro Azure CLI"):
            graph_service.resolve_az_executable()


class TestRunAz:
    def setup_method(self):
        pass

    def _fake_completed_process(self, returncode=0, stdout="", stderr=""):
        return subprocess.CompletedProcess(args=["az"], returncode=returncode, stdout=stdout, stderr=stderr)

    def test_returns_none_when_json_not_expected(self, monkeypatch):
        monkeypatch.setattr(graph_service, "resolve_az_executable", lambda: "az")
        monkeypatch.setattr(
            graph_service.subprocess, "run", lambda *a, **k: self._fake_completed_process(stdout="ok")
        )
        assert graph_service.run_az(["login"]) is None

    def test_parses_json_output_when_expected(self, monkeypatch):
        monkeypatch.setattr(graph_service, "resolve_az_executable", lambda: "az")
        monkeypatch.setattr(
            graph_service.subprocess,
            "run",
            lambda *a, **k: self._fake_completed_process(stdout='{"appId": "123"}'),
        )
        result = graph_service.run_az(["ad", "app", "show"], expect_json=True)
        assert result == {"appId": "123"}

    def test_empty_output_with_json_expected_returns_empty_dict(self, monkeypatch):
        monkeypatch.setattr(graph_service, "resolve_az_executable", lambda: "az")
        monkeypatch.setattr(
            graph_service.subprocess, "run", lambda *a, **k: self._fake_completed_process(stdout="")
        )
        assert graph_service.run_az(["ad", "app", "show"], expect_json=True) == {}

    def test_non_zero_exit_code_raises_with_details(self, monkeypatch):
        monkeypatch.setattr(graph_service, "resolve_az_executable", lambda: "az")
        monkeypatch.setattr(
            graph_service.subprocess,
            "run",
            lambda *a, **k: self._fake_completed_process(returncode=1, stderr="boom"),
        )
        with pytest.raises(RuntimeError, match="boom"):
            graph_service.run_az(["login"])

    def test_invalid_json_output_raises(self, monkeypatch):
        monkeypatch.setattr(graph_service, "resolve_az_executable", lambda: "az")
        monkeypatch.setattr(
            graph_service.subprocess, "run", lambda *a, **k: self._fake_completed_process(stdout="not-json")
        )
        with pytest.raises(RuntimeError, match="Invalid JSON output"):
            graph_service.run_az(["ad", "app", "show"], expect_json=True)


class TestGetApplicationByIdWithRetry:
    def test_returns_immediately_on_first_success(self, monkeypatch):
        monkeypatch.setattr(graph_service, "get_application_by_id", lambda object_id: {"id": object_id})
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        result = graph_service.get_application_by_id_with_retry("obj-1", max_attempts=3, delay_seconds=0)
        assert result == {"id": "obj-1"}

    def test_retries_on_resource_not_found_then_succeeds(self, monkeypatch):
        attempts = {"count": 0}

        def fake_get(object_id):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("Request_ResourceNotFound")
            return {"id": object_id}

        monkeypatch.setattr(graph_service, "get_application_by_id", fake_get)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        result = graph_service.get_application_by_id_with_retry("obj-1", max_attempts=5, delay_seconds=0)
        assert result == {"id": "obj-1"}
        assert attempts["count"] == 3

    def test_raises_after_exhausting_attempts(self, monkeypatch):
        def fake_get(object_id):
            raise RuntimeError("Request_ResourceNotFound")

        monkeypatch.setattr(graph_service, "get_application_by_id", fake_get)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        with pytest.raises(RuntimeError, match="tras reintentos"):
            graph_service.get_application_by_id_with_retry("obj-1", max_attempts=2, delay_seconds=0)

    def test_reraises_immediately_on_unrelated_error(self, monkeypatch):
        def fake_get(object_id):
            raise RuntimeError("Authorization_RequestDenied")

        monkeypatch.setattr(graph_service, "get_application_by_id", fake_get)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: (_ for _ in ()).throw(AssertionError("should not sleep")))

        with pytest.raises(RuntimeError, match="Authorization_RequestDenied"):
            graph_service.get_application_by_id_with_retry("obj-1", max_attempts=5, delay_seconds=0)


class TestUpsertOauth2PermissionGrantWithRetry:
    def test_creates_new_grant_when_none_exists(self, monkeypatch):
        created = {}

        monkeypatch.setattr(graph_service, "graph_get", lambda url: {"value": []})

        def fake_post(url, body):
            created["url"] = url
            created["body"] = body
            return {}

        monkeypatch.setattr(graph_service, "graph_post", fake_post)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        status = graph_service.upsert_oauth2_permission_grant_with_retry(
            client_id="sp-1", resource_id="sp-2", scopes=["openid", "offline_access"]
        )

        assert status == "created"
        assert created["body"]["clientId"] == "sp-1"
        assert created["body"]["resourceId"] == "sp-2"
        assert created["body"]["scope"] == "offline_access openid"

    def test_updates_existing_grant_by_merging_scopes(self, monkeypatch):
        monkeypatch.setattr(
            graph_service,
            "graph_get",
            lambda url: {"value": [{"id": "grant-1", "scope": "openid"}]},
        )

        patched = {}

        def fake_patch(url, body):
            patched["url"] = url
            patched["body"] = body

        monkeypatch.setattr(graph_service, "graph_patch", fake_patch)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        status = graph_service.upsert_oauth2_permission_grant_with_retry(
            client_id="sp-1", resource_id="sp-2", scopes=["offline_access"]
        )

        assert status == "updated"
        assert patched["url"] == "https://graph.microsoft.com/v1.0/oauth2PermissionGrants/grant-1"
        assert set(patched["body"]["scope"].split()) == {"openid", "offline_access"}


class TestUpsertAppRoleAssignmentsWithRetry:
    def test_creates_only_missing_assignments(self, monkeypatch):
        monkeypatch.setattr(
            graph_service,
            "list_app_role_assignments",
            lambda client_sp_id, resource_sp_id: [{"appRoleId": "role-1"}],
        )

        created_role_ids = []

        def fake_create(client_sp_id, resource_sp_id, app_role_id):
            created_role_ids.append(app_role_id)
            return {}

        monkeypatch.setattr(graph_service, "create_app_role_assignment", fake_create)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        created_count = graph_service.upsert_app_role_assignments_with_retry(
            client_sp_id="sp-1",
            resource_sp_id="sp-2",
            app_role_ids=["role-1", "role-2"],
        )

        assert created_count == 1
        assert created_role_ids == ["role-2"]

    def test_returns_zero_when_no_role_ids_given(self, monkeypatch):
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)
        created_count = graph_service.upsert_app_role_assignments_with_retry(
            client_sp_id="sp-1", resource_sp_id="sp-2", app_role_ids=[]
        )
        assert created_count == 0


class TestPatchServicePrincipal:
    def test_patches_the_expected_url_and_body(self, monkeypatch):
        calls = []

        def fake_graph_patch(url, body):
            calls.append((url, body))

        monkeypatch.setattr(graph_service, "graph_patch", fake_graph_patch)

        graph_service.patch_service_principal("sp-1", {"accountEnabled": False})

        assert calls == [
            ("https://graph.microsoft.com/v1.0/servicePrincipals/sp-1", {"accountEnabled": False})
        ]


class TestRunAzText:
    def _fake_completed_process(self, returncode=0, stdout="", stderr=""):
        return subprocess.CompletedProcess(args=["az"], returncode=returncode, stdout=stdout, stderr=stderr)

    def test_returns_stripped_stdout(self, monkeypatch):
        monkeypatch.setattr(graph_service, "resolve_az_executable", lambda: "az")
        monkeypatch.setattr(
            graph_service.subprocess, "run", lambda *a, **k: self._fake_completed_process(stdout="  token123  \n")
        )
        assert graph_service.run_az_text(["account", "get-access-token"]) == "token123"

    def test_non_zero_exit_code_raises_with_details(self, monkeypatch):
        monkeypatch.setattr(graph_service, "resolve_az_executable", lambda: "az")
        monkeypatch.setattr(
            graph_service.subprocess,
            "run",
            lambda *a, **k: self._fake_completed_process(returncode=1, stderr="auth failed"),
        )
        with pytest.raises(RuntimeError, match="auth failed"):
            graph_service.run_az_text(["account", "get-access-token"])


class TestGetGraphAccessToken:
    def test_returns_token_from_run_az_text(self, monkeypatch):
        monkeypatch.setattr(graph_service, "run_az_text", lambda args: "abc123")
        assert graph_service.get_graph_access_token() == "abc123"

    def test_raises_when_token_is_empty(self, monkeypatch):
        monkeypatch.setattr(graph_service, "run_az_text", lambda args: "")
        with pytest.raises(RuntimeError, match="No se pudo obtener access token"):
            graph_service.get_graph_access_token()


class TestGraphHttpClientRequest:
    def setup_method(self):
        self.client = GraphHttpClient()

    def _patch_token(self, monkeypatch):
        monkeypatch.setattr(graph_service, "get_graph_access_token", lambda: "fake-token")

    def test_successful_get_returns_parsed_json(self, monkeypatch):
        self._patch_token(monkeypatch)
        monkeypatch.setattr(
            graph_service, "urlopen", lambda request, timeout: FakeHTTPResponse(200, '{"id": "app-1"}')
        )
        result = self.client.request("GET", "/v1.0/applications/app-1")
        assert result == {"id": "app-1"}

    def test_204_no_content_returns_empty_dict(self, monkeypatch):
        self._patch_token(monkeypatch)
        monkeypatch.setattr(graph_service, "urlopen", lambda request, timeout: FakeHTTPResponse(204, ""))
        assert self.client.request("PATCH", "/v1.0/applications/app-1", {"x": 1}) == {}

    def test_empty_body_with_200_returns_empty_dict(self, monkeypatch):
        self._patch_token(monkeypatch)
        monkeypatch.setattr(graph_service, "urlopen", lambda request, timeout: FakeHTTPResponse(200, ""))
        assert self.client.request("POST", "/v1.0/applications") == {}

    def test_invalid_json_response_raises(self, monkeypatch):
        self._patch_token(monkeypatch)
        monkeypatch.setattr(graph_service, "urlopen", lambda request, timeout: FakeHTTPResponse(200, "not-json"))
        with pytest.raises(RuntimeError, match="Respuesta JSON invalida"):
            self.client.request("GET", "/v1.0/applications/app-1")

    def test_http_error_raises_runtime_error_with_details(self, monkeypatch):
        self._patch_token(monkeypatch)

        def fake_urlopen(request, timeout):
            raise HTTPError(
                url="https://graph.microsoft.com/v1.0/applications/app-1",
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=io.BytesIO(b'{"error": "not found"}'),
            )

        monkeypatch.setattr(graph_service, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="404"):
            self.client.request("GET", "/v1.0/applications/app-1")

    def test_url_error_raises_runtime_error(self, monkeypatch):
        self._patch_token(monkeypatch)

        def fake_urlopen(request, timeout):
            raise URLError("connection refused")

        monkeypatch.setattr(graph_service, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="network"):
            self.client.request("GET", "/v1.0/applications/app-1")


class TestGraphWrappers:
    def test_graph_get_delegates_to_client_with_get(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            graph_service.GRAPH_CLIENT,
            "request",
            lambda method, url, body=None: calls.append((method, url, body)) or {"ok": True},
        )
        assert graph_service.graph_get("/v1.0/x") == {"ok": True}
        assert calls == [("GET", "/v1.0/x", None)]

    def test_graph_post_delegates_to_client_with_post(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            graph_service.GRAPH_CLIENT,
            "request",
            lambda method, url, body=None: calls.append((method, url, body)) or {"created": True},
        )
        assert graph_service.graph_post("/v1.0/x", {"a": 1}) == {"created": True}
        assert calls == [("POST", "/v1.0/x", {"a": 1})]

    def test_graph_patch_delegates_to_client_with_patch(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            graph_service.GRAPH_CLIENT,
            "request",
            lambda method, url, body=None: calls.append((method, url, body)),
        )
        graph_service.graph_patch("/v1.0/x", {"a": 1})
        assert calls == [("PATCH", "/v1.0/x", {"a": 1})]


class TestGraphReadHelpers:
    def test_get_service_principal_by_app_id_builds_filter_url(self, monkeypatch):
        captured = {}

        def fake_graph_get(url):
            captured["url"] = url
            return {"value": [{"id": "sp-1"}]}

        monkeypatch.setattr(graph_service, "graph_get", fake_graph_get)
        result = graph_service.get_service_principal_by_app_id("app-id-1")
        assert result == {"id": "sp-1"}
        assert "servicePrincipals?$filter=appId eq 'app-id-1'" in captured["url"]

    def test_get_application_by_display_name_escapes_quotes(self, monkeypatch):
        captured = {}

        def fake_graph_get(url):
            captured["url"] = url
            return {"value": []}

        monkeypatch.setattr(graph_service, "graph_get", fake_graph_get)
        graph_service.get_application_by_display_name("O'Brien App")
        assert "O''Brien App" in captured["url"]

    def test_get_application_by_id_calls_direct_endpoint(self, monkeypatch):
        captured = {}

        def fake_graph_get(url):
            captured["url"] = url
            return {"id": "obj-1"}

        monkeypatch.setattr(graph_service, "graph_get", fake_graph_get)
        result = graph_service.get_application_by_id("obj-1")
        assert result == {"id": "obj-1"}
        assert captured["url"] == "https://graph.microsoft.com/v1.0/applications/obj-1"

    def test_get_application_by_app_id_escapes_and_filters(self, monkeypatch):
        captured = {}

        def fake_graph_get(url):
            captured["url"] = url
            return {"value": [{"appId": "x"}]}

        monkeypatch.setattr(graph_service, "graph_get", fake_graph_get)
        result = graph_service.get_application_by_app_id("app-id-1")
        assert result == {"appId": "x"}
        assert "appId eq 'app-id-1'" in captured["url"]


class TestGetApplicationWithFallbackByAppId:
    def test_falls_back_to_app_id_search_when_object_id_not_found(self, monkeypatch):
        def fake_get_by_id(object_id):
            raise RuntimeError("Request_ResourceNotFound")

        monkeypatch.setattr(graph_service, "get_application_by_id", fake_get_by_id)
        monkeypatch.setattr(graph_service, "get_application_by_app_id", lambda app_id: {"appId": app_id})
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        result = graph_service.get_application_with_fallback_by_app_id(
            "obj-1", "app-1", max_attempts=2, delay_seconds=0
        )
        assert result == {"appId": "app-1"}

    def test_raises_when_fallback_also_fails(self, monkeypatch):
        def fake_get_by_id(object_id):
            raise RuntimeError("Request_ResourceNotFound")

        monkeypatch.setattr(graph_service, "get_application_by_id", fake_get_by_id)
        monkeypatch.setattr(graph_service, "get_application_by_app_id", lambda app_id: None)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        with pytest.raises(RuntimeError, match="fallback por appId"):
            graph_service.get_application_with_fallback_by_app_id(
                "obj-1", "app-1", max_attempts=2, delay_seconds=0
            )

    def test_reraises_immediately_on_unrelated_error(self, monkeypatch):
        def fake_get_by_id(object_id):
            raise RuntimeError("Authorization_RequestDenied")

        monkeypatch.setattr(graph_service, "get_application_by_id", fake_get_by_id)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        with pytest.raises(RuntimeError, match="Authorization_RequestDenied"):
            graph_service.get_application_with_fallback_by_app_id(
                "obj-1", "app-1", max_attempts=3, delay_seconds=0
            )


class TestWriteHelpers:
    def test_create_application_posts_expected_body(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            graph_service,
            "graph_post",
            lambda url, body: captured.update(url=url, body=body) or {"id": "new-app"},
        )
        result = graph_service.create_application("my-app")
        assert result == {"id": "new-app"}
        assert captured["url"] == "https://graph.microsoft.com/v1.0/applications"
        assert captured["body"] == {"displayName": "my-app", "signInAudience": "AzureADMyOrg"}

    def test_patch_application_calls_graph_patch(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(graph_service, "graph_patch", lambda url, body: captured.update(url=url, body=body))
        graph_service.patch_application("obj-1", {"displayName": "renamed"})
        assert captured["url"] == "https://graph.microsoft.com/v1.0/applications/obj-1"
        assert captured["body"] == {"displayName": "renamed"}

    def test_add_application_password_without_expiry(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            graph_service,
            "graph_post",
            lambda url, body: captured.update(url=url, body=body) or {"secretText": "shh"},
        )
        result = graph_service.add_application_password("obj-1", display_name="my-secret")
        assert result == {"secretText": "shh"}
        assert captured["url"] == "https://graph.microsoft.com/v1.0/applications/obj-1/addPassword"
        assert captured["body"] == {"passwordCredential": {"displayName": "my-secret"}}

    def test_add_application_password_with_expiry(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            graph_service, "graph_post", lambda url, body: captured.update(url=url, body=body) or {}
        )
        graph_service.add_application_password(
            "obj-1", display_name="my-secret", end_datetime_utc="2027-01-01T00:00:00Z"
        )
        assert captured["body"]["passwordCredential"]["endDateTime"] == "2027-01-01T00:00:00Z"

    def test_create_service_principal_posts_app_id(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            graph_service,
            "graph_post",
            lambda url, body: captured.update(url=url, body=body) or {"id": "sp-1"},
        )
        result = graph_service.create_service_principal("app-1")
        assert result == {"id": "sp-1"}
        assert captured["url"] == "https://graph.microsoft.com/v1.0/servicePrincipals"
        assert captured["body"] == {"appId": "app-1"}


class TestListAppRoleAssignments:
    def test_filters_by_resource_id_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(
            graph_service,
            "graph_get",
            lambda url: {
                "value": [
                    {"resourceId": "RES-1", "appRoleId": "role-a"},
                    {"resourceId": "res-2", "appRoleId": "role-b"},
                ]
            },
        )
        result = graph_service.list_app_role_assignments("sp-client", "res-1")
        assert result == [{"resourceId": "RES-1", "appRoleId": "role-a"}]

    def test_returns_empty_list_when_value_is_not_a_list(self, monkeypatch):
        monkeypatch.setattr(graph_service, "graph_get", lambda url: {"value": None})
        assert graph_service.list_app_role_assignments("sp-client", "res-1") == []


class TestCreateAppRoleAssignment:
    def test_posts_expected_body(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            graph_service,
            "graph_post",
            lambda url, body: captured.update(url=url, body=body) or {"id": "assignment-1"},
        )
        result = graph_service.create_app_role_assignment("sp-client", "sp-resource", "role-1")
        assert result == {"id": "assignment-1"}
        assert captured["url"] == "https://graph.microsoft.com/v1.0/servicePrincipals/sp-client/appRoleAssignments"
        assert captured["body"] == {
            "principalId": "sp-client",
            "resourceId": "sp-resource",
            "appRoleId": "role-1",
        }


class TestUpsertOauth2PermissionGrantWithRetryExhaustion:
    def test_raises_after_exhausting_attempts_on_propagation_error(self, monkeypatch):
        def fake_get(url):
            raise RuntimeError("Directory_ObjectNotFound")

        monkeypatch.setattr(graph_service, "graph_get", fake_get)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        with pytest.raises(RuntimeError, match="tras reintentos"):
            graph_service.upsert_oauth2_permission_grant_with_retry(
                client_id="sp-1", resource_id="sp-2", scopes=["openid"], max_attempts=2, delay_seconds=0
            )

    def test_reraises_immediately_on_unrelated_error(self, monkeypatch):
        def fake_get(url):
            raise RuntimeError("Authorization_RequestDenied")

        monkeypatch.setattr(graph_service, "graph_get", fake_get)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        with pytest.raises(RuntimeError, match="Authorization_RequestDenied"):
            graph_service.upsert_oauth2_permission_grant_with_retry(
                client_id="sp-1", resource_id="sp-2", scopes=["openid"], max_attempts=3, delay_seconds=0
            )


class TestUpsertAppRoleAssignmentsWithRetryExhaustion:
    def test_raises_after_exhausting_attempts_on_propagation_error(self, monkeypatch):
        def fake_list(client_sp_id, resource_sp_id):
            raise RuntimeError("Request_ResourceNotFound")

        monkeypatch.setattr(graph_service, "list_app_role_assignments", fake_list)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        with pytest.raises(RuntimeError, match="tras reintentos"):
            graph_service.upsert_app_role_assignments_with_retry(
                client_sp_id="sp-1",
                resource_sp_id="sp-2",
                app_role_ids=["role-1"],
                max_attempts=2,
                delay_seconds=0,
            )

    def test_reraises_immediately_on_unrelated_error(self, monkeypatch):
        def fake_list(client_sp_id, resource_sp_id):
            raise RuntimeError("Authorization_RequestDenied")

        monkeypatch.setattr(graph_service, "list_app_role_assignments", fake_list)
        monkeypatch.setattr(graph_service.time, "sleep", lambda seconds: None)

        with pytest.raises(RuntimeError, match="Authorization_RequestDenied"):
            graph_service.upsert_app_role_assignments_with_retry(
                client_sp_id="sp-1",
                resource_sp_id="sp-2",
                app_role_ids=["role-1"],
                max_attempts=3,
                delay_seconds=0,
            )
