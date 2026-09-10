# Operación

Ejecutar desde la raíz, salvo donde se indique otra carpeta. El [estado](status.md) identifica qué se comprobó en esta revisión.

## Entorno Python

[pyproject.toml](../pyproject.toml) declara Python `>=3.10`, dependencias, extras y el comando `engineering-team`. Para desarrollo con RAG y FastAPI:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,rag,sample-app]'
.venv/bin/python -m engineering_team.cli --help
```

La instalación descarga dependencias. Activar después el entorno con `. .venv/bin/activate` para que los comandos `python3` siguientes usen sus dependencias. El extra `observability` se declara aparte en el mismo manifest. Ver [testing](testing.md) para requisitos de pruebas.

## Configuración y modelos

La fuente de valores, aliases y validaciones es [Settings](../src/engineering_team/config.py). Usa variables de entorno y un `.env` localizado desde el archivo de implementación. No copiar secretos a documentación o reportes.

Los defaults de clase son `local_first=True` y `cloud_enabled=False`. [execute_on_project](../src/engineering_team/apply_run.py) selecciona el orden de runtimes según esos ajustes. `LOCAL_FIRST=false` y `CLOUD_ENABLED=true` seleccionan cloud primero; la prioridad no garantiza que todas las rutas de fallback excluyan modelos locales. Proveedores y cadenas se implementan en [llm](../src/engineering_team/llm/) y deben revisarse antes de ejecutar con modelos.

Consultar ayuda no lanza un run ni requiere instalar modelos. Las ejecuciones reales pueden consumir recursos de los proveedores configurados.

## CLI sobre proyectos

La firma y opciones exactas están en [cli.py](../src/engineering_team/cli.py):

```sh
python3 -m engineering_team.cli --help
python3 -m engineering_team.cli run-project --help
```

`run-project` recibe una ruta y `--spec`; admite `--test-spec`. `--authorize-writes` habilita escritura en el proyecto y es falso por defecto. La entrega requiere otra opción, `--confirm-delivery`, el backend `gh` y las condiciones de [apply_run.py](../src/engineering_team/apply_run.py). Sin autorización de escritura no significa sin coste ni sin reportes.

`reset-project` es destructivo sobre el repositorio de destino; revisar [reset_project.py](../src/engineering_team/reset_project.py) antes de usarlo. No se usa para preparar documentación.

## Calidad y servicios

`QUALITY_RUNNER=container` es el único valor admitido y el default de clase: [QualityMCP](../src/engineering_team/mcp/quality.py) rechaza por nombre cualquier otro desde que el sandbox de proceso se retiró ([decisión 15](architecture/decisions/0015-container-only.md)). Docker pasa a ser requisito para correr el gate. Los campos `quality_stack`, `quality_component_path`, `quality_test_filter` y `quality_timeout_seconds` están en [Settings](../src/engineering_team/config.py). La selección efectiva pasa por [apply_run.py](../src/engineering_team/apply_run.py).

Consultar [perfiles](../src/engineering_team/stacks.py) para comandos e imágenes y [servicios](../src/engineering_team/services.py) para infraestructura y preparación. No asumir que iniciar un servicio equivale a tener listo su esquema o sus datos.

## API y frontend

Con las dependencias de `sample-app` instaladas, la app que monta los routers de runs se inicia con:

```sh
python3 -m uvicorn app.main:app --app-dir demo-projects/sample_app --host 127.0.0.1 --port 8000
```

En `frontend/`, usar los scripts de [package.json](../frontend/package.json):

```sh
npm ci
npm run dev
```

[Vite](../frontend/vite.config.ts) reenvía `/api` y `/ws` al backend local en el puerto 8000. Las rutas reales están en [run_api.py](../src/engineering_team/run_api.py) y [project_api.py](../src/engineering_team/project_api.py). La app incluye también endpoints del ejemplo bancario.

## Benchmarks

[run_trial.py](../evaluation/benchmarks/multistack/run_trial.py) carga `ingresos`, `interview` y `northgate` desde Markdown contiguo. Son entradas ejecutables del benchmark y conservan su ubicación. La migración documental no ejecuta trials.

La demo bancaria de evaluación vive en [demo-projects/sample_app](../demo-projects/sample_app/). El runtime la copia a un workspace aislado para los escenarios; no es un módulo del paquete principal.
