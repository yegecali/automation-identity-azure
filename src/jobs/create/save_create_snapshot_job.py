#!/usr/bin/env python3
"""Save a rollback snapshot right after a create operation succeeds.

Stores just enough to let revert-create-app-registration.yml find and disable
what was created: app_id, app_object_id and sp_id, keyed by ticket_number.
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

from services.operation_history_service import CREATE_OPERATION, build_snapshot_entity, save_snapshot
from services.table_storage_client import connect_table
from utils.common import load_dispatch_input_from_env


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def build_run_url() -> str:
    server_url = os.getenv("GITHUB_SERVER_URL", "").strip()
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    if not (server_url and repository and run_id):
        return ""
    return f"{server_url}/{repository}/actions/runs/{run_id}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Save create rollback snapshot job")
    parser.add_argument("--ticket-number", required=True, help="Ticket number that identifies this operation")
    parser.add_argument("--app-id", required=True, help="Application (client) ID created/reused")
    parser.add_argument("--app-object-id", required=True, help="Application object ID")
    parser.add_argument("--app-display-name", required=True, help="Application displayName")
    parser.add_argument("--sp-id", default="", help="Service principal object ID")
    parser.add_argument("--app-type", default="", help="ac or cc")
    args = parser.parse_args()

    ticket_number = args.ticket_number.strip()
    if not ticket_number:
        logging.info("[SNAPSHOT] ticket_number vacio, se omite el snapshot de rollback.")
        set_output("snapshot_status", "skipped")
        return 0

    input_data = load_dispatch_input_from_env()
    env = str(input_data.get("env", "")).strip().lower()
    tennant = str(input_data.get("tennant") or input_data.get("tenant") or "").strip().lower()

    connection_string = os.getenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "").strip()
    table_name = os.getenv("AZURE_TABLE_STORAGE_TABLE_NAME_AUDIT", "").strip()
    if not connection_string or not table_name:
        raise RuntimeError(
            "Faltan AZURE_TABLE_STORAGE_CONNECTION_STRING o AZURE_TABLE_STORAGE_TABLE_NAME_AUDIT "
            "para guardar el snapshot de rollback."
        )

    entity = build_snapshot_entity(
        ticket_number=ticket_number,
        operation=CREATE_OPERATION,
        env=env,
        tennant=tennant,
        application_name=args.app_display_name,
        app_id=args.app_id,
        app_object_id=args.app_object_id,
        sp_id=args.sp_id,
        after_summary={"app_type": args.app_type, "app_display_name": args.app_display_name},
        run_id=os.getenv("GITHUB_RUN_ID", ""),
        run_url=build_run_url(),
    )

    table = connect_table(connection_string, table_name, create_if_missing=True)
    save_snapshot(table, entity)

    logging.info("[SNAPSHOT] Snapshot de creacion guardado para ticket_number=%s", ticket_number)
    set_output("snapshot_status", "saved")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
