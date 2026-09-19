from __future__ import annotations

import os

from models.dto import CredentialsDTO

VALID_ENVS = ("dev", "cer", "pro")
VALID_TENNANTS = ("persona", "pyme")


def _safe_value(value: str | None) -> str:
    """Normaliza valores de entorno eliminando nulos y espacios.

    Efecto en tenant:
    - Ninguno.

    Pasos funcionales:
    1. Convierte None a string vacio.
    2. Aplica strip.
    """
    return str(value or "").strip()


TENANT_ID_VAR = "B2CC_TENANT_ID"
CLIENT_ID_VAR = "B2CC_CLIENT_ID"
CLIENT_SECRET_VAR = "B2CC_CLIENT_SECRET"


def get_env_credentials(env: str, tennant: str = "persona") -> CredentialsDTO:
    """Obtiene credenciales desde el GitHub Environment activo (env+tennant).

    El job de GitHub Actions que invoca este script ya selecciono el
    GitHub Environment correspondiente (`environment: <env>-<tennant>`, ej.
    'dev-persona' o 'cer-pyme'), asi que las tres variables ya apuntan a las
    credenciales correctas sin necesidad de armar un nombre distinto por cada
    combinacion de ambiente/tennant.

    Efecto en tenant:
    - Ninguno. Solo resuelve credenciales para autenticacion posterior.

    Pasos funcionales:
    1. Valida que env/tennant sean valores permitidos (evita autenticar con el
       Environment equivocado por un typo silencioso).
    2. Lee B2CC_TENANT_ID / B2CC_CLIENT_ID / B2CC_CLIENT_SECRET.
    3. Verifica que no falte ninguna.
    """
    safe_env = _safe_value(env).lower()
    if safe_env not in VALID_ENVS:
        raise RuntimeError("El campo env debe ser uno de: dev, cer, pro.")

    safe_tennant = _safe_value(tennant).lower()
    if safe_tennant not in VALID_TENNANTS:
        raise RuntimeError("El campo tennant debe ser 'persona' o 'pyme'.")

    tenant_id = _safe_value(os.getenv(TENANT_ID_VAR))
    client_id = _safe_value(os.getenv(CLIENT_ID_VAR))
    client_secret = _safe_value(os.getenv(CLIENT_SECRET_VAR))

    missing = []
    if not tenant_id:
        missing.append(TENANT_ID_VAR)
    if not client_id:
        missing.append(CLIENT_ID_VAR)
    if not client_secret:
        missing.append(CLIENT_SECRET_VAR)

    if missing:
        raise RuntimeError(
            f"Faltan variables de entorno para el GitHub Environment '{safe_env}-{safe_tennant}': "
            + ", ".join(missing)
        )

    return CredentialsDTO(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
