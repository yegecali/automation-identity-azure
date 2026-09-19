#!/usr/bin/env python3
"""Update job: configure redirect URI in target application."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

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

from configure import resolve_runtime_values, validate_redirect_uri
from models.dto import UpdateInputDTO
from services.graph_service import get_application_by_id_with_retry, patch_application, run_az
from utils.common import get_obfuscated_secret, load_dispatch_input_from_env


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update configure redirect URI job")
    parser.add_argument("--app-object-id", required=True, help="Application object ID")
    parser.add_argument("--redirect-uri", default="", help="Optional redirect URI override")
    args = parser.parse_args()

    input_data = load_dispatch_input_from_env()
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

    redirect_uri = str(args.redirect_uri or runtime.redirect_uri).strip()
    validate_redirect_uri(redirect_uri)

    is_cc = runtime.app_type == "cc"
    platform_key = "spa" if is_cc else "web"

    patch_body = {platform_key: {"redirectUris": [redirect_uri]}}
    if is_cc:
        patch_body["web"] = {
            "implicitGrantSettings": {
                "enableAccessTokenIssuance": True,
                "enableIdTokenIssuance": True,
            }
        }

    patch_application(args.app_object_id, patch_body)

    confirmed = False
    for _ in range(6):
        app = get_application_by_id_with_retry(args.app_object_id)
        redirect_uris = [str(item) for item in (app.get(platform_key) or {}).get("redirectUris", [])]
        if redirect_uri in redirect_uris:
            confirmed = True
            break
        time.sleep(3)

    if not confirmed:
        raise RuntimeError(
            f"No se pudo confirmar {platform_key}.redirectUris tras actualizar redirect URI."
        )

    if is_cc:
        logging.info("[AUTH] Implicit/hybrid habilitado en CC: access tokens + id tokens")
    logging.info("[REDIRECT] redirectUri configurado en %s: %s", platform_key, redirect_uri)
    set_output("redirect_uri", redirect_uri)
    set_output("redirect_status", "updated")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
