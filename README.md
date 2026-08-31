# Autonomous Software Engineering Team (ASET)

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Workflow-orange)
![MCP](https://img.shields.io/badge/Model_Context_Protocol-Integrated-green)
![Langfuse](https://img.shields.io/badge/Observability-Langfuse-purple)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

Equipo de exactamente seis agentes — Product, Architecture, Developer,
Security, Testing y Reviewer — coordinado unicamente por un `LangGraph
StateGraph`. Pydantic valida toda salida que afecta estado o rutas; routers
deterministicos controlan remediacion, limites e HITL.

**El proyecto opera cloud-first con fallback local.** Los cuatro agentes que
invocan modelo se atienden con cadenas de proveedores cloud repartidas por rol;
Ollama queda como red de seguridad cuando la cadena cloud se agota. El modo
local-first sigue soportado y puede ser configurado en `.env.example`.

El sistema trabaja siempre sobre una **copia aislada** del proyecto destino. El
proyecto fuente solo cambia tras un Apply confirmado explicitamente.

## Arquitectura y stack

Monolito modular bajo `src/engineering_team/` mas un frontend Vite/React en
`frontend/`. LangGraph es el unico orquestador; LangChain aporta `Document` y
text splitting al RAG; Sentence Transformers genera embeddings y Chroma los
persiste. Repository y Quality se exponen como MCP Servers reales y el grafo
los consume con un MCP Client oficial por stdio.

QualityMCP separa tres cosas: los controles de calidad, el runner que los
ejecuta y el perfil de cada componente. El runner en contenedor es la direccion
del producto porque puede proveer el toolchain que un proyecto necesita, sin
usar el interprete ni las dependencias del operador. Los perfiles actuales
cubren Python, JVM/Maven, .NET, Node/TypeScript y Go. Python 3.10+, Pydantic,
Ollama, Langfuse, pytest y FastAPI siguen siendo las dependencias de ASET, no
una restriccion sobre los proyectos destino.

| Capa | Modulo | Rol |
|---|---|---|
| Orquestacion | `graph/stategraph.py` | grafo unico, HITL, remediacion, reporte final |
| Ruteo | `graph/routers.py`, `graph/hitl.py` | decisiones deterministas de arista |
| Contratos | `contracts/models.py`, `contracts/state.py` | Pydantic strict sobre toda salida que afecta estado |
| Modelo local | `llm/runtime.py`, `llm/ollama.py` | runtime primario con `LOCAL_FIRST=true` |
| Modelo cloud | `llm/cloud.py` | cadenas por rol, presupuesto y categorias de error HTTP |
| Prompts | `llm/prompting.py`, `src/engineering_team/prompts/<rol>/` | compartidos por ambos runtimes |
| MCP | `mcp/repository.py`, `mcp/quality.py`, `mcp/server.py`, `mcp/client.py` | puertos de minimo privilegio via stdio |
| Calidad | `mcp/runner.py`, `mcp/container.py`, `stacks.py`, `components.py` | runner de proceso o contenedor, perfiles por componente y comandos de calidad |
| Servicios | `services.py`, `topology.py` | Compose declarado o topologia derivada, aislados por corrida |
| Entrega | `delivery.py` | rama `aset/` y pull request bajo confirmacion explicita |
| RAG | `rag/loaders.py`, `rag/index.py`, `rag/retrievers.py` | indice Chroma persistente sobre `knowledge/` |
| Guardrails | `guardrails/` | redaccion de secretos, validacion, timeouts, rutas |
| Transporte | `run_api.py`, `project_api.py` | runs durables + WebSocket; selector de carpeta solo loopback |
| Persistencia | `runs/store.py`, `runs/models.py` | snapshots de corrida, thread-safe |
| Aislamiento | `workspace/isolation.py`, `apply_service.py` | copia por corrida; Apply con hashes y restore |
| Observabilidad | `observability/` | Langfuse v4 con modo offline correlacionado |

Detalle en `docs/architecture/overview.md` y los diagramas de `docs/diagrams/`.

## Instalacion

El proyecto usa unicamente `pyproject.toml`; no hay un segundo gestor de
dependencias.

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,rag,observability,sample-app]"
cp .env.example .env
ollama pull qwen3.5:4b
ollama pull qwen3.5:9b
```

Para ejecutar proyectos destino en contenedor, instale Docker Desktop (o Docker
Engine en Linux) y confirme que `docker info` responde antes de configurar
`QUALITY_RUNNER=container`.

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,rag,observability,sample-app]"
Copy-Item .env.example .env
ollama pull qwen3.5:4b
ollama pull qwen3.5:9b
```

### QualityMCP y contenedores

La ruta recomendada para ejecutar build, tests y scans de un proyecto destino
es Docker. Configure:

```sh
QUALITY_RUNNER=container
# Opcional: fija una imagen; si se omite, ASET deriva una imagen Python del proyecto.
QUALITY_CONTAINER_IMAGE=
```

Con Docker Desktop en Windows, macOS o Linux, el mismo runner puede ejecutar el
proyecto con su toolchain dentro de un contenedor. Para Python, ASET deriva la
version a partir de sus pines o declaracion; FlaskApiProduct, por ejemplo, se
ejecuto con Python 3.12 cuando el host tenia Python 3.14. Una imagen explicita
es necesaria si no se puede derivar una compatible.

El runner de proceso y sus sandbox de Darwin/Linux se conservan para
compatibilidad local, pero no son la frontera estrategica ni dan soporte
cross-platform. En particular, Windows debe usar el runner en contenedor.

Si el proyecto declara `docker-compose.yml`, ASET levanta solo servicios con
`image:` para la corrida, en una red interna y sin puertos del host. Si no lo
declara, puede derivar Postgres, MySQL o MongoDB desde sus configuraciones;
SQLite es correctamente un resultado sin servicios. Las imagenes de produccion
del proyecto (`build:`) nunca se construyen para ejecutar QA.

La arquitectura, los limites y lo que aun falta estan en
[`docs/architecture/`](docs/architecture/README.md), especialmente los
[ADRs](docs/architecture/decisions/README.md) y el
[roadmap](docs/architecture/roadmap.md).

### Que agente usa modelo

Cuatro de los seis agentes invocan un modelo. **Testing y Reviewer son
compuertas deterministas** sobre la evidencia que produjeron los MCP: clasifican
y puntuan con reglas, no con un LLM. Esto es intencional — ninguna decision de
ruta depende de texto libre de un modelo.

| Agente | Proveedor primario (cloud) | Respaldo local | Perfil local |
|---|---|---|---|
| Product | Groq | `qwen3.5:9b` | `DEEP_MODEL` |
| Architecture | Mistral | `qwen3.5:4b` | `FAST_MODEL` |
| Developer | Mistral (Codestral) | `qwen3.5:9b` | `CODING_MODEL` |
| Security | OpenRouter | `qwen3.5:9b` | `DEEP_MODEL` |
| Testing | — | — | compuerta determinista |
| Reviewer | — | — | compuerta determinista |

## Configuracion

Copie `.env.example`. Los valores RAG aprobados son 800 tokens, overlap 160,
top_k 4, fetch_k 8 y relevancia normalizada 0.55. Ninguna API key se imprime
nunca.

`.env.example` trae los defaults **cloud-first** (`CLOUD_ENABLED=true`,
`LOCAL_FIRST=false`), que es el modo en que opera el proyecto. Requiere cargar
al menos una API key. Para volver al modo local sin credenciales, invierta
ambos flags y levante Ollama.

Langfuse live requiere `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` y
`LANGFUSE_BASE_URL`; sin credenciales el adapter conserva una traza local
correlacionada y el core continua.

La entrega externa permanece desactivada por defecto (`DELIVERY_BACKEND=none`).
El backend `gh` puede enviar una propuesta confirmada en una rama nueva bajo
`aset/`, nunca escribe sobre la rama por defecto y abre un pull request separado.
El backend `mcp` esta configurado pero aun rechaza la entrega de forma explicita;
no lo use hasta que implemente la operacion de apertura. El token de GitHub se
guarda solo en `.env`.

### Estrategia de modelos cloud, por agente

Cada rol tiene su propia **cadena de fallback**, definida en `_ROLE_CHAINS` de
[`llm/cloud.py`](src/engineering_team/llm/cloud.py). Se recorre en orden hasta
que un modelo devuelve una salida que valida contra el contrato Pydantic del
rol. Los primarios se reparten entre tres proveedores a proposito, y el primer
fallback **siempre cruza de proveedor**, para que una cuota agotada en un
proveedor no detenga la corrida.

| Rol | 1º (primario) | 2º | 3º | 4º |
|---|---|---|---|---|
| **Product** | `groq:openai/gpt-oss-120b` | `mistral:mistral-small-latest` | `openrouter:nvidia/nemotron-3-super-120b-a12b:free` | `google:gemini-3.5-flash` |
| **Architecture** | `mistral:mistral-medium-latest` | `groq:openai/gpt-oss-120b` | `openrouter:nvidia/nemotron-3-super-120b-a12b:free` | `google:gemini-3.5-flash` |
| **Developer** | `mistral:codestral-latest` | `groq:openai/gpt-oss-120b` | `mistral:mistral-small-latest` | `google:gemini-3.5-flash` |
| **Security** | `openrouter:nvidia/nemotron-3-super-120b-a12b:free` | `groq:openai/gpt-oss-120b` | `mistral:mistral-small-latest` | `google:gemini-3.5-flash` |

Por que estas y no otras — las razones estan en los comentarios de `cloud.py`,
que registran resultados observados por rol, no tamano de catalogo:

- **Developer** encabeza con Codestral: Medium fue 0/10 en Developer pese a ser
  fiable en Architecture. Gemini va ultimo porque su espera no debe gastarse
  antes de probar Small.
- **Google** queda siempre al final y nunca comparte cadena consigo mismo: sus
  cuotas pueden ser por modelo, y una falla de cuota en una version no debe
  inhabilitar otra que si responde.
- Varios modelos estan **deliberadamente ausentes** (SambaNova entero por
  HTTP 402; `gpt-oss-120b:free` por 404; `nemotron-3-ultra:free` por devolver
  JSON malformado). Estan listados en `cloud.py` para que nadie los reintroduzca.
- Testing y Reviewer aparecen en `_CLOUD_MAP` por completitud del mapa, pero al
  ser compuertas deterministas nunca llegan a invocarse.

Todos los proveedores menos Google hablan el formato chat-completions de
OpenAI, asi que un solo camino de codigo los atiende; solo cambian endpoint y
credencial.

#### Activarlo

```sh
CLOUD_ENABLED=true
LOCAL_FIRST=false
GROQ_API_KEY=...
MISTRAL_API_KEY=...
OPEN_ROUTER_API_KEY=...
GEMINI_API_KEY=...      # opcional: solo lo usa el ultimo eslabon
```

Sobreescribir la cadena de un rol sin tocar codigo:

```sh
CLOUD_CHAIN_DEVELOPER=mistral:codestral-latest,groq:openai/gpt-oss-120b,google:gemini-3.5-flash
```

Disponibles: `CLOUD_CHAIN_PRODUCT`, `CLOUD_CHAIN_ARCHITECTURE`,
`CLOUD_CHAIN_DEVELOPER`, `CLOUD_CHAIN_SECURITY`. Vacio conserva los defaults.

#### Presupuesto y limites

`MAX_CLOUD_ESCALATIONS_PER_AGENT` y `_PER_RUN` **solo acotan a cloud cuando
actua como contingencia** (`LOCAL_FIRST=true`). Como runtime primario no esta
limitado por esos contadores: atender seis agentes por corrida es el caso
normal, no una escalada. `CLOUD_ROLE_TIMEOUT_SECONDS` acota cada intento de rol.

`MCP_ERROR`, `TOOL_ERROR` y `RAG_ERROR` nunca activan cloud automaticamente:
son fallas de herramienta o de evidencia, no de modelo.

#### El proveedor no cambia el contrato

Ambos runtimes construyen el prompt desde los mismos archivos
`src/engineering_team/prompts/<rol>/{system,user}.md` (via
`engineering_team.llm.prompting`), y validan contra el mismo modelo Pydantic.
Cambiar de proveedor no altera las boundaries ni el contrato de salida de un
agente — solo quien lo responde.

## Run

CLI interactiva:

```sh
./run.sh          # macOS / Linux (levanta Ollama si hace falta)
```

```powershell
.\run.ps1         # Windows
```

Comandos directos:

```sh
.venv/bin/engineering-team run "<requerimiento>"
.venv/bin/engineering-team run-project <ruta> --spec "<especificacion>"
.venv/bin/engineering-team reset-project <ruta>
```

### Frontend y API en tiempo real

El frontend Vite consume la aplicacion FastAPI mediante `POST /api/runs` y
`WebSocket /ws/runs/{run_id}`. En macOS/Linux ambos procesos se levantan juntos:

```sh
./start_systems.sh    # backend :8000 + frontend :5173, Ctrl+C detiene ambos
./stop_systems.sh     # detiene los procesos que quedaron vivos
```

Manualmente, en dos terminales desde la raiz del repositorio:

```sh
.venv/bin/python -m uvicorn sample_app.app.main:app --host 127.0.0.1 --port 8000 --reload
```

```sh
cd frontend && npm install && npm run dev -- --host 127.0.0.1 --port 5173
```

Abra `http://127.0.0.1:5173`. Vite redirige `/api` y `/ws` hacia FastAPI en el
puerto 8000. Las rutas de proyecto ingresadas en la UI se resuelven desde la
raiz donde se inicio FastAPI.

Hoy la UI trabaja sobre rutas locales. Su siguiente evolucion esta documentada
en el roadmap: aceptar un enlace GitHub, mostrar el runner, perfiles y servicios
seleccionados, pedir el cambio y presentar la rama, evidencia y pull request.
No debe prometer una entrega externa que el backend no haya confirmado.

Validaciones del frontend:

```sh
cd frontend && npm test && npm run typecheck && npm run lint && npm run build
```

### Escenario de demostracion: calculadora QA

`demo-projects/calculadora-qa-demo` es un proyecto real e independiente (no un
mock) usado para ejercer el flujo completo desde el chat: copia aislada,
ejecucion del workflow, aprobacion y Apply seguro contra el proyecto fuente.
Instalelo en modo editable antes de usarlo como destino:

```sh
.venv/bin/python -m pip install -e ./demo-projects/calculadora-qa-demo
```

Seleccione en la UI una **copia temporal** del demo (nunca el original) y envie
un mensaje de chat acotado. Como verificar cada etapa sin confiar en la sola
respuesta de la UI:

- `GET /api/runs/{run_id}/events` (o el panel de la corrida) confirma que el
  workflow realmente se ejecuto.
- Los archivos bajo el workspace aislado del run — no el proyecto original —
  confirman que la implementacion ocurrio antes de cualquier Apply.
- Solo tras `POST /api/runs/{run_id}/apply` con `confirmed: true` el estado pasa
  a `applied` y el proyecto fuente cambia. El `test_exit_code` de la respuesta
  refleja pytest sobre el proyecto fuente ya modificado, no sobre la copia.

Para devolver un demo a su baseline: `engineering-team reset-project <ruta>`.

`tests/e2e/test_chat_apply_flow.py` reproduce este recorrido de forma
determinista y automatizada (sin LLM real), y es la prueba de referencia del
flujo.

## Ejecucion y evidencia

```sh
.venv/bin/python -m pytest                                  # suite completa
.venv/bin/python scripts/run_evaluation.py                  # escenarios SC-01..SC-05
.venv/bin/python scripts/run_evaluation.py --live-models    # los mismos con Ollama real + Langfuse
.venv/bin/python scripts/run_multimodel.py                  # corrida real qwen3.5:4b + 9b
```

El modo rapido escribe `scenarios.json` / `aggregate.json`; el modo LIVE escribe
por separado `scenarios-live.json` / `aggregate-live.json` y conserva llamadas,
latencias y usage reales. Todo va a `evaluation/reports/`. Las trazas locales
redacted quedan en `evaluation/reports/traces/`; Quality MCP valida la copia
aislada de la corrida. La demo completa esta en `docs/demo-runbook.md`.

## Continuidad entre sesiones

El estado de trabajo vive en `PROJECT_STATE.md`, y su bloque de handoff lo
mantiene `scripts/handoff.py`. Para retomar donde quedo la sesion anterior:

```sh
python3 scripts/handoff.py read
```
