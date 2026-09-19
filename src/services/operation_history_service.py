#!/usr/bin/env python3
"""Persist and query operation snapshots used to revert the last create/update
performed on a B2C App Registration.

Storage layout (Azure Table Storage, separate table from the lightweight
audit log in persist_table_storage.py):

    PartitionKey = ticket_number
    RowKey       = "{created_at_iso}_{run_id}"   (sorts chronologically as text)

Each row records everything a revert job needs: which app/env/tennant was
touched, and either the identifiers of what was created (for revert-create)
or a full snapshot of the application manifest captured immediately before
an update was applied (for revert-update).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from azure.data.tables import UpdateMode

logging.basicConfig(level=logging.INFO)

CREATE_OPERATION = "create"
UPDATE_OPERATION = "update"
VALID_OPERATIONS = {CREATE_OPERATION, UPDATE_OPERATION}


def build_snapshot_entity(
    *,
    ticket_number: str,
    operation: str,
    env: str,
    tennant: str,
    application_name: str,
    app_id: str = "",
    app_object_id: str = "",
    sp_id: str = "",
    before_manifest: dict[str, Any] | None = None,
    after_summary: dict[str, Any] | None = None,
    run_id: str = "",
    run_url: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    """Construye la entidad de snapshot a persistir en Table Storage.

    Efecto en tenant:
    - Ninguno. Solo arma el diccionario en memoria.

    Pasos funcionales:
    1. Valida ticket_number y operation.
    2. Arma RowKey cronologico ('createdAt_runId') para poder ordenar snapshots
       del mismo ticket sin pisar filas anteriores.
    3. Serializa beforeManifestJson/afterSummaryJson como texto JSON si se
       proveen.
    """
    clean_ticket = str(ticket_number or "").strip()
    clean_operation = str(operation or "").strip().lower()

    if not clean_ticket:
        raise RuntimeError("ticket_number no puede ser vacio para guardar un snapshot.")
    if clean_operation not in VALID_OPERATIONS:
        raise RuntimeError(f"operation debe ser uno de: {', '.join(sorted(VALID_OPERATIONS))}")

    created_at_iso = created_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    row_key = f"{created_at_iso}_{run_id or 'local'}"

    entity: dict[str, Any] = {
        "PartitionKey": clean_ticket,
        "RowKey": row_key,
        "operation": clean_operation,
        "env": str(env or "").strip().lower(),
        "tennant": str(tennant or "").strip().lower(),
        "applicationName": str(application_name or "").strip(),
        "appId": str(app_id or "").strip(),
        "appObjectId": str(app_object_id or "").strip(),
        "spId": str(sp_id or "").strip(),
        "runId": str(run_id or "").strip(),
        "runUrl": str(run_url or "").strip(),
        "createdAt": created_at_iso,
        "reverted": False,
        "revertedAt": "",
        "revertedRunId": "",
    }

    if before_manifest is not None:
        entity["beforeManifestJson"] = json.dumps(before_manifest, ensure_ascii=False)
    if after_summary is not None:
        entity["afterSummaryJson"] = json.dumps(after_summary, ensure_ascii=False)

    return entity


def select_latest_snapshot(entities: list[dict[str, Any]], operation: str) -> dict[str, Any] | None:
    """Elige el snapshot mas reciente y no revertido de un tipo de operacion.

    Efecto en tenant:
    - Ninguno. Operacion pura sobre datos ya leidos.

    Pasos funcionales:
    1. Filtra por `operation` y descarta snapshots ya marcados como revertidos.
    2. Toma el de mayor RowKey (el prefijo ISO-8601 ordena cronologicamente
       tambien como texto).
    3. Devuelve None si no hay candidatos.
    """
    clean_operation = str(operation or "").strip().lower()
    candidates = [
        entity
        for entity in entities
        if str(entity.get("operation", "")).strip().lower() == clean_operation and not entity.get("reverted", False)
    ]
    if not candidates:
        return None

    return max(candidates, key=lambda entity: str(entity.get("RowKey", "")))


def parse_before_manifest(entity: dict[str, Any]) -> dict[str, Any]:
    """Deserializa el manifest 'antes' guardado en un snapshot de update.

    Efecto en tenant:
    - Ninguno. Solo parsea datos ya leidos.
    """
    raw = entity.get("beforeManifestJson")
    if not raw:
        raise RuntimeError("El snapshot no contiene beforeManifestJson; no se puede revertir el update.")
    return json.loads(raw)


def save_snapshot(table: Any, entity: dict[str, Any]) -> None:
    """Persiste un snapshot de operacion (una fila nueva por operacion).

    Efecto en tenant:
    - Ninguno sobre Azure AD/Graph. Escribe una fila en Table Storage.
    """
    table.upsert_entity(entity=entity, mode=UpdateMode.MERGE)


def query_snapshots_for_ticket(table: Any, ticket_number: str) -> list[dict[str, Any]]:
    """Lee todos los snapshots guardados para un ticket_number dado.

    Efecto en tenant:
    - Ninguno. Solo lectura de Table Storage.
    """
    clean_ticket = str(ticket_number or "").strip()
    if not clean_ticket:
        raise RuntimeError("ticket_number no puede ser vacio para consultar snapshots.")

    escaped_ticket = clean_ticket.replace("'", "''")
    entities = table.query_entities(query_filter=f"PartitionKey eq '{escaped_ticket}'")
    return [dict(entity) for entity in entities]


def find_latest_snapshot(table: Any, ticket_number: str, operation: str) -> dict[str, Any] | None:
    """Busca el snapshot mas reciente y no revertido para ticket_number+operation.

    Efecto en tenant:
    - Ninguno. Solo lectura de Table Storage.
    """
    entities = query_snapshots_for_ticket(table, ticket_number)
    return select_latest_snapshot(entities, operation)


def mark_snapshot_reverted(
    table: Any,
    entity: dict[str, Any],
    *,
    reverted_run_id: str,
    reverted_at: str | None = None,
) -> None:
    """Marca un snapshot como revertido para evitar reversiones duplicadas.

    Efecto en tenant:
    - Ninguno sobre Azure AD/Graph. Actualiza la fila de Table Storage.
    """
    update = {
        "PartitionKey": entity["PartitionKey"],
        "RowKey": entity["RowKey"],
        "reverted": True,
        "revertedAt": reverted_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "revertedRunId": str(reverted_run_id or "").strip(),
    }
    table.update_entity(entity=update, mode=UpdateMode.MERGE)
