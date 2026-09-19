# automation-azure-b2c

Automatiza la creación y actualización de App Registrations de Azure AD B2C (flujos
Authorization Code y Client Credentials) vía Microsoft Graph, disparado por un workflow
de GitHub Actions (`workflow_dispatch`) que abre/comenta/cierra un issue de seguimiento
y audita cada corrida en Azure Table Storage.

## Estructura

```
.github/workflows/automation.yml   Workflow de GitHub Actions (dispatch manual)
src/
  constants.py                     IDs y permisos fijos de Microsoft Graph
  configure.py                     Lógica de configuración (scopes, app roles, redirect/API URI) para el flujo update
  create_app_registration_job.py   Job: crea o reutiliza la App Registration (operación create)
  validate_service_principal_job.py    Job: crea/valida el Service Principal de la app
  verify_service_principal_propagation_job.py  Job: espera propagación del SP en el directorio
  delegate_graph_permissions_job.py    Job: delega permisos delegados de Microsoft Graph (openid/offline_access/...)
  create_cc_client_secret_job.py   Job: genera client secret (solo flujo CC)
  update_search_application_job.py     Job: localiza la app a actualizar
  update_configure_redirect_uri_job.py Job: configura redirect URI (web/spa)
  update_add_application_id_uri_job.py Job: configura Application ID URI
  update_add_scopes_job.py         Job: agrega/actualiza scopes delegados (flujo AC)
  update_add_app_roles_job.py      Job: agrega/actualiza app roles (flujo CC)
  persist_table_storage.py         Job: persiste el JSONL de auditoría en Azure Table Storage
  models/dto.py                    DTOs de input/runtime (CreateInputDTO, UpdateInputDTO, ...)
  services/graph_service.py        Cliente Azure CLI + Microsoft Graph (auth, GET/POST/PATCH, retries)
  utils/common.py                  Helpers puros (nombres, dedupe, ofuscación de secretos, carga de JSON)
  utils/runtime_config.py          Resuelve credenciales por ambiente/tenant desde variables de entorno
  utils/audit.py                   Helper para anexar eventos de auditoría en JSONL (ver nota abajo)
```

Cada job se invoca como script independiente (`python ./src/<job>.py --input ...`);
todos insertan su propio directorio (`src/`) en `sys.path`, por lo que `configure.py`,
`constants.py` y los paquetes `models/`, `services/`, `utils/` deben permanecer junto a
ellos.

## Variables de entorno esperadas (por ambiente/tenant)

Para `env` en `{dev, cer, pro}` y `tennant` en `{persona, pyme}`:

```
B2CC_<ENV>_TENANT_ID / B2CC_<ENV>_CLIENT_ID / B2CC_<ENV>_CLIENT_SECRET           (persona)
B2CC_<ENV>_PYME_TENANT_ID / B2CC_<ENV>_PYME_CLIENT_ID / B2CC_<ENV>_PYME_CLIENT_SECRET  (pyme)
```

Además, para la auditoría: `AZURE_TABLE_STORAGE_CONNECTION_STRING` (SAS) y
`AZURE_TABLE_STORAGE_TABLE_NAME`.

## Dependencias

Solo `persist_table_storage.py` requiere una dependencia externa:
`pip install -r requirements.txt` (azure-data-tables). El resto usa únicamente stdlib
+ Azure CLI (`az`) instalado en el runner.
