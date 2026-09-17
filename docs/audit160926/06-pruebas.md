# Suite de pruebas

Ejecución del 2026-09-17 sobre `gh-run-testing` @ `92742b7`. Fuente de trabajo:
auditor A5 ([papel de trabajo](anexos/A5-tests.md)). Las corridas no
modificaron archivos del repositorio; los tests e2e se ejecutaron sobre una copia
porque escriben trazas en una ruta relativa al directorio de trabajo.

## Entorno

| Elemento | Valor |
|---|---|
| Python | 3.14.7 (`.venv`) |
| pytest / Ruff | 8.4.2 / 0.16.5 |
| Aislamiento | Script `bash` que quita los 56 nombres de `Settings.model_fields` en mayúsculas, `LANGFUSE_HOST` y `RUN_LIVE_MULTIMODEL`, y exporta `DELIVERY_BACKEND=none`; en este shell ninguno de esos nombres estaba exportado |
| Docker | **Daemon no alcanzable** (sin Docker Desktop, colima ni orbstack en ejecución) |
| Ollama | Alcanzable; ningún test lo usó |
| Verificador de tipos | Ninguno configurado |
| Hook de pre-commit | **No instalado** en este clon (solo `*.sample`, sin `core.hooksPath`) |

## Resultados

| Grupo | Tests | Pasan | Fallan | Omitidos | Tiempo |
|---|---|---|---|---|---|
| `tests/unit` + `tests/mcp` (selección del hook) | 1157 | 1112 | 22 | 23 | 43,6 s |
| `tests/graph`, `tests/integration`, `tests/test_run_api.py`, `tests/rag` | 107 | 106 | 1 | 0 | 33,9 s |
| `tests/e2e` (copia) | 6 | 3 | 3 | 0 | 22,7 s |
| **Total** | **1270** | **1221** | **26** | **23** | 100,2 s |
| Repetición hermética: copia sin `.env`, suite completa | 1270 | 1221 | 26 | 23 | 82,7 s |

Por carpeta: `unit` 848/0/0, `mcp` 264/22/23, `graph` 9/0/0, `integration`
39/1/0, `test_run_api.py` 47/0/0, `rag` 11/0/0, `e2e` 3/3/0.

**Los 26 fallos se deben a la ausencia del daemon Docker; ninguno es un defecto
del código ni un test intermitente.** La corrida hermética falló exactamente los
mismos 26 identificadores, así que `.env` no influye hoy en el resultado. Los 23
omitidos requieren imágenes o variables de activación explícita.

| Fallos | Causa | Clase |
|---|---|---|
| `mcp/test_protocol.py` (1) y 16 tests de `mcp/test_quality.py` | `run_tests` y la preparación del entorno necesitan el daemon | Docker ausente, sin `skipif` |
| 5 tests de `mcp/test_quality.py` basados en mocks | `_patch_executor` parchea `ContainerRunner.execute`, pero `QualityMCP._interpreter` llama antes a `require_available()` sin parchear, que ejecuta `docker version`. Con solo esa comprobación neutralizada pasan 5 de 6 | **Defecto de diseño de test**: unitario acoplado a un daemon vivo |
| `integration/test_workflow.py::test_real_mcp_protocol_failure_changes_reviewer_route_and_is_remediated` | Sin daemon, Security queda sin herramientas, la corrida sale a revisión humana antes de Testing y el test cae con `IndexError` que oculta la causa | Docker ausente |
| 3 tests de `e2e/test_evaluation_scenarios.py` | Las 7 trazas escritas dicen «container runtime is unavailable» | Docker ausente |

No se pudo comprobar si quedan recursos Docker etiquetados, porque el daemon no
respondía.

## Lint

Ruff termina con 3 hallazgos: `SIM103` en `agents/security.py:59` y `PYI034` en
`mcp/quality.py:1545` (preexistentes; el [estado](../status.md) los citaba con
números de línea viejos) y `PIE807` en `tests/unit/test_ghcycle_scoring.py:35`
(nuevo, corregible). `pyproject.toml` no fija `select`, así que el conjunto de
reglas depende de la versión de Ruff. `git diff --check` pasa.

## Cobertura de invariantes críticos

S = tests de comportamiento con casos negativos · M = unitario o parcial ·
W = solo mocks o snapshots, o falta el caso negativo clave · — = ninguno.

| Invariante | Fuerza | Brecha principal |
|---|---|---|
| Máximo de iteraciones de remediación | S | La conexión de `Settings` al grafo (`apply_run.py:383`) no se prueba; los tests usan un Reviewer guionado, no un bucle Security/Testing como los de Langfuse |
| Detector de estancamiento | M | Solo rechazos idénticos de Reviewer; nada cubre fallos repetidos con texto distinto (C-03) ni CVEs previos repetidos |
| Presupuestos de reintento y escalado | M | En modo nube primero, `CloudBudget(unlimited=primary)` (`llm/cloud.py:407`); ningún test afirma un límite de intentos o gasto |
| Enrutado a `HUMAN_REVIEW_REQUIRED` | S | — |
| Lista de herramientas por rol | M | No hay matriz rol × herramienta |
| Restricción de rutas y escape del sandbox | S | Rama de enlace simbólico de `HostWorkspace.path` sin test directo |
| Redacción antes de la nube | M-S | Se prueba como función; ningún test planta un secreto y verifica que falte en el **cuerpo HTTP saliente** en el camino exitoso |
| Cadena de fallback y campos gobernados | M | Las reglas gobernadas de `SecurityReview`, `TestResult` y `ReviewerDecision` (`llm/runtime.py:329-373`) no tienen test directo; los tests de cadenas fijan posiciones de lista con docstrings fechados |
| Aislamiento del ledger de salud de modelos | M | Tests con `tmp_path`; la ruta por omisión es relativa al directorio de trabajo y su conexión en `apply_run.py` no se prueba |
| Baseline de seguridad frente a cambio | S (unitario) | Ningún test de grafo impide el bucle sobre CVEs previos |
| Compuerta de entrega | M | **Sin caso negativo** para `confirm=True` + backend `gh` + revisión no aprobada, ni para `authorize_writes=False`; todo usa backends falsos |
| Scorer ghcycle | M | `run_cycle.main()` sin test; la semántica de corridas en seco solo se afirma indirectamente |
| Tests sin escribir en el repositorio ni en servicios vivos | W | Sin `conftest.py`; 44 de 116 construcciones de `Settings` leen el `.env` real; `LangfuseTracer` toma claves de `os.environ` y el e2e no pasa tracer, así que con claves exportadas enviaría trazas reales |

**Tests que son snapshots de evidencia.** `tests/e2e/test_live_evaluation_evidence.py`
y `tests/e2e/test_multimodel_evidence.py` leen JSON versionados del 2026-09-09 y
pasan con independencia del código; con `RUN_LIVE_MULTIMODEL=1` el segundo
**sobrescribe** el fixture versionado. `test_quality_container_contract_is_documented`
afirma cadenas literales de [operaciones](../operations.md): reescribir ese texto
rompe el gate.

## Contraste con afirmaciones previas

| Afirmación | Medición | Veredicto |
|---|---|---|
| «978 PASS, 20 SKIP» tras repetir 26 fallos con Docker (estado) | 1221/26/23 sobre 1270 sin Docker; también 26 fallos, todos por Docker | Coherente en naturaleza, no reproducible tal como se enunció: la selección no está escrita como comando y la colección creció |
| «1038 aprobadas y 17 omitidas» el 09-14 (estado) | 1270 recolectados; 30 commits y 19 archivos de test (+1801 líneas) desde entonces | Obsoleta |
| «111», «156» y «73» pruebas focales (estado) | Sin comando registrado | No verificable |
| «143 focales PASS; 1 test preexistente de ProcessRunner FAIL en Python 3.14» (`PROJECT_STATE.md`) | `ProcessRunner` se retiró en `f09ffd4` ([decisión 15](../architecture/decisions/0015-container-only.md)); en 3.14.7 solo fallan los 26 de Docker | Obsoleta |
| «El hook de pre-commit corre `tests/unit tests/mcp` y bloquea el commit» (memoria del operador) | Hook no instalado en este clon; esa selección tiene 22 fallos sin daemon | El gate **no se está aplicando** aquí |

## Hallazgos de esta sección

| ID | Severidad | Hallazgo | Confianza |
|---|---|---|---|
| A-13 | Alta | El gate depende de un daemon Docker vivo y falla en lugar de omitirse; con el hook no instalado, «rojo = Docker» se normaliza y oculta regresiones reales | 0.9 |
| M-23 | Media | Invariantes críticos sin test: negativos de entrega, límite de presupuesto en modo nube, reglas gobernadas de Security/Testing/Reviewer, redacción verificada en el cuerpo HTTP | 0.75 |
| M-24 | Media | Aislamiento de tests ad hoc: sin `conftest.py`, lectura del `.env` real, claves de Langfuse desde el entorno, rutas relativas al directorio de trabajo | 0.8 |
| M-25 | Media | Tests de snapshot que osifican artefactos y configuración, y uno puede sobrescribir un fixture versionado | 0.8 |
| B-12 | Baja | Ruff con 3 hallazgos y reglas implícitas; sin verificador de tipos; `run_cycle.main()` sin test; test que acopla la redacción de operaciones al gate | 0.8 |
