from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
import uuid

VALID_ENVS = {"dev", "cer", "pro"}
VALID_TYPES = {"ac", "cc"}
VALID_TENNANTS = {"persona", "pyme"}


@dataclass(frozen=True)
class CredentialsDTO:
    """Representa credenciales de autenticacion para un ambiente.

    Efecto en tenant:
    - Ninguno. Solo encapsula datos de acceso para operaciones posteriores.

    Pasos funcionales:
    1. Transporta tenant id, client id y client secret.
    2. Evita manejo de diccionarios sueltos entre metodos.
    """

    tenant_id: str
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class CreateInputDTO:
    """Representa el payload de input para operacion create."""

    operation: str
    name: str
    tennant: str
    env: str
    channel: str
    app_type: str
    use_interactive_az_login: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CreateInputDTO":
        operation = str(data.get("operation", "")).strip().lower()
        name = str(data.get("name", "")).strip()
        tennant = str(data.get("tennant") or data.get("tenant") or "").strip().lower()
        env = str(data.get("env", "")).strip().lower()
        channel = str(data.get("channel", "")).strip()
        app_type = str(data.get("type", "")).strip().lower()
        use_interactive = bool(data.get("useInteractiveAzLogin", False))

        missing = []
        if not operation:
            missing.append("operation")
        if not name:
            missing.append("name")
        if not tennant:
            missing.append("tennant")
        if not env:
            missing.append("env")
        if not channel:
            missing.append("channel")
        if not app_type:
            missing.append("type")
        if missing:
            raise RuntimeError(f"Faltan campos obligatorios en input.json: {', '.join(missing)}")

        if operation != "create":
            raise RuntimeError("operation para CreateInputDTO debe ser 'create'.")
        if tennant not in VALID_TENNANTS:
            raise RuntimeError("El campo tennant en input.json debe ser 'persona' o 'pyme'.")
        if env not in VALID_ENVS:
            raise RuntimeError("El campo env debe ser uno de: dev, cer, pro.")
        if app_type not in VALID_TYPES:
            raise RuntimeError("El campo type en input.json debe ser 'cc' o 'ac'.")

        return cls(
            operation=operation,
            name=name,
            tennant=tennant,
            env=env,
            channel=channel,
            app_type=app_type,
            use_interactive_az_login=use_interactive,
        )


@dataclass(frozen=True)
class UpdateInputDTO:
    """Representa el payload de input para operacion update."""

    operation: str
    tennant: str
    env: str
    application_name: str
    scopes: list[str]
    app_type: str | None
    web_redirect_uri: str | None
    use_interactive_az_login: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateInputDTO":
        operation = str(data.get("operation", "")).strip().lower()
        tennant = str(data.get("tennant") or data.get("tenant") or "").strip().lower()
        env = str(data.get("env", "")).strip().lower()
        app_name = str(data.get("applicationName") or data.get("name") or "").strip()
        raw_scopes = data.get("scopes")
        app_type_raw = str(data.get("type", "")).strip().lower()
        redirect_uri = str(data.get("webRedirectUri") or data.get("web_redirect_uri") or "").strip() or None
        use_interactive = bool(data.get("useInteractiveAzLogin", False))

        if operation != "update":
            raise RuntimeError("operation para UpdateInputDTO debe ser 'update'.")
        if tennant not in VALID_TENNANTS:
            raise RuntimeError("El campo tennant en input.json debe ser 'persona' o 'pyme'.")
        if env not in VALID_ENVS:
            raise RuntimeError("El campo env en input.json debe ser uno de: dev, cer, pro.")
        if not app_name:
            raise RuntimeError("Debes enviar applicationName o name en input.json con el nombre completo de la app.")

        normalized_scopes: list[str]
        if isinstance(raw_scopes, list):
            normalized_scopes = []
            for item in raw_scopes:
                # Support values separated by comma/newline inside each list item.
                raw_item = str(item).replace("\\n", "\n")
                normalized_scopes.extend(
                    [token.strip() for token in re.split(r"[\n\r,]+", raw_item) if token.strip()]
                )
        elif isinstance(raw_scopes, str):
            normalized_scopes = [
                token.strip()
                for token in re.split(r"[\n\r,]+", raw_scopes.replace("\\n", "\n"))
                if token.strip()
            ]
        else:
            raise RuntimeError("El campo scopes en input.json debe ser una lista o string separado por comas o saltos de linea.")

        scopes = sorted(set(normalized_scopes))
        if not scopes:
            raise RuntimeError("Debes enviar al menos un scope en input.json -> scopes.")

        app_type = app_type_raw or None
        if app_type and app_type not in VALID_TYPES:
            raise RuntimeError("El campo type en input.json debe ser 'cc' o 'ac'.")

        return cls(
            operation=operation,
            tennant=tennant,
            env=env,
            application_name=app_name,
            scopes=scopes,
            app_type=app_type,
            web_redirect_uri=redirect_uri,
            use_interactive_az_login=use_interactive,
        )


@dataclass(frozen=True)
class CreateRuntimeDTO:
    """Representa valores de runtime para flujo create."""

    env: str
    credentials: CredentialsDTO
    app_display_name: str
    app_type: str
    graph_permissions: list[str]


@dataclass(frozen=True)
class UpdateRuntimeDTO:
    """Representa valores de runtime para flujo update."""

    env: str
    app_type: str
    credentials: CredentialsDTO
    application_name: str
    redirect_uri: str
    scopes: list[str]
    use_interactive_az_login: bool


@dataclass(frozen=True)
class AppRoleDTO:
    """Representa un app role del manifest para Microsoft Graph."""

    id: str
    allowed_member_types: list[str]
    description: str
    display_name: str
    is_enabled: bool
    value: str

    @classmethod
    def from_role_value(cls, role_value: str) -> "AppRoleDTO":
        clean_value = str(role_value).strip()
        if not clean_value:
            raise RuntimeError("El valor del app role no puede ser vacio.")

        return cls(
            id=str(uuid.uuid4()),
            allowed_member_types=["Application"],
            description=clean_value,
            display_name=clean_value,
            is_enabled=True,
            value=clean_value,
        )

    def to_graph_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "allowedMemberTypes": self.allowed_member_types,
            "description": self.description,
            "displayName": self.display_name,
            "isEnabled": self.is_enabled,
            "value": self.value,
        }


@dataclass(frozen=True)
class ScopeDTO:
    """Representa un oauth2PermissionScope del manifest para Microsoft Graph."""

    id: str
    value: str
    scope_type: str
    is_enabled: bool
    admin_consent_display_name: str
    admin_consent_description: str
    user_consent_display_name: str
    user_consent_description: str

    @classmethod
    def from_scope_name(cls, scope_name: str) -> "ScopeDTO":
        clean_scope = str(scope_name).strip()
        if not clean_scope:
            raise RuntimeError("El valor del scope no puede ser vacio.")

        return cls(
            id=str(uuid.uuid4()),
            value=clean_scope,
            scope_type="Admin",
            is_enabled=True,
            admin_consent_display_name=clean_scope,
            admin_consent_description=clean_scope,
            user_consent_display_name=clean_scope,
            user_consent_description=clean_scope,
        )

    def to_graph_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "value": self.value,
            "type": self.scope_type,
            "isEnabled": self.is_enabled,
            "adminConsentDisplayName": self.admin_consent_display_name,
            "adminConsentDescription": self.admin_consent_description,
            "userConsentDisplayName": self.user_consent_display_name,
            "userConsentDescription": self.user_consent_description,
        }
