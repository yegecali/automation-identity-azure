#!/usr/bin/env python3
"""Persist B2CC audit events into Azure Table Storage."""

from __future__ import annotations

import os
import logging
import json
import re
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
            "AZURE_TABLE_STORAGE_CONNECTION_STRING no tiene formato valido para SAS. "
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


def load_audit_events(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        logging.info("[TABLE] No existe archivo de auditoria: %s", path)
        return []

    events: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def _normalize_scopes(raw_scopes: Any) -> str:
    raw = str(raw_scopes or "").replace("\\n", "\n")
    tokens = [item.strip() for item in re.split(r"[\s,]+", raw) if item.strip()]
    seen: set[str] = set()
    normalized: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return ",".join(normalized)


def _resolve_partition_key(event: dict[str, Any]) -> str:
    partition_key = str(event.get("PartitionKey") or event.get("partitionKey") or "").strip()
    if partition_key:
        return partition_key

    # Fallback de compatibilidad con esquema anterior.
    return str(event.get("applicationName") or event.get("appAlias") or event.get("operation") or "").strip()


def _resolve_row_key(event: dict[str, Any]) -> str:
    row_key = str(event.get("RowKey") or event.get("rowKey") or "").strip()
    if row_key:
        return row_key

    # Fallback de compatibilidad con esquema anterior.
    return str(event.get("tennant") or event.get("tenant") or "").strip()


def build_entity(event: dict[str, Any]) -> dict[str, Any]:
    operation = str(event.get("operation", "")).strip().lower()
    app_type = str(event.get("type", "")).strip().lower()
    partition_key = _resolve_partition_key(event)
    row_key = _resolve_row_key(event)
    client_code = str(event.get("Clientcode") or event.get("clientCode") or event.get("channel") or "").strip()
    app_code = str(event.get("appcode") or event.get("appCode") or event.get("singleCode") or "").strip()
    client_id = str(event.get("clientid") or event.get("clientId") or "").strip()
    scope = _normalize_scopes(event.get("scope") or event.get("scopes") or "")
    user_app = str(event.get("userApp") or "").strip()
    created_at = str(event.get("createdAt") or "").strip()

    entity: dict[str, Any] = {
        "PartitionKey": partition_key,
        "RowKey": row_key,
        "operation": operation,
        "type": app_type,
        "Clientcode": client_code,
        "appcode": app_code,
        "clientid": client_id,
        "scope": scope,
        "userApp": user_app,
    }

    if created_at:
        entity["createdAt"] = created_at

    # Mantener nombres legacy para consultas existentes.
    entity["clientId"] = client_id
    entity["scopes"] = scope

    return entity


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


def main() -> int:
    connection_string = os.getenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "").strip()
    table_name = os.getenv("AZURE_TABLE_STORAGE_TABLE_NAME", "").strip()
    audit_file = os.getenv("B2CC_AUDIT_FILE", "./b2cc_audit_events.jsonl").strip()
    create_table_if_missing = _to_bool(os.getenv("B2CC_CREATE_TABLE_IF_MISSING", "false"))

    if not connection_string:
        raise RuntimeError("Falta AZURE_TABLE_STORAGE_CONNECTION_STRING.")
    if not table_name:
        raise RuntimeError("Falta AZURE_TABLE_STORAGE_TABLE_NAME.")

    validate_sas_connection_string(connection_string)
    logging.info("[TABLE] Connection string validada para autenticacion con Shared Access Signature (SAS).")
    account_name, endpoint = resolve_connection_target(connection_string)
    logging.info("[TABLE] Cuenta de almacenamiento: %s", account_name)
    logging.info("[TABLE] Endpoint de tabla: %s", endpoint)
    logging.info("[TABLE] Tabla objetivo: %s", table_name)
    logging.info("[TABLE] Crear tabla si falta: %s", create_table_if_missing)

    events = load_audit_events(audit_file)
    if not events:
        logging.info("[TABLE] No hay eventos para persistir.")
        return 0

    service = build_table_service_client_from_sas(connection_string)
    table = ensure_table_client(
        service=service,
        table_name=table_name,
        create_if_missing=create_table_if_missing,
    )
    logging.info("[TABLE] Conexion establecida y cliente de tabla inicializado.")

    persisted = 0
    for event in events:
        entity = build_entity(event=event)

        if not entity.get("PartitionKey"):
            logging.info("[TABLE] Evento ignorado por PartitionKey vacio")
            continue
        if not entity.get("RowKey"):
            logging.info("[TABLE] Evento ignorado por RowKey vacio")
            continue

        table.upsert_entity(entity=entity, mode="MERGE")
        persisted += 1

    logging.info("[TABLE] Registros persistidos (upsert): %s", persisted)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[TABLE][ERROR] %s", exc)
        raise SystemExit(1)
