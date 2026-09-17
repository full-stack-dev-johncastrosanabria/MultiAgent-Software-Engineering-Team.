# Auditoría de las 12 capas del agente

Auditoría del 2026-09-16 sobre `gh-run-testing` @ `92742b7` con el método
«agent-architecture-audit»: doce capas donde un envoltorio puede corromper,
ocultar o mutar el comportamiento del modelo. Fuente de trabajo: auditor A3
([papel de trabajo](anexos/A3-12-layer.md)). Referencias relativas a
`src/engineering_team/`.

**Salvedad de versión.** El export de Langfuse termina antes de `4ff4ae2`
(ledger de salud de modelos); lo dicho sobre el ledger se basa solo en código.

## Veredicto

**Salud general: alto riesgo.** No se encontró un camino donde el sistema
entregue código erróneo pasando una compuerta: las compuertas de escritura y
entrega aguantan. El fallo dominante es otro: **las capas envolventes terminan
corridas y desvían la remediación** antes de que exista un veredicto de
ingeniería. La capa 11 (bucles ocultos de reparación y reintento) es donde
mueren las corridas; la capa 4 (destilación) es donde se tuerce la remediación.

## Diagnóstico por capa

| Capa | Estado | Qué corrompe y por qué |
|---|---|---|
| 1 Prompt de sistema | Defecto | El prompt de Architecture pide «definir un diseño» y «decir si falta evidencia», pero el validador exige igualdad exacta con el candidato; los campos `evidence_sufficient` y `evidence_gap` se rellenan después de la llamada, así que un modelo que «lo dice» es rechazado (9/9 contradicciones de Architecture los incluyen). `system.md` de Testing y Reviewer nunca se envía; el contrato de salida de Developer se cambia por reemplazo literal de cadena (`llm/prompting.py:66-69`) |
| 2 Historia de sesión | Duplicación | Los valores gobernados aparecen cuatro veces: prompt de sistema, `const` del esquema, candidato e instrucción final. Architecture (eco) recibe 22 KB, 66 % de evidencia de repositorio; el planificador de Developer, mediana 51 KB y máximo 84 KB. Groq rechazó 18 de 21 llamadas de Developer por tamaño |
| 3 Memoria de largo plazo | Riesgo | El ledger `model-health.json` es memoria entre corridas: clave `rol\|proveedor\|modelo` sin stack ni proyecto; cuenta el estado de toda la suite como resultado de autoría ignorando `baseline_tests`; cuenta 413 como mala calidad; sin decaimiento; última escritura gana entre hilos de la Run API; ruta relativa al directorio de trabajo compartida por benchmarks y operador; el reordenamiento no se traza. Sin evidencia de ejecución |
| 4 Destilación | **Defecto grave** | Security construye un hallazgo de *baseline* con la cola de 2000 caracteres del escáner y la etiqueta «no enrutar a Developer»; Reviewer lo coloca **primero** en `problems`; `build_context` conserva solo los **últimos** 2000 bytes de cada problema (`models/context.py:199-201`), lo que borra la etiqueta, y el resto aparece bajo «FAILED ASSERTIONS AND OTHER REQUIRED DIAGNOSTICS» con la orden «Resolve every listed regression». 29 de 33 prompts de remediación de Developer (spring-demo) contienen la lista de CVEs ahí; en 17 de 33 falta el error de compilación que causó el fallo |
| 5 Recuperación activa | Estancada | El RAG consulta 6 textos distintos en toda la ventana: cada iteración recupera exactamente los mismos fragmentos; 30 % de las consultas vuelven vacías y la tarea Java recibe «C# and .NET Development Standards» 23 de 23 veces (dato de A4) |
| 6 Selección de herramientas | Sano | Los modelos no tienen API de herramientas; el orquestador llama a todas |
| 7 Ejecución de herramientas | Sano, con pérdida | Llamadas reales; en fallo JVM se descartan los resultados Surefire estructurados (`mcp/quality.py:1163-1168`) |
| 8 Interpretación | Defecto | El parser de fallos solo entiende líneas `FAILED` de pytest (`testing_evidence.py:42-56`); para Maven quedan colas de 4000 → 2000 → 600 caracteres que conservan el reporte de autoconfiguración y pierden la causa |
| 9 Forma de la respuesta | Riesgo latente | La redacción hacia la nube se aplica a todo el prompt, incluidos los archivos que Developer debe reescribir, pese al comentario de `llm/prompting.py:221-222`. `secret_key=[REDACTED]` es Python válido y pasa `ast.parse`; el bucle de escritura no rechaza el marcador. 18 de 90 prompts aceptados lo contenían; **ninguna salida aceptada ni ningún diff de las corridas lo escribió** (verificado por el auditor principal) |
| 10 Transporte y render | Defecto | La redacción por nombre de clave en Langfuse y en el flujo de eventos de la Run API sustituye el veredicto `authorization: PASS\|FAIL` del checklist OWASP por `[REDACTED]` (42 de 42 generaciones de Security); hay tres conjuntos de claves sensibles divergentes |
| 11 Bucles ocultos | **Defecto dominante** | Diez mecanismos pueden reemplazar, validar o reparar una salida (tabla abajo). La cadena conserva solo el error del último modelo; el grafo etiqueta como disponibilidad todo lo que no empiece con `LLM_QUALITY_ERROR` y el reintento de etapa reenvía prompts idénticos. 12 de 26 fallos de etapa ocultaban fallos de calidad previos; 10 de 16 reintentos volvieron a fallar. El autor cambia silenciosamente de modelo a mitad de remediación (traza `1885fc593d`: Cohere, Codestral, Cloudflare gpt-oss) |
| 12 Persistencia | Mayormente sana | Run store atómico y reconciliación de corridas interrumpidas. Excepciones: la colección RAG compartida se borra y recrea en cada corrida (`apply_run.py:357`), los getters cacheados no marcan obsolescencia y un registro inválido aborta el arranque de la Run API |

## Inventario de segundas pasadas (capa 11)

| # | Dónde | Qué hace | ¿Visible? | Contrato |
|---|---|---|---|---|
| 1 | `llm/cloud.py:622-628, 679-693` | El siguiente modelo de la cadena (hasta 10–11) reemplaza al que falló por HTTP, esquema, gobernanza o remediación ineficaz | Generación ERROR solo con metadatos; el error de etapa conserva el último | Implícito; tras un fallo de calidad cambia el modelo, no la entrada |
| 2 | `llm/cloud.py:466-475` | Espera al enfriamiento más próximo dentro del plazo del rol | No trazado; el mensaje habla de «budget» | Solo plazo |
| 3 | `graph/stategraph.py:633-658` | Runtime secundario (Ollama en modo nube) | Span «cloud fallback error» | Sin preflight; 0/26 |
| 4 | `graph/stategraph.py:660-667` | Reintento de etapa con entrada idéntica | Span WARNING | Reintentable si no empieza por `LLM_QUALITY_ERROR` |
| 5 | `llm/runtime.py:123-125` | Reintento local por disponibilidad | Metadato `retry` | `max_local_retries` |
| 6 | `llm/runtime.py:150-153, 169-183, 211-218` | Reparación local a ciegas o reemplazo del prompt por uno de eco | Metadato `repair` | Sin el error de validación; convierte una autoría en eco |
| 7 | `graph/stategraph.py:687-779` | Plan de destinos de Developer | Span «Developer target plan» | `validate_target_plan` (fuerte) |
| 8 | `llm/cloud.py:577-581` | Remediación byte-idéntica rechazada; otro modelo escribe | Generación ERROR | Solo igualdad de bytes |
| 9 | `llm/cloud.py:439-440` | Reordenamiento por ledger de salud entre corridas | No visible | Heurísticas del ledger |
| 10 | Bucle Reviewer → Developer/Architecture | Re-ejecución completa de etapas hasta 5 veces | Spans de ruta | Tope de iteraciones y huella volátil |

## Preguntas de diagnóstico rápido

| # | Pregunta | Respuesta |
|---|---|---|
| 1 | ¿El modelo puede saltarse una herramienta obligatoria y responder igual? | No: no tiene API de herramientas y Reviewer exige un `run_tests` real. Hueco residual: `diff` y `validation_result` libres en modo APPLIED |
| 2 | ¿Reaparece contenido viejo en turnos nuevos? | Sí dentro de la corrida (archivos rechazados se reinyectan; `remediation_request` llega a todos los roles; los CVEs previos vuelven como diagnóstico). Entre corridas, solo las etiquetas del ledger |
| 3 | ¿La misma información está en prompt, memoria e historia? | Sí: valores gobernados cuatro veces; roles eco con más de 15 KB de evidencia |
| 4 | ¿Hay una segunda pasada LLM antes de entregar? | Sí: diez mecanismos; 61 % de las generaciones falló |
| 5 | ¿La salida cambia entre generación y entrega? | Sí: veredicto `authorization` redactado en trazas y eventos; `review.reason` muestra el último error de transporte; salidas rechazadas nunca se conservan |
| 6 | ¿Hay reglas «debe usar X» solo en prompt? | No para herramientas. Sí para «ejecutar mentalmente cada test», «nunca añadir una dependencia» (parcialmente cubierta por reglas de manifiesto del plan) y «no añadir prosa» en roles eco |
| 7 | ¿El monólogo del agente puede volverse memoria persistente? | Dentro de la corrida sí (`file_contents` rechazados, `diff` del modelo en el reporte); entre corridas solo etiquetas de resultado |

## Hallazgos de esta sección

Identificadores del [registro consolidado](11-registro-de-hallazgos.md). Los
hallazgos ya confirmados por otras secciones (C-01, C-02, C-03, A-01, A-08, M-06)
no se repiten aquí.

| ID | Severidad | Hallazgo | Confianza |
|---|---|---|---|
| A-09 | Alta | Error de cadena sin tipo: se conserva solo el último error, los fallos de calidad se reportan como disponibilidad y el reintento de etapa repite entradas idénticas; 400 y 413 no enfrían | 0.9 |
| A-10 | Alta | Destilación que convierte riesgo de baseline en «aserción fallida» y pierde el error de compilación real (capa 4) | 0.85 |
| M-14 | Media | Redacción de salida a la nube aplicada a archivos que Developer debe reescribir, sin guardia contra escribir `[REDACTED]`; no observado en diffs | 0.8 mecanismo · 0.3 daño |
| M-15 | Media | Redacción por nombre de clave oculta el veredicto `authorization` de Security en trazas y eventos | 0.85 |
| M-16 | Media | Evidencia JVM estructurada descartada en fallo; parser de fallos solo para pytest | 0.7 |
| M-17 | Media | Contexto duplicado y sobredimensionado; sin presupuesto de bytes por proveedor | 0.8 |
| M-18 | Media | Reparación local a ciegas y fallback local muerto | 0.85 |
| M-19 | Media | Cambio silencioso de autor y planificador durante la remediación, contrario a la intención de `31defca` | 0.85 |
| B-05 | Baja | Colección RAG compartida reconstruida en cada corrida; consultas idénticas por iteración | 0.5–0.85 |
| B-09 | Baja | Getters cacheados sin marca de obsolescencia; un registro inválido aborta la Run API; `diff` y `validation_result` libres en modo APPLIED | 0.7 |

## Informe estructurado

El informe en el esquema `ecc.agent-architecture-audit.report.v1`, consolidado
con las demás secciones, está en [report.json](report.json).
