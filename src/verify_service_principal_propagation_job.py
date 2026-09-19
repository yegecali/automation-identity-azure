#!/usr/bin/env python3
"""Validate service principal propagation for a given application id."""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from services.graph_service import get_service_principal_by_app_id, run_az
from utils.common import get_obfuscated_secret, load_json_file
from utils.runtime_config import get_env_credentials


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify service principal propagation")
    parser.add_argument("--input", default="input.json", help="Path to input JSON")
    parser.add_argument("--app-id", required=True, help="Application (client) ID")
    parser.add_argument("--expected-sp-id", default="", help="Expected service principal object ID")
    args = parser.parse_args()

    input_data = load_json_file(args.input)
    env = str(input_data.get("env", "")).strip().lower()
    tennant = str(input_data.get("tennant") or input_data.get("tenant") or "").strip().lower()

    creds = get_env_credentials(env=env, tennant=tennant)
    logging.info("[VERIFY-SP] TenantId: %s", creds.tenant_id)
    logging.info("[VERIFY-SP] ClientId: %s", creds.client_id)
    logging.info("[VERIFY-SP] ClientSecret (obfuscado): %s", get_obfuscated_secret(creds.client_secret))

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

    service_principal = get_service_principal_by_app_id(args.app_id)
    if not service_principal:
        raise RuntimeError(f"Aun no existe service principal para appId={args.app_id}.")

    found_sp_id = str(service_principal.get("id") or "").strip()
    if not found_sp_id:
        raise RuntimeError("Se encontro el service principal pero no contiene id.")

    expected_sp_id = str(args.expected_sp_id or "").strip()
    if expected_sp_id and found_sp_id != expected_sp_id:
        raise RuntimeError(
            f"SP propagado con id distinto. esperado={expected_sp_id} encontrado={found_sp_id}"
        )

    logging.info("[VERIFY-SP] Propagacion OK. appId=%s spId=%s", args.app_id, found_sp_id)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
