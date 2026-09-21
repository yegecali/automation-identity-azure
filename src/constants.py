from __future__ import annotations

MICROSOFT_GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
CC_GRAPH_DELEGATED_PERMISSIONS = ["openid", "offline_access"]
AC_GRAPH_DELEGATED_PERMISSIONS = ["openid", "offline_access", "User.Read.All"]

# Permisos de Graph que, aunque figuren en las listas de arriba, se deben
# declarar y consentir como Application (Role) en vez de Delegated (Scope) —
# User.Read.All existe en Graph como ambos tipos, y para este flujo el rol de
# aplicacion es el que corresponde.
GRAPH_APPLICATION_PERMISSIONS = {"User.Read.All"}
