# Historia documental

## 2026-09-10 — Política de recursos Docker, workspace efímero e infraestructura como prerrequisito

Se midió el host del operador y se limpiaron ≈ 14.3 GB de recursos Docker que
corridas anteriores dejaron atrás: un contenedor demonio, 33 volúmenes,
10 imágenes y 8.4 GB de caché de build. El inventario, el antes y el después y
los hallazgos están en [estado](status.md).

De ahí salen tres decisiones, **ninguna implementada todavía**:
la [16](architecture/decisions/0016-every-docker-resource-carries-its-run.md)
—todo recurso que un run crea lleva `aset.owner` y `aset.run`, y se recoge
incluso tras una caída—, la
[17](architecture/decisions/0017-the-project-lives-in-the-run.md) —el proyecto
vive en un volumen del run y no en el disco del operador, lo que exige extraer
un contrato `Workspace` de `RepositoryMCP`— y la
[18](architecture/decisions/0018-missing-infrastructure-is-a-blocking-prerequisite.md)
—la infraestructura que falta bloquea, se entrega en un PR propio y nunca se
improvisa.

Las tres se registran como decisión y no como trabajo hecho a propósito: el
sistema hoy se comporta como describe el estado, no como describen los récords.

La pregunta del operador sobre agrupar API, frontend y base de datos en un solo
contenedor por proyecto se resolvió el mismo día, tras un consejo de cuatro
voces: **no** un contenedor físico único —obligaría a un supervisor, un solo
PID 1 y un runtime que no se parece a cómo el proyecto despliega—, **sí** una
unidad de proyecto: proyecto compose nombrado `aset-<proyecto>` en lugar de
`aset-apply-<uuid4>`, más etiqueta `aset.project`. Queda en la decisión 16, con
su coste explícito: dos corridas simultáneas sobre el mismo proyecto se
rechazan por nombre.

Del mismo consejo salió una comprobación que corrige una premisa: el demonio por
run de la decisión 14 es **opt-in y está apagado por defecto**
(`quality_run_daemon_image` vacío en `config.py`), así que el camino por defecto
usa el demonio del host — que es exactamente donde se acumularon los 19 GB. Las
etiquetas no son redundantes con la decisión 14.

## 2026-09-10 — Retirada del sandbox de proceso: el contenedor es la única frontera

Se eliminaron `src/engineering_team/mcp/runner.py` (~1.025 líneas) y su suite
`tests/mcp/test_process_sandbox.py`. `CommandRunner` queda con una sola
implementación, `ContainerRunner`, y Docker pasa a ser dependencia dura para
correr el gate. El razonamiento completo, incluido lo que la retirada **no**
demuestra, está en la [decisión 15](architecture/decisions/0015-container-only.md);
la [decisión 10](architecture/decisions/0010-integration-tests-need-the-host-docker-api.md)
queda superseded en su elección de backend, pero su negativa a montar el socket
del host sigue vigente.

Esto es una eliminación de código funcional y revisado, no de código muerto. Se
hace porque la [decisión 14](architecture/decisions/0014-a-docker-api-that-is-not-the-hosts.md)
retiró la única razón que mantenía vivo el segundo backend, y porque mantener
dos implementaciones obligaba a argumentar cada cambio del gate dos veces. El
camino de vuelta es git, y volvería como decisión con la evidencia de plataforma
que hoy falta, no como fallback silencioso.

Lo que la retirada dejó a la vista importa más que lo que borró: al quedar el
contenedor como único camino que las pruebas ejercitan, aparecieron cuatro
defectos que el sandbox de proceso ocultaba —una ruta del host pasada a `ruff
--config`, un punto de montaje que convertía el proyecto en paquete de Python,
un proyecto sin restricciones que se quedaba sin intérprete y un piso
`>=3.10` leído como afirmación—. Los cuatro están corregidos en el mismo cambio
y descritos en la decisión 15.

Documentación corregida en el mismo cambio, en lugar de reescrita: la tabla de
soporte por plataforma de [estado](status.md), la fila de lint que citaba el
archivo eliminado, la afirmación de que `QUALITY_RUNNER=process` era el default,
`.env.example`, la insignia de aislamiento del README y dos correcciones
fechadas dentro de la decisión 14. El texto anterior no se borró donde
registraba algo que fue cierto; se anotó.

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
