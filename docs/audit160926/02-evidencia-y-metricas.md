# Evidencia, corridas y métricas

Auditoría del 2026-09-16/17 sobre `gh-run-testing` @ `92742b7`. Fuentes de
trabajo: auditor A4 ([papel de trabajo](anexos/A4-evidence-metrics.md)),
conciliado con A2 y con el análisis propio del auditor principal sobre el export
de Langfuse. Todas las cifras se calcularon con scripts sobre los archivos
citados; aquí solo aparecen agregados.

## Base de evidencia

| Fuente | Contenido | Observación |
|---|---|---|
| Export de Langfuse (fuera del repositorio) | 2839 observaciones, 17 trazas, 2026-09-16 16:49Z → 2026-09-17 00:11Z | Cubre todo salvo los tres últimos commits (`4ff4ae2`, `31defca`, `92742b7`). La traza de flask-k está incompleta (faltan 33 observaciones de herramienta y el span de revisión humana) |
| `evaluation/benchmarks/ghcycle/results/*.json` | 26 corridas puntuadas: 8 versionadas y 18 sin versionar | `shallow-push.json` es una sonda, no una corrida |
| `evaluation/benchmarks/ghcycle/results/raw/*-run.json` (ignorado por Git) | 27 reportes crudos | Tres crudos del 09-12 sin JSON puntuado; dos corridas puntuadas sin crudo porque terminaron abruptamente |
| Resto de `evaluation/` | multistack, adr14/16/17/18, `reports/`, `evidence/archived/` | Inventario abajo |

Corrección al punto de partida de la auditoría: son **26** corridas puntuadas, no
25. Los conteos de error de Langfuse incluyen spans espejo: las 421 observaciones
`ERROR` son 290 generaciones, 79 `TOOL_ERROR`, 26 «cloud fallback error» y 26
`LLM_AVAILABILITY_ERROR`.

## Resultado principal

**Ninguna evidencia del arnés actual muestra trabajo aceptado.**

| Medida | Valor |
|---|---|
| Corridas ghcycle con todas las etapas | 0/26 |
| Corridas con reporte crudo aprobadas por Reviewer | 0/24 |
| Trazas raíz aprobadas | 0/16 |
| Decisiones de Reviewer aprobadas | 0/42 |
| Corridas con `run_tests` fallido que volvieron a verde | 0/23 |
| Corridas con escaneo de seguridad fallido que se recuperaron | 0/26 |
| PR entregados | 0 |

**Histórico no citado.** El 2026-09-03, con el arnés anterior a las compuertas
deterministas, FlaskApiProduct obtuvo **3 de 8** corridas APPROVED
(`evaluation/reports/apply-debugger-flask-writes-v4.json` en la iteración 0;
`-v7` y `-v8` tras tres iteraciones; verificado por el auditor principal). Todos
los subpuntajes de Reviewer valían 100, así que la calidad de esas aprobaciones
no está demostrada. Ningún documento cita esta evidencia, ni la posible regresión.

## Causas de fallo y de parada

Pareto de 138 resultados de herramienta no exitosos en las 26 corridas:

| Clase | Casos | % | Acum. | Corridas | Naturaleza |
|---|---|---|---|---|---|
| CVEs previos en dependencias | 70 | 51 % | 51 % | **23/23** que llegaron a Security | Preexistente; el cambio no puede arreglarlo |
| Aserción de test fallida (filtro `?q=` sin efecto) | 19 | 14 % | 64 % | 9 | Implementación del agente |
| Fallo del bind mount (`ENOTDIR`/`ENOENT`) | 12 | 9 % | 73 % | 4 | Entorno conocido del Mac |
| Símbolo ausente al compilar | 11 | 8 % | 81 % | 3 | Cambio incompleto (Spring) o referencias de proyecto (Banking, F-7) |
| Referencia de proyecto fuera del montaje (PropFlow) | 9 | 7 % | 88 % | 2 | Arnés (F-7), corregido después; **sin nueva corrida** |
| Causa perdida por el extracto de 600 caracteres | 8 | 6 % | 93 % | 5 | Pérdida de observabilidad |
| API de test de Spring Boot 3 en un proyecto Boot 4 | 7 | 5 % | 99 % | 2 (+3 en la corrida caída) | Falta de conocimiento del stack |
| `WorkspaceSyncError` | 2 | 1 % | 100 % | 1 | Entorno |

Causas de parada (24 corridas con reporte crudo y 2 caídas):

| Causa | Corridas |
|---|---|
| Cadena de proveedores LLM agotada | **13** |
| Límite de iteraciones (5) | 8 |
| Estancamiento detectado | 2 |
| MCP no disponible | 1 |
| Caída por entorno (DNS en sandbox) | 1 |
| Caída por `ValueError` del guardarraíl de nube en Architecture | 1 |

La primera clase de **fallo** es la baseline de CVEs; la primera causa de
**parada** es la disponibilidad de modelos. El conjunto de CVEs fue idéntico en
**28 de 28** re-escaneos consecutivos, y los 44 escaneos trazados reportaron los
mismos CVEs previos.

> **Conciliación A2–A4, verificada por el auditor principal.** A2 reportó «41/44
> escaneos con los mismos CVEs»; A4 encontró 44/44. Los 44 escaneos reportan el
> mismo conjunto por repositorio. La diferencia está en la clasificación: de las
> 42 decisiones de Security trazadas, **39 devolvieron `PASS` con el hallazgo
> «baseline dependencies»** y **3 devolvieron `FAIL` sin esa clasificación**,
> todas en spring-demo-a (traza `d29547c7b7`, anterior a `b99c939`, que corrigió
> el directorio de advisories de Maven).

## Métricas de Langfuse

### Por rol

| Rol | Generaciones | Éxito estructurado | Latencia p50/p95 (ms) | Tiempo LLM (s), en intentos fallidos | Errores principales |
|---|---|---|---|---|---|
| Developer | 209 | 90 (43 %) | 7981 / 45250 | 2774 (1267) | 429 (27), 413 (17), Ollama (14), timeout (13), 503 (12), plan rechazado (10), remediación sin cambios (7) |
| Architecture | 137 | 39 (28 %) | 1028 / 20149 | 929 (591) | **429 (66; mistral-medium 46/46)**, campos gobernados (9), 413 (6), 503 (5) |
| Security | 115 | 42 (37 %) | 16106 / 55396 | 2259 (**1678, 74 %**) | **campos gobernados `findings` (26+)**, salida incompleta (15), 400 (7) |
| Product | 17 | 17 (100 %) | 2920 / 3330 | 49 | — |
| Testing y Reviewer | 0 | deterministas | — | — | — |

### Por proveedor y modelo (principales)

| Proveedor | Modelo | Intentos | Éxito | Errores principales |
|---|---|---|---|---|
| cohere | command-a-03-2025 | 63 | **92 %** | campos gobernados ×5 |
| mistral | codestral-latest | 87 | 74 % | campos gobernados ×9, timeout ×7, remediación sin cambios ×5 |
| groq | openai/gpt-oss-120b | 95 | 48 % | **413 ×23** (no reintentable, repetido entre corridas), 429 ×14, 400 ×8 |
| xkiro | deepseek-v4-pro | 10 | 50 % | 429 ×5 |
| openrouter | nemotron-3-super gratuito | 56 | 7 % | campos gobernados ×29, incompleta ×13 |
| mistral | mistral-medium-latest | 46 | **0 %** | **429 ×46** (cabeza de la cadena de Architecture) |
| mistral | mistral-small-latest | 19 | 0 % | 429 ×19 |
| google | gemini-3.5-flash | 21 | 5 % | 503 ×13, timeout ×4 |
| ollama | qwen3.5:9b y 4b | 26 | **0 %** | HTTPStatusError en unos 50 ms (servidor no alcanzable) |

Categorías a nivel de generación (290): 429 = 98 · campos gobernados = 55 ·
Ollama sin categoría = 26 · 413 = 23 · 503 = 21 · salida incompleta = 16 ·
timeout = 15 · 400 = 13 · no disponible transmitido = 8 · remediación sin
cambios = 7 · 500 = 4 · esquema = 2 · respuesta inválida (`KeyError` de F-9
funcionando) = 2.

### Tiempo

De 10 624 s de reloj en 17 trazas: **espera de LLM 6010 s (57 %)**, de los cuales
**3536 s (33 % del total) en intentos que fallan**; herramientas 2165 s (20 %):
escaneo de seguridad 1414 s (13 %; 321 s en re-escaneos idénticos), dependencias
481 s, tests 270 s (2,5 %); sin atribuir (arranque de contenedores, sincronización
de workspace, embeddings) 2449 s (23 %). Mediana por corrida: 667 s; máximo
1366 s.

### Recuperación documental (RAG)

- 128 recuperaciones, solo **6 consultas distintas**: cada iteración recupera
  exactamente los mismos fragmentos y no aporta información nueva al bucle.
- **38/128 (30 %) vacías**: Architecture sobre Flask 28/28 y sobre Spring 10/14.
- La tarea Java/Spring recibe «Coding Standards / C# and .NET 10 Development
  Standards» **23 de 23 veces** en Testing; Security para Flask recibe «Password
  Hashing» siempre.
- Nunca se recupera código del proyecto, versiones del framework ni guía de API
  de test de Boot 4, lo que coincide con la causa de compilación Boot 3.

### Telemetría

- `fallback_used` es falso en 478/478 generaciones, aunque 452 corrieron con perfil
  `CLOUD_FALLBACK`: el runtime de nube es primario y el campo se calcula como
  `not self.primary` (`llm/cloud.py:607`). Campo muerto.
- Costo presente en **1/478** generaciones (el precio que Langfuse asignó a una
  llamada Gemini: 0,0472 USD). Tokens solo en éxitos: 1 555 919, sin contar los 23
  prompts rechazados por tamaño.
- Las 1649 observaciones de herramienta tienen `latencyMs=0` y cuelgan planas de la
  raíz, no del agente ni de la iteración.
- La revisión humana no tiene motivo legible por máquina: el span solo trae
  `{hitl, iteration}`.
- **Traza `b798793c96`** = `spring-demo-dry-20260916c`: interrumpida por un
  `ValueError: sensitive content is not allowed in cloud context` no capturado
  durante la tercera pasada de Architecture; sin reporte crudo ni span raíz; el
  scorer la registró como fallo de **clone** (verificado en su `cli_stderr_tail`).

## Métricas de trabajo aceptado (§18 de Harness Engineering)

| Métrica | Valor conciliado |
|---|---|
| Tasa de trabajo aceptado | 0 en el arnés actual; 3/8 en el arnés del 09-03 (sin calibrar) |
| Aceptación en primera pasada | 0 actual; 1/8 histórica |
| Fallo repetido | Mismos CVEs 28/28; mismo conjunto de tests fallidos en 14/22 pares consecutivos; diff idéntico en 11/28; clase de fallo repetida en 22/27 transiciones (81 %), detectada 7 veces |
| Reintentos sin cambio no detectados | spring-e: 4 diffs idénticos consecutivos con los mismos errores Boot 3 y **0** detecciones de «remediación sin cambios» |
| Recuperación tras fallo de herramienta | 0/23 (tests), 0/26 (seguridad) |
| Recuperación tras fallo de modelo | 96/106 grupos de etapa se recuperan dentro de la cadena (91 %); una vez agotada, el reintento de etapa recupera 6/16 y 13 corridas terminan ahí |
| Intervenciones humanas por tarea | 1,0; el 09-16 hubo 17 relanzamientos y 31 commits (1,8 cambios de arnés por corrida) |
| Afirmaciones de completitud sin sustento | 0 a nivel de corrida; a nivel de scorer, 21/26 aprobados vacíos, 1 clone mal atribuido y «archivos escritos» inflado en 10/15; a nivel documental, conteos de tests sin artefacto |
| Tiempo hasta resultado verificado | Indefinido |

**Intercalado de commits y corridas el 09-16.** 31 commits y 17 corridas alternan
casi uno a uno; cuatro commits llegaron **durante** corridas (`eaa0aa3` en
flask-c, `7af574e` en flask-i, `c2d29d2` y `004b612` en spring-b); ninguna
corrida registra su commit.

## Defectos del scorer `run_cycle.py`

| # | Defecto | Referencia | Efecto |
|---|---|---|---|
| S1 | `infrastructure.passed` es verdadero siempre que no haya entrega | `run_cycle.py:113-118` | 21/26 aprobados vacíos |
| S2 | `delivery.passed = not delivered or url`, con `skipped=true` al lado | `run_cycle.py:174-180` | 21/26 aprobados vacíos; el [estado](../status.md) lo advierte, el scorer sigue igual |
| S3 | `clone.passed` significa «existe un reporte» | `run_cycle.py:109-112` | spring-demo-c clonó y corrió tres iteraciones; se puntuó como fallo de clone |
| S4 | «N archivos escritos» cuenta operaciones | `run_cycle.py:171` | flask-j «11» = 4 archivos distintos |
| S5 | Higiene global, no acotada a la corrida | `run_cycle.py:59-95` | flask-k falla por recursos de otra evaluación |
| S6 | `reviewer said None` cuando nunca se llegó a Reviewer | `run_cycle.py:171` | Una caída de proveedor parece un defecto de revisión |
| S7 | No registra commit, especificación, cadena de modelos, horas ni SHA del objetivo | `run_cycle.py:239-246` | Resultados no atribuibles a una versión |
| S8 | `cli_stderr_tail` lleno de avisos y barras de progreso de Hugging Face | JSON puntuado | La señal de caída sobrevive por azar |

## Inventario de evidencia en `evaluation/`

| # | Familia | Afirmación que sostiene | ¿Reproducible? | ¿Obsoleta frente a `92742b7`? | ¿Citada correctamente en el estado? |
|---|---|---|---|---|---|
| 1 | ghcycle versionado (8) | La campaña de 4 repositorios no cumple aceptación | Parcial: sin commit, especificación ni cadena | Sí | **Sí**: tabla de etapas y conteos 97/31/36/102/103/95/67 exactos |
| 2 | `shallow-push.json` | Push desde clon superficial aceptado | Sí, con credenciales | Baja | Sí, con alcance honesto |
| 3 | ghcycle sin versionar (18) | 0/18 etapas completas | Parcial | Es la evidencia más nueva | **No citada** |
| 4 | ghcycle crudo (27, ignorado) | Recibos completos | No para terceros | — | Sí |
| 5 | `multistack/baselines.json` | Baseline independiente de 3 repos externos | Sí | Baja | No citada |
| 6 | `multistack/cases`, fixtures, `run_trial.py` | Entradas del benchmark | Entradas | — | Sí |
| 7 | `multistack/gemini-key2-probes.json` | Sonda de gemini-3.1-flash-lite | Parcial | **Sí** | No citada |
| 8 | adr14 trials 1–4 | Red cerrada dind; trial 4 SUCCESS con 75 tests | Sí | Moderada | Sí, pero el estado cita un `adr14/results/report.json` **inexistente** |
| 9 | `adr16/results/report.json` | Etiquetas y barrido 5/5 | Sí; JSON sin fecha ni commit | Baja | Sí |
| 10 | `adr17/results/*.json` | Costos de volumen; workspace 9/9 | Sí; JSON sin fecha ni commit | **Sí** (`da8558f`) | 9/9 sí; la tabla muestra «0.000 s» que son valores negativos recortados: ruido presentado como costo cero |
| 11 | `adr18/results/verification.json` | Prerequisito de infraestructura 11/11 | Sí; JSON sin fecha ni commit | Moderada | Sí |
| 12 | `reports/curated/` | Escenarios, agregados y pytest | Parcial | **Muy obsoleta**: el XML es de 103 tests del 2026-08-25 en Windows; A5 recolecta 1270 | No citada; dos tests e2e afirman sobre estos JSON congelados |
| 13 | `reports/runs/*.json` | Demos APPROVED y otras corridas HRR | No | Sí | No citada |
| 14 | `reports/traces/` (1747 versionadas) | Registros de eventos | No | Sí | No citada ni descrita en su README |
| 15 | `reports/generated/traces/` (ignorado) | Transitoria | — | — | — |
| 16 | `apply-debugger-flask-writes*.json` (8, duplicados byte a byte en `evidence/archived/`) | **3/8 APPROVED en FlaskApiProduct** | No | Sí | **No citada** |
| 17 | `reports/ui-audit-2026-08-27.*` (ignorado) | Prueba manual de UI en macOS | Manual | Sí | No citada |
| 18 | Export de Langfuse | 17 trazas de la campaña del 09-16 | Solo export | Salvo los 3 últimos commits | No citada |

## Contraste de afirmaciones del estado

| Afirmación | Evidencia encontrada | Veredicto |
|---|---|---|
| Tabla de siete resultados y conteos de herramientas | JSON puntuado y crudo coinciden | ✓ Sostenida |
| Corrida corregida del 09-14: 62 tests de backend verdes en 3 iteraciones | Crudos: «62 passed» en los tres extractos | ✓ Sostenida |
| Las tres propuestas quedaron en `PROPOSED` | Crudos: `action_mode=PROPOSED`, 0 escrituras | ✓ Sostenida para esas corridas; **superada** por `37c7400` (ver el estado actualizado) |
| Transporte de 4 MiB para escáneres estructurados | `mcp/command.py:19-20`; los escaneos del 09-16 traen advisories completos | ✓ En código; el conteo de 111 tests no tiene artefacto |
| F-8: CVEs previos clasificados como riesgo de baseline | spring-demo-a (09-16 13:29, después de `d6b503c`) siguió REJECTED por seguridad; Maven solo funcionó tras `b99c939` (15:55) y el bucle continúa | ⚠ **Exagerada** |
| F-7 corregido; Banking con 71 tests originales verdes | Sin nueva corrida de PropFlow ni Banking; sin artefacto de los 71 tests ni de los 156 focales | ⚠ Sin evidencia persistida |
| F-9: `KeyError` informa solo claves de protocolo | Traza: `missing response field 'choices'` ×2 | ✓ Sostenida |
| Suite integrada del 09-14: 1038 aprobadas y 17 omitidas; Task 7: 978 PASS, 20 SKIP | Sin log, XML ni commit; en `92742b7` se recolectan 1270 tests | ⚠ Sin artefacto; no reproducible |
| MySQL `healthy` según captura | Sin captura en el repositorio | ⚠ Sin artefacto |
| `adr14/results/report.json` | No existe; los reportes viven en `reports/runs/adr14-trial-*` | ✗ Referencia rota |
| Encabezado «Base inspeccionada: 4294b9e…» | Rama y HEAD actuales distintos | ✗ Obsoleto |

## Hallazgos de esta sección

| ID | Severidad | Hallazgo | Confianza |
|---|---|---|---|
| A-02 | Alta | La disponibilidad de modelos, no el razonamiento ni el presupuesto, termina la mayoría de las corridas (13/24); configuraciones que nunca se recuperan siguen en las cadenas | 0.85 |
| A-11 | Alta | El scorer ghcycle produce etapas vacías o mal atribuidas y resultados no atribuibles a un commit | 0.85 |
| A-12 | Alta | La evidencia de diagnóstico pierde información justo donde vive la causa raíz (extractos de 600 caracteres, diff capado, herramientas sin tiempo) | 0.85 |
| M-07 | Media | La brecha de conocimiento del stack causa los fallos de compilación; el arreglo (`92742b7`) es solo prompt y no tiene corrida; el RAG recupera estándares de otro lenguaje | 0.75 |
| M-20 | Media | El estado contiene conteos de tests sin artefacto, afirmaciones exageradas (F-8) o sin nueva corrida (F-7), una referencia rota y no registraba la campaña del 09-16 | 0.8 |
| M-21 | Media | Una negativa del guardarraíl de nube hace caer la corrida sin reporte en lugar de degradarla | 0.8 |
| M-22 | Media | Regresión no documentada: el único trabajo aceptado en un repositorio externo (09-03) no se cita ni se compara con el arnés actual | 0.8 |
| B-10 | Baja | Higiene de evidencia: 8 JSON duplicados byte a byte, 1747 trazas versionadas sin describir, snapshots de pytest de otra máquina, JSON de decisiones sin fecha ni commit | 0.7 |
| B-11 | Baja | Los fallos de entorno (bind mount, `WorkspaceSyncError`, DNS, permisos Docker) no se separan de las métricas de producto | 0.8 |

Los hallazgos C-03 (reintentos sin cambio), C-04 (compuerta léxica) y M-05
(telemetría muerta) también se apoyan en esta evidencia; ver el
[registro consolidado](11-registro-de-hallazgos.md).
