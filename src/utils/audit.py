from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any


def append_audit_event(
    *,
    operation: str,
    tennant: str | None = None,
    client_id: str,
    app_type: str | None = None,
    scopes: list[str] | None = None,
    client_secret_obfuscated: str | None = None,
    created_at: str | None = None,
    file_path: str | None = None,
) -> None:
    """Guarda un evento de auditoria en formato JSONL para su envio a Table Storage."""
    output_file = file_path or os.getenv("B2CC_AUDIT_FILE", "./b2cc_audit_events.jsonl")
    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    event = {
        "operation": str(operation or "").strip().lower(),
        "tennant": str(tennant or "").strip().lower(),
        "clientId": str(client_id or "").strip(),
        "type": str(app_type or "").strip().lower(),
        "scopes": ",".join([str(item).strip() for item in (scopes or []) if str(item).strip()]),
        "clientSecretObfuscated": str(client_secret_obfuscated or "").strip(),
        "createdAt": created_at or dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }

    with open(output_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=True) + "\n")
