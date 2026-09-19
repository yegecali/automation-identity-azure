#!/usr/bin/env python3
"""Create a B2C app registration using Azure CLI + Microsoft Graph."""

from __future__ import annotations

import argparse
import datetime as dt
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

from services.graph_service import (
    create_application,
    get_application_by_display_name,
    get_application_with_fallback_by_app_id,
    run_az,
)
from constants import AC_GRAPH_DELEGATED_PERMISSIONS, CC_GRAPH_DELEGATED_PERMISSIONS
from models.dto import CreateInputDTO, CreateRuntimeDTO
from utils.common import (
    build_app_display_name,
    get_obfuscated_secret,
    load_dispatch_input_from_env,
)
from utils.runtime_config import get_env_credentials

VALID_ENVS = {"dev", "cer", "pro"}


def set_output(name: str, value: str) -> None:
    github_output = os.getenv("GITHUB_OUTPUT", "").strip()
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def resolve_runtime_values(input_dto: CreateInputDTO) -> CreateRuntimeDTO:
    """Resuelve y valida valores de ejecucion para create.

    Efecto en tenant:
    - Ninguno. Solo validacion y preparacion de datos.

    Pasos funcionales:
    1. Valida campos requeridos del input.
    2. Lee credenciales por ambiente desde variables.
    3. Determina tipo de flujo y permisos default de Graph.
    4. Construye nombre de aplicacion final.
    """
    env_config = get_env_credentials(input_dto.env, input_dto.tennant)

    app_type = input_dto.app_type

    graph_permissions = CC_GRAPH_DELEGATED_PERMISSIONS if app_type == "cc" else AC_GRAPH_DELEGATED_PERMISSIONS

    app_display_name = build_app_display_name(
        name=input_dto.name,
        channel=input_dto.channel,
        app_type=input_dto.app_type,
    )

    return CreateRuntimeDTO(
        env=input_dto.env,
        credentials=env_config,
        app_display_name=app_display_name,
        app_type=app_type,
        graph_permissions=graph_permissions,
    )


def get_created_app_with_retry(object_id: str, app_id: str, max_attempts: int = 6, delay_seconds: int = 3) -> dict[str, Any]:
    """Obtiene app creada con fallback por appId para cubrir propagacion.

    Efecto en tenant:
    - Solo lectura de la aplicacion.

    Pasos funcionales:
    1. Intenta leer por object id.
    2. Si no aparece, usa fallback por appId.
    """
    return get_application_with_fallback_by_app_id(
        app_object_id=object_id,
        app_id=app_id,
        max_attempts=max_attempts,
        delay_seconds=delay_seconds,
    )


def build_parser() -> argparse.ArgumentParser:
    """Construye parser CLI para flujo de creacion.

    Efecto en tenant:
    - Ninguno.

    Pasos funcionales:
    1. Define flag opcional para login interactivo.
    """
    parser = argparse.ArgumentParser(
        description="Create an App Registration equivalent to Create-B2CCAppRegistration.ps1"
    )
    parser.add_argument(
        "--use-interactive-az-login",
        action="store_true",
        help="Also run interactive az login after service principal login",
    )
    return parser


def run_create_from_input(*, use_interactive_az_login: bool = False) -> int:
    """Ejecuta la creacion/base de App Registration para el flujo create.

    Efecto en tenant:
    - Crea o reutiliza App Registration.

    Pasos funcionales:
    1. Lee el input del dispatch desde variables de entorno (B2CC_INPUT_*).
    2. Autentica con service principal.
    3. Crea o reutiliza la app destino.
    4. Valida lectura de la app creada/reutilizada.
    5. Exporta contexto para jobs posteriores via GITHUB_OUTPUT.
    """
    input_data = load_dispatch_input_from_env()
    input_dto = CreateInputDTO.from_dict(input_data)
    runtime = resolve_runtime_values(input_dto)

    tenant_id = runtime.credentials.tenant_id
    client_id = runtime.credentials.client_id
    client_secret = runtime.credentials.client_secret
    app_display_name = runtime.app_display_name
    app_type = runtime.app_type

    script_start = dt.datetime.now()
    logging.info("[INIT] Inicio de ejecucion: %s", f"{script_start:%Y-%m-%d %H:%M:%S}")
    logging.info("[INIT] Script: Create-B2CCAppRegistration.py")
    logging.info("[INIT] Ambiente objetivo: %s", runtime.env)
    logging.info("[INIT] Tenant objetivo: %s", tenant_id)
    logging.info("[INIT] Tipo de flujo: %s", app_type)
    logging.info("[INIT] Nombre de aplicacion generado: %s", app_display_name)

    logging.info("[1/4] Conectando con Service Principal...")
    obfuscated_secret = get_obfuscated_secret(client_secret)
    logging.info("      [AUTH] TenantId: %s", tenant_id)
    logging.info("      [AUTH] ClientId: %s", client_id)
    logging.info("      [AUTH] ClientSecret (obfuscado): %s", obfuscated_secret)
    logging.info("      [AUTH] Ejecutando az login --service-principal --allow-no-subscriptions")

    run_az(
        [
            "login",
            "--service-principal",
            "--username",
            client_id,
            "--password",
            client_secret,
            "--tenant",
            tenant_id,
            "--allow-no-subscriptions",
            "--output",
            "none",
        ]
    )
    logging.info("      [AUTH] az login service principal OK")

    if use_interactive_az_login:
        logging.info("      [AUTH] Ejecutando az login interactivo...")
        run_az(
            [
                "login",
                "--tenant",
                tenant_id,
                "--allow-no-subscriptions",
                "--output",
                "none",
            ]
        )
        logging.info("      [AUTH] az login interactivo OK")

    logging.info("[2/5] Validando si la App Registration ya existe...")
    logging.info("      Name: %s", app_display_name)

    existing_app = get_application_by_display_name(app_display_name)
    if existing_app:
        new_app_id = existing_app.get("appId")
        new_object_id = existing_app.get("id")
        if not new_app_id or not new_object_id:
            raise RuntimeError("La App Registration existente no tiene appId/id validos.")

        logging.info("      [APP] La App Registration ya existe. Se omite la creacion.")
    else:
        logging.info("      [APP] No existe. Creando App Registration...")
        logging.info("      SignInAudience: AzureADMyOrg (single tenant)")
        logging.info("      [APP] Enviando payload de creacion a Microsoft Graph...")

        new_app = create_application(app_display_name)

        new_app_id = new_app.get("appId")
        new_object_id = new_app.get("id")
        if not new_app_id or not new_object_id:
            raise RuntimeError("Microsoft Graph response did not include appId/id for the created application.")

        logging.info("      [APP] Payload procesado por Graph.")

    logging.info("[3/5] App Registration lista para continuar.")
    logging.info("      Application (client) ID: %s", new_app_id)
    logging.info("      Application Object ID:  %s", new_object_id)
    logging.info("      [APP] Confirmando lectura de la app recien creada...")

    created_app = get_created_app_with_retry(new_object_id, new_app_id)

    if not created_app:
        raise RuntimeError("No se pudo validar la App Registration recien creada.")

    # Usa el Object ID visible mas reciente (fallback por appId) para evitar 404 por propagacion.
    current_app_object_id = str(created_app.get("id") or new_object_id)

    logging.info("      [APP] Validacion OK -> DisplayName: %s", created_app.get("displayName", ""))

    logging.info("[4/4] Creacion base completada. Jobs siguientes manejan SP/permisos/secret/auditoria.")

    script_end = dt.datetime.now()
    elapsed = script_end - script_start

    logging.info("[RESUMEN] Finalizado.")
    logging.info("      [RESUMEN] Inicio: %s", f"{script_start:%Y-%m-%d %H:%M:%S}")
    logging.info("      [RESUMEN] Fin:    %s", f"{script_end:%Y-%m-%d %H:%M:%S}")
    logging.info("      [RESUMEN] Duracion: %s", elapsed)
    logging.info("      [RESUMEN] AppId creada: %s", new_app_id)
    logging.info("      [RESUMEN] ObjectId creado: %s", new_object_id)

    set_output("app_id", str(new_app_id))
    set_output("app_object_id", str(current_app_object_id))
    set_output("app_display_name", app_display_name)
    set_output("app_type", app_type)

    return 0


def main() -> int:
    """Entrada CLI para create; delega en run_create_from_input."""
    args = build_parser().parse_args()
    return run_create_from_input(use_interactive_az_login=args.use_interactive_az_login)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logging.error("[ERROR] %s", exc)
        raise SystemExit(1)
