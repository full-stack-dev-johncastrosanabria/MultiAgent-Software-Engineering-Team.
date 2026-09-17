# Gobernanza documental y deriva

Auditoría del 2026-09-16/17 con los métodos «living-docs-governance» (roles de
constitución, mapa, estado e historia; un propietario por hecho; zona de no
recrear) y «update-docs» (documentación contrastada con sus fuentes de verdad).
Fuente de trabajo: auditor A6 ([papel de trabajo](anexos/A6-docs-drift.md)). El
auditor principal verificó cada corrección antes de aplicarla.

## Mapa de roles

| Documento | Rol | Evaluación |
|---|---|---|
| [AGENTS.md](../../AGENTS.md) | Constitución y mapa de nivel superior | Correcto; una fila de prompts incompleta (corregida) |
| `CLAUDE.md`, `.github/copilot-instructions.md` | Adaptadores del arnés | Correctos: solo punteros |
| [README.md](../../README.md) | Portada del producto | **Repetía hechos con otro propietario** (valores de configuración, CLI, conteos, límite de iteraciones) y la mayor parte de la deriva estaba aquí |
| [docs/README.md](../README.md) | Mapa por tarea | Faltaban filas del código del 09-16 (añadidas) |
| [Arquitectura](../architecture/overview.md) | Composición implementada | Desfasada desde el 09-10 con 35 commits sobre el código descrito (corregida) |
| [Decisiones](../architecture/decisions/README.md) | Porqué | Índice coherente; la decisión 8 contradecía el código (corrección fechada añadida) |
| [Operaciones](../operations.md) | Instalación, configuración y ejecución | CLI y configuración incompletas; proveedores delegados al código (corregida) |
| [Pruebas](../testing.md) | Comprobaciones | No decía que la suite necesita entorno aislado ni daemon Docker (corregida) |
| [Estado](../status.md) | Evidencia y zona de no recrear | **Rol mezclado**: unas 736 líneas, cerca del 70 % bitácoras fechadas con forma de historia; desfasado tras el 09-14; sin tabla de estado vigente (añadida) |
| [Historia](../history.md) | Decisiones y retiros | Última entrada del 09-13 (entradas del 09-14, 09-16 y 09-17 añadidas) |
| `evaluation/*/README.md` | Mapas locales de evaluación (inglés) | No listaban ghcycle, los verificadores adr14/16/17/18 ni los reportes antiguos (corregidos) |
| `PROJECT_STATE.md` (ignorado por Git) | Handoff personal | Contiene secciones sombra de arquitectura, decisiones y «cosas que no hacer» fechadas entre el 09-01 y el 09-06; la sesión lo marca desfasado |
| Comentarios de `llm/cloud.py` y cuerpos de commits | Estado y zona de no recrear *de facto* para proveedores | **Evidencia fuera de su propietario** (resumen trasladado al estado) |

## Deriva: corregida en esta auditoría

| ID de A6 | Documento | Antes | Ahora |
|---|---|---|---|
| D-1, D-8 | README, arquitectura | «El tercer rechazo termina la automatización» | Límite `MAX_REMEDIATION_ITERATIONS` (5 por omisión) o tercera huella idéntica; segunda huella de implementación vuelve a Architecture; advertencia sobre huellas volátiles |
| D-2, D-3 | README | «`.env.example` documenta el conjunto»; columna «Por omisión» con valores de `.env.example` | `Settings` es la lista completa; columna «En `.env.example`» y valores de clase reales |
| D-4, D-5 | README | «72 archivos» de tests; «Catorce decisiones» | Sin conteos que envejecen |
| D-6, D-9, D-14 | README, arquitectura, operaciones | CLI sin `docker-sweep`, `--repo`, `--clone-depth`, `--report-path` | Superficie completa |
| D-7 | README | Extras sin `langchain-core` ni `quality-toolchain` | Extras completos |
| D-10, D-11 | Arquitectura | «groq · mistral · openrouter · google» y sin plan de destinos, hechos del stack ni ledger | Cadenas por rol con doce proveedores, ledger de salud, plan de destinos, hechos del proyecto, plazos de Developer, roles sin modelo y roles eco |
| D-12 | Arquitectura | Contenedor como única ejecución, sin variante `node` | Volumen nativo para `node` y `.git` de solo lectura |
| D-13, D-15 | Operaciones | «Proveedores y cadenas se implementan en llm» | Variables `CLOUD_CHAIN_<ROL>`, credenciales, plazos, `MODEL_HEALTH_PATH`, daemon por run; advertencia de salida de código y de la Run API sin guardia |
| D-16 | Pruebas | Sin requisito de entorno aislado | Receta de aislamiento, dependencia de Docker de 26 tests y fixtures sobrescribibles |
| D-17 | Decisión 8 | «Los hallazgos de política bloquean la aprobación» | Corrección fechada: excepción de baseline confirmada desde el 09-07/14 |
| D-18 | Decisión 17 | Sin mención del volumen nativo de `node` | Nota fechada que lo distingue de `VolumeWorkspace` |
| D-19 | Mapa | Sin filas para `model_health.py`, `developer_plan.py`, `project_facts.py`, `workspace_runner.py`, `test_scope.py` | Filas con implementación y tests |
| D-20 | AGENTS.md | «Un `system.md` por rol, cargado en ejecución» | Aclara que los `user.md` no se cargan y que Testing y Reviewer no envían su prompt |
| D-21, D-22 | READMEs de evaluación | Sin ghcycle, adr14–18, trazas antiguas ni duplicados | Descritos, con la advertencia sobre la semántica del scorer en seco |
| S-1 | Estado | «Falta habilitar la resolución de destinos» | Corrección fechada: `37c7400` la añade; 15/16 corridas escribieron archivos |
| S-2 | Estado | Sin las 18 corridas del 09-13/16 | Subsección con resultados, causa real de los dos «clone» fallidos e intercalado de commits |
| S-3 | Estado | Conteos de suite sin artefacto | Nota fechada y remisión a la ejecución sobre `92742b7` |
| S-4 | Estado | F-8 «decisión pendiente» | Actualización: implementada; Maven solo tras `b99c939` |
| S-5, S-6 | Estado | Bloques de la reorganización del 09-08 dentro del cierre del 09-13, bajo «esta revisión» | Encabezado fechado propio |
| S-7 | Estado | Decisiones 16–18 «ninguna implementada» | Corrección fechada |
| S-8 | Estado | Números de línea de Ruff y `config.py` movidos | Referencias por símbolo |
| S-9 | Estado | Sin volumen nativo de `node` | Nota fechada |
| S-10 | Estado | Proveedores del 09-16 sin evidencia registrada | Sección con sondas, medición de Langfuse y política de salida de datos |
| S-11 | Estado | Zona de no recrear sin retiros de LLM | Rotación revertida, SambaNova y modelos excluidos |
| H-1 | Historia | Sin entradas desde el 09-13 | Entradas del 09-14, 09-16 y 09-17 |
| Hallazgos A4 | Estado | Referencia a `adr14/results/report.json`, «0.000 s» de la decisión 17, F-7 sin nueva corrida | Ruta real, nota sobre ruido y nota sobre ausencia de corrida |

Además se añadió al estado una **tabla de estado vigente** (capacidad → última
evidencia → veredicto → pendiente), que era el rol ausente más importante.

**Registro de la auditoría en la comprobación documental.**
`tests/integration/test_documentation.py` exigía que toda página Markdown bajo
`docs/` fuera propietaria o decisión. Se añadió el concepto de auditoría fechada:
las páginas de `docs/audit*/` son activas (sus enlaces se comprueban), sus
`anexos/` son papeles de trabajo sin comprobación de enlaces, y cada auditoría
debe entrar desde el [mapa](../README.md).

## Deriva pendiente

| Asunto | Por qué no se aplicó | Recomendación |
|---|---|---|
| 10 campos de `Settings` ausentes de `.env.example` (entre ellos `MAX_REMEDIATION_ITERATIONS`, `DELIVERY_BACKEND`, `MODEL_HEALTH_PATH`) | Es configuración ejecutable, no documentación | Añadirlos o generar la tabla desde `Settings.model_fields` |
| Separar las bitácoras fechadas del estado hacia la historia | Movimiento grande que cambia anclas usadas por el mapa y la historia | Hacerlo en un cambio propio y actualizar las anclas |
| Decisión propia para la política de baseline de dependencias | Una decisión la toma el equipo | Registrar una decisión 19 que refine la 8 |
| Decisión que refine la 7 (razón de cobertura de Architecture) | Ídem | Ver C-02 en el [registro](11-registro-de-hallazgos.md) |
| Versionar los 18 JSON puntuados sin versionar | Decisión del operador; el repositorio no los incluye hoy | Versionarlos o dejar constancia de por qué quedan locales |
| Retirar o conectar los seis `user.md` | Decisión de producto | Añadir a la zona de no recrear si se retiran |
| Recortar `PROJECT_STATE.md` a handoff y protocolo | Archivo personal ignorado por Git | Sustituir sus secciones sombra por enlaces a AGENTS, arquitectura, decisiones y zona de no recrear |
| Pruebas de contrato documental que comprueben verdad, no solo estructura | Cambio de código de tests | Todo campo de `Settings` nombrado en `.env.example` u operaciones; todo comando Typer en operaciones; todo proveedor en arquitectura; ningún conteo literal en README |

## Hallazgos de esta sección

| ID | Severidad | Hallazgo | Estado tras la auditoría | Confianza |
|---|---|---|---|---|
| A-14 | Alta | La documentación no acompañó una jornada de 31 commits: afirmaciones erróneas sobre proveedores, límite de iteraciones, CLI y resolución de destinos; evidencia de proveedores y retiros solo en comentarios y commits; decisión 8 contradicha por el código | **Corregido** en documentos; falta la regla que lo evite | 0.9 |
| M-26 | Media | Hechos duplicados que divergen (README frente a operaciones y arquitectura) y comprobaciones documentales que verifican estructura, no verdad | README reducido a enlaces en los puntos corregidos; pruebas de verdad pendientes | 0.85 |
| B-13 | Baja | `PROJECT_STATE.md` con roles sombra desfasados; citas por número de línea que se pudren; mezcla de idiomas sin convención escrita | Pendiente | 0.75 |

M-20 (afirmaciones del estado sin artefacto) está en
[evidencia y métricas](02-evidencia-y-metricas.md).
