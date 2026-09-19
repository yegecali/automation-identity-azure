#!/usr/bin/env python3
"""Validate create-operation inputs against Microsoft Graph before running the
real create-app-registration flow.

Checks, read-only:
1. Whether an App Registration with the derived displayName (the "client id")
   already exists.
2. If the flow is CC and the app already exists, whether a client secret with
   the expected alias ('{app_display_name}-secret') already exists on it.

Never creates, updates or deletes anything in Graph. Writes its findings as a
markdown comment body to disk so the workflow can post it on the tracking
issue.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

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

from models.dto import CreateInputDTO
from services.graph_service import get_application_by_display_name, run_az
from utils.common import build_app_display_name, get_obfuscated_secret, load_dispatch_input_from_env
from utils.runtime_config import get_env_credentials


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def write_comment(path: str, comment: str) -> None:
    output_dir = os.path.dirname(path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(comment)


def build_create_validation_report(
    app: dict[str, Any] | None,
    *,
    app_display_name: str,
    app_type: str,
) -> dict[str, Any]:
    """Arma el resultado de validacion a partir de la app ya consultada (o None).

    Efecto en tenant:
    - Ninguno. Operacion pura sobre datos ya leidos de Graph.

    Pasos funcionales:
    1. Determina si el client id (la App Registration) ya existe.
    2. Si es flujo CC y la app existe, revisa si ya hay un password credential
       con el alias '{app_display_name}-secret'.
    """
    secret_alias = f"{app_display_name}-secret"
    client_id_exists = app is not None
    secret_alias_exists = False

    if client_id_exists and str(app_type or "").strip().lower() == "cc":
        password_credentials = app.get("passwordCredentials") or []
        secret_alias_exists = any(
            str(item.get("displayName") or "").strip() == secret_alias for item in password_credentials
        )

    return {
        "app_display_name": app_display_name,
        "app_id": str((app or {}).get("appId") or ""),
        "client_id_exists": client_id_exists,
        "secret_alias": secret_alias,
        "secret_alias_exists": secret_alias_exists,
        "app_type": str(app_type or "").strip().lower(),
    }


def format_create_validation_comment(report: dict[str, Any]) -> str:
    """Formatea el reporte de validacion como comentario markdown para el issue."""
    lines = ["### Validación de inputs (creación)", ""]

    if report["client_id_exists"]:
        lines.append(
            f"- Client ID ya existe: **SI** (appId: `{report['app_id']}`, "
            f"displayName: `{report['app_display_name']}`)"
        )
    else:
        lines.append(f"- Client ID ya existe: **NO** (displayName: `{report['app_display_name']}`)")

    if report["app_type"] == "cc":
        exists_label = "SI" if report["secret_alias_exists"] else "NO"
        lines.append(f"- Alias de client secret `{report['secret_alias']}` ya existe: **{exists_label}**")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate create inputs job")
    parser.add_argument(
        "--comment-output",
        default="./artifacts/validate_create_comment.md",
        help="Path to write the markdown comment body",
    )
    args = parser.parse_args()

    input_data = load_dispatch_input_from_env()
    input_dto = CreateInputDTO.from_dict(input_data)
    creds = get_env_credentials(env=input_dto.env, tennant=input_dto.tennant)

    logging.info("[VALIDATE-CREATE] TenantId: %s", creds.tenant_id)
    logging.info("[VALIDATE-CREATE] ClientId: %s", creds.client_id)
    logging.info("[VALIDATE-CREATE] ClientSecret (obfuscado): %s", get_obfuscated_secret(creds.client_secret))

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

    app_display_name = build_app_display_name(
        name=input_dto.name, channel=input_dto.channel, app_type=input_dto.app_type
    )
    app = get_application_by_display_name(app_display_name)

    report = build_create_validation_report(app, app_display_name=app_display_name, app_type=input_dto.app_type)
    comment = format_create_validation_comment(report)

    logging.info("[VALIDATE-CREATE] %s", comment.replace("\n", " | "))
    write_comment(args.comment_output, comment)

    set_output("client_id_exists", "true" if report["client_id_exists"] else "false")
    set_output("secret_alias_exists", "true" if report["secret_alias_exists"] else "false")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
