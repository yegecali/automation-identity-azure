#!/usr/bin/env python3
"""Configure Expose an API, requiredResourceAccess and admin consent for a B2C app."""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid
import re
from typing import Any
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from services.graph_service import (
    create_service_principal,
    get_application_by_id_with_retry,
    get_service_principal_by_app_id,
    patch_application,
    upsert_app_role_assignments_with_retry,
    upsert_oauth2_permission_grant_with_retry,
)
from models.dto import AppRoleDTO, ScopeDTO, UpdateInputDTO, UpdateRuntimeDTO
from utils.common import (
    dedupe_resource_access,
    unique_scopes,
)
from utils.runtime_config import get_env_credentials

VALID_ENVS = {"dev", "cer", "pro"}
VALID_TYPES = {"ac", "cc"}
DEFAULT_REDIRECT_URI = "https://jwt.ms"
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def validate_app_client_id(app_client_id: str) -> None:
    """Valida que el app client id exista y tenga formato UUID.

    Efecto en tenant:
    - Ninguno. Validacion local de entrada.

    Pasos funcionales:
    1. Verifica presencia.
    2. Intenta parsear UUID.
    3. Lanza error en formato invalido.
    """
    if not app_client_id:
        raise RuntimeError("No se encontro client id (appId) en la aplicacion a configurar.")

    try:
        uuid.UUID(app_client_id)
    except ValueError as exc:
        raise RuntimeError(f"El client id de la aplicacion no tiene formato valido: {app_client_id}") from exc


def build_default_application_id_uri(app_id_or_uri: str, tenant_domain: str | None = None) -> str:
    """Construye un Application ID URI compatible con politicas actuales de Entra.

    Efecto en tenant:
    - Ninguno. Solo transforma el valor localmente.

    Pasos funcionales:
    1. Extrae un appId GUID desde formatos comunes (`urn:spn`, `api://`, GUID plano).
    2. Si tiene `tenant_domain`, construye `https://<tenant_domain>/<appId>`.
    3. Si no tiene `tenant_domain`, usa fallback `api://<appId>`.
    4. Si no puede extraer GUID, devuelve el valor original.
    """
    raw = str(app_id_or_uri or "").strip()
    if not raw:
        raise RuntimeError("No se encontro valor para construir Application ID URI.")

    lowered = raw.lower()
    app_id_candidate = ""

    if lowered.startswith("urn:spn:"):
        tail = raw.split(":", 2)[-1].strip()
        if UUID_RE.fullmatch(tail):
            app_id_candidate = tail

    if not app_id_candidate and lowered.startswith("api://"):
        tail = raw[6:].strip()
        if UUID_RE.fullmatch(tail):
            app_id_candidate = tail

    if not app_id_candidate and UUID_RE.fullmatch(raw):
        app_id_candidate = raw

    if not app_id_candidate:
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"}:
            tail = parsed.path.strip("/").split("/")[-1].strip()
            if UUID_RE.fullmatch(tail):
                app_id_candidate = tail

    if not app_id_candidate:
        return raw

    normalized_domain = str(tenant_domain or "").strip().lower().lstrip(".")
    if normalized_domain:
        return f"https://{normalized_domain}/{app_id_candidate}"

    return f"api://{app_id_candidate}"


def validate_redirect_uri(redirect_uri: str) -> None:
    """Valida webRedirectUri obligatorio y con formato URL valido.

    Efecto en tenant:
    - Ninguno. Validacion previa al PATCH de aplicacion.

    Pasos funcionales:
    1. Valida que no sea vacio.
    2. Parsea URL.
    3. Exige esquema http/https y host.
    """
    if not redirect_uri:
        raise RuntimeError("webRedirectUri no puede ser vacio tras resolver valor por defecto.")

    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(
            "webRedirectUri no es valida. Debe incluir esquema y host, por ejemplo: https://midominio.com/callback"
        )


def assign_application_id_uri_and_redirect(
    app_object_id: str,
    app_id: str,
    redirect_uri: str,
    app_type: str = "ac",
) -> str:
    """Asigna Application ID URI y redirect URI en la app destino.

    Efecto en tenant:
    - Actualiza `identifierUris` y redirect URIs en App Registration.

    Pasos funcionales:
    1. Usa `<appId>` como valor de `identifierUris`.
    2. Ejecuta PATCH de aplicacion.
    3. Relee app y valida persistencia del identifier URI.
    """
    app_before_patch = get_application_by_id_with_retry(app_object_id)
    publisher_domain = str(app_before_patch.get("publisherDomain") or "").strip()
    default_identifier_uri = build_default_application_id_uri(app_id, publisher_domain)
    patch_body: dict[str, Any] = {"identifierUris": [default_identifier_uri]}
    if redirect_uri:
        is_cc = str(app_type or "").strip().lower() == "cc"
        platform_key = "spa" if is_cc else "web"
        patch_body[platform_key] = {"redirectUris": [redirect_uri]}
        if is_cc:
            patch_body["web"] = {
                "implicitGrantSettings": {
                    "enableAccessTokenIssuance": True,
                    "enableIdTokenIssuance": True,
                }
            }

    # Always assign in update flow (do not skip based on previous value).
    patch_application(app_object_id, patch_body)

    last_identifier_uris: list[str] = []
    for attempt in range(1, 7):
        app_after_identifier_uri = get_application_by_id_with_retry(app_object_id)
        identifier_uris = [str(item) for item in (app_after_identifier_uri.get("identifierUris") or [])]
        last_identifier_uris = identifier_uris

        if default_identifier_uri in identifier_uris:
            return default_identifier_uri

        logging.info(
            "      [APP] Application ID URI aun no visible (%s/6), reintentando...",
            attempt,
        )
        time.sleep(3)

    raise RuntimeError(
        "No se guardo correctamente el Application ID URI en la app. "
        f"Esperado: {default_identifier_uri}. Actuales: {', '.join(last_identifier_uris) or '(vacio)'}"
    )


def resolve_app_type(input_dto: UpdateInputDTO) -> str:
    """Resuelve tipo de flujo de update (`ac` o `cc`).

    Efecto en tenant:
    - Ninguno.

     Pasos funcionales:
     1. Usa `type` explicito si viene en input.
     2. Si no viene, infiere por sufijo de `applicationName`:
         `-ac-client-id` o `-cc-client-id`.
     3. Si no puede inferir, falla para evitar configurar el flujo equivocado.
    """
    app_type = str(input_dto.app_type or "").strip().lower()
    if app_type:
        if app_type not in VALID_TYPES:
            raise RuntimeError("El campo type en inputs-update.json debe ser 'cc' o 'ac'.")
        return app_type

    lowered_name = input_dto.application_name.strip().lower()
    if lowered_name.endswith("-cc-client-id"):
        logging.info("[UPDATE] Tipo inferido desde applicationName: cc")
        return "cc"
    if lowered_name.endswith("-ac-client-id"):
        logging.info("[UPDATE] Tipo inferido desde applicationName: ac")
        return "ac"

    # Backward-compatible fallback for legacy names containing -ac- / -cc-.
    if "-cc-" in lowered_name:
        logging.info("[UPDATE] Tipo inferido por patron legacy en applicationName: cc")
        return "cc"
    if "-ac-" in lowered_name:
        logging.info("[UPDATE] Tipo inferido por patron legacy en applicationName: ac")
        return "ac"

    raise RuntimeError(
        "No se pudo inferir el tipo de flujo desde applicationName. "
        "Debe terminar en '-ac-client-id' o '-cc-client-id', o enviar type='ac'/'cc'."
    )


def upsert_app_roles_for_cc(app_object_id: str, clean_scopes: list[str]) -> list[dict[str, Any]]:
    """Crea o reutiliza appRoles en manifest para flujo client credentials.

    Efecto en tenant:
    - Actualiza `appRoles` de la App Registration.

    Pasos funcionales:
    1. Lee appRoles actuales.
    2. Reutiliza roles existentes por `value`.
    3. Crea roles faltantes y aplica PATCH.
    4. Devuelve roles objetivo procesados.
    """
    app = get_application_by_id_with_retry(app_object_id)
    existing_app_roles = app.get("appRoles") or []

    app_role_by_value: dict[str, dict[str, Any]] = {}
    for role in existing_app_roles:
        value = role.get("value")
        if value:
            app_role_by_value[str(value)] = role

    merged_app_roles = [dict(role) for role in existing_app_roles]
    target_roles: list[dict[str, Any]] = []

    for role_value in clean_scopes:
        if role_value in app_role_by_value:
            logging.info("      App role ya existe, se reutiliza: %s", role_value)
            target_roles.append(app_role_by_value[role_value])
            continue

        new_role = AppRoleDTO.from_role_value(role_value).to_graph_dict()
        merged_app_roles.append(new_role)
        target_roles.append(new_role)
        logging.info("      App role agregado: %s", role_value)

    patch_application(app_object_id, {"appRoles": merged_app_roles})
    return target_roles


def configure_ac_scopes(
    app_object_id: str,
    app_id: str,
    clean_scopes: list[str],
    apply_admin_consent: bool = True,
) -> None:
    """Configura scopes delegados y consent para flujo authorization code.

    Efecto en tenant:
    - Actualiza `api.oauth2PermissionScopes` y `requiredResourceAccess` tipo Scope.

    Pasos funcionales:
    1. Hace merge de scopes existentes y nuevos.
    2. Actualiza bloque `api` en la app.
    3. Actualiza permisos configurados (`requiredResourceAccess`).
    4. Verifica propagacion de scopes configurados.
    5. Aplica admin consent (grant) para que no queden en estado `Not granted for tenant`.
    """
    logging.info("[4/8] Agregando scopes en Expose an API...")
    app = get_application_by_id_with_retry(app_object_id)

    api_data = app.get("api") or {}
    existing_scopes = api_data.get("oauth2PermissionScopes") or []

    scope_by_value: dict[str, dict[str, Any]] = {}
    for scope in existing_scopes:
        value = scope.get("value")
        if value:
            scope_by_value[str(value)] = scope

    all_scopes_for_api = [dict(scope) for scope in existing_scopes]
    target_scope_objects: list[dict[str, Any]] = []

    for scope_name in clean_scopes:
        if scope_name in scope_by_value:
            logging.info("      Scope ya existe, se reutiliza: %s", scope_name)
            target_scope_objects.append(scope_by_value[scope_name])
            continue

        new_scope = ScopeDTO.from_scope_name(scope_name).to_graph_dict()
        all_scopes_for_api.append(new_scope)
        target_scope_objects.append(new_scope)
        logging.info("      Scope agregado: %s", scope_name)

    api_body: dict[str, Any] = {"oauth2PermissionScopes": all_scopes_for_api}
    if api_data.get("preAuthorizedApplications") is not None:
        api_body["preAuthorizedApplications"] = api_data.get("preAuthorizedApplications")
    if api_data.get("knownClientApplications") is not None:
        api_body["knownClientApplications"] = api_data.get("knownClientApplications")
    if api_data.get("requestedAccessTokenVersion") is not None:
        api_body["requestedAccessTokenVersion"] = api_data.get("requestedAccessTokenVersion")

    patch_application(app_object_id, {"api": api_body})

    logging.info("[5/8] Configurando API permissions (My organization uses)...")
    app = get_application_by_id_with_retry(app_object_id)

    resource_access_for_target_api = [{"id": item.get("id"), "type": "Scope"} for item in target_scope_objects]
    existing_rra = app.get("requiredResourceAccess") or []
    same_api_entry = next((entry for entry in existing_rra if entry.get("resourceAppId") == app_id), None)

    merged_resource_access = []
    if same_api_entry and isinstance(same_api_entry.get("resourceAccess"), list):
        merged_resource_access.extend(same_api_entry.get("resourceAccess") or [])
    merged_resource_access.extend(resource_access_for_target_api)
    merged_resource_access = dedupe_resource_access(merged_resource_access)

    if not merged_resource_access:
        raise RuntimeError("No se pudo construir requiredResourceAccess para la API destino porque resourceAccess quedo vacio.")

    new_required_resource_access = []
    for api_entry in existing_rra:
        resource_app_id = api_entry.get("resourceAppId")
        if not resource_app_id or resource_app_id == app_id:
            continue

        safe_resource_access = dedupe_resource_access(api_entry.get("resourceAccess") or [])
        if safe_resource_access:
            new_required_resource_access.append(
                {"resourceAppId": resource_app_id, "resourceAccess": safe_resource_access}
            )

    new_required_resource_access.append(
        {"resourceAppId": app_id, "resourceAccess": merged_resource_access}
    )

    logging.info("      requiredResourceAccess entries a enviar: %s", len(new_required_resource_access))
    patch_application(app_object_id, {"requiredResourceAccess": new_required_resource_access})

    expected_scope_ids = [
        str(item.get("id")) for item in merged_resource_access if item.get("type") == "Scope" and item.get("id")
    ]
    configured_scope_ids, missing_configured_scope_ids = wait_for_configured_permissions(
        app_object_id=app_object_id,
        app_id=app_id,
        expected_scope_ids=expected_scope_ids,
    )

    if missing_configured_scope_ids:
        raise RuntimeError(
            "No quedaron todos los scopes en Configured permissions. "
            f"Faltan IDs: {', '.join(missing_configured_scope_ids)}"
        )
    logging.info(
        "      API permissions configurados en la app (Configured permissions): %s scope(s).",
        len(configured_scope_ids),
    )

    if not apply_admin_consent:
        logging.info("[6/8] Se omite admin consent de scopes (flujo no AC).")
        return

    logging.info("[6/8] Aplicando admin consent para scopes AC...")
    app_sp = get_service_principal_by_app_id(app_id)
    if not app_sp:
        app_sp = create_service_principal(app_id)

    app_sp_id = str(app_sp.get("id") or "").strip()
    if not app_sp_id:
        raise RuntimeError("No se pudo resolver service principal id para aplicar grant de scopes AC.")

    grant_status = upsert_oauth2_permission_grant_with_retry(
        client_id=app_sp_id,
        resource_id=app_sp_id,
        scopes=clean_scopes,
    )
    logging.info("      Grant AC aplicado sobre Configured permissions. Estado: %s", grant_status)


def configure_cc_app_roles(
    app_object_id: str,
    app_id: str,
    clean_scopes: list[str],
    sp_id: str,
) -> None:
    """Configura app roles y asignaciones para flujo client credentials.

    Efecto en tenant:
    - Actualiza `appRoles`, `requiredResourceAccess` tipo Role y `appRoleAssignments`.

    Pasos funcionales:
    1. Crea/reutiliza appRoles de la API.
    2. Construye `requiredResourceAccess` con tipo Role.
    3. Aplica PATCH de permisos.
    4. Crea app role assignments faltantes.
    """
    logging.info("[4/8] Agregando app roles (client credentials) en Manifest...")
    target_roles = upsert_app_roles_for_cc(app_object_id, clean_scopes)

    role_resource_access = [{"id": item.get("id"), "type": "Role"} for item in target_roles if item.get("id")]
    if not role_resource_access:
        raise RuntimeError("No se pudo construir requiredResourceAccess tipo Role para la API destino.")

    app = get_application_by_id_with_retry(app_object_id)
    existing_rra = app.get("requiredResourceAccess") or []
    same_api_entry = next((entry for entry in existing_rra if entry.get("resourceAppId") == app_id), None)

    merged_resource_access = []
    if same_api_entry and isinstance(same_api_entry.get("resourceAccess"), list):
        merged_resource_access.extend(same_api_entry.get("resourceAccess") or [])
    merged_resource_access.extend(role_resource_access)
    merged_resource_access = dedupe_resource_access(merged_resource_access)

    new_required_resource_access = []
    for api_entry in existing_rra:
        resource_app_id = api_entry.get("resourceAppId")
        if not resource_app_id or resource_app_id == app_id:
            continue

        safe_resource_access = dedupe_resource_access(api_entry.get("resourceAccess") or [])
        if safe_resource_access:
            new_required_resource_access.append(
                {"resourceAppId": resource_app_id, "resourceAccess": safe_resource_access}
            )

    new_required_resource_access.append(
        {"resourceAppId": app_id, "resourceAccess": merged_resource_access}
    )

    logging.info("[5/8] Configurando API permissions tipo Role (CC)...")
    patch_application(app_object_id, {"requiredResourceAccess": new_required_resource_access})

    role_ids = [str(item.get("id")) for item in target_roles if item.get("id")]
    created_count = upsert_app_role_assignments_with_retry(
        client_sp_id=sp_id,
        resource_sp_id=sp_id,
        app_role_ids=role_ids,
    )
    logging.info("      App role assignments creados: %s", created_count)


def resolve_runtime_values(input_dto: UpdateInputDTO) -> UpdateRuntimeDTO:
    """Resuelve y valida valores de runtime para operacion update.

    Efecto en tenant:
    - Ninguno. Solo validacion/normalizacion de input.

    Pasos funcionales:
    1. Valida ambiente y carga credenciales.
    2. Valida scopes y nombre de aplicacion.
    3. Resuelve tipo de flujo (`ac`/`cc`).
    4. Valida redirect URI.
    """
    env = input_dto.env
    if env not in VALID_ENVS:
        raise RuntimeError("El campo env en inputs-update.json debe ser uno de: dev, cer, pro.")

    env_config = get_env_credentials(env, input_dto.tennant)

    clean_scopes = unique_scopes(input_dto.scopes)
    if not clean_scopes:
        raise RuntimeError("Debes enviar al menos un scope en inputs-update.json -> scopes.")

    app_type = resolve_app_type(input_dto)

    redirect_uri = str(input_dto.web_redirect_uri or "").strip()
    if not redirect_uri:
        redirect_uri = DEFAULT_REDIRECT_URI
    validate_redirect_uri(redirect_uri)

    return UpdateRuntimeDTO(
        env=env,
        app_type=app_type,
        credentials=env_config,
        application_name=input_dto.application_name,
        redirect_uri=redirect_uri,
        scopes=clean_scopes,
        use_interactive_az_login=input_dto.use_interactive_az_login,
    )


def wait_for_configured_permissions(
    app_object_id: str,
    app_id: str,
    expected_scope_ids: list[str],
    max_attempts: int = 8,
    delay_seconds: int = 3,
) -> tuple[list[str], list[str]]:
    """Espera propagacion de permisos Scope en configured permissions.

    Efecto en tenant:
    - Solo lectura para verificacion de estado.

    Pasos funcionales:
    1. Relee app en reintentos.
    2. Extrae scopes configurados para resourceAppId objetivo.
    3. Devuelve IDs configurados y faltantes.
    """
    last_missing_api: list[str] = []

    for attempt in range(1, max_attempts + 1):
        app_after_rra = get_application_by_id_with_retry(app_object_id)
        configured_entry = next(
            (entry for entry in (app_after_rra.get("requiredResourceAccess") or []) if entry.get("resourceAppId") == app_id),
            None,
        )

        configured_scope_ids = [
            str(item.get("id"))
            for item in (configured_entry or {}).get("resourceAccess", [])
            if item.get("type") == "Scope" and item.get("id")
        ]

        missing_configured_scope_ids = [item for item in expected_scope_ids if item not in configured_scope_ids]

        if not missing_configured_scope_ids:
            return (configured_scope_ids, missing_configured_scope_ids)

        last_missing_api = missing_configured_scope_ids
        logging.info(
            "      [APP] Configured permissions aun en propagacion (%s/%s), reintentando...",
            attempt,
            max_attempts,
        )
        time.sleep(delay_seconds)

    return ([], last_missing_api)
