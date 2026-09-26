#!/usr/bin/env python3
"""Update job: add app roles for CC flow."""

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

from configure import configure_cc_app_roles, resolve_runtime_values
from models.dto import UpdateInputDTO
from services.graph_service import create_service_principal, get_service_principal_by_app_id, run_az
from utils.common import load_dispatch_input_from_env, unique_scopes


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update add app roles job")
    parser.add_argument("--app-object-id", required=True, help="Application object ID")
    parser.add_argument("--app-id", required=True, help="Application (client) ID")
    parser.add_argument("--scopes-csv", default="", help="Optional app roles override as CSV")
    args = parser.parse_args()

    input_data = load_dispatch_input_from_env()
    input_dto = UpdateInputDTO.from_dict(input_data)
    runtime = resolve_runtime_values(input_dto)

    if runtime.app_type != "cc":
        raise RuntimeError("Este job solo aplica para flujo CC.")

    scopes = runtime.scopes
    if args.scopes_csv.strip():
        scopes = unique_scopes([item.strip() for item in args.scopes_csv.split(",")])

    creds = runtime.credentials
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

    app_sp = get_service_principal_by_app_id(args.app_id)
    if not app_sp:
        app_sp = create_service_principal(args.app_id)
    app_sp_id = str(app_sp.get("id") or "").strip()
    if not app_sp_id:
        raise RuntimeError("No se pudo resolver service principal id para aplicar app roles CC.")

    target_roles, summary = configure_cc_app_roles(
        app_object_id=args.app_object_id,
        app_id=args.app_id,
        clean_scopes=scopes,
        sp_id=app_sp_id,
    )

    role_values = [str(item.get("value")) for item in target_roles if item.get("value")]
    logging.info("[APP-ROLES] App roles CC aplicados (Application, con consent): %s", ", ".join(role_values))
    logging.info(
        "[APP-ROLES] added=%s kept=%s removed=%s", summary.added, summary.kept, summary.removed
    )
    set_output("app_roles_status", "updated")
    set_output("app_roles_applied", ",".join(role_values))
    set_output("scopes_status", "updated")
    set_output("scopes_applied", ",".join(scopes))
    set_output("scopes_added", ",".join(summary.added))
    set_output("scopes_kept", ",".join(summary.kept))
    set_output("scopes_removed", ",".join(summary.removed))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
