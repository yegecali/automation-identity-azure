#!/usr/bin/env python3
"""Update job: add scopes for AC flow."""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from configure import configure_ac_scopes, resolve_runtime_values
from models.dto import UpdateInputDTO
from services.graph_service import run_az
from utils.common import load_json_file, unique_scopes


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update add scopes job")
    parser.add_argument("--input", default="input.json", help="Path to input JSON")
    parser.add_argument("--app-object-id", required=True, help="Application object ID")
    parser.add_argument("--app-id", required=True, help="Application (client) ID")
    parser.add_argument("--scopes-csv", default="", help="Optional scopes override as CSV")
    args = parser.parse_args()

    input_data = load_json_file(args.input)
    input_dto = UpdateInputDTO.from_dict(input_data)
    runtime = resolve_runtime_values(input_dto)

    if runtime.app_type != "ac":
        raise RuntimeError("Este job solo aplica para flujo AC.")

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

    configure_ac_scopes(
        app_object_id=args.app_object_id,
        app_id=args.app_id,
        clean_scopes=scopes,
    )

    logging.info("[SCOPES] Scopes AC aplicados: %s", ", ".join(scopes))
    set_output("scopes_status", "updated")
    set_output("scopes_applied", ",".join(scopes))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
