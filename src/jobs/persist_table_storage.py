#!/usr/bin/env python3
"""Persist B2CC audit events into Azure Table Storage."""

from __future__ import annotations

import os
import logging
import json
import re
import sys
from typing import Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = CURRENT_DIR
while not os.path.isdir(os.path.join(SRC_DIR, "models")):
    parent = os.path.dirname(SRC_DIR)
    if parent == SRC_DIR:
        raise RuntimeError("No se encontro el directorio 'src' (falta el paquete 'models').")
    SRC_DIR = parent
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from services.table_storage_client import (
    build_table_service_client_from_sas,
    connect_table,
    ensure_table_client,
    parse_connection_string_parts,
    resolve_connection_target,
    validate_sas_connection_string,
    _to_bool,
)

logging.basicConfig(level=logging.INFO)


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


def main() -> int:
    connection_string = os.getenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "").strip()
    table_name = os.getenv("AZURE_TABLE_STORAGE_TABLE_NAME", "").strip()
    audit_file = os.getenv("B2CC_AUDIT_FILE", "./b2cc_audit_events.jsonl").strip()
    create_table_if_missing = _to_bool(os.getenv("B2CC_CREATE_TABLE_IF_MISSING", "false"))

    if not connection_string:
        raise RuntimeError("Falta AZURE_TABLE_STORAGE_CONNECTION_STRING.")
    if not table_name:
        raise RuntimeError("Falta AZURE_TABLE_STORAGE_TABLE_NAME.")

    logging.info("[TABLE] Crear tabla si falta: %s", create_table_if_missing)
    events = load_audit_events(audit_file)
    if not events:
        logging.info("[TABLE] No hay eventos para persistir.")
        return 0

    table = connect_table(connection_string, table_name, create_if_missing=create_table_if_missing)
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
