# Verificación

[pyproject.toml](../pyproject.toml) configura pytest bajo `tests/`, con patrón `test_*.py`, y Ruff con longitud 100 y target `py310`. La instalación del entorno está en [operaciones](operations.md).

## Documentación

Desde la raíz:

```sh
python3 -m pytest tests/integration/test_documentation.py tests/mcp/test_quality.py::test_quality_container_contract_is_documented -q
git diff --check
```

[test_documentation.py](../tests/integration/test_documentation.py) comprueba navegación activa, destinos locales, conservación de originales y recursos runtime, y retiro de rutas sin reemplazo. Comprueba estructura, no la exactitud de las afirmaciones: conteos, comandos o proveedores desactualizados no lo hacen fallar. Las páginas de auditorías fechadas (`docs/audit*/`) se registran como páginas activas; sus `anexos/` son papeles de trabajo sin comprobación de enlaces. El [contrato documental de calidad](../tests/mcp/test_quality.py) comprueba su referencia en el propietario canónico. El contrato del archivo histórico es preservación, no vigencia de sus afirmaciones ni de sus enlaces.

## Backend

```sh
python3 -m pytest tests/unit/test_config.py tests/unit/test_prompts.py tests/unit/test_stack_profiles.py tests/unit/test_apply_run_delivery.py tests/test_run_api.py -q
python3 -m engineering_team.cli --help
python3 -m engineering_team.cli run-project --help
```

Estos tests cubren configuración, prompts, perfiles, entrega y API con el alcance de sus fixtures; no certifican proveedores ni infraestructura en vivo. Elegir otros tests desde el [mapa](README.md).

La suite completa se invoca con `python3 -m pytest`. Algunos grupos requieren dependencias opcionales, herramientas, modelos o contenedores. Leer los fixtures del grupo antes de ejecutarlo. Los tests de [RAG](../tests/rag/) incluyen tokenización e indexación y pueden necesitar artefactos de modelos.

Los tests de valores por defecto leen el entorno: `Settings` carga variables con los nombres de sus campos en mayúsculas y un `.env` desde la raíz del repositorio. No hay `conftest.py` que los aísle. Para medir el código y no el shell, ejecutar la suite en un proceso sin esas variables —derivadas de `Settings.model_fields`, no escritas a mano— y con `DELIVERY_BACKEND=none` exportado después, sin modificar `.env`. En zsh, usar un script `bash`: zsh no separa palabras en `$VAR`.

Veintiséis tests de `tests/mcp`, `tests/integration` y `tests/e2e` necesitan un daemon Docker accesible y **fallan** sin él en lugar de omitirse; cinco de ellos son unitarios con mocks que igualmente consultan `docker version`. Un rojo limitado a esos tests sin daemon no indica un defecto, pero tampoco valida nada: registrar en el [estado](status.md) si el daemon estaba disponible. Los tests `tests/e2e/test_live_evaluation_evidence.py` y `tests/e2e/test_multimodel_evidence.py` leen JSON versionados en `evaluation/reports/curated/`; con `RUN_LIVE_MULTIMODEL=1` el segundo sobrescribe su fixture. Detalle y medición del 2026-09-17 en la [auditoría](audit160926/06-pruebas.md).

## Frontend

Tras instalar dependencias, ejecutar en `frontend/`:

```sh
npm test
npm run typecheck
npm run build
```

Los scripts están en [package.json](../frontend/package.json) y el entorno de pruebas en [Vite](../frontend/vite.config.ts). Un script declarado no equivale a una prueba aprobada.

## Registro de resultados

En [estado](status.md), indicar fecha, base de código, comando, resultado y límites. No copiar resultados a README o arquitectura. Marcar las integraciones no ejecutadas como no comprobadas aunque sus tests unitarios pasen.
