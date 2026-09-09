# Verificación

[pyproject.toml](../pyproject.toml) configura pytest bajo `tests/`, con patrón `test_*.py`, y Ruff con longitud 100 y target `py310`. La instalación del entorno está en [operaciones](operations.md).

## Documentación

Desde la raíz:

```sh
python3 -m pytest tests/integration/test_documentation.py tests/mcp/test_quality.py::test_quality_container_contract_is_documented -q
git diff --check
```

[test_documentation.py](../tests/integration/test_documentation.py) comprueba navegación activa, destinos locales, conservación de originales y recursos runtime, y retiro de rutas sin reemplazo. El [contrato documental de calidad](../tests/mcp/test_quality.py) comprueba su referencia en el propietario canónico. El contrato del archivo histórico es preservación, no vigencia de sus afirmaciones ni de sus enlaces.

## Backend

```sh
python3 -m pytest tests/unit/test_config.py tests/unit/test_prompts.py tests/unit/test_stack_profiles.py tests/unit/test_apply_run_delivery.py tests/test_run_api.py -q
python3 -m engineering_team.cli --help
python3 -m engineering_team.cli run-project --help
```

Estos tests cubren configuración, prompts, perfiles, entrega y API con el alcance de sus fixtures; no certifican proveedores ni infraestructura en vivo. Elegir otros tests desde el [mapa](README.md).

La suite completa se invoca con `python3 -m pytest`. Algunos grupos requieren dependencias opcionales, herramientas, modelos o contenedores. Leer los fixtures del grupo antes de ejecutarlo. Los tests de [RAG](../tests/rag/) incluyen tokenización e indexación y pueden necesitar artefactos de modelos.

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
