#!/usr/bin/env python3
"""Revert the last update operation for a ticket_number.

Restores identifierUris/web/spa/api/appRoles/requiredResourceAccess to the
values captured right before that update was applied.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = CURRENT_DIR
while not os.path.isdir(os.path.join(SRC_DIR, "models")):
    parent = os.path.dirname(SRC_DIR)
    if parent == SRC_DIR:
        raise RuntimeError("No se encontro el directorio 'src' (falta el paquete 'models').")
    SRC_DIR = parent
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from configure import build_manifest_restore_patch
from services.graph_service import patch_application, run_az
from services.operation_history_service import (
    UPDATE_OPERATION,
    find_latest_snapshot,
    mark_snapshot_reverted,
    parse_before_manifest,
)
from services.table_storage_client import connect_table
from utils.common import get_obfuscated_secret
from utils.runtime_config import get_env_credentials


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Revert last update operation job")
    parser.add_argument("--ticket-number", required=True, help="Ticket number of the update operation to revert")
    args = parser.parse_args()

    ticket_number = args.ticket_number.strip()
    if not ticket_number:
        raise RuntimeError("Debes indicar --ticket-number para poder revertir.")

    connection_string = os.getenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "").strip()
    table_name = os.getenv("AZURE_TABLE_STORAGE_HISTORY_TABLE_NAME", "").strip()
    if not connection_string or not table_name:
        raise RuntimeError(
            "Faltan AZURE_TABLE_STORAGE_CONNECTION_STRING o AZURE_TABLE_STORAGE_HISTORY_TABLE_NAME."
        )

    table = connect_table(connection_string, table_name, create_if_missing=False)
    snapshot = find_latest_snapshot(table, ticket_number, UPDATE_OPERATION)
    if not snapshot:
        raise RuntimeError(
            f"No se encontro un snapshot de actualizacion sin revertir para ticket_number='{ticket_number}'."
        )

    env = str(snapshot.get("env", "")).strip().lower()
    tennant = str(snapshot.get("tennant", "")).strip().lower()
    app_id = str(snapshot.get("appId", "")).strip()
    app_object_id = str(snapshot.get("appObjectId", "")).strip()
    application_name = str(snapshot.get("applicationName", "")).strip()

    if not app_object_id:
        raise RuntimeError(
            f"El snapshot para ticket_number='{ticket_number}' no tiene appObjectId; no se puede revertir."
        )

    before_manifest = parse_before_manifest(snapshot)
    patch_body = build_manifest_restore_patch(before_manifest)

    logging.info(
        "[REVERT-UPDATE] Snapshot encontrado: env=%s tennant=%s app=%s appObjectId=%s",
        env,
        tennant,
        application_name,
        app_object_id,
    )
    logging.info("[REVERT-UPDATE] Propiedades a restaurar: %s", ", ".join(sorted(patch_body.keys())))

    creds = get_env_credentials(env=env, tennant=tennant)
    logging.info("[REVERT-UPDATE] TenantId: %s", creds.tenant_id)
    logging.info("[REVERT-UPDATE] ClientId: %s", creds.client_id)
    logging.info("[REVERT-UPDATE] ClientSecret (obfuscado): %s", get_obfuscated_secret(creds.client_secret))

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

    patch_application(app_object_id, patch_body)
    logging.info("[REVERT-UPDATE] Manifest restaurado sobre appObjectId=%s", app_object_id)

    mark_snapshot_reverted(table, snapshot, reverted_run_id=os.getenv("GITHUB_RUN_ID", ""))

    set_output("revert_status", "restored")
    set_output("app_id", app_id)
    set_output("app_object_id", app_object_id)
    set_output("app_display_name", application_name)
    set_output("env", env)
    set_output("tennant", tennant)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
