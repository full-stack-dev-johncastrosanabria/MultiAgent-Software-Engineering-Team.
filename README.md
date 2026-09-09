# ASET — Autonomous Engineering Team

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-orange)
![MCP](https://img.shields.io/badge/Model_Context_Protocol-repositorio_y_calidad-green)
![Stacks](https://img.shields.io/badge/stacks-python_%7C_jvm_%7C_dotnet_%7C_go_%7C_node-blue)
![Modelos](https://img.shields.io/badge/modelos-nube_con_fallback_local-black)
![RAG](https://img.shields.io/badge/RAG-Chroma-yellow)
![Aislamiento](https://img.shields.io/badge/aislamiento-sandbox--exec_%7C_bubblewrap_%7C_Docker-informational)
![HITL](https://img.shields.io/badge/HITL-HUMAN__REVIEW__REQUIRED-red)
![Ruff](https://img.shields.io/badge/lint-Ruff-D7FF64?logo=ruff&logoColor=black)
![Langfuse](https://img.shields.io/badge/observabilidad-Langfuse_%28opcional%29-purple)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

Un equipo de ingeniería de software gobernado, que corre en tu máquina y trabaja
sobre un repositorio real. Recibe un requisito y lo lleva por seis etapas
—producto, arquitectura, implementación, seguridad, pruebas y revisión—
produciendo en cada una un contrato tipado y evidencia ejecutada, no prosa.

Lo que distingue a ASET no es que varios modelos conversen, sino que **ningún
modelo decide el paso siguiente**. Un grafo de estados determinista enruta el
trabajo según la evidencia declarada, y las compuertas rechazan lo que ninguna
prueba demuestra.

## Cómo funciona

```mermaid
flowchart LR
  R["Requisito"] --> G["StateGraph<br/>enrutado determinista"]
  G --> A["Seis roles<br/>contratos tipados"]
  A --> M["MCP<br/>repositorio · calidad"]
  M --> W[("Workspace aislado<br/>lint · tests · scans")]
  W -->|evidencia| G
  G --> O["Informe redactado<br/>· PR opcional"]
```

- **Las herramientas viven detrás de MCP.** Un servidor de repositorio y otro de
  calidad hablan por stdio; los comandos del proyecto corren en un sandbox de
  proceso o en un contenedor Docker, nunca sobre el intérprete del operador.
- **Cada componente trae su propio toolchain.** Los perfiles `python`, `jvm`,
  `dotnet`, `go` y `node` declaran instalación, lint, pruebas, build, integridad
  de dependencias, evidencia de seguridad y migración de esquema.
- **La revisión humana es una salida real.** Cualquier etapa puede terminar en
  `HUMAN_REVIEW_REQUIRED`; el tercer rechazo del Reviewer detiene la
  automatización en lugar de reintentar indefinidamente.
- **Se redacta antes de negar.** Los secretos se enmascaran en el prompt antes de
  que una guardarraíl rechace la operación.

El detalle está en la [arquitectura](docs/architecture/overview.md) y el porqué,
en las [decisiones](docs/architecture/decisions/README.md).

## Requisitos

- Python ≥ 3.10
- Un runtime de modelos: [Ollama](https://ollama.com) en local, o claves de
  proveedor en la nube
- Docker, solo si se usa el runner en contenedor
- Node, solo para el frontend

## Instalación

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Extras declarados en `pyproject.toml`:

| Extra | Instala | Para |
|---|---|---|
| `dev` | pytest, pytest-cov, ruff | Desarrollo y pruebas |
| `rag` | chromadb, langchain-text-splitters, sentence-transformers | Recuperación sobre el corpus |
| `observability` | langfuse | Trazas de ejecución |
| `sample-app` | fastapi, uvicorn | Run API y proyecto de demo |

## Uso

```sh
python3 -m engineering_team.cli --help
python3 -m engineering_team.cli run-project --help
```

| Comando | Qué hace |
|---|---|
| `run` | Ejecuta el flujo y escribe un informe de evidencia redactado |
| `run-project PATH --spec "..."` | Ejecuta sobre un repositorio real; admite `--test-spec` |
| `reset-project PATH` | Restaura el repositorio de demo. **Destructivo** |

`run-project` es de solo lectura por omisión: escribir en el proyecto exige
`--authorize-writes`, y abrir un pull request exige además `--confirm-delivery`
y el backend `gh`. Las ramas se crean bajo el espacio `aset/`. Que no haya
autorización de escritura no significa que no haya coste ni informes.

Tras la instalación editable, `pyproject.toml` también expone el ejecutable
`engineering-team`.

## Configuración

Todo se configura por variables de entorno leídas en
[`config.py`](src/engineering_team/config.py); `.env.example` documenta el
conjunto. Las de uso más frecuente:

| Variable | Por omisión | Efecto |
|---|---|---|
| `LOCAL_FIRST` | `false` | Intenta primero el modelo local |
| `CLOUD_ENABLED` | `true` | Habilita las cadenas de proveedor en la nube |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Runtime local |
| `QUALITY_TIMEOUT_SECONDS` | `600` | Presupuesto por operación de QualityMCP |
| `QUALITY_TEST_FILTER` | vacío | Qué pruebas corre la compuerta |
| `WORKSPACE_ROOT` | `workspace/runs` | Raíz de los espacios aislados |

Detalle completo en [operaciones](docs/operations.md).

## Pruebas

```sh
PYTHONPATH=src python3 -m pytest
```

La suite tiene 72 archivos organizados por alcance: `tests/unit/`, `tests/mcp/`,
`tests/graph/`, `tests/integration/`, `tests/rag/` y `tests/e2e/`. El alcance de
cada grupo, y qué exige ejecutar cada uno, están en
[pruebas](docs/testing.md).

```sh
python3 -m ruff check src tests
```

## Estado

Este README describe capacidades implementadas y verificadas en el código. **La
existencia de una integración no implica validación en vivo**: la evidencia
ejecutada tiene un único propietario, [estado](docs/status.md), que también
registra lo que se retiró y no debe recrearse.

## Documentación

| | |
|---|---|
| [Mapa del proyecto](AGENTS.md) | Punto de entrada para agentes y personas |
| [Mapa por tarea](docs/README.md) | Dónde cambiar cada parte y qué comprobar |
| [Arquitectura](docs/architecture/overview.md) | Composición implementada |
| [Decisiones](docs/architecture/decisions/README.md) | Catorce decisiones aceptadas |
| [Operaciones](docs/operations.md) | Instalación, configuración, CLI y frontend |
| [Pruebas](docs/testing.md) | Comandos y alcance de validación |
| [Estado](docs/status.md) | Evidencia y limitaciones actuales |
| [Historia](docs/history.md) | Decisiones documentales y retiros |
