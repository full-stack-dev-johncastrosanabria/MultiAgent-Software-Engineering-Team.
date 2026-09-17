# Plan de remediación

Orden derivado del [consejo](10-consejo.md) y de la regla del método de 12 capas
(primero código, después prompt), con la disciplina de Harness Engineering: cada
fase se mide antes de pasar a la siguiente y la complejidad solo se añade si un
fallo observado la justifica. Los identificadores remiten al
[registro](11-registro-de-hallazgos.md).

Este plan es una recomendación de auditoría. No se aplicó ningún cambio de código
del producto; solo se corrigió documentación y se registró la auditoría en la
comprobación documental.

## Fase 0 — Contener (horas, sin código)

| Acción | Hallazgos | Cómo | Criterio de salida |
|---|---|---|---|
| No correr sobre repositorios privados con las cadenas actuales | A-06 | `CLOUD_CHAIN_PRODUCT`, `CLOUD_CHAIN_ARCHITECTURE`, `CLOUD_CHAIN_DEVELOPER` y `CLOUD_CHAIN_SECURITY` restringidas a proveedores aprobados; retirar del `.env` las credenciales de pasarelas no aceptadas | Cada cadena contiene solo proveedores aprobados por escrito |
| Congelar el código durante una campaña | M-03, A-11 | Ninguna corrida se lanza con cambios sin commit ni durante un commit; anotar el SHA a mano hasta que el scorer lo registre | Cada resultado tiene su SHA |
| Desactivar el ledger de salud de modelos hasta validarlo | M-06 | `MODEL_HEALTH_PATH=` vacío (`apply_run.py:347` construye `health=None`) | Orden de cadena determinista entre corridas |
| Quitar de las cadenas lo que nunca responde | A-02 | Retirar de las cadenas mistral-medium (cabeza de Architecture) y mistral-small, ambos con 429 en todos sus intentos; el Ollama local en modo nube si no está levantado; y los modelos con <10 % de éxito estructurado | Ningún modelo con 0 % en la última medición |

## Fase 1 — Medición confiable (1–2 días)

| Acción | Hallazgos | Arreglo en código | Prueba que lo demuestra |
|---|---|---|---|
| Scorer atribuible | A-11, B-11 | Registrar SHA de ASET, especificación, cadena efectiva, horas y SHA del objetivo; estado «no ejercitado» distinto de «aprobado»; `clone` según el clon real; causa de parada; fallos de entorno separados | Tests de `_score` para corrida en seco, caída de guardarraíl y fallo de entorno; test de `main()` |
| Recibo correcto | A-05 | Último `get_diff` en `apply_run.py:634-637`; sección de riesgos no resueltos | Test con dos diffs |
| Telemetría útil | M-05, A-12 | `fallback_used` real; salida rechazada redactada y acotada con la regla violada; motivo tipado de la revisión humana; uso y costo por generación; duración y padre en observaciones de herramienta; extracción de errores Maven y Surefire desde el inicio | Test de traza para fallo de cadena |
| Gate de tests honesto | A-13, M-24 | `skipif` que compruebe el daemon; parchear `require_available` en tests con mocks; `conftest.py` que aísle `Settings` y Langfuse; hook versionado con instrucción de instalación | La suite sin Docker termina verde con omisiones explicadas |
| Conjunto de reproducción | C-01 a C-04, A-10 | Congelar como fixtures los sobres y decisiones reales de las 26 corridas (incluidas `a2cb449e2a`, `f9ca92d099`, `38863321ef`) | Tests de enrutado y compuerta que hoy reproducen el fallo |
| Calibrar la aceptación | C-04, M-22 | Pasar a Reviewer parches malos conocidos; lectura humana de los diffs finales de las 26 corridas; comparar el arnés del 09-03 con el actual | Reviewer rechaza todos los parches malos; tabla de diffs aceptables por humano |

El conjunto de reproducción prueba que el **enrutado** cambió; no puede probar
que Developer ahora escriba código que pase, porque esa salida viene de un modelo
vivo. Eso lo mide la fase 3.

## Fase 2 — Borrar y desbloquear (≈1 día; primero código)

| Orden | Acción | Hallazgos | Arreglo |
|---|---|---|---|
| 1 | Quitar las llamadas eco | A-01, M-18 | Añadir Architecture, Security y Developer en modo PROPOSED a la exclusión de `graph/stategraph.py:600-603` |
| 2 | Diagnóstico siempre a Developer | C-01, A-10 | En `build_context`, adjuntar los fallos de test a Developer sin depender de `return_to`; sobre tipado sin riesgo de baseline |
| 3 | Enrutado a Architecture solo por fronteras | C-02 | Razón de cobertura consultiva; volver a Architecture solo si la pasada anterior aumentó fronteras visibles; **decisión nueva** que refine la 7 |
| 4 | Aceptación por contrato del operador | C-04, M-08 | Obligaciones de aceptación con ids de test (extensión de la [decisión 11](../architecture/decisions/0011-the-operator-states-which-tests-the-gate-runs.md)); cobertura léxica consultiva |
| 5 | Huella por clase de fallo | C-03 | (categoría, ids de tests fallidos, primer tipo de error o símbolo, hash del diff) |
| 6 | Seguridad de baseline una vez | A-04 | Escaneo previo a escribir; re-escaneo solo si cambia un manifiesto; compilar y testear antes de Security; señal de superficie por palabra completa; **decisión 19** que refine la 8 |
| 7 | Fallo de cadena tipado | A-09, A-02, M-13 | `ChainFailure` con categorías; reintento solo si cambió una condición de disponibilidad; enfriar 400 y 413 por tamaño; preflight del runtime secundario |

## Fase 3 — Experimento discriminante (2–3 días)

- **Condiciones fijas:** mismo commit congelado, mismo modelo de pago fiable por
  rol, mismas compuertas deterministas, mismos requisitos (filtro `?q=` en
  FlaskApiProduct y validación de nombre en spring-demo).
- **Brazos:** ASET tras las fases 0–2 frente a un agente de código estándar como
  control, con herramientas de lectura, búsqueda, edición y test dentro del mismo
  sandbox.
- **Criterio fijado antes de correr** (propuesta): al menos 2 aprobaciones en 8
  corridas por requisito, diffs aceptables para una persona, tests originales
  intactos, cero afirmaciones de completitud sin sustento.
- **Diagnóstico opcional de regresión:** correr el arnés del 09-03 con los
  proveedores de hoy. Si también da 0, cambiaron los proveedores, no el workflow.

## Fase 4 — Decidir

| Resultado | Decisión |
|---|---|
| ASET cumple el criterio | Continuar con el resto: checkpoint y reanudación (A-03); compuerta de compilación tras la autoría y hechos del stack validados (M-07); ledger endurecido o retirado (M-06); corrección de redacción (M-14, M-15); higiene de prompts y contexto (M-02, M-17); ablación del RAG (B-05); artefactos muertos (B-03) |
| El control cumple y ASET no | Registrar una decisión hacia un único agente de código que conserve compuertas, sandbox, redacción y entrega con dos llaves |
| Ninguno cumple | El problema está en la aceptación, en el modelo o en el alcance de los requisitos; revisar antes de invertir en arquitectura |

## Líneas paralelas

| Línea | Hallazgos | Acciones |
|---|---|---|
| Seguridad | A-07, M-10, M-11, B-07, B-08 | Salida limitada a registros durante instalaciones; pasada de entropía y corpus adversarial de redacción; guardia de loopback o token en la Run API; detectores de forma en la comprobación de la entrega |
| Documentación | A-14, M-20, M-26, B-13 | Regla en AGENTS.md: un `feat:` o un `fix:` que cambie evidencia actualiza su propietario o explica por qué no; pruebas documentales de verdad (campos de `Settings`, comandos Typer, proveedores); mover bitácoras fechadas del estado a la historia; recortar `PROJECT_STATE.md` |
| Pruebas | M-23, M-25, B-12 | Negativos de entrega; límite de presupuesto en modo nube; reglas gobernadas de Security, Testing y Reviewer; redacción verificada en el cuerpo HTTP; snapshots de evidencia fuera del gate |

## Métricas por corrida

Emitirlas en el recibo y agregarlas en ghcycle (Harness Engineering §18):

| Métrica | Hoy |
|---|---|
| Trabajo aceptado | 0/26 |
| Aceptación en primera pasada | 0 |
| Tasa de fallo repetido | 81 % de transiciones |
| Recuperación tras fallo de herramienta | 0/23 |
| Intervenciones humanas por tarea | 1,0 |
| Afirmaciones de completitud sin sustento | 0 en corridas; 21/26 aprobados vacíos en el scorer |
| Tiempo hasta resultado verificado | Indefinido |
| Proporción de reloj en intentos fallidos | 33 % |
| Costo por corrida | No registrado |

## Criterio de cierre de la auditoría

La auditoría se considera atendida cuando los cuatro hallazgos críticos están
resueltos con tests de reproducción, la fase 3 cumple su criterio fijado de
antemano y el [estado](../status.md) registra esa evidencia con su commit.
