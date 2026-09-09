# Historia documental

## 2026-09-09 — Corrección: las decisiones de arquitectura vuelven a la documentación activa

La reorganización del 2026-09-08 archivó los 24 archivos de `docs/architecture/`,
incluidos los trece registros de decisión aceptados, y dejó cinco directorios
vacíos. Fue un error de clasificación: un ADR aceptado no es documentación
relegada, es el diseño vigente que explica por qué el sistema es como es.

Se auditó cada registro contra el código antes de restaurarlo. Los trece
describen símbolos que siguen existiendo —`QualityMCP`, `CommandRunner`,
`StackProfile`, `ServiceStack`, `evidence_sufficient`, `quality_runner`,
`schema_template`, `INFRASTRUCTURE_ERROR`, `redact_secrets` y la superficie de
`delivery.py`— y ninguno contradice la implementación actual. Se restauraron con
sus bytes originales en `docs/architecture/decisions/`; la única edición fue
reparar seis enlaces a `../findings/README.md` y uno a `../roadmap.md`, cuyos
destinos sí quedaron retirados. Sus entradas se retiraron del manifiesto del
archivo, que pasó de 74 a 60 originales, porque no llegaron a estar retiradas.

Se descartó restaurar `roadmap.md`, `checklists/` y `findings/`: son
planificación y auditoría fechada, no diseño inmutable, y sus preguntas ya
tienen propietario en [estado](status.md). De ese registro se verificó su
conclusión abierta más relevante: el hallazgo 20 —escaneos de seguridad fijados a
`pip`/`ruff`— **está resuelto**, porque `scan_dependencies` y `run_security_scan`
expanden hoy `dependency_template` y `security_template` del perfil.

Los diagramas de `docs/diagrams/` no se restauraron sino que se regeneraron como
Mermaid embebido en `docs/architecture/`, porque el original describía
`HUMAN_REVIEW_REQUIRED` como salida exclusiva del Reviewer cuando el código lo
alcanza desde cualquier etapa. El directorio `docs/diagrams/` ya no existe.

Los tests documentales se actualizaron para expresar esta política en lugar de la
anterior: las decisiones son documentación activa con una página por registro, y
el índice debe listarlas todas.

## 2026-09-08 — Reorganización aprobada

Se retiró la documentación narrativa heredada y se reconstruyeron propietarios separados para mapa, operación, pruebas, estado e historia. La propuesta se aprobó contra `4294b9ef5904bed3b239a06c95e77491437b9aed`; los textos históricos no se utilizaron para inferir comportamiento actual.

El [archivo](deprecated/README.md) conserva originales, rutas y hashes. Los Markdown de prompts, RAG y benchmarks se conservan provisionalmente por su relación con el runtime, no por haber sido certificados como documentación vigente.

`AGENTS.md` define navegación y reglas documentales aprobadas; `CLAUDE.md` y Copilot remiten a los mismos propietarios. Los nuevos tests comprueban integridad y navegación en lugar de exigir frases o índices retirados.

Los movimientos exactos pertenecen al manifiesto del archivo y al diff de Git. Los resultados de ejecución pertenecen únicamente a [estado](status.md).

La revisión final corrigió la clasificación del README de la demo bancaria: sus consumidores lo interpretan como entrada de siete casos. Se restituyó sin alterar sus bytes y se conservó la copia archivada. El usuario confirmó conservarlo como README operativo en su ruta original, sin separar los casos. Esta excepción preserva sus consumidores; no lo convierte en documentación canónica del harness.

El usuario aprobó retirar también la instalación restante de SpecKit. Sus 28 archivos no Markdown se movieron al archivo y quedaron registrados en `specify-manifest.json`; no se mantienen scripts o manifests activos de ese flujo.

La aplicación bancaria que sirve como objetivo de evaluación se movió de `sample_app/` a `demo-projects/sample_app/`. Se actualizaron el runtime de evaluación, QualityMCP, scripts de arranque/parada, imports de tests y enlaces del mapa. El paquete principal conserva solo el código de ASET; la demo sigue siendo ejecutable desde su nueva ruta.

La carpeta `evaluation/` se reorganizó por ciclo de vida: entradas ejecutables bajo `benchmarks/`, snapshots bajo `reports/curated/`, resultados de runs bajo `reports/runs/`, salida transitoria bajo `reports/generated/` y evidencia histórica bajo `evidence/archived/`. Los consumidores de rutas fueron actualizados y los payloads no se editaron.
