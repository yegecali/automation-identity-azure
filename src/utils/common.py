from __future__ import annotations

import json
import os
from typing import Any


def get_obfuscated_secret(value: str) -> str:
    """Ofusca secretos para logging seguro.

    Efecto en tenant:
    - Ninguno. Solo formato de salida local.

    Pasos funcionales:
    1. Mantiene primeros y ultimos caracteres.
    2. Reemplaza segmento central por asteriscos.
    """
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}{'*' * (len(value) - 6)}{value[-3:]}"


def normalize_token(value: str) -> str:
    """Normaliza un token textual para nombres tecnicos.

    Efecto en tenant:
    - Ninguno.

    Pasos funcionales:
    1. Quita espacios extra.
    2. Reemplaza separadores por guion.
    3. Convierte a minusculas.
    """
    return "-".join(value.strip().replace("_", " ").split()).lower()


def build_app_display_name(name: str, channel: str, app_type: str) -> str:
    """Construye displayName estandar de App Registration B2CC.

    Efecto en tenant:
    - Indirecto. Define nombre con el que se creara/buscara la app.

    Pasos funcionales:
    1. Normaliza nombre, canal y tipo.
    2. Aplica patron `b2c-{channel}-{name}-{type}-client-id`.
    """
    safe_name = normalize_token(name)
    safe_channel = normalize_token(channel)
    safe_type = normalize_token(app_type)
    return f"b2c-{safe_channel}-{safe_name}-{safe_type}-client-id"


def unique_scopes(values: list[str]) -> list[str]:
    """Limpia y deduplica lista de scopes.

    Efecto en tenant:
    - Indirecto. Evita enviar scopes vacios o duplicados a Graph.

    Pasos funcionales:
    1. Recorta espacios y descarta vacios.
    2. Elimina duplicados.
    3. Ordena resultado.
    """
    cleaned = []
    for value in values:
        item = str(value).strip()
        if item:
            cleaned.append(item)
    return sorted(set(cleaned))


def escape_odata(value: str) -> str:
    """Escapa comillas simples para filtros OData.

    Efecto en tenant:
    - Ninguno.

    Pasos funcionales:
    1. Duplica `'` segun reglas OData.
    """
    return value.replace("'", "''")


def load_json_file(path: str) -> dict[str, Any]:
    """Carga un archivo JSON validando estructura de objeto.

    Efecto en tenant:
    - Ninguno. Operacion local de archivos.

    Pasos funcionales:
    1. Verifica path.
    2. Lee y parsea JSON.
    3. Valida tipo dict.
    """
    if not path:
        raise RuntimeError("Debes especificar la ruta del archivo JSON.")

    if not os.path.exists(path):
        raise RuntimeError(f"No existe el archivo: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise RuntimeError(f"El archivo {path} debe contener un objeto JSON.")

    return data


DISPATCH_INPUT_ENV_KEYS = {
    "operation": "B2CC_INPUT_OPERATION",
    "channel": "B2CC_INPUT_CHANNEL",
    "env": "B2CC_INPUT_ENV",
    "tennant": "B2CC_INPUT_TENNANT",
    "type": "B2CC_INPUT_TYPE",
    "name": "B2CC_INPUT_NAME",
    "applicationName": "B2CC_INPUT_APPLICATION_NAME",
    "webRedirectUri": "B2CC_INPUT_WEB_REDIRECT_URI",
    "scopes": "B2CC_INPUT_SCOPES",
}


def load_dispatch_input_from_env() -> dict[str, Any]:
    """Arma el dict de input del dispatch leyendo variables de entorno B2CC_INPUT_*.

    Reemplaza el patron anterior de escribir un JSON a disco y volver a leerlo:
    el job de GitHub Actions ya expone estos valores como variables de entorno
    (definidas en el `env:` del job, sin interpolarlas dentro de un script), asi
    que no hace falta el archivo intermedio.

    Efecto en tenant:
    - Ninguno. Solo lee variables de entorno del proceso actual.

    Pasos funcionales:
    1. Recorre las claves esperadas por CreateInputDTO/UpdateInputDTO.
    2. Por cada una, lee la variable B2CC_INPUT_* correspondiente si esta definida.
    3. Omite las no definidas (para no pisar defaults/opcionales de los DTOs).
    """
    data: dict[str, Any] = {}
    for field_name, env_name in DISPATCH_INPUT_ENV_KEYS.items():
        raw_value = os.getenv(env_name)
        if raw_value is not None:
            data[field_name] = raw_value
    return data


def dedupe_resource_access(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplica elementos resourceAccess por combinacion id|type.

    Efecto en tenant:
    - Indirecto. Evita PATCH con permisos repetidos.

    Pasos funcionales:
    1. Filtra entradas incompletas.
    2. Usa llave `id|type` para deduplicar.
    3. Devuelve lista normalizada.
    """
    deduped: dict[str, dict[str, Any]] = {}
    for item in values:
        item_id = item.get("id")
        item_type = item.get("type")
        if not item_id or not item_type:
            continue
        deduped[f"{item_id}|{item_type}"] = {"id": item_id, "type": item_type}
    return list(deduped.values())
