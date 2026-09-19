#!/usr/bin/env python3
"""Create client secret only for CC flow and expose outputs."""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from services.graph_service import add_application_password, get_application_by_display_name, run_az
from utils.common import build_app_display_name, get_obfuscated_secret, load_json_file
from utils.runtime_config import get_env_credentials


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def resolve_app_context(input_data: dict, app_object_id_arg: str, app_name_arg: str) -> tuple[str, str]:
    app_object_id = str(app_object_id_arg or "").strip()
    app_name = str(app_name_arg or "").strip()

    if app_object_id and app_name:
        return app_object_id, app_name

    if not app_name:
        app_name = str(input_data.get("applicationName") or "").strip()
    if not app_name and str(input_data.get("operation", "")).strip().lower() == "create":
        app_name = build_app_display_name(
            name=str(input_data.get("name", "")),
            channel=str(input_data.get("channel", "")),
            app_type=str(input_data.get("type", "")),
        )

    if not app_name:
        raise RuntimeError("No se pudo resolver nombre de app para crear el secret CC.")

    app = get_application_by_display_name(app_name)
    if not app:
        raise RuntimeError(f"No se encontro aplicacion con displayName '{app_name}'.")

    app_object_id = str(app_object_id or app.get("id") or "").strip()
    if not app_object_id:
        raise RuntimeError("La aplicacion no tiene object id para crear secret.")

    return app_object_id, app_name


def main() -> int:
    parser = argparse.ArgumentParser(description="Create CC client secret job")
    parser.add_argument("--input", default="input.json", help="Path to input JSON")
    parser.add_argument("--app-object-id", default="", help="Application object ID")
    parser.add_argument("--app-name", default="", help="Application displayName")
    args = parser.parse_args()

    input_data = load_json_file(args.input)
    app_type = str(input_data.get("type", "")).strip().lower()
    if app_type != "cc":
        logging.info("[SECRET] Flujo no CC, se omite creacion de client secret.")
        set_output("secret_status", "skipped")
        set_output("client_secret_obfuscated", "")
        return 0

    env = str(input_data.get("env", "")).strip().lower()
    tennant = str(input_data.get("tennant") or input_data.get("tenant") or "").strip().lower()
    creds = get_env_credentials(env=env, tennant=tennant)

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

    app_object_id, app_name = resolve_app_context(input_data, args.app_object_id, args.app_name)
    secret_display_name = f"{app_name}-secret"
    password_result = add_application_password(app_object_id, display_name=secret_display_name)

    secret_value = str(password_result.get("secretText") or "").strip()
    if not secret_value:
        raise RuntimeError("Graph no devolvio secretText al crear el client secret.")

    secret_obfuscated = get_obfuscated_secret(secret_value)
    logging.info("[SECRET] Client secret creado (obfuscado): %s", secret_obfuscated)

    set_output("secret_status", "created")
    set_output("client_secret_obfuscated", secret_obfuscated)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
