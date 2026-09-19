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


def get_env_credentials(env: str, tennant: str = "persona") -> CredentialsDTO:
    """Obtiene credenciales por ambiente desde variables de entorno.

    Efecto en tenant:
    - Ninguno. Solo resuelve credenciales para autenticacion posterior.

    Pasos funcionales:
    1. Valida ambiente permitido.
     3. Resuelve aliases por `tennant`:
         - persona: `B2CC_<ENV>_*`
         - pyme: `B2CC_<ENV>_PYME_*`
    4. Verifica que no falte ninguna variable.
    """
    safe_env = _safe_value(env).lower()
    if safe_env not in VALID_ENVS:
        raise RuntimeError("El campo env debe ser uno de: dev, cer, pro.")

    safe_tennant = _safe_value(tennant).lower()
    if safe_tennant not in VALID_TENNANTS:
        raise RuntimeError("El campo tennant debe ser 'persona' o 'pyme'.")

    env_alias = safe_env.upper()
    suffix = "" if safe_tennant == "persona" else "_PYME"
    tenant_var = f"B2CC_{env_alias}{suffix}_TENANT_ID"
    client_var = f"B2CC_{env_alias}{suffix}_CLIENT_ID"
    secret_var = f"B2CC_{env_alias}{suffix}_CLIENT_SECRET"

    tenant_id = _safe_value(os.getenv(tenant_var))
    client_id = _safe_value(os.getenv(client_var))
    client_secret = _safe_value(os.getenv(secret_var))

    missing = []
    if not tenant_id:
        missing.append(tenant_var)
    if not client_id:
        missing.append(client_var)
    if not client_secret:
        missing.append(secret_var)

    if missing:
        raise RuntimeError(
            "Faltan variables de entorno para el ambiente "
            f"'{safe_env}': {', '.join(missing)}"
        )

    return CredentialsDTO(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
