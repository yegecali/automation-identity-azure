#!/usr/bin/env python3
"""Shared SAS-based Azure Table Storage connection helpers.

Used by both the lightweight audit log (persist_table_storage.py) and the
operation history/rollback service (services/operation_history_service.py),
so the SAS connection-string parsing and table-client bootstrap logic lives
in exactly one place.
"""

from __future__ import annotations

import logging
from typing import Any

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.core.credentials import AzureSasCredential
from azure.data.tables import TableServiceClient

logging.basicConfig(level=logging.INFO)


def parse_connection_string_parts(connection_string: str) -> dict[str, str]:
    """Convierte una connection string en un diccionario clave=valor."""
    parts: dict[str, str] = {}
    for token in connection_string.split(";"):
        item = token.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts[key.strip()] = value.strip()
    return parts


def validate_sas_connection_string(connection_string: str) -> None:
    """Valida formato minimo para autenticar con Shared Access Signature."""
    parts = parse_connection_string_parts(connection_string)

    has_table_endpoint = bool(parts.get("TableEndpoint"))
    has_sas = bool(parts.get("SharedAccessSignature"))

    # Formato esperado para SAS en tablas:
    # TableEndpoint=https://<account>.table.core.windows.net/;SharedAccessSignature=sv=...&sig=...
    if not (has_table_endpoint and has_sas):
        raise RuntimeError(
            "La connection string no tiene formato valido para SAS. "
            "Se espera TableEndpoint y SharedAccessSignature."
        )


def resolve_connection_target(connection_string: str) -> tuple[str, str]:
    """Obtiene datos no sensibles del destino de conexion."""
    parts = parse_connection_string_parts(connection_string)
    endpoint = str(parts.get("TableEndpoint", "")).strip()

    account_name = "(desconocido)"
    if endpoint:
        safe_endpoint = endpoint.rstrip("/")
        account_name = safe_endpoint.split("//")[-1].split(".")[0] or "(desconocido)"

    return (account_name, endpoint)


def build_table_service_client_from_sas(connection_string: str) -> TableServiceClient:
    """Construye cliente de tablas autenticado con SAS."""
    parts = parse_connection_string_parts(connection_string)
    endpoint = str(parts.get("TableEndpoint", "")).strip()
    sas_token = str(parts.get("SharedAccessSignature", "")).strip()

    if not endpoint or not sas_token:
        raise RuntimeError("No se pudo construir el cliente SAS. Falta TableEndpoint o SharedAccessSignature.")

    normalized_sas = sas_token[1:] if sas_token.startswith("?") else sas_token
    return TableServiceClient(endpoint=endpoint, credential=AzureSasCredential(normalized_sas))


def _to_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def ensure_table_client(service: TableServiceClient, table_name: str, create_if_missing: bool) -> Any:
    """Valida acceso a la tabla y la crea solo si esta habilitado."""
    table = service.get_table_client(table_name=table_name)

    try:
        # Valida acceso real de lectura sobre la tabla (sin requerir operacion ACL).
        pager = table.list_entities(results_per_page=1)
        next(pager.by_page(), None)
        logging.info("[TABLE] Tabla existente y accesible para lectura: %s", table_name)
        return table
    except ResourceNotFoundError:
        if not create_if_missing:
            raise RuntimeError(
                "La tabla no existe o no es visible y la creacion automatica esta deshabilitada. "
                "Define B2CC_CREATE_TABLE_IF_MISSING=true para permitir crearla."
            )

        logging.info("[TABLE] Tabla no encontrada. Se intentara crear: %s", table_name)
        service.create_table(table_name=table_name)
        logging.info("[TABLE] Tabla creada correctamente: %s", table_name)
        return service.get_table_client(table_name=table_name)
    except HttpResponseError as exc:
        raise RuntimeError(
            f"No se pudo validar acceso a la tabla '{table_name}'. "
            "Revisa permisos, network rules y allowSharedKeyAccess. "
            f"Detalle: {exc}"
        ) from exc


def connect_table(connection_string: str, table_name: str, *, create_if_missing: bool = False) -> Any:
    """Valida la connection string y devuelve un TableClient listo para usar."""
    validate_sas_connection_string(connection_string)
    account_name, endpoint = resolve_connection_target(connection_string)
    logging.info("[TABLE] Cuenta de almacenamiento: %s", account_name)
    logging.info("[TABLE] Endpoint de tabla: %s", endpoint)
    logging.info("[TABLE] Tabla objetivo: %s", table_name)

    service = build_table_service_client_from_sas(connection_string)
    return ensure_table_client(service=service, table_name=table_name, create_if_missing=create_if_missing)
