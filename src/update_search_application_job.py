#!/usr/bin/env python3
"""Update job: search target application and expose context outputs."""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from configure import resolve_runtime_values, validate_app_client_id
from models.dto import UpdateInputDTO
from services.graph_service import get_application_by_display_name, run_az
from utils.common import get_obfuscated_secret, load_json_file


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update search app job")
    parser.add_argument("--input", default="input.json", help="Path to input JSON")
    args = parser.parse_args()

    input_data = load_json_file(args.input)
    input_dto = UpdateInputDTO.from_dict(input_data)
    runtime = resolve_runtime_values(input_dto)

    creds = runtime.credentials
    logging.info("[SEARCH] TenantId: %s", creds.tenant_id)
    logging.info("[SEARCH] ClientId: %s", creds.client_id)
    logging.info("[SEARCH] ClientSecret (obfuscado): %s", get_obfuscated_secret(creds.client_secret))

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

    app = get_application_by_display_name(runtime.application_name)
    if not app:
        raise RuntimeError(f"No se encontro ninguna aplicacion con nombre '{runtime.application_name}'.")

    app_id = str(app.get("appId") or "").strip()
    app_object_id = str(app.get("id") or "").strip()
    if not app_id or not app_object_id:
        raise RuntimeError("La aplicacion encontrada no tiene appId/id valido.")

    validate_app_client_id(app_id)

    set_output("app_id", app_id)
    set_output("app_object_id", app_object_id)
    set_output("application_name", runtime.application_name)
    set_output("app_type", runtime.app_type)
    set_output("redirect_uri", runtime.redirect_uri)
    set_output("scopes_csv", ",".join(runtime.scopes))

    logging.info("[SEARCH] appId=%s objectId=%s type=%s", app_id, app_object_id, runtime.app_type)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
