from __future__ import annotations

import json
import logging
import shlex
import shutil
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from utils.common import escape_odata

logging.basicConfig(level=logging.INFO)


def resolve_az_executable() -> str:
    """Resuelve el ejecutable de Azure CLI disponible en la maquina.

    Efecto en tenant:
    - Ninguno. Solo resuelve ruta local del binario `az`.

    Pasos funcionales:
    1. Busca candidatos `az`, `az.cmd`, `az.exe` en PATH.
    2. Devuelve la primera ruta encontrada.
    3. Lanza error si Azure CLI no esta instalado o no esta en PATH.
    """
    # On Windows, subprocess may fail resolving .cmd if called only as "az".
    for candidate in ("az", "az.cmd", "az.exe"):
        path = shutil.which(candidate)
        if path:
            return path

    raise RuntimeError(
        "No se encontro Azure CLI en PATH. Instala Azure CLI o agrega la carpeta que contiene az.cmd al PATH."
    )


def run_az(args: list[str], *, expect_json: bool = False) -> Any:
    """Ejecuta un comando de Azure CLI y opcionalmente parsea JSON.

    Efecto en tenant:
    - Indirecto y depende del comando recibido en `args`.
    - Puede leer o modificar recursos de Entra/Azure si `args` lo indican.

    Pasos funcionales:
    1. Construye el comando completo con el ejecutable `az` resuelto.
    2. Ejecuta subprocess y captura stdout/stderr.
    3. Si hay error, construye mensaje detallado con comando y salida.
    4. Si `expect_json=True`, parsea stdout como JSON.
    """
    cmd = [resolve_az_executable(), *args]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        details = stderr if stderr else stdout
        rendered_cmd = " ".join(shlex.quote(part) for part in cmd)
        raise RuntimeError(f"Command failed ({result.returncode}): {rendered_cmd}\\n{details}")

    if not expect_json:
        return None

    output = (result.stdout or "").strip()
    if not output:
        return {}

    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON output from Azure CLI: {exc}") from exc


def run_az_text(args: list[str]) -> str:
    """Ejecuta Azure CLI y devuelve salida como texto plano.

    Efecto en tenant:
    - Indirecto y depende de `args`.

    Pasos funcionales:
    1. Construye comando con `az`.
    2. Ejecuta subprocess.
    3. Lanza error detallado si el codigo de salida no es 0.
    4. Devuelve stdout en formato string.
    """
    cmd = [resolve_az_executable(), *args]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        details = stderr if stderr else stdout
        rendered_cmd = " ".join(shlex.quote(part) for part in cmd)
        raise RuntimeError(f"Command failed ({result.returncode}): {rendered_cmd}\\n{details}")

    return (result.stdout or "").strip()


def get_graph_access_token() -> str:
    """Obtiene access token para Microsoft Graph usando Azure CLI.

    Efecto en tenant:
    - No modifica recursos.
    - Consulta token de acceso para operar contra Graph con el contexto autenticado.

    Pasos funcionales:
    1. Ejecuta `az account get-access-token --resource-type ms-graph`.
    2. Extrae access token en formato TSV.
    3. Valida que el token exista.
    """
    token = run_az_text(
        [
            "account",
            "get-access-token",
            "--resource-type",
            "ms-graph",
            "--query",
            "accessToken",
            "--output",
            "tsv",
        ]
    )
    if not token:
        raise RuntimeError("No se pudo obtener access token para Microsoft Graph.")
    return token


class GraphHttpClient:
    """Cliente HTTP minimo para Microsoft Graph.

    Efecto en tenant:
    - Segun metodo HTTP invocado: GET lee estado, POST/PATCH modifican estado.

    Pasos funcionales:
    1. Obtiene token de Graph para cada request.
    2. Inyecta headers de autorizacion y content-type.
    3. Ejecuta request con timeout controlado.
    4. Normaliza respuesta y errores.
    """

    def __init__(self, timeout_seconds: int = 30) -> None:
        """Inicializa sesion HTTP reutilizable con timeout por defecto."""
        self.timeout_seconds = timeout_seconds

    def _normalize_graph_url(self, url: str) -> str:
        """Normaliza URL Graph y encodea query/path para evitar caracteres de control.

        Efecto en tenant:
        - Ninguno. Solo transforma la URL localmente antes del request.
        """
        normalized = url.strip()
        if normalized.startswith("/"):
            normalized = f"https://graph.microsoft.com{normalized}"

        parts = urlsplit(normalized)
        encoded_path = quote(unquote(parts.path), safe="/:@-._~!$&'()*+,;=")
        encoded_query = quote(parts.query, safe="=&$(),':@/?+-._~%")
        return urlunsplit((parts.scheme, parts.netloc, encoded_path, encoded_query, parts.fragment))

    def request(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Ejecuta una llamada autenticada a Microsoft Graph.

        Efecto en tenant:
        - GET: lectura.
        - POST/PATCH: creacion/actualizacion en objetos del tenant.

        Pasos funcionales:
        1. Obtiene access token.
        2. Arma headers y body JSON.
        3. Ejecuta request.
        4. Si hay error HTTP, lanza RuntimeError con detalles.
        5. Devuelve JSON parseado o dict vacio en respuestas sin cuerpo.
        """
        normalized_url = self._normalize_graph_url(url)
        token = get_graph_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(url=normalized_url, data=payload, headers=headers, method=method)

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = int(response.getcode() or 0)
                response_text = response.read().decode("utf-8")
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"Graph request failed ({exc.code}) {method} {normalized_url}\\n{details}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"Graph request failed (network) {method} {normalized_url}\\n{exc}"
            ) from exc

        if status_code >= 400:
            raise RuntimeError(
                f"Graph request failed ({status_code}) {method} {normalized_url}\\n{response_text.strip()}"
            )

        if status_code == 204 or not response_text:
            return {}

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Respuesta JSON invalida de Graph: {exc}") from exc


GRAPH_CLIENT = GraphHttpClient()


def graph_get(url: str) -> dict[str, Any]:
    """Wrapper GET para Microsoft Graph.

    Efecto en tenant:
    - Solo lectura de estado.

    Pasos funcionales:
    1. Delega en `GraphHttpClient.request` con metodo GET.
    """
    return GRAPH_CLIENT.request("GET", url)


def graph_post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    """Wrapper POST para Microsoft Graph.

    Efecto en tenant:
    - Crea recursos o asignaciones segun endpoint.

    Pasos funcionales:
    1. Delega en `GraphHttpClient.request` con metodo POST.
    """
    return GRAPH_CLIENT.request("POST", url, body)


def graph_patch(url: str, body: dict[str, Any]) -> None:
    """Wrapper PATCH para Microsoft Graph.

    Efecto en tenant:
    - Actualiza propiedades de recursos en el tenant.

    Pasos funcionales:
    1. Delega en `GraphHttpClient.request` con metodo PATCH.
    """
    GRAPH_CLIENT.request("PATCH", url, body)


def graph_delete(url: str) -> None:
    """Wrapper DELETE para Microsoft Graph.

    Efecto en tenant:
    - Elimina el recurso apuntado por `url`.

    Pasos funcionales:
    1. Delega en `GraphHttpClient.request` con metodo DELETE.
    """
    GRAPH_CLIENT.request("DELETE", url)


def get_first_value(response: dict[str, Any]) -> dict[str, Any] | None:
    """Extrae el primer elemento de una respuesta Graph basada en `value`.

    Efecto en tenant:
    - Ninguno. Solo transforma datos en memoria.

    Pasos funcionales:
    1. Lee `response["value"]`.
    2. Si es lista no vacia, devuelve el primer item.
    3. Si no, devuelve None.
    """
    items = response.get("value")
    if isinstance(items, list) and items:
        return items[0]
    return None


def get_service_principal_by_app_id(app_id: str) -> dict[str, Any] | None:
    """Busca Service Principal por `appId`.

    Efecto en tenant:
    - Solo lectura de objetos servicePrincipals.

    Pasos funcionales:
    1. Ejecuta GET con filtro `appId eq '<app_id>'`.
    2. Devuelve el primer resultado si existe.
    """
    return get_first_value(
        graph_get(f"https://graph.microsoft.com/v1.0/servicePrincipals?$filter=appId eq '{app_id}'")
    )


def get_application_by_display_name(display_name: str) -> dict[str, Any] | None:
    """Busca App Registration por displayName exacto.

    Efecto en tenant:
    - Solo lectura de objetos applications.

    Pasos funcionales:
    1. Escapa el nombre para OData.
    2. Ejecuta GET filtrando por displayName.
    3. Devuelve primer resultado.
    """
    escaped_name = escape_odata(display_name)
    return get_first_value(
        graph_get(f"https://graph.microsoft.com/v1.0/applications?$filter=displayName eq '{escaped_name}'")
    )


def get_application_by_id(app_object_id: str) -> dict[str, Any]:
    """Lee una App Registration por Object ID.

    Efecto en tenant:
    - Solo lectura de la aplicacion.

    Pasos funcionales:
    1. Ejecuta GET directo a `/applications/{id}`.
    """
    return graph_get(f"https://graph.microsoft.com/v1.0/applications/{app_object_id}")


def get_application_by_app_id(app_id: str) -> dict[str, Any] | None:
    """Busca App Registration por Application (client) ID.

    Efecto en tenant:
    - Solo lectura de aplicaciones.

    Pasos funcionales:
    1. Escapa appId para OData.
    2. Ejecuta filtro por `appId`.
    3. Devuelve primer resultado.
    """
    escaped_app_id = escape_odata(app_id)
    return get_first_value(
        graph_get(f"https://graph.microsoft.com/v1.0/applications?$filter=appId eq '{escaped_app_id}'")
    )


def get_application_by_id_with_retry(
    app_object_id: str,
    *,
    max_attempts: int = 6,
    delay_seconds: int = 3,
) -> dict[str, Any]:
    """Lee una aplicacion con reintentos por propagacion en Graph.

    Efecto en tenant:
    - Solo lectura.

    Pasos funcionales:
    1. Intenta GET por Object ID.
    2. Si recibe `Request_ResourceNotFound`, espera y reintenta.
    3. Si no aparece tras maximo de intentos, lanza error.
    """
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return get_application_by_id(app_object_id)
        except RuntimeError as exc:
            last_error = exc
            if "Request_ResourceNotFound" in str(exc):
                logging.info(
                    "      [APP] Aun no visible por Object ID (intento %s/%s), reintentando...",
                    attempt,
                    max_attempts,
                )
                time.sleep(delay_seconds)
                continue
            raise

    if last_error:
        raise RuntimeError(f"No se pudo leer la aplicacion por Object ID tras reintentos. Error: {last_error}")
    raise RuntimeError("No se pudo leer la aplicacion por Object ID tras reintentos.")


def get_application_with_fallback_by_app_id(
    app_object_id: str,
    app_id: str,
    *,
    max_attempts: int = 6,
    delay_seconds: int = 3,
) -> dict[str, Any]:
    """Obtiene una aplicacion con fallback de Object ID a appId.

    Efecto en tenant:
    - Solo lectura.

    Pasos funcionales:
    1. Reintenta lectura por Object ID para cubrir propagacion.
    2. Si no aparece, intenta busqueda por appId.
    3. Devuelve la app encontrada o lanza error.
    """
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return get_application_by_id(app_object_id)
        except RuntimeError as exc:
            last_error = exc
            if "Request_ResourceNotFound" in str(exc):
                logging.info(
                    "      [APP] Aun no visible por Object ID (intento %s/%s), reintentando...",
                    attempt,
                    max_attempts,
                )
                time.sleep(delay_seconds)
                continue
            raise

    logging.info("      [APP] Fallback: buscando por appId...")
    app = get_application_by_app_id(app_id)
    if app:
        return app

    if last_error:
        raise RuntimeError(
            "No se pudo validar la App Registration recien creada tras reintentos y fallback por appId. "
            f"Error original: {last_error}"
        )

    raise RuntimeError("No se pudo validar la App Registration recien creada tras reintentos y fallback por appId.")


def create_application(display_name: str, *, sign_in_audience: str = "AzureADMyOrg") -> dict[str, Any]:
    """Crea una App Registration en el tenant.

    Efecto en tenant:
    - Crea un nuevo objeto `application`.

    Pasos funcionales:
    1. Ejecuta POST a `/applications` con `displayName` y `signInAudience`.
    2. Devuelve el objeto creado.
    """
    return graph_post(
        "https://graph.microsoft.com/v1.0/applications",
        {
            "displayName": display_name,
            "signInAudience": sign_in_audience,
        },
    )


def patch_application(app_object_id: str, body: dict[str, Any]) -> None:
    """Actualiza propiedades de una App Registration existente.

    Efecto en tenant:
    - Modifica el objeto `application` (manifest parcial).

    Pasos funcionales:
    1. Ejecuta PATCH a `/applications/{id}` con el body recibido.
    """
    graph_patch(f"https://graph.microsoft.com/v1.0/applications/{app_object_id}", body)


def add_application_password(
    app_object_id: str,
    *,
    display_name: str,
    end_datetime_utc: str | None = None,
) -> dict[str, Any]:
    """Crea una password credential (client secret) en una App Registration.

    Efecto en tenant:
    - Agrega un `passwordCredential` a la aplicacion indicada.

    Pasos funcionales:
    1. Construye payload con display name del secreto.
    2. Opcionalmente define fecha de expiracion UTC.
    3. Invoca endpoint Graph addPassword.
    4. Retorna el resultado con `secretText` (solo visible en creacion).
    """
    password_credential: dict[str, Any] = {"displayName": display_name}
    if end_datetime_utc:
        password_credential["endDateTime"] = end_datetime_utc

    return graph_post(
        f"https://graph.microsoft.com/v1.0/applications/{app_object_id}/addPassword",
        {"passwordCredential": password_credential},
    )


def patch_service_principal(sp_id: str, body: dict[str, Any]) -> None:
    """Actualiza propiedades de un Service Principal existente.

    Efecto en tenant:
    - Modifica el objeto `servicePrincipal` (ej. deshabilitarlo con accountEnabled=false).

    Pasos funcionales:
    1. Ejecuta PATCH a `/servicePrincipals/{id}` con el body recibido.
    """
    graph_patch(f"https://graph.microsoft.com/v1.0/servicePrincipals/{sp_id}", body)


def create_service_principal(app_id: str) -> dict[str, Any]:
    """Crea Service Principal para una aplicacion en el tenant.

    Efecto en tenant:
    - Crea un objeto `servicePrincipal` asociado al `appId`.

    Pasos funcionales:
    1. Ejecuta POST a `/servicePrincipals` con el `appId`.
    2. Devuelve el SP creado.
    """
    return graph_post("https://graph.microsoft.com/v1.0/servicePrincipals", {"appId": app_id})


def upsert_oauth2_permission_grant_with_retry(
    client_id: str,
    resource_id: str,
    scopes: list[str],
    *,
    max_attempts: int = 8,
    delay_seconds: int = 3,
) -> str:
    """Crea o reemplaza OAuth2PermissionGrant para scopes delegados.

    Efecto en tenant:
    - Crea/reemplaza consent de tipo delegado (`oauth2PermissionGrants`).

    Pasos funcionales:
    1. Busca grant existente para client/resource (`AllPrincipals`).
    2. Si existe, reemplaza su `scope` por exactamente `scopes` (el caller ya
       resolvio la lista definitiva; no se conserva lo que ya no venga).
    3. Si no existe, crea grant nuevo con los scopes esperados.
    4. Reintenta ante errores de propagacion de directorio.
    """
    target_scope_string = " ".join(sorted(set([scope for scope in scopes if scope.strip()])))
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            existing_grant = get_first_value(
                graph_get(
                    "https://graph.microsoft.com/v1.0/oauth2PermissionGrants"
                    f"?$filter=clientId eq '{client_id}' and resourceId eq '{resource_id}' and consentType eq 'AllPrincipals'"
                )
            )

            if existing_grant:
                graph_patch(
                    f"https://graph.microsoft.com/v1.0/oauth2PermissionGrants/{existing_grant.get('id')}",
                    {"scope": target_scope_string},
                )
                return "updated"

            graph_post(
                "https://graph.microsoft.com/v1.0/oauth2PermissionGrants",
                {
                    "clientId": client_id,
                    "consentType": "AllPrincipals",
                    "resourceId": resource_id,
                    "scope": target_scope_string,
                },
            )
            return "created"
        except RuntimeError as exc:
            last_error = exc
            error_text = str(exc)
            if "Directory_ObjectNotFound" in error_text or "Request_ResourceNotFound" in error_text:
                logging.info(
                    "      [APP] Grant aun en propagacion (%s/%s), reintentando...",
                    attempt,
                    max_attempts,
                )
                time.sleep(delay_seconds)
                continue
            raise

    raise RuntimeError(f"No se pudo crear/actualizar oauth2PermissionGrant tras reintentos. Error: {last_error}")


def list_app_role_assignments(client_sp_id: str, resource_sp_id: str) -> list[dict[str, Any]]:
    """Lista appRoleAssignments entre un SP cliente y un recurso.

    Efecto en tenant:
    - Solo lectura de asignaciones de roles de aplicacion.

    Pasos funcionales:
    1. Consulta `/servicePrincipals/{client}/appRoleAssignments` filtrando por `resourceId`.
    2. Devuelve lista normalizada.
    """
    response = graph_get(
        f"https://graph.microsoft.com/v1.0/servicePrincipals/{client_sp_id}/appRoleAssignments"
    )
    items = response.get("value")
    if not isinstance(items, list):
        return []

    expected_resource_id = str(resource_sp_id).strip().lower()
    return [
        item
        for item in items
        if str(item.get("resourceId", "")).strip().lower() == expected_resource_id
    ]


def create_app_role_assignment(client_sp_id: str, resource_sp_id: str, app_role_id: str) -> dict[str, Any]:
    """Crea una asignacion de app role para client credentials.

    Efecto en tenant:
    - Crea `appRoleAssignment` (equivalente funcional a consent de roles de aplicacion).

    Pasos funcionales:
    1. Ejecuta POST sobre appRoleAssignments del SP cliente.
    2. Envia `principalId`, `resourceId` y `appRoleId`.
    3. Devuelve la asignacion creada.
    """
    return graph_post(
        f"https://graph.microsoft.com/v1.0/servicePrincipals/{client_sp_id}/appRoleAssignments",
        {
            "principalId": client_sp_id,
            "resourceId": resource_sp_id,
            "appRoleId": app_role_id,
        },
    )


def upsert_app_role_assignments_with_retry(
    client_sp_id: str,
    resource_sp_id: str,
    app_role_ids: list[str],
    *,
    max_attempts: int = 8,
    delay_seconds: int = 3,
) -> int:
    """Crea las appRoleAssignments faltantes con reintentos por propagacion.

    Efecto en tenant:
    - Crea asignaciones de roles de aplicacion para el SP cliente.

    Pasos funcionales:
    1. Calcula conjunto esperado de `appRoleId`.
    2. Lee asignaciones actuales para evitar duplicados.
    3. Crea solo las faltantes.
    4. Reintenta ante errores de propagacion de directorio.
    5. Devuelve cantidad de asignaciones creadas.
    """
    expected_role_ids = sorted(set([item for item in app_role_ids if item]))
    if not expected_role_ids:
        return 0

    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            existing_assignments = list_app_role_assignments(client_sp_id, resource_sp_id)
            existing_role_ids = set(
                [str(item.get("appRoleId")) for item in existing_assignments if item.get("appRoleId")]
            )
            missing_role_ids = [item for item in expected_role_ids if item not in existing_role_ids]

            for role_id in missing_role_ids:
                create_app_role_assignment(client_sp_id, resource_sp_id, role_id)

            return len(missing_role_ids)
        except RuntimeError as exc:
            last_error = exc
            error_text = str(exc)
            if "Directory_ObjectNotFound" in error_text or "Request_ResourceNotFound" in error_text:
                logging.info(
                    "      [APP] App role assignment aun en propagacion (%s/%s), reintentando...",
                    attempt,
                    max_attempts,
                )
                time.sleep(delay_seconds)
                continue
            raise

    raise RuntimeError(f"No se pudo crear appRoleAssignments tras reintentos. Error: {last_error}")


def delete_app_role_assignment(client_sp_id: str, assignment_id: str) -> None:
    """Elimina una asignacion puntual de app role.

    Efecto en tenant:
    - Revoca una `appRoleAssignment` (equivalente a retirar el consent de un
      permiso de aplicacion).

    Pasos funcionales:
    1. Ejecuta DELETE sobre appRoleAssignments/{assignment_id} del SP cliente.
    """
    graph_delete(f"https://graph.microsoft.com/v1.0/servicePrincipals/{client_sp_id}/appRoleAssignments/{assignment_id}")


def remove_app_role_assignments(client_sp_id: str, resource_sp_id: str, app_role_ids: list[str]) -> int:
    """Elimina las appRoleAssignments de los roles indicados si existen.

    Efecto en tenant:
    - Revoca asignaciones de roles de aplicacion para el SP cliente.

    Pasos funcionales:
    1. Lee asignaciones actuales entre client/resource.
    2. Filtra las que correspondan a `app_role_ids`.
    3. Elimina cada una encontrada.
    4. Devuelve cantidad de asignaciones eliminadas.
    """
    target_role_ids = set([item for item in app_role_ids if item])
    if not target_role_ids:
        return 0

    existing_assignments = list_app_role_assignments(client_sp_id, resource_sp_id)
    to_delete = [
        item for item in existing_assignments if str(item.get("appRoleId")) in target_role_ids and item.get("id")
    ]

    for assignment in to_delete:
        delete_app_role_assignment(client_sp_id, str(assignment.get("id")))

    return len(to_delete)
