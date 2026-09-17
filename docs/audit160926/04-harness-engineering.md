# ASET frente a «Harness Engineering» (LunarResearcher)

Auditoría del 2026-09-16 sobre `gh-run-testing` @ `92742b7`. Fuente de
trabajo: auditor A2 ([papel de trabajo](anexos/A2-harness-engineering.md)),
adjudicado por el auditor principal. Referencias relativas a
`src/engineering_team/`.

Tesis del marco: muchas fallas de agentes son fallas del entorno, no del
razonamiento; un prompt cambia un intento y el arnés cambia todos. Se evaluaron
sus 19 secciones y los niveles L1–L6 del arnés mínimo viable.

**Advertencia de tiempo.** La última traza termina a las 00:11Z. Los commits
`4ff4ae2` (ledger de salud de modelos, 00:15Z) y `92742b7` (bloque PROJECT FACTS,
00:21Z) son posteriores a todas las corridas trazadas y no tienen evidencia de
ejecución. `workspace/model-health.json` no existe.

## Métricas de trabajo aceptado (§18)

| Métrica | Valor | Cómo se midió |
|---|---|---|
| Aceptación en primera pasada | **0/16** corridas trazadas; **0/27** reportes crudos ghcycle; **0/42** decisiones de Reviewer aprobadas | `output.status` raíz; `review.status` crudo; observaciones `Reviewer` |
| Rechazos plausiblemente falsos | ≥1: `apply-de2851ce` (traza `38863321ef`) tuvo 5/5 suites verdes con `createProductWithBlankNameShouldReturn400` y fue rechazada 4 veces por la compuerta léxica | `run_tests` `test_cases` y `problems` de Reviewer |
| Recuperación tras fallo de tests | **0/13** corridas con `run_tests` fallido volvieron a verde | secuencia de estados por traza |
| Recuperación tras fallo de modelo | reintento de etapa 6/16; fallback local Ollama **0/26** | eventos de reintento; generaciones `provider=ollama` |
| Por qué terminaron las corridas | 10/16 disponibilidad de LLM (Developer 6, Security 2, Architecture 2); 5/16 límite de iteraciones o estancamiento; 1 MCP no disponible (`WorkspaceSyncError`, el fallo conocido del bind mount); 1 traza sin nodo terminal | última ruta o error antes de `HUMAN_REVIEW_REQUIRED` |
| Tasa de fallo repetido | **22/27 (81 %)** transiciones de remediación repitieron la clase de fallo; el arnés lo detectó (`repeated_failures ≥ 2`) solo en 7 | problemas etiquetados por iteración |
| Intervenciones humanas por tarea | Toda corrida termina en revisión humana terminal; el operador relanzó Flask 11 veces y Spring 6 en un día, con 31 commits de arnés entre medio. Resultados confiables por unidad de atención: **0** | resultados a–k y a–f; git log |
| Afirmaciones de completitud sin sustento | 0 (nada se aprobó). **Recibo inexacto en 7/15** corridas con escrituras: los archivos de `applied_diff` no coinciden con `changed_files` | `applied_diff` frente a `changed_files` crudos |
| Tiempo hasta resultado verificado | Indefinido (ningún resultado verificado); 177 min de reloj en 17 trazas, media 10,4 min | inicio y fin por traza |
| Fallo de generaciones | **290/478 (61 %)**; 171 de ellas en Architecture y Security, cuyo resultado debe igualar o preservar un candidato determinista | GENERATION con `level=ERROR` por rol |
| Éxito estructurado por proveedor | cohere 58/63 · groq 46/95 · mistral 64/152 · xkiro 8/38 · vyce 3/11 · openrouter 4/56 · google 1/25 (google2 0/4) · cloudflare 3/4 · kilo 1/3 · nvidia 0/1 · ollama 0/26 | `metadata.provider × structured_output_success` |
| Costo | Los 0,0472 USD de Langfuse vienen de **una** generación `gemini-3.5-flash` que Langfuse tarificó por su cuenta; 477/478 generaciones cuestan 0. ASET no registra costo | `totalCost` y `modelId` por generación |

Sobrecarga por componente (17 trazas, 177 minutos):

| Componente | Minutos | Proporción | ¿Cambia el veredicto? |
|---|---|---|---|
| LLM de Developer (plan y autoría) | 46,2 | 26 % | Sí, escribe el código |
| **LLM de Security** (instruido a copiar el candidato) | **37,6** | **21 %** | No: estado, severidad y HITL están gobernados |
| **Escaneos de seguridad** (44 × `run_security_scan` y 44 × `scan_dependencies`) | **31,6** | **18 %** | Rara vez: 41/44 reportan los mismos CVEs previos |
| **LLM de Architecture** (debe igualar al candidato) | **15,5** | **9 %** | No |
| `run_tests` | 4,5 | 2,5 % | Sí, es la verdad del entorno |
| LLM de Product | 0,8 | <1 % | Cambia los términos de aceptación (ver C-04) |

## Tabla de las 19 secciones

| § | Sección | Veredicto | Brecha principal | Arreglo mínimo |
|---|---|---|---|---|
| 1 | El modelo no es el agente | Parcial | El arnés tiene la forma correcta, pero recuperación y prueba de completitud son débiles | Resolver C-01 a C-04 |
| 2 | Contrato de tarea | Parcial | Lo que no debe cambiar está en código (tests originales, manifiestos, rutas de credenciales; `contracts/developer_plan.py:106-201`), pero el resultado y la evidencia de completitud los redacta el LLM de Product en idioma variable; `--test-spec` se anexa como texto libre (`apply_run.py:322-323`) | Compilar la especificación de tests en un `AcceptanceContract` tipado y congelado |
| 3 | Mapa, no manual | Parcial | Diagnósticos ausentes para Developer en la ruta Architecture; CVEs previos consumen el presupuesto de diagnóstico; el prompt del planificador crece de 33 a 83 KB en 5 iteraciones; RAG de 6 guías genéricas con 38/128 recuperaciones vacías | Diagnósticos siempre a Developer; hallazgos previos fuera de `problems`; tope de inventario por iteración |
| 4 | Pasarela de herramientas | **Fuerte** | Entradas de escrituras y `run_tests` registradas como `"safe"`; sin memoización de escaneos idénticos | Registrar rutas y filtros; memoizar por hash de manifiesto |
| 5 | Cerebro, manos e historia | Parcial | No reanudable: checkpointer solo con `interactive_hitl` (`graph/stategraph.py:1033`), que producción nunca activa | Checkpointer persistente por `run_id` y endpoint de reanudación |
| 6 | Memoria como estado durable | Parcial | La única memoria entre corridas (`model-health.json`) no está validada, no distingue stack y cuenta fallos de entorno como fallos de autoría | Clave por stack, solo fallos inducidos por el cambio, ruta anclada |
| 7 | Completitud desde el entorno, chequeos baratos primero | Parcial | Orden invertido: Developer → Security (hasta 324 s) → Testing; el atajo `testing_only` es inalcanzable por la subcadena `"api"` | Compilar y testear antes de Security; baseline de seguridad única |
| 8 | Verificación adversarial | Parcial | Reviewer determinista y solo-rechazo (bien), pero su rúbrica de cobertura es léxica y no re-verifica el árbol final | Cobertura por identificadores de test declarados por obligación |
| 9 | El modelo propone, la política autoriza | Parcial | Escritura, entrega, roles y rutas están en código; la **salida de código fuente a proveedores** y el **gasto** no tienen política | Lista de proveedores permitidos por proyecto; tope de tokens o costo |
| 10 | Recuperación por clase de fallo | **Débil** | La huella de estancamiento hashea texto volátil; la ruta Architecture no converge; un fallo de entorno termina la corrida sin reintento; el fallback local falla 26/26 sin comprobación previa | Huella por (categoría, ids de tests fallidos, tipo de error); reintentar UNAVAILABLE una vez; preflight de runtimes |
| 11 | Instrucciones → infraestructura | Parcial | Siguen solo en prompt: «API ausente del classpath → dejar de usarla», los hechos de Boot 4, «toda clase referenciada debe existir» | Compuerta de compilación de tests tras la autoría |
| 12 | Observar la corrida | Parcial | Generaciones fallidas sin prompt; sin costo; aprobaciones fuera de la traza raíz; argumentos de `run_tests` no registrados | Uso → costo, banderas de aprobación y hash de prompt en fallos |
| 13 | Recibo de cambios | Parcial | `applied_diff` toma el **primer** `get_diff` (`apply_run.py:634-637`) aunque es acumulativo: 7/15 recibos erróneos; sin sección de riesgos no resueltos | Tomar el último diff; añadir `unresolved_risks` |
| 14 | Cada fallo mejora el arnés | Parcial | 47/55 commits desde el 09-10 tocan tests (bien), pero el 09-16 fue mayormente parcheo por corrida: 12 cambios de cadena de modelos, 3 ajustes a la compuerta léxica para que el modelo la satisfaga, una rotación revertida a los 52 minutos con n=2 | Conjunto congelado de fallos grabados reproducidos como tests de regresión |
| 15 | Los arneses decaen | **Débil** | Llamadas eco, fallback local, `security_hitl` inalcanzable, guardarraíles solo de tests y RAG sin valor medido | Aplicar la lista de eliminación |
| 16 | Arnés mínimo viable | L3 alcanzado; L4–L6 parciales o débiles | ver abajo | — |
| 17 | Especificación reutilizable | Parcial | La rúbrica de aceptación vive en tablas de palabras clave; la política de recuperación está repartida en routers, runtime, cloud y settings | Un módulo o documento de política por clase de fallo |
| 18 | Medir trabajo aceptado | **Débil** | El arnés no calcula ninguna de las métricas anteriores; todas se derivaron fuera de línea | Emitirlas por corrida en el recibo y agregarlas en ghcycle |
| 19 | Cuándo no hace falta un arnés pesado | **Débil** | Sin triaje: un filtro `?q=` de unas 10 líneas recorre seis roles, contenedores, OWASP dependency-check hasta 5 veces, reindexado RAG y hasta 5 ciclos | Vía rápida para cambios acotados: plan, autoría, compilación, test, revisión |

## Contraste con los artefactos del artículo

El primer texto del artículo que recibieron los auditores omitía sus bloques de
código y diagramas. Se recuperaron después de la API pública de fxtwitter y se
contrastaron con la tabla anterior. No cambian ningún veredicto; precisan estos
puntos:

| Artefacto del artículo | Lo que pide | ASET | Hallazgo |
|---|---|---|---|
| Clases de riesgo (§9) | Leer: automático · cambio reversible: automático con traza · **efecto externo: aprobación explícita** · irreversible o sensible: compuerta dura o prohibido | Leer es automático; escribir exige `--authorize-writes` (más estricto que el artículo); abrir un PR exige confirmación, backend y aprobación. **Enviar código fuente a un proveedor externo es un efecto externo y no tiene compuerta** | A-06 |
| Invariantes de política (§9) | Nunca publicar sin aprobación · nunca exponer un secreto · nunca escribir fuera del workspace · **nunca superar el tope de gasto** · **nunca marcar tests como pasados si no corrieron** | Los tres primeros están en código. No hay tope de gasto; una suite Python con todo omitido cuenta como camino feliz | A-02, A-06, M-12 |
| Clase de fallo → acción (§10) | Timeout de herramienta → reintento con espera · argumentos inválidos → reparar la llamada · contexto ausente → recuperar la fuente concreta · **test fallido → inspeccionar el comportamiento que falla** · permiso denegado → pedir aprobación o camino seguro · requisitos contradictorios → escalar · **fallo repetido sin cambios → detener el bucle** | Timeout o `UNAVAILABLE` → revisión humana sin reintento; salida inválida → siguiente modelo, no reparación; contexto ausente → re-lectura de Architecture con la misma ventana; test fallido → el diagnóstico no llega a Developer; fallo repetido → la huella volátil no lo detecta | M-09, A-09, C-02, C-01, C-03 |
| Bucle acotado (§10) | Observar → decidir → actuar → medir → aceptar, reparar, escalar o **parar** | Parar solo por tope de iteraciones o huella idéntica | C-03 |
| Escalera de verificación (§7) | Sintaxis → tipos → tests focales → integración → revisión semántica → aprobación humana, del más barato al más caro | `ast.parse` solo para Python; Security (lo más caro) antes que los tests; sin compilación tras la autoría en JVM y .NET | A-04, M-07 |
| Afirmación → evidencia (§7) | «El bug está arreglado» = el test que fallaba ahora pasa; «la tarea está completa» = pasa cada chequeo de aceptación | Aceptación por coincidencia léxica, no por tests declarados por obligación | C-04 |
| Verificador (§8) | Comprueba el contrato, busca casos faltantes, prueba afirmaciones sin sustento, intenta romper el resultado y **devuelve evidencia dirigida** | Reviewer comprueba y rechaza, pero la evidencia dirigida no llega al generador en la ruta Architecture | C-01, A-10 |
| Contrato de herramienta (§4) | Entradas, precondiciones, evidencia de éxito, comportamiento ante fallo («sin sobrescritura parcial»), clase de riesgo | Precondiciones y rutas en código; herramientas MCP sin descripción ni clase de riesgo declarada | B-04 |
| Estado durable (§6) | Hechos · decisiones · progreso · **lecciones** | Estado tipado por corrida; entre corridas solo etiquetas de resultado del ledger; sin lecciones ni formato de checkpoint | A-03, M-06 |
| Recibo de cambios (§13) | Objetivo · cambiado · verificado · **no verificado** · decisiones · riesgos · aprobación necesaria | Ruta, herramientas, uso de modelos, errores y archivos; diff equivocado; sin secciones de no verificado ni de riesgos | A-05 |
| Preguntas tras un fallo (§14) | ¿Contrato ambiguo? ¿Contexto invisible? ¿Herramienta equivocada expuesta? ¿Precondición ausente? ¿Resultado no verificable? ¿Política en el prompt? ¿Recuperación demasiado amplia? ¿Traza insuficiente? | El 09-16 los arreglos respondieron sobre todo «cambiar de modelo» y «enseñar palabras a la compuerta», no estas preguntas | M-03 |
| Especificación del arnés (§17) | Contrato, contexto (con reglas de frescura), herramientas, estado (con formato de checkpoint), política (con **límites de presupuesto**), verificación, recuperación (clases de fallo y límites) | Faltan límites de presupuesto, formato de checkpoint, reglas de frescura del RAG y un catálogo explícito de clases de fallo | A-02, A-03, B-05, A-09 |
| Métrica (§18) | Salidas aceptadas ÷ (minutos de revisión humana + costo de la corrida) | Numerador 0; ni los minutos de revisión ni el costo se registran, así que el denominador no se puede calcular | M-05, A-11 |

## Madurez L1–L6

| Nivel | Estado | Falta |
|---|---|---|
| L1 tarea acotada | Parcial | Resultado y aceptación redactados por LLM e inestables; sin presupuesto de gasto |
| L2 entorno legible | Parcial | Architecture ve como máximo unos 7 archivos; PROJECT FACTS sin validar; RAG genérico |
| L3 acciones controladas | **Fuerte** | Política de salida de código fuente |
| L4 ejecución durable | Débil | Sin checkpoint ni reanudación; revisión humana terminal |
| L5 evidencia | Parcial | Compuerta léxica, orden de chequeos invertido, diff del recibo erróneo, CVEs previos mezclados |
| L6 recuperación y aprendizaje | Débil | Detector de repeticiones ciego, bucle no convergente, 0/13 recuperaciones de tests, aprendizaje por commits de proveedor en vez de clases de fallo reproducidas |

El marco dice que la complejidad debe ganarse con fallos observados. ASET tiene
maquinaria de nivel L3 —seis roles, RAG, once proveedores, un ledger de salud—
apoyada en fundamentos L4–L6 que todavía no convierten un fallo en una
recuperación.

## Construir para borrar

| # | Componente | Qué previene | Costo observado | Veredicto |
|---|---|---|---|---|
| 1 | Llamada LLM de Architecture | Nada: la salida se descarta salvo que sea idéntica | 15,5 min, 91 generaciones fallidas, 2 corridas terminadas | **Eliminar** (añadir a la exclusión de `graph/stategraph.py:600`) |
| 2 | Llamada LLM de Security | En teoría, hallazgos adicionales; ninguno cambió una ruta | 37,6 min, 68 fallos (27 contradicciones gobernadas), 2 corridas terminadas | **Eliminar** o hacerla consultiva y asíncrona |
| 3 | `LocalModelRuntime` como fallback en modo nube | Caída de proveedor | 0/26 éxitos | **Eliminar** o condicionar a preflight |
| 4 | Nodo `security_hitl`, rama CRITICAL, `interactive_hitl` + `InMemorySaver`, `graph/hitl.py` | Nada en producción: inalcanzable | Complejidad y falsa sensación de reanudabilidad | **Eliminar** y sustituir por checkpointer real |
| 5 | `guardrails/routes.py`, `guardrails/timeouts.py`, `build_walking_graph` | Nada: solo tests | Mantenimiento | **Eliminar** |
| 6 | Reglas de palabras clave de `ProductAgent` | Escenarios de demo | Valores por defecto erróneos en repos reales | **Eliminar** y usar el contrato del operador |
| 7 | Escaneos de seguridad por iteración con manifiestos sin cambios | Regresiones por cambio de dependencias | 31,6 min (18 %) | **Sustituir** por baseline + re-escaneo si cambia un manifiesto |
| 8 | Cobertura léxica de `business_rule` y sus parches (`766e1e5`, `928503b`, `1b054ef`) | Tests verdes pero irrelevantes | ≥4 rechazos falsos en una corrida; sigue atrayendo parches | **Sustituir** por obligaciones de test declaradas en el plan |
| 9 | Re-enrutado a Architecture por razón de cobertura ([decisión 7](../architecture/decisions/0007-declared-coverage-decides-remediation.md) y su implementación) | Diseños sobre evidencia escasa | 9/9 trazas Flask atrapadas en bucle no convergente | **Reformular** (solo fronteras requeridas) o eliminar la rama de razón |
| 10 | Proveedores con <10 % de éxito estructurado: openrouter, google, google2, nvidia | Caídas en otros eslabones | Latencia, esperas por 429, superficie de salida de datos | **Quitar** de las cadenas |
| 11 | Ledger `model-health.json` | Orden de cadena obsoleto | Sin medir; riesgo de contaminación entre stacks | **Detrás de bandera** hasta un A/B reproducido; si no, eliminar |
| 12 | RAG sobre `knowledge/` con reindexado por corrida | Texto de diseño o seguridad sin fundamento | Carga de embeddings; `RAG_ERROR` puede rechazar corridas; lo consumen sobre todo roles eco | **Ablación**: conservar solo si la aceptación cambia sin él |

**Ganado y digno de conservar** (cada uno previene un fallo observado a bajo
costo): Testing y Reviewer deterministas, validación del plan de destinos,
autorización de escrituras, entrega con dos llaves, redacción antes de la nube,
tests de baseline, guardia de remediación byte-idéntica, normalización de
espacios al escribir, plazos por rol y enfriamientos con `Retry-After`.

> **Nota de adjudicación sobre la fila 9.** Verificado: la decisión 7 (aceptada el
> 2026-08-31, commit `3905bb6`) establece tanto el umbral de la mitad de los
> candidatos rankeados como el envío a Architecture de los fallos sobre evidencia
> escasa. Sus supuestos —«la remediación cambia lo que se lee» y «la ventana
> siguiente se gasta en evidencia no vista»— no se cumplen en las trazas: los
> términos de la retroalimentación **agrandan el denominador** (de 27 a 67
> candidatos en `a2cb449e2a`) mientras la ventana visible sigue fija en unos 7
> archivos. Como los registros de decisión son inmutables, el cambio requiere una
> decisión nueva que refine o reemplace la 7; no editar la existente.

## Respuestas a las preguntas del auditor principal

- **¿Developer conoce Spring Boot 4 frente a 3?** Antes de `92742b7`, solo como
  texto crudo de `pom.xml`; el modelo escribió imports de Boot 3 en 5 de 5
  iteraciones (`f9ca92d099`). Después recibe un bloque PROJECT FACTS ≤4 KB con
  notas de API de Boot 4 codificadas a mano (`project_facts.py:28-40`). Es solo
  prompt y no tiene evidencia de corrida.
- **¿`model-health.json` es estado durable o contaminación?** Estado durable con
  riesgo de contaminación: sin clave de stack, cuenta fallos de entorno como
  autoría, ventana por conteo sin decaimiento y ruta relativa al directorio de
  trabajo (`config.py:93`). Sin validar.
- **¿Una corrida puede reanudarse desde un checkpoint?** No.
- **¿Reviewer tiene rúbrica de rechazo y permiso para rechazar sin reparar?** Sí:
  es determinista y solo rechaza. Su rúbrica de cobertura es léxica y reutiliza la
  misma evidencia en lugar de re-verificar.
- **¿«Terminado» lo decide el entorno o el modelo?** El entorno, mediante código.
  La excepción son las dimensiones de cobertura, que vienen del texto del LLM de
  Product.
- **¿Se clasifica baseline frente a cambio, y entorno frente a código?** Tests: sí
  (`baseline_tests` + `classify_failures`). Seguridad: solo una heurística
  (manifiestos intactos y hallazgos confirmados, `agents/security.py:86-127`) que
  funcionó en 41/44 escaneos; aun así se re-ejecutan y contaminan los problemas de
  Reviewer. Entorno frente a código: no.
- **¿El seguimiento de costo es real?** No.
