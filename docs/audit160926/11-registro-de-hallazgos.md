# Registro consolidado de hallazgos

Auditoría del 2026-09-16/17 sobre `gh-run-testing` @ `92742b7`. Cada hallazgo
tiene un único identificador; las secciones temáticas remiten aquí. Referencias
`ruta:línea` relativas a `src/engineering_team/` salvo otra raíz.

## Claves

**Severidad** (método de las 12 capas): **Crítica**, el agente puede producir con
confianza un comportamiento operativo erróneo o no puede cumplir su función;
**Alta**, degrada con frecuencia la corrección o la estabilidad; **Media**, la
corrección suele sobrevivir pero el resultado es frágil o costoso; **Baja**,
mantenibilidad.

**Verificación.** **P**: el auditor principal leyó el código o recalculó la cifra.
**X**: al menos dos auditores independientes llegaron al mismo mecanismo.
**E**: un auditor lo midió ejecutando (tests, scripts). **S**: un solo auditor,
lectura estática.

**Marcos.** `ABE` = «Building effective agents» (S simplicidad, T transparencia,
ACI interfaz, A1 condiciones de agentes de código). `HE§n` = sección de Harness
Engineering. `Ln` = capa del método de 12 capas.

## Críticos

| ID | Hallazgo | Evidencia clave | Marcos | Verif. | Conf. | Arreglo mínimo |
|---|---|---|---|---|---|---|
| C-01 | **El diagnóstico de tests no llega al único rol que edita código** cuando Reviewer enruta por Architecture | `models/context.py:149-150` adjunta diagnósticos solo si `return_to == rol`; 26 de 42 transiciones fueron a Architecture; 34 prompts de Developer sin diagnóstico | ABE A1 · HE§3, §10 · L4 | P, X | 0.9 | Adjuntar siempre los diagnósticos de tests a Developer, con independencia de la ruta |
| C-02 | **La remediación por Architecture no puede converger**: la suficiencia exige leer ≥50 % de los candidatos rankeados y la ventana visible ronda 7 archivos, mientras la retroalimentación agranda el denominador | `repository_evidence.py:16-26, 501, 513-552`; `graph/stategraph.py:468-490`; `agents/reviewer.py:241-265`; [decisión 7](../architecture/decisions/0007-declared-coverage-decides-remediation.md); traza `a2cb449e2a`: de 27 a 67 candidatos, cobertura del 26 % al 10 % | ABE A1 · HE§10 · L11 | P, X | 0.9 | Decisión nueva que refine la 7: medir cobertura contra las lecturas planificadas o fronteras requeridas; enrutar a Architecture solo si la pasada anterior aumentó fronteras visibles |
| C-03 | **El detector de estancamiento hashea texto volátil** y los fallos repetidos corren hasta el tope | `graph/routers.py:17-26`; traza `a2cb449e2a`: 5 revisiones, 1 motivo, 5 huellas; 22 de 27 transiciones repitieron clase y se detectaron 7; spring-e: 4 diffs idénticos sin detección | HE§10 · L11 | P, X | 0.85 | Huella = (categoría, ids de tests fallidos ordenados, primer tipo de error o símbolo, hash del diff) |
| C-04 | **La compuerta de cobertura léxica rechaza suites verdes**: palabras de ≥6 letras de reglas redactadas por el LLM de Product, en idioma variable, deben aparecer en nombres de tests | `agents/testing.py:70-92`; `agents/reviewer.py:363-408`; spring-demo-d con `run_tests` verde 5/5 rechazada; tres commits del 09-16 enseñaron las palabras al modelo en lugar de corregir la compuerta | ABE A1 · HE§2, §8 · L1 | P, X | 0.85 | Contrato de aceptación del operador con ids de test por obligación; la cobertura léxica, solo consultiva |

## Altos

| ID | Hallazgo | Evidencia clave | Marcos | Verif. | Conf. | Arreglo mínimo |
|---|---|---|---|---|---|---|
| A-01 | Llamadas LLM que solo pueden hacer eco (Architecture y Security) cuestan 53 minutos de modelo y terminan corridas | `llm/runtime.py:293-297, 336-374`; 81/81 éxitos idénticos al candidato; 4 de 17 trazas murieron ahí | ABE S · HE§15 · L11 | P, X | 0.95 | Añadir ambos roles a la exclusión de `graph/stategraph.py:600-603`, o hacer la llamada consultiva |
| A-02 | La disponibilidad de modelos decide la mayoría de los resultados; configuraciones crónicamente caídas siguen en las cadenas; fallback local sin preflight; presupuesto ilimitado en modo nube | 13 de 24 paradas por cadena agotada; mistral-medium 46/46 con 429; Ollama 0/26; `llm/cloud.py:407` | ABE S · HE§10, §9 · L11 | P, X | 0.85 | Uno o dos proveedores fiables y aprobados por rol, preflight, tope de intentos y gasto |
| A-03 | Sin checkpoint ni reanudación; la revisión humana es terminal, sin motivo legible y mezcla caída de proveedor, fallo de infraestructura y rechazo | `graph/stategraph.py:1030-1033`; `runs/store.py:26`; `run_api.py:119-127` | ABE A1 · HE§5, §12 | X | 0.9 | Checkpointer persistente por `run_id`, endpoint de reanudación y estado final tipado |
| A-04 | Orden de chequeos invertido y escaneo de seguridad repetido en cada ciclo; el atajo `testing_only` es inalcanzable porque `"api"` aparece en «no API change declared» | `agents/developer.py:350, 375-378, 460, 506-509`; `graph/stategraph.py:1000-1011`; 44 escaneos con el mismo conjunto de CVEs, 13–18 % del reloj | HE§7, §19 | P, X | 0.9 | Escaneo de baseline único antes de escribir; re-escaneo solo si cambia un manifiesto; compilar y testear antes de Security; señal de superficie por palabra completa |
| A-05 | El recibo de cambios reporta el primer diff, no el final | `apply_run.py:634-637` toma el primer `get_diff`, que es acumulativo; 7 de 15 recibos no coinciden con `changed_files` | HE§13 | P, X | 0.9 | Tomar el último `get_diff`; test con dos diffs |
| A-06 | Salida de código fuente a proveedores sin nivel de confianza, lista permitida ni tope de gasto | `llm/cloud.py:32-45, 67-158`; solo `cloud_enabled` global (`config.py:25`) | HE§9 | P, X | 0.85 | `cloud_allowed_providers` obligatorio por proyecto; pasarelas no revisadas con opt-in; costo registrado |
| A-07 | Instalación de dependencias del repositorio objetivo con red a internet | `mcp/quality.py:975-1047`; `mcp/container.py:303-314` | HE§4 | P | 0.7 | Salida limitada a registros; `--ignore-scripts` donde sea compatible |
| A-08 | El barrido Docker trata fallos de consulta y de borrado como «nada que limpiar» | `docker_labels.py:92-128`; `apply_run.py:211`; restos en flask-a y flask-k | HE§12 | P | 0.85 | Distinguir consulta fallida, vacío y borrado fallido; registrar el reporte |
| A-09 | Error de cadena sin tipo: se conserva el error del último modelo, los fallos de calidad se reportan como disponibilidad y el reintento de etapa reenvía la misma entrada; 400 y 413 no enfrían | `llm/cloud.py:585-602, 622-628, 679-693`; `graph/stategraph.py:614-667`; 12 de 26 fallos de etapa ocultaban fallos de calidad; 10 de 16 reintentos fallaron otra vez | ABE T · HE§10 · L11, L8 | X | 0.9 | `ChainFailure` tipado con categorías; reintentar solo si una condición de disponibilidad cambió |
| A-10 | La destilación convierte riesgo de baseline en «aserción fallida» y borra el error real | `agents/reviewer.py:210-220`; `models/context.py:163-206` conserva la cola de 2000 bytes; 42 % del diagnóstico de Developer son advisories; en 17 de 33 prompts falta el error de compilación | HE§3 · L4 | P, X | 0.85 | Sobre tipado `{regresiones, fallos_nuevos, errores_de_compilación, riesgo_baseline}`; el riesgo de baseline nunca va a Developer |
| A-11 | El scorer ghcycle produce etapas vacías o mal atribuidas y resultados no atribuibles | `evaluation/benchmarks/ghcycle/run_cycle.py:109-118, 171-180, 239-246`; 21/26 aprobados vacíos; caída de guardarraíl puntuada como clone | HE§18 | P, X | 0.85 | Registrar commit, especificación, cadena y horas; «no ejercitado» distinto de «aprobado»; causa de parada |
| A-12 | La evidencia de diagnóstico pierde información donde vive la causa raíz | `apply_run.py:565, 597` (600 caracteres); `mcp/quality.py:713` (4000); diff capado; herramientas con `latencyMs=0` | ABE T · HE§12 · L8 | X | 0.85 | Extraer bloques de error (Maven `[ERROR]`, Surefire) en la herramienta, desde el inicio |
| A-13 | El gate de tests depende de un daemon Docker vivo y falla en lugar de omitirse; el hook de pre-commit no está instalado | 26 fallos sin daemon, 5 de ellos unitarios con mocks; `.git/hooks` solo con `*.sample` | HE§11 | E, P | 0.9 | `skipif` que compruebe el daemon; parchear `require_available` en tests con mocks; hook versionado e instalable |
| A-14 | La documentación no acompañó 31 commits: afirmaciones erróneas sobre proveedores, límite de iteraciones, CLI y resolución de destinos; decisión 8 contradicha | Ver [documentación](07-documentacion.md) | HE§11, §14 | P, X | 0.9 | **Corregido en documentos**; falta la regla de que un `feat:` actualice su propietario |

## Medios

| ID | Hallazgo | Evidencia clave | Marcos | Verif. | Conf. |
|---|---|---|---|---|---|
| M-02 | Formato de salida con sobrecarga: archivos completos como cadenas JSON, sin espacio para razonar mientras el prompt pide «ejecutar mentalmente» | `llm/prompting.py:94-128`; `llm/runtime.py:97`; `llm/cloud.py:535-547`; mediana 190 `\n` escapados | ABE ACI | S | 0.7 |
| M-03 | Ajuste sin métrica de resultado: una corrida por cambio, cuatro commits durante corridas, rotación revertida a los 52 minutos con n=2 | git log del 09-16; `d8cd3f3` → `31defca` | ABE S · HE§14, §15 | X | 0.85 |
| M-05 | Telemetría ciega: 264 de 290 generaciones fallidas sin prompt ni respuesta; `fallback_used` siempre falso; costo en 1 de 478; herramientas sin tiempo; revisión humana sin motivo | `llm/cloud.py:607, 615-621, 672-678` | ABE T · HE§12 · L11 | P, X | 0.9 |
| M-06 | Ledger de salud de modelos sin validar: clave sin stack, fallos de entorno contados como autoría, sin decaimiento, última escritura gana, ruta relativa, errores de E/S silenciosos | `llm/model_health.py:26-39, 86-87, 101-138`; `config.py:93`; sin corrida | HE§6 · L3, L12 | P, X | 0.75 |
| M-07 | Brecha de conocimiento del stack: imports de Spring Boot 3 repetidos; el arreglo es solo prompt y no tiene corrida; el RAG recupera estándares de C#/.NET para Java | `project_facts.py:28-40`; 23 de 23 recuperaciones de Testing en Spring | HE§3, §11 | X | 0.75 |
| M-08 | El contrato de tarea es un artefacto del LLM: especificación de tests anexada como texto libre; reglas de demo en `ProductAgent` | `apply_run.py:322-323`; `agents/product.py:14-19` | HE§2 | X | 0.8 |
| M-09 | Los fallos de entorno no tienen recuperación: `WorkspaceSyncError` termina una corrida de 13 minutos | `graph/stategraph.py:218-246, 561-570`; flask-k | HE§10 | S | 0.75 |
| M-10 | Redacción acotada por patrones conocidos | `guardrails/secrets.py:140-142`; commits `41463de`, `78b487e` | HE§9 | S | 0.75 |
| M-11 | Rutas de runs de la Run API sin autenticación ni guardia de loopback | `run_api.py:279-360` frente a `project_api.py:35` | HE§9 | P | 0.6 |
| M-12 | Una suite Python con todos los tests omitidos cuenta como camino feliz | `agents/testing.py:164-170`; `mcp/quality.py:638-647` | HE§7 | P (parcial) | 0.5 |
| M-13 | `except` amplio en la cadena de nube puede disfrazar defectos internos | `llm/cloud.py:629` | L11 | S | 0.5 |
| M-14 | La redacción hacia la nube alcanza archivos que Developer debe reescribir y nada impide escribir `[REDACTED]`; no observado en diffs | `llm/cloud.py:496-497`; `graph/stategraph.py:826-835`; 18 de 90 prompts | L9 | P | 0.8 · daño 0.3 |
| M-15 | La redacción por nombre de clave oculta el veredicto `authorization` de Security en trazas y eventos | `observability/langfuse.py:14-24`; `run_events.py:21-25, 71, 98`; 42 de 42 | L10 | S | 0.85 |
| M-16 | En fallo JVM se descartan los resultados Surefire; el parser de fallos solo entiende pytest | `mcp/quality.py:1163-1168`; `testing_evidence.py:42-56` | L7, L8 | S | 0.7 |
| M-17 | Contexto duplicado y sobredimensionado; sin presupuesto de bytes por proveedor | Valores gobernados cuatro veces; planificador hasta 84 KB; 18 de 21 llamadas de Developer a Groq rechazadas por tamaño | ABE ACI · HE§3 · L2, L5 | X | 0.8 |
| M-18 | Reparación local a ciegas que puede convertir una autoría en eco | `llm/runtime.py:150-153, 169-183, 211-218` | L11 | S | 0.85 |
| M-19 | Autor y planificador cambian de modelo en silencio durante la remediación | `llm/cloud.py:577-581, 679-685`; traza `1885fc593d` | L11 | S | 0.85 |
| M-20 | El estado contenía conteos sin artefacto, afirmaciones exageradas (F-8) o sin nueva corrida (F-7), una referencia rota y no registraba la campaña del 09-16 | Ver [evidencia](02-evidencia-y-metricas.md) | HE§13, §18 | P, X | 0.8 |
| M-21 | Una negativa del guardarraíl de nube hace caer la corrida sin reporte | `spring-demo-dry-20260916c.json` (`cli_stderr_tail`); traza `b798793c96` | HE§10 · L11 | P | 0.8 |
| M-22 | Regresión no documentada: el único trabajo aceptado en un repositorio externo (3/8 el 09-03) no se cita ni se comparó con el arnés actual | `evaluation/reports/apply-debugger-flask-writes-v4/v7/v8.json` | HE§14, §18 | P | 0.8 |
| M-23 | Invariantes críticos sin test: negativos de entrega, límite en modo nube, reglas gobernadas de Security/Testing/Reviewer, redacción en el cuerpo HTTP | [Pruebas](06-pruebas.md) | HE§9, §11 | S | 0.75 |
| M-24 | Aislamiento de tests ad hoc: sin `conftest.py`, `.env` real, claves de Langfuse del entorno, rutas relativas | 44 de 116 `Settings(`; `observability/langfuse.py:128-133` | HE§11 | E | 0.8 |
| M-25 | Tests de snapshot que osifican artefactos y pueden sobrescribir un fixture | `tests/e2e/test_multimodel_evidence.py:16, 29-33` | HE§18 | E | 0.8 |
| M-26 | Hechos duplicados que divergen y comprobaciones documentales que verifican estructura, no verdad | `tests/integration/test_documentation.py` | HE§11 | X | 0.85 |

## Bajos

| ID | Hallazgo | Evidencia clave | Verif. | Conf. |
|---|---|---|---|---|
| B-02 | Heurísticas con forma de benchmark dentro de agentes de producción; `security_hitl` inalcanzable; HITL de seguridad por listas de palabras | `agents/product.py:14-19`; `agents/security.py:141-183`; `mcp/quality.py:1296-1302` | X | 0.8 |
| B-03 | Artefactos muertos: seis `user.md`, `system.md` de Testing y Reviewer, `tokenforge` sin cadena, `allowed_tools` sin renderizar, `guardrails/routes.py`, `guardrails/timeouts.py`, `build_walking_graph` | `llm/prompting.py:63-64` | P, X | 0.9 |
| B-04 | ACI MCP sin docstrings, rol declarado por el llamador, `search_code` sin límite ni líneas | `mcp/server.py:30-122`; `mcp/repository.py:117-121` | S | 0.9 |
| B-05 | Colección RAG compartida reconstruida en cada corrida; 6 consultas idénticas; 30 % vacías | `apply_run.py:357`; `rag/__init__.py:20-27` | X | 0.7 |
| B-07 | Daemon dind con `seccomp` y `systempaths` sin confinar | `mcp/run_daemon.py:78-90` | S | 0.5 |
| B-08 | Comprobación de secretos de la entrega más estrecha que la redacción | `delivery.py:26-29, 213-247` | S | 0.5 |
| B-09 | Getters cacheados sin marca de obsolescencia; un registro inválido aborta la Run API; `diff` y `validation_result` libres en modo APPLIED | `mcp/quality.py:1100-1119`; `runs/store.py:194-200`; `llm/runtime.py:298-325` | S | 0.7 |
| B-10 | Higiene de evidencia: JSON duplicados byte a byte, 1747 trazas versionadas sin describir, snapshots de otra máquina, JSON de decisiones sin fecha ni commit | `evaluation/reports/`, `evaluation/evidence/archived/` | P | 0.7 |
| B-11 | Fallos de entorno no separados de las métricas de producto | Bind mount, `WorkspaceSyncError`, DNS, permisos Docker | X | 0.8 |
| B-12 | Ruff con 3 hallazgos y reglas implícitas; sin verificador de tipos; `run_cycle.main()` sin test | Ver [pruebas](06-pruebas.md) | E | 0.8 |
| B-13 | `PROJECT_STATE.md` con roles sombra desfasados; citas por número de línea que se pudren; mezcla de idiomas sin convención | `.gitignore:26` | S | 0.75 |

## Fusiones

Durante la consolidación, tres hallazgos resultaron ser el mismo mecanismo que
otro de mayor severidad y se retiraron sus identificadores: **M-01** se fusionó
en A-10, **M-04** en A-09 y **B-01** en A-03. No se reutilizan.

## Resumen

| Severidad | Cantidad | Verificados por el auditor principal (P) o por dos auditores (X) |
|---|---|---|
| Crítica | 4 | 4 |
| Alta | 14 | 14 |
| Media | 24 | 13 |
| Baja | 11 | 5 |
| **Total** | **53** | **36** |
