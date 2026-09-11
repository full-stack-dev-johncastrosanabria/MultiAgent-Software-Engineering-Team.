# Mapa del proyecto

Este índice responde dónde mirar y cómo verificar. El [estado](status.md) contiene la evidencia ejecutada; [operaciones](operations.md) contiene los comandos.

| Quiero… | Implementación | Pruebas relevantes |
|---|---|---|
| Cambiar la CLI o ejecutar sobre un proyecto | [CLI](../src/engineering_team/cli.py), [apply_run](../src/engineering_team/apply_run.py) | [Entrega desde runs](../tests/unit/test_apply_run_delivery.py), [selección de calidad](../tests/unit/test_apply_quality_profiles.py) |
| Entender etapas y retornos de revisión | [StateGraph](../src/engineering_team/graph/stategraph.py) | [Workflow](../tests/integration/test_workflow.py) |
| Ajustar modelos y contexto | [LLM](../src/engineering_team/llm/), [evidencia](../src/engineering_team/repository_evidence.py) | [Prompts](../tests/unit/test_prompts.py), [runtime](../tests/unit/test_model_runtime.py), [grounding](../tests/unit/test_architecture_grounding.py) |
| Cambiar recuperación documental | [RAG](../src/engineering_team/rag/), [corpus de entrada](../knowledge/) | [RAG tests](../tests/rag/) |
| Cambiar herramientas o perfiles de stack | [MCP](../src/engineering_team/mcp/), [perfiles](../src/engineering_team/stacks.py) | [MCP tests](../tests/mcp/), [perfiles](../tests/unit/test_stack_profiles.py) |
| Cambiar preparación de servicios | [Servicios](../src/engineering_team/services.py) | [Servicios tests](../tests/unit/test_services.py) |
| Cambiar runs, eventos o aplicación de resultados | [Run API](../src/engineering_team/run_api.py), [persistencia](../src/engineering_team/runs/), [app que monta los routers](../demo-projects/sample_app/app/main.py) | [Run API tests](../tests/test_run_api.py) |
| Cambiar interfaz o conexión con la API | [Frontend](../frontend/src/), [cliente](../frontend/src/api/runClient.ts), [Vite](../frontend/vite.config.ts) | Scripts de [package.json](../frontend/package.json) |
| Cambiar entrega GitHub | [Delivery](../src/engineering_team/delivery.py) | [Delivery tests](../tests/unit/test_delivery.py) |
| Cambiar evaluación multistack | [Runner](../evaluation/benchmarks/multistack/run_trial.py) | [Trial tests](../tests/unit/test_multistack_trial.py) |
| Cambiar el daemon Docker por run (decisión 14) | [RunDaemon](../src/engineering_team/mcp/run_daemon.py), [red y fases](../src/engineering_team/mcp/container.py) | [Configuración](../tests/unit/test_run_daemon_config.py), [unitarios](../tests/mcp/test_run_daemon.py), [en vivo](../tests/mcp/test_run_daemon_live.py), [trial](../evaluation/benchmarks/adr14/verify_run_daemon.py) |
| Cambiar el etiquetado y el barrido de recursos Docker (decisión 16) | [Etiquetas y barrido](../src/engineering_team/docker_labels.py) | [Etiquetado](../tests/unit/test_docker_labels.py) |
| Cambiar dónde viven los archivos del proyecto (decisión 17) | [Contrato de workspace](../src/engineering_team/workspace/contract.py), [Repositorio MCP](../src/engineering_team/mcp/repository.py) | [Contrato](../tests/mcp/test_workspace_contract.py), [medición](../evaluation/benchmarks/adr17/measure_workspace.py) |
| Cambiar qué pasa si el proyecto no declara su infraestructura (decisión 18) | [Prerequisito bloqueante](../src/engineering_team/infrastructure_prerequisite.py), [topología](../src/engineering_team/topology.py) | [Prerequisito](../tests/unit/test_infrastructure_prerequisite.py) |
| Cambiar la demo bancaria usada como fixture | [Demo](../demo-projects/sample_app/), [evaluación](../src/engineering_team/observability/evaluation.py) | [Demo tests](../tests/integration/test_sample_app.py) |
| Cambiar guardarraíles o redacción de secretos | [Guardrails](../src/engineering_team/guardrails/secrets.py) | [Guardrails tests](../tests/unit/test_guardrails.py), [redacción en nube](../tests/unit/test_cloud_redaction.py) |
| Cambiar configuración | [Settings](../src/engineering_team/config.py) | [Config tests](../tests/unit/test_config.py) |

## Propietarios documentales

- [Arquitectura](architecture/overview.md): composición y límites implementados.
- [Decisiones](architecture/decisions/README.md): por qué el sistema es así; dieciocho registros, uno de ellos reemplazado.
- [Operaciones](operations.md): instalación y superficies de ejecución.
- [Testing](testing.md): comprobaciones y requisitos.
- [Estado](status.md): evidencia, pendientes y zona de no recrear.
- [Historia](history.md): decisiones documentales y retiros.

Las reglas para agentes están en [AGENTS.md](../AGENTS.md). El [archivo histórico](deprecated/README.md) se consulta explícitamente, nunca como paso habitual de navegación.
