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

Los defaults de clase son `local_first=True` y `cloud_enabled=False`. [execute_on_project](../src/engineering_team/apply_run.py) selecciona el orden de runtimes según esos ajustes. `LOCAL_FIRST=false` y `CLOUD_ENABLED=true` seleccionan cloud primero; la prioridad no garantiza que todas las rutas de fallback excluyan modelos locales.

Las cadenas por rol están en [cloud.py](../src/engineering_team/llm/cloud.py); `CLOUD_CHAIN_PRODUCT`, `CLOUD_CHAIN_ARCHITECTURE`, `CLOUD_CHAIN_DEVELOPER` y `CLOUD_CHAIN_SECURITY` las sobreescriben con `proveedor:modelo` separados por comas. Cada proveedor se habilita con su credencial (`GROQ_API_KEY`, `MISTRAL_API_KEY`, `OPEN_ROUTER_API_KEY`, `GEMINI_API_KEY`, `GEMINI_API_KEY_2`, `X_KIRO_API_KEY`, `VYCE_AI_API_KEY`, `TOKEN_FORGE_API_KEY`, `NVIDIA_API_KEY`, `KILO_API_KEY`, `COHERE_API_KEY`, `CLOUDFLARE_WORKER_AI_API` con `CLOUDFLARE_ACCOUNT_ID`); sin credencial el proveedor se omite. Plazos: `LLM_TIMEOUT_SECONDS`, `CLOUD_ROLE_TIMEOUT_SECONDS`, `OLLAMA_TIMEOUT_SECONDS` y, solo para Developer, `DEVELOPER_LLM_TIMEOUT_SECONDS` y `DEVELOPER_ROLE_TIMEOUT_SECONDS`. `MODEL_HEALTH_PATH` (por omisión `workspace/model-health.json`, relativo al directorio de trabajo) guarda el historial que reordena las cadenas; si no se puede leer o escribir, el run continúa sin registrarlo. Que un proveedor esté en una cadena no demuestra que responda hoy; ver [estado](status.md).

**Salida de código a proveedores.** Con la nube habilitada, fragmentos redactados del repositorio, el código que escribe Developer y los hallazgos de escáneres se envían al proveedor que la cadena seleccione, incluidas pasarelas de terceros. No existe hoy una lista de proveedores permitidos por proyecto; antes de ejecutar sobre un repositorio privado, restringir las cadenas con `CLOUD_CHAIN_<ROL>` y retirar las credenciales de los proveedores no aceptados. Ver la [auditoría del 2026-09-16](audit160926/08-seguridad-y-politica.md).

Consultar ayuda no lanza un run ni requiere instalar modelos. Las ejecuciones reales pueden consumir recursos de los proveedores configurados.

## CLI sobre proyectos

La firma y opciones exactas están en [cli.py](../src/engineering_team/cli.py):

```sh
python3 -m engineering_team.cli --help
python3 -m engineering_team.cli run-project --help
```

`run-project` recibe una ruta, o `--repo URL` para clonar a un temporal que se elimina al terminar (`--clone-depth`, 1 por omisión), y `--spec`; admite `--test-spec` y `--report-path`. `--authorize-writes` habilita escritura en el proyecto y es falso por defecto. La entrega requiere otra opción, `--confirm-delivery`, `DELIVERY_BACKEND=gh` y las condiciones de [apply_run.py](../src/engineering_team/apply_run.py). `MAX_REMEDIATION_ITERATIONS` (5 por omisión) acota los ciclos de remediación. Sin autorización de escritura no significa sin coste ni sin reportes.

`docker-sweep` retira los recursos Docker con `aset.owner=aset` que ningún run vivo posee ([decisión 16](architecture/decisions/0016-every-docker-resource-carries-its-run.md)); `--build-cache` poda la caché de build del daemon entero. Si Docker no responde, el barrido actual no lo distingue de «nada que limpiar»; ver la [auditoría del 2026-09-16](audit160926/09-fallos-silenciosos.md).

`reset-project` es destructivo sobre el repositorio de destino; revisar [reset_project.py](../src/engineering_team/reset_project.py) antes de usarlo. No se usa para preparar documentación.

## Calidad y servicios

`QUALITY_RUNNER=container` es el único valor admitido y el default de clase: [QualityMCP](../src/engineering_team/mcp/quality.py) rechaza por nombre cualquier otro desde que el sandbox de proceso se retiró ([decisión 15](architecture/decisions/0015-container-only.md)). Docker pasa a ser requisito para correr el gate. Los campos `quality_stack`, `quality_component_path`, `quality_test_filter` y `quality_timeout_seconds` están en [Settings](../src/engineering_team/config.py). `quality_run_daemon_image` (fijada por digest) y `quality_run_daemon_images` activan el daemon Docker por run de la [decisión 14](architecture/decisions/0014-a-docker-api-that-is-not-the-hosts.md); `config.py` rechaza cualquier otra combinación. La selección efectiva pasa por [apply_run.py](../src/engineering_team/apply_run.py).

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

La Run API no autentica ni restringe a loopback sus rutas de runs (`/api/runs`, aplicar, restaurar); las de proyectos sí exigen loopback. Mantener `--host 127.0.0.1`. [Vite](../frontend/vite.config.ts) reenvía `/api` y `/ws` al backend local en el puerto 8000. Las rutas reales están en [run_api.py](../src/engineering_team/run_api.py) y [project_api.py](../src/engineering_team/project_api.py). La app incluye también endpoints del ejemplo bancario.

## Benchmarks

[run_trial.py](../evaluation/benchmarks/multistack/run_trial.py) carga `ingresos`, `interview` y `northgate` desde Markdown contiguo. Son entradas ejecutables del benchmark y conservan su ubicación. La migración documental no ejecuta trials.

La demo bancaria de evaluación vive en [demo-projects/sample_app](../demo-projects/sample_app/). El runtime la copia a un workspace aislado para los escenarios; no es un módulo del paquete principal.
