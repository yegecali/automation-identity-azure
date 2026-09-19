#!/usr/bin/env python3
"""Validate/create application service principal and expose job outputs."""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from services.graph_service import create_service_principal, get_application_by_display_name, get_service_principal_by_app_id, run_az
from utils.common import build_app_display_name, get_obfuscated_secret, load_json_file
from utils.runtime_config import get_env_credentials


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def resolve_app_id(input_data: dict, app_id_from_arg: str) -> tuple[str, str]:
    app_id = str(app_id_from_arg or "").strip()
    if app_id:
        return app_id, ""

    app_name = str(input_data.get("applicationName") or "").strip()
    if not app_name and str(input_data.get("operation", "")).strip().lower() == "create":
        app_name = build_app_display_name(
            name=str(input_data.get("name", "")),
            channel=str(input_data.get("channel", "")),
            app_type=str(input_data.get("type", "")),
        )

    if not app_name:
        raise RuntimeError("No se pudo resolver la aplicacion. Envia --app-id o applicationName/name en input.")

    app = get_application_by_display_name(app_name)
    if not app:
        raise RuntimeError(f"No se encontro aplicacion con displayName '{app_name}'.")

    resolved_app_id = str(app.get("appId") or "").strip()
    if not resolved_app_id:
        raise RuntimeError("La aplicacion encontrada no tiene appId.")

    return resolved_app_id, app_name


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate/create service principal job")
    parser.add_argument("--input", default="input.json", help="Path to input JSON")
    parser.add_argument("--app-id", default="", help="Application (client) ID")
    args = parser.parse_args()

    input_data = load_json_file(args.input)
    env = str(input_data.get("env", "")).strip().lower()
    tennant = str(input_data.get("tennant") or input_data.get("tenant") or "").strip().lower()

    creds = get_env_credentials(env=env, tennant=tennant)
    logging.info("[SP] TenantId: %s", creds.tenant_id)
    logging.info("[SP] ClientId: %s", creds.client_id)
    logging.info("[SP] ClientSecret (obfuscado): %s", get_obfuscated_secret(creds.client_secret))

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

    app_id, app_name = resolve_app_id(input_data, args.app_id)
    service_principal = get_service_principal_by_app_id(app_id)

    status = "existing"
    if not service_principal:
        service_principal = create_service_principal(app_id)
        status = "created"

    sp_id = str(service_principal.get("id") or "").strip()
    if not sp_id:
        raise RuntimeError("No se pudo resolver id del service principal.")

    logging.info("[SP] appId=%s spId=%s status=%s", app_id, sp_id, status)
    set_output("app_id", app_id)
    set_output("sp_id", sp_id)
    set_output("sp_status", status)
    if app_name:
        set_output("app_name", app_name)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
