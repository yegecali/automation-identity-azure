#!/usr/bin/env python3
"""Revert the last create operation for a ticket_number.

Disables (does NOT delete) the Service Principal that was created, so the
client_id/secret combination stops authenticating immediately while the
objects stay available for inspection or manual cleanup.
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

from services.graph_service import patch_service_principal, run_az
from services.operation_history_service import (
    CREATE_OPERATION,
    find_latest_snapshot,
    mark_snapshot_reverted,
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
    parser = argparse.ArgumentParser(description="Revert last create operation job")
    parser.add_argument("--ticket-number", required=True, help="Ticket number of the create operation to revert")
    args = parser.parse_args()

    ticket_number = args.ticket_number.strip()
    if not ticket_number:
        raise RuntimeError("Debes indicar --ticket-number para poder revertir.")

    connection_string = os.getenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "").strip()
    table_name = os.getenv("AZURE_TABLE_STORAGE_TABLE_NAME_AUDIT", "").strip()
    if not connection_string or not table_name:
        raise RuntimeError(
            "Faltan AZURE_TABLE_STORAGE_CONNECTION_STRING o AZURE_TABLE_STORAGE_TABLE_NAME_AUDIT."
        )

    table = connect_table(connection_string, table_name, create_if_missing=False)
    snapshot = find_latest_snapshot(table, ticket_number, CREATE_OPERATION)
    if not snapshot:
        raise RuntimeError(
            f"No se encontro un snapshot de creacion sin revertir para ticket_number='{ticket_number}'."
        )

    env = str(snapshot.get("env", "")).strip().lower()
    tennant = str(snapshot.get("tennant", "")).strip().lower()
    app_id = str(snapshot.get("appId", "")).strip()
    sp_id = str(snapshot.get("spId", "")).strip()
    application_name = str(snapshot.get("applicationName", "")).strip()

    if not sp_id:
        raise RuntimeError(
            f"El snapshot para ticket_number='{ticket_number}' no tiene spId; no se puede deshabilitar el Service Principal."
        )

    logging.info(
        "[REVERT-CREATE] Snapshot encontrado: env=%s tennant=%s app=%s appId=%s spId=%s",
        env,
        tennant,
        application_name,
        app_id,
        sp_id,
    )

    creds = get_env_credentials(env=env, tennant=tennant)
    logging.info("[REVERT-CREATE] TenantId: %s", creds.tenant_id)
    logging.info("[REVERT-CREATE] ClientId: %s", creds.client_id)
    logging.info("[REVERT-CREATE] ClientSecret (obfuscado): %s", get_obfuscated_secret(creds.client_secret))

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

    patch_service_principal(sp_id, {"accountEnabled": False})
    logging.info("[REVERT-CREATE] Service Principal deshabilitado: spId=%s", sp_id)

    mark_snapshot_reverted(table, snapshot, reverted_run_id=os.getenv("GITHUB_RUN_ID", ""))

    set_output("revert_status", "disabled")
    set_output("app_id", app_id)
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
