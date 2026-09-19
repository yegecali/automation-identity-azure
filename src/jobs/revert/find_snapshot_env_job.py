#!/usr/bin/env python3
"""Look up the env/tennant of the latest unreverted snapshot for a ticket_number.

Runs before the real revert job so the workflow can pick the right GitHub
Environment (env-tennant) for it. Only needs Table Storage credentials — no
Azure AD / Microsoft Graph access, so it can run before that environment is
even selected.
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

from services.operation_history_service import find_latest_snapshot
from services.table_storage_client import connect_table


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Find snapshot env/tennant job")
    parser.add_argument("--ticket-number", required=True, help="Ticket number to look up")
    parser.add_argument("--operation", required=True, choices=["create", "update"])
    args = parser.parse_args()

    ticket_number = args.ticket_number.strip()
    if not ticket_number:
        raise RuntimeError("Debes indicar --ticket-number.")

    connection_string = os.getenv("AZURE_TABLE_STORAGE_CONNECTION_STRING", "").strip()
    table_name = os.getenv("AZURE_TABLE_STORAGE_TABLE_NAME", "").strip()
    if not connection_string or not table_name:
        raise RuntimeError(
            "Faltan AZURE_TABLE_STORAGE_CONNECTION_STRING o AZURE_TABLE_STORAGE_TABLE_NAME."
        )

    table = connect_table(connection_string, table_name, create_if_missing=False)
    snapshot = find_latest_snapshot(table, ticket_number, args.operation)
    if not snapshot:
        raise RuntimeError(
            f"No se encontro un snapshot de {args.operation} sin revertir para ticket_number='{ticket_number}'."
        )

    env = str(snapshot.get("env", "")).strip().lower()
    tennant = str(snapshot.get("tennant", "")).strip().lower()
    if not env or not tennant:
        raise RuntimeError("El snapshot encontrado no tiene env/tennant validos.")

    logging.info(
        "[FIND-SNAPSHOT] operation=%s ticket_number=%s -> env=%s tennant=%s",
        args.operation,
        ticket_number,
        env,
        tennant,
    )
    set_output("env", env)
    set_output("tennant", tennant)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
