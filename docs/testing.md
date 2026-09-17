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

Los tests de valores por defecto leen el entorno: `Settings` carga variables con los nombres de sus campos en mayúsculas y un `.env` desde la raíz del repositorio. [tests/conftest.py](../tests/conftest.py) los aísla con un fixture `autouse` que corre antes de cada test: fija `Settings.model_config["env_file"]` en `None` —la línea que sostiene el mecanismo, porque `pydantic-settings` lee ese archivo sin pasar por `os.environ` y borrar variables no basta—, borra las variables derivadas de `Settings.model_fields` más `LANGFUSE_HOST` y `RUN_LIVE_MULTIMODEL`, y fija `DELIVERY_BACKEND=none`. No desactiva ningún código: un test que quiera una traza viva inyecta `client=` o construye `Settings(...)` con argumentos explícitos, que siempre ganan sobre el entorno y sobre `.env`.

Lo que el `conftest.py` **no** cubre sigue exigiendo un proceso limpio con `env -i`: `PYTHONPATH`, las variables de herramientas externas y cualquier lectura de `os.environ` que no pase por `Settings`. En zsh, usar un script `bash`: zsh no separa palabras en `$VAR`. Un efecto deliberado del aislamiento: bajo pytest, `RUN_LIVE_MULTIMODEL=1` ya no llega al cuerpo del test, así que `tests/e2e/test_multimodel_evidence.py` no reescribe su fixture; regenerar esa evidencia en vivo se hace fuera de pytest con [scripts/run_multimodel.py](../scripts/run_multimodel.py).

Trece tests de `tests/mcp`, `tests/integration` y `tests/e2e` necesitan un daemon Docker accesible; llevan la marca `needs_docker` de [tests/_docker.py](../tests/_docker.py) y se **omiten con su razón** en lugar de fallar cuando el daemon no responde, visible con `-rs`. El sondeo (`docker version`, con límite de 5 s) se evalúa una vez por proceso. Los tests unitarios con mocks ya no consultan el daemon: `_patch_executor` neutraliza `require_available`, una precondición que nunca quisieron tener. El tamaño de ese presupuesto está fijado en [test_docker_skip_budget.py](../tests/unit/test_docker_skip_budget.py): crecerlo o reducirlo obliga a cambiar la constante a propósito. Registrar en el [estado](status.md) si el daemon estaba disponible, porque una corrida verde con trece omisiones no ejercitó los contenedores. Los tests `tests/e2e/test_live_evaluation_evidence.py` y `tests/e2e/test_multimodel_evidence.py` leen JSON versionados en `evaluation/reports/curated/`. La medición previa al gate, del 2026-09-17, está en la [auditoría](audit160926/06-pruebas.md).

El criterio «suite sin Docker verde con omisiones explicadas» solo lo comprueba un comando que colecte `tests/mcp/`:

```sh
PYTHONPATH=src .venv/bin/python -m pytest tests -rs -p no:cacheprovider
```

El hook versionado [scripts/githooks/pre-commit](../scripts/githooks/pre-commit) es deliberadamente más angosto —para ser rápido no colecta `tests/mcp/` salvo `test_test_evidence.py`—, así que **estructuralmente no puede** comprobar ese criterio: es la regresión fijada, no el gate de Docker. Se instala una vez por clon, y lo ejecuta el operador:

```sh
git config core.hooksPath scripts/githooks
```

`core.hooksPath` apunta al directorio versionado, de modo que una edición futura del hook llega sin copiar nada a `.git/hooks/`. Es configuración local del clon: no afecta a otros repositorios.

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
