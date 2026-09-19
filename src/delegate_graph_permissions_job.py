#!/usr/bin/env python3
"""Delegate Graph permissions for app SP based on app type (CC/AC)."""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from constants import AC_GRAPH_DELEGATED_PERMISSIONS, CC_GRAPH_DELEGATED_PERMISSIONS, MICROSOFT_GRAPH_APP_ID
from services.graph_service import (
    get_application_by_app_id,
    get_service_principal_by_app_id,
    patch_application,
    run_az,
    upsert_oauth2_permission_grant_with_retry,
)
from utils.common import dedupe_resource_access, get_obfuscated_secret, load_json_file
from utils.runtime_config import get_env_credentials


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def resolve_permissions(app_type: str) -> list[str]:
    clean_type = str(app_type or "").strip().lower()
    if clean_type == "cc":
        return CC_GRAPH_DELEGATED_PERMISSIONS
    if clean_type == "ac":
        return AC_GRAPH_DELEGATED_PERMISSIONS
    raise RuntimeError("type debe ser 'cc' o 'ac' para delegar permisos de Graph.")


def ensure_graph_required_resource_access(app_id: str, graph_app_id: str, permissions: list[str]) -> int:
    """Declara delegated permissions de Graph en requiredResourceAccess.

    Efecto en tenant:
    - Actualiza `requiredResourceAccess` en la App Registration cliente.

    Pasos funcionales:
    1. Resuelve app por appId y service principal de Graph.
    2. Mapea valores de scope (openid/offline_access/User.Read.All) a IDs de Graph.
    3. Hace merge en entry de Graph (`resourceAppId` de Microsoft Graph).
    4. Ejecuta PATCH solo con permisos deduplicados.
    """
    app = get_application_by_app_id(app_id)
    if not app:
        raise RuntimeError("No se encontro la App Registration por appId para actualizar requiredResourceAccess.")

    app_object_id = str(app.get("id") or "").strip()
    if not app_object_id:
        raise RuntimeError("La App Registration no tiene object id valido para actualizar requiredResourceAccess.")

    graph_sp = get_service_principal_by_app_id(graph_app_id)
    if not graph_sp:
        raise RuntimeError("No se encontro service principal de Microsoft Graph para resolver IDs de scopes.")

    graph_scope_id_by_value: dict[str, str] = {}
    for scope in graph_sp.get("oauth2PermissionScopes") or []:
        value = str(scope.get("value") or "").strip()
        scope_id = str(scope.get("id") or "").strip()
        if value and scope_id:
            graph_scope_id_by_value[value] = scope_id

    missing = [scope for scope in permissions if scope not in graph_scope_id_by_value]
    if missing:
        raise RuntimeError(
            "No se pudieron resolver IDs de permisos delegados de Graph para: "
            + ", ".join(missing)
        )

    graph_resource_access = [
        {"id": graph_scope_id_by_value[scope], "type": "Scope"}
        for scope in permissions
    ]

    existing_rra = app.get("requiredResourceAccess") or []
    same_graph_entry = next((entry for entry in existing_rra if entry.get("resourceAppId") == graph_app_id), None)

    merged_resource_access = []
    if same_graph_entry and isinstance(same_graph_entry.get("resourceAccess"), list):
        merged_resource_access.extend(same_graph_entry.get("resourceAccess") or [])
    merged_resource_access.extend(graph_resource_access)
    merged_resource_access = dedupe_resource_access(merged_resource_access)

    new_required_resource_access = []
    for api_entry in existing_rra:
        resource_app_id = api_entry.get("resourceAppId")
        if not resource_app_id or resource_app_id == graph_app_id:
            continue

        safe_resource_access = dedupe_resource_access(api_entry.get("resourceAccess") or [])
        if safe_resource_access:
            new_required_resource_access.append(
                {"resourceAppId": resource_app_id, "resourceAccess": safe_resource_access}
            )

    new_required_resource_access.append(
        {"resourceAppId": graph_app_id, "resourceAccess": merged_resource_access}
    )

    patch_application(app_object_id, {"requiredResourceAccess": new_required_resource_access})
    return len(merged_resource_access)


def main() -> int:
    parser = argparse.ArgumentParser(description="Delegate Graph permissions job")
    parser.add_argument("--input", default="input.json", help="Path to input JSON")
    parser.add_argument("--app-id", required=True, help="Application (client) ID")
    parser.add_argument("--app-sp-id", default="", help="Application service principal ID")
    args = parser.parse_args()

    input_data = load_json_file(args.input)
    env = str(input_data.get("env", "")).strip().lower()
    tennant = str(input_data.get("tennant") or input_data.get("tenant") or "").strip().lower()
    app_type = str(input_data.get("type", "")).strip().lower()

    permissions = resolve_permissions(app_type)
    creds = get_env_credentials(env=env, tennant=tennant)

    logging.info("[PERM] TenantId: %s", creds.tenant_id)
    logging.info("[PERM] ClientId: %s", creds.client_id)
    logging.info("[PERM] ClientSecret (obfuscado): %s", get_obfuscated_secret(creds.client_secret))

    run_az(
        [
            "login",
            "--service-principal",
            "--username",
            creds.client_id,
            "--password",
            creds.client_secret,
            "--tenant",
            creds.tenant_id,
            "--allow-no-subscriptions",
            "--output",
            "none",
        ]
    )

    app_sp_id = str(args.app_sp_id or "").strip()
    if not app_sp_id:
        app_sp = get_service_principal_by_app_id(args.app_id)
        if not app_sp:
            raise RuntimeError("No se encontro service principal de la aplicacion para delegar permisos.")
        app_sp_id = str(app_sp.get("id") or "").strip()

    graph_sp = get_service_principal_by_app_id(MICROSOFT_GRAPH_APP_ID)
    if not graph_sp:
        raise RuntimeError("No se encontro service principal de Microsoft Graph.")

    graph_sp_id = str(graph_sp.get("id") or "").strip()
    if not graph_sp_id:
        raise RuntimeError("Service principal de Graph no tiene id.")

    configured_count = ensure_graph_required_resource_access(
        app_id=args.app_id,
        graph_app_id=MICROSOFT_GRAPH_APP_ID,
        permissions=permissions,
    )
    logging.info("[PERM] requiredResourceAccess (Graph) actualizado con %s scope(s).", configured_count)

    grant_status = upsert_oauth2_permission_grant_with_retry(
        client_id=app_sp_id,
        resource_id=graph_sp_id,
        scopes=permissions,
    )

    scope_string = " ".join(sorted(set(permissions)))
    logging.info("[PERM] grant_status=%s scopes=%s", grant_status, scope_string)

    set_output("grant_status", grant_status)
    set_output("granted_scopes", scope_string)
    set_output("app_sp_id", app_sp_id)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
