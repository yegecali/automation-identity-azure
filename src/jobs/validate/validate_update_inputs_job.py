#!/usr/bin/env python3
"""Validate update-operation inputs against Microsoft Graph before running the
real update-app-registration flow: diff the requested scopes/app roles
against what the app currently has configured, and report what would be
added versus what is configured today but left out of this request.

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

from configure import resolve_app_type
from models.dto import UpdateInputDTO
from services.graph_service import get_application_by_display_name, run_az
from utils.common import get_obfuscated_secret, load_dispatch_input_from_env, unique_scopes
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


def extract_current_scopes(app: dict[str, Any], app_type: str) -> list[str]:
    """Extrae los scopes/app roles actualmente configurados en la app.

    Efecto en tenant:
    - Ninguno. Operacion pura sobre datos ya leidos de Graph.

    Pasos funcionales:
    1. CC: lee `appRoles[].value`.
    2. AC (o cualquier otro): lee `api.oauth2PermissionScopes[].value`.
    """
    clean_type = str(app_type or "").strip().lower()

    if clean_type == "cc":
        items = app.get("appRoles") or []
    else:
        items = ((app.get("api") or {}).get("oauth2PermissionScopes")) or []

    return unique_scopes([str(item.get("value") or "") for item in items])


def diff_scopes(current: list[str], requested: list[str]) -> tuple[list[str], list[str]]:
    """Compara scopes actuales vs solicitados.

    Efecto en tenant:
    - Ninguno. Operacion pura.

    Pasos funcionales:
    1. `added`: en `requested` pero no en `current` (se agregarian con este dispatch).
    2. `missing`: en `current` pero no en `requested` (quedan fuera del request).
    """
    current_set = set(current)
    requested_set = set(requested)
    added = sorted(requested_set - current_set)
    missing = sorted(current_set - requested_set)
    return added, missing


def format_update_validation_comment(
    *,
    application_name: str,
    app_type: str,
    current_scopes: list[str],
    requested_scopes: list[str],
    added: list[str],
    missing: list[str],
) -> str:
    """Formatea el reporte de validacion como comentario markdown para el issue."""
    label = "app roles (CC)" if app_type == "cc" else "scopes delegados (AC)"
    lines = [
        f"### Validación de inputs (actualización) — `{application_name}`",
        "",
        f"Tipo de flujo: **{app_type or 'desconocido'}** — comparando {label}.",
        "",
        f"- Configurados actualmente: {', '.join(f'`{s}`' for s in current_scopes) or '_(ninguno)_'}",
        f"- Solicitados en este dispatch: {', '.join(f'`{s}`' for s in requested_scopes) or '_(ninguno)_'}",
        "",
    ]

    if added:
        lines.append(f"- Se **agregarían**: {', '.join(f'`{s}`' for s in added)}")
    else:
        lines.append("- Se agregarían: _(ninguno)_")

    if missing:
        lines.append(
            "- Configurados hoy pero **no incluidos** en este request: "
            + ", ".join(f"`{s}`" for s in missing)
        )
        lines.append(
            "  > El flujo de actualización actual solo agrega scopes/app roles nuevos; "
            "no elimina de Graph los que falten en el request."
        )
    else:
        lines.append("- No hay scopes/app roles configurados hoy que falten en el request.")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate update inputs job")
    parser.add_argument(
        "--comment-output",
        default="./artifacts/validate_update_comment.md",
        help="Path to write the markdown comment body",
    )
    args = parser.parse_args()

    input_data = load_dispatch_input_from_env()
    input_dto = UpdateInputDTO.from_dict(input_data)
    creds = get_env_credentials(env=input_dto.env, tennant=input_dto.tennant)

    logging.info("[VALIDATE-UPDATE] TenantId: %s", creds.tenant_id)
    logging.info("[VALIDATE-UPDATE] ClientId: %s", creds.client_id)
    logging.info("[VALIDATE-UPDATE] ClientSecret (obfuscado): %s", get_obfuscated_secret(creds.client_secret))

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

    app = get_application_by_display_name(input_dto.application_name)
    if not app:
        comment = (
            f"### Validación de inputs (actualización) — `{input_dto.application_name}`\n\n"
            "No se encontró ninguna aplicación con ese `applicationName` en el tenant/ambiente indicado."
        )
        logging.info("[VALIDATE-UPDATE] Aplicacion no encontrada: %s", input_dto.application_name)
        write_comment(args.comment_output, comment)
        set_output("app_found", "false")
        return 0

    app_type = resolve_app_type(input_dto)
    current_scopes = extract_current_scopes(app, app_type)
    requested_scopes = unique_scopes(input_dto.scopes)
    added, missing = diff_scopes(current_scopes, requested_scopes)

    comment = format_update_validation_comment(
        application_name=input_dto.application_name,
        app_type=app_type,
        current_scopes=current_scopes,
        requested_scopes=requested_scopes,
        added=added,
        missing=missing,
    )

    logging.info("[VALIDATE-UPDATE] added=%s missing=%s", added, missing)
    write_comment(args.comment_output, comment)

    set_output("app_found", "true")
    set_output("scopes_added", ",".join(added))
    set_output("scopes_missing", ",".join(missing))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
