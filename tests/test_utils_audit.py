from __future__ import annotations

import json

from utils.audit import append_audit_event


class TestAppendAuditEvent:
    def test_writes_expected_jsonl_line(self, tmp_path):
        target = tmp_path / "nested" / "audit.jsonl"

        append_audit_event(
            operation="create",
            tennant="persona",
            client_id="app-id-123",
            app_type="cc",
            scopes=["scope.b", "scope.a", " "],
            client_secret_obfuscated="abc***xyz",
            created_at="2026-01-01T00:00:00Z",
            file_path=str(target),
        )

        assert target.exists()
        lines = target.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

        event = json.loads(lines[0])
        assert event == {
            "operation": "create",
            "tennant": "persona",
            "clientId": "app-id-123",
            "type": "cc",
            "scopes": "scope.b,scope.a",
            "clientSecretObfuscated": "abc***xyz",
            "createdAt": "2026-01-01T00:00:00Z",
        }

    def test_appends_without_overwriting_previous_events(self, tmp_path):
        target = tmp_path / "audit.jsonl"

        append_audit_event(operation="create", client_id="app-1", file_path=str(target))
        append_audit_event(operation="update", client_id="app-2", file_path=str(target))

        lines = target.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["clientId"] == "app-1"
        assert json.loads(lines[1])["clientId"] == "app-2"

    def test_defaults_created_at_when_not_provided(self, tmp_path):
        target = tmp_path / "audit.jsonl"

        append_audit_event(operation="create", client_id="app-1", file_path=str(target))

        event = json.loads(target.read_text(encoding="utf-8").strip())
        assert event["createdAt"].endswith("Z")
