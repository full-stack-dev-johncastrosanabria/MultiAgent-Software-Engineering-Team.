# Fallos silenciosos y retrocesos con forma de éxito

Auditoría del 2026-09-16 sobre `gh-run-testing` @ `92742b7`. Fuente de
trabajo: auditor A8 ([papel de trabajo](anexos/A8-silent-failures.md)).
Referencias relativas a `src/engineering_team/`.

## Hallazgos

| ID | Severidad | Hallazgo | Verificación del auditor principal | Arreglo | Confianza |
|---|---|---|---|---|---|
| A-08 | Alta | **El barrido Docker trata un fallo de consulta o de borrado como «nada que limpiar».** `_listed` devuelve `set()` ante `OSError`, `SubprocessError` o código de salida distinto de cero (`docker_labels.py:92-102`); `_removed` descarta los borrados fallidos (`:116-128`); `apply_run.py:211` ignora el resultado de `sweep()`. El corredor de benchmark ya tiene `DockerQueryFailed` (`evaluation/benchmarks/ghcycle/run_cycle.py:36-56`) precisamente para distinguirlo, pero el código de producción no lo adoptó | **Verificado** en código. Coincide con recursos etiquetados sobrantes en `flaskapiproduct-dry-20260916a` (`container/aset-5a1c22db92d4-3`, `volume/aset-env-5a1c22db92d4`) y `…k` (`container/aset-spring-eval-mysql`, `network/aset-spring-eval-default`). Severidad ajustada de crítica a alta: es una fuga de recursos, no una decisión errónea del agente | Distinguir consulta fallida, nada encontrado y borrado fallido; registrar el reporte del barrido | 0.85 |
| M-06 | Media | **Errores de lectura y escritura del ledger de salud de modelos totalmente silenciosos.** `_load` devuelve `{}` ante JSON corrupto o error de E/S (`llm/model_health.py:108-114`); `_save` retorna sin registrar (`:127-138`) | **Verificado.** Un ledger con permisos rotos queda reiniciado en cada corrida sin rastro | Mantener la falla abierta, pero emitir advertencia o evento de traza | 0.7 |
| M-13 | Media | **Un `except` amplio en la cadena de nube puede disfrazar defectos internos como errores de proveedor.** `llm/cloud.py:629` captura `httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError` alrededor de petición y parseo | Plausible, no reproducido. Un `TypeError` de programación agotaría la cadena y aparecería como `CLOUD_FALLBACK_UNAVAILABLE` | Separar la llamada de red del parseo; registrar tipo y traza para `TypeError` | 0.5 |
| M-12 | Media | **Una suite Python con todos los tests omitidos cuenta como evidencia de camino feliz.** El perfil Python solo inspecciona la salida en la fase de seguridad (`mcp/quality.py:638-647`) y `agents/testing.py:164-170` acredita `happy_path` a cualquier `SUCCESS` sin `test_cases` | **Verificado en parte.** Pytest sale con código 5 si no recolecta tests, así que «0 tests» no es `SUCCESS`; el hueco real es «todos los tests recolectados fueron omitidos» (salida 0). JVM y .NET leen reportes y no tienen este hueco. Severidad ajustada de alta a media | Leer el resumen de pytest; 0 aprobados implica sin cobertura | 0.5 |

`_json_payload` (`llm/cloud.py:164-177`), que acepta un único bloque JSON
delimitado, fue revisado y **no** se considera defecto: cualquier otra forma pasa
sin cambios a la validación de esquema.

## Manejado correctamente (falla cerrada)

- Errores de proveedor transmitidos dentro de una respuesta 200,
  `finish_reason == "length"` como salida incompleta y contradicciones de campos
  gobernados se detectan explícitamente (`llm/cloud.py:566-581`).
- El detalle de `KeyError` se redacta sin perder la señal (`llm/cloud.py:215-221`).
- El error interno de .NET con salida cero nunca cuenta como escaneo completo; los
  reportes JVM se leen con `O_NOFOLLOW` (`mcp/quality.py:1388-1465`).
- La salida truncada se mapea a `UNAVAILABLE`, no a `SUCCESS` ni `FAIL`
  (`mcp/quality.py:718-722`).
- La agregación compuesta conserva la procedencia del escaneo de dependencias, la
  clase de fallo F-8 (`mcp/quality.py:1590-1599`).
- Reviewer tiene una compuerta de cobertura independiente del estado y rechaza
  evidencia que cita herramientas que nunca corrieron (`agents/reviewer.py:363-398`).
- La limpieza corre ante `BaseException` y re-lanza sin alterar
  (`apply_run.py:236-240`).
- `DeliveryRefused` falla cerrada y queda registrada en la evidencia
  (`delivery.py`, `apply_run.py:556-759`).
