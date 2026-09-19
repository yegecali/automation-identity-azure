#!/usr/bin/env python3
"""Update job: configure default Application ID URI (<appId>)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from configure import resolve_runtime_values
from configure import build_default_application_id_uri
from models.dto import UpdateInputDTO
from services.graph_service import get_application_by_id_with_retry, patch_application, run_az
from utils.common import load_json_file


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update add application id uri job")
    parser.add_argument("--input", default="input.json", help="Path to input JSON")
    parser.add_argument("--app-object-id", required=True, help="Application object ID")
    parser.add_argument("--app-id", required=True, help="Application (client) ID")
    args = parser.parse_args()

    input_data = load_json_file(args.input)
    input_dto = UpdateInputDTO.from_dict(input_data)
    runtime = resolve_runtime_values(input_dto)

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

    app_before_patch = get_application_by_id_with_retry(args.app_object_id)
    publisher_domain = str(app_before_patch.get("publisherDomain") or "").strip()
    application_id_uri = build_default_application_id_uri(args.app_id, publisher_domain)
    if application_id_uri != args.app_id:
        logging.info("[APP-ID-URI] normalizado: %s -> %s", args.app_id, application_id_uri)
    else:
        logging.info("[APP-ID-URI] valor: %s", application_id_uri)
    patch_application(args.app_object_id, {"identifierUris": [application_id_uri]})

    confirmed = False
    for _ in range(6):
        app = get_application_by_id_with_retry(args.app_object_id)
        identifier_uris = [str(item) for item in (app.get("identifierUris") or [])]
        if application_id_uri in identifier_uris:
            confirmed = True
            break
        time.sleep(3)

    if not confirmed:
        raise RuntimeError("No se pudo confirmar Application ID URI tras actualizar identifierUris.")

    logging.info("[APP-ID-URI] configurado: %s", application_id_uri)
    set_output("application_id_uri", application_id_uri)
    set_output("application_id_uri_status", "updated")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
