# Estado y límites de evidencia

## Estado vigente (auditoría del 2026-09-16)

Base: `gh-run-testing` @ `92742b7`. Resume el veredicto actual por capacidad;
las secciones fechadas que siguen conservan la evidencia de cada medición. El
detalle, las cifras y el método están en la
[auditoría del 2026-09-16](audit160926/README.md).

| Capacidad | Última evidencia | Veredicto | Pendiente |
|---|---|---|---|
| Cambio aceptado sobre un repositorio real con el arnés actual | 26 corridas ghcycle (2026-09-12 a 16) y 16 trazas raíz de Langfuse | **Fallando**: 0 aprobadas, 0 PR; toda corrida termina en `HUMAN_REVIEW_REQUIRED` | Bloqueos estructurales C-01 a C-04 de la auditoría |
| Aceptación histórica | `evaluation/reports/apply-debugger-flask-writes*.json` (2026-09-03, arnés anterior) | 3 de 8 APPROVED en FlaskApiProduct, con todos los subpuntajes en 100; calidad no calibrada | Comparar ese arnés con el actual |
| Entrega gobernada de PR | Tests con backends de push y PR falsos | **No verificado** en vivo; sin test negativo para revisión no aprobada | — |
| Plan de destinos de Developer para requisitos sin rutas (`37c7400`) | 15 de 16 corridas en seco del 09-16 escribieron 1–3 archivos | Verificado que escribe; ninguna escritura aprobó tests y revisión | — |
| Riesgo previo de dependencias como baseline (F-8) | 44 escaneos trazados con el mismo conjunto de CVEs; 39 de 42 decisiones de Security lo clasificaron como baseline | Verificado en Flask y en Spring solo después de `b99c939`; **el escaneo se repite en cada ciclo** y el texto del escáner llega a Developer como diagnóstico | Escaneo de baseline único y fuera de la remediación |
| Hechos declarados del stack (`92742b7`) | Ninguna corrida | **No verificado** | — |
| Ledger de salud de modelos (`4ff4ae2`) | Ninguna corrida; `workspace/model-health.json` no existe | **No verificado** | — |
| Disponibilidad de las cadenas de modelos | 290 de 478 generaciones fallidas; 13 de 24 corridas con reporte crudo pararon por cadena agotada | **Fallando** | Lista de proveedores aprobados y tope de gasto |
| Fallback local Ollama en modo nube | 0 de 26 intentos | **Fallando** | Preflight o retiro |
| Suite de tests (`fix/audit160926`, cierre de la fase 1) | 2026-09-18, `env -i`, daemon Docker real: 1393 passed, 19 skipped (imágenes locales ausentes), 5 xfailed, salida 0; con el daemon colgado (criterio de salida de la fase): 1375 passed, 37 skipped con razón, 5 xfailed, 0 failed | Verde con daemon; sin daemon verde con omisiones nombradas. Ver el [cierre de la fase 1](#comprobaciones-del-2026-09-18-cierre-de-la-fase-1-de-la-remediación) | Omisiones fuera del presupuesto `needs_docker`; marca de red para el test de PyPI |
| Sandbox de contenedor, contención de rutas, escritura autorizada, entrega con dos llaves, redacción antes de la nube | Código y tests; revisión de seguridad del 2026-09-16 | Verificado en código | Salida de código fuente a proveedores sin política |
| Decisiones 16, 17 y 18 contra daemon real | `results/` de `adr16/`, `adr17/` y `adr18/` en `evaluation/benchmarks/` (2026-09-11): 5/5, 9/9, 11/11 | Verificado en esa fecha; los JSON no registran commit y los cambios del 09-16 en servicios y workspace no se re-verificaron | — |
| Scorer `run_cycle.py` | Esquema v2 de la fase 1 (2026-09-18): tests de `_score` y `main()` | Atribuible **en código**: SHA de ASET leído antes y después de la corrida, «no ejercitado» distinto de «aprobado», causa de parada, fallos de entorno separados; **ninguna corrida ghcycle real con v2** todavía | Cuelgue tras el clon sin reporte; causa tipada para una suite que excede su plazo. Ver el [cierre de la fase 1](#comprobaciones-del-2026-09-18-cierre-de-la-fase-1-de-la-remediación) |
| Reviewer contra parches malos conocidos | [test_known_bad_patches.py](../tests/unit/test_known_bad_patches.py) (fase 1) | **Fallando**: aprueba con puntuación 100 un test vacuo nombrado con las palabras de la especificación (#5, `xfail(strict=True)`) | Fase 4 del plan; ver el [cierre de la fase 1](#comprobaciones-del-2026-09-18-cierre-de-la-fase-1-de-la-remediación) |

## Campaña GitHub del 2026-09-13 — aceptación no cumplida

La campaña `gh-run-testing` mide FlaskApiProduct, spring-demo, PropFlow y
Banking con el CLI real y checkout temporal del host. **No demuestra las seis
etapas verdes en los cuatro repositorios.** Los resultados conservados están en
[`ghcycle/results`](../evaluation/benchmarks/ghcycle/results/); los reportes
crudos permanecen locales e ignorados por Git. `delivered` expresa que se pidió
entrega, no que se haya abierto un PR.

La ampliación del 2026-09-13 incluye corregir los defectos y repetir los cuatro
ciclos hasta verificar las seis etapas y los PR. Sustituye el alcance anterior
que excluía F-7, F-8 y F-9. La tabla conserva la medición de `eaeee71`; las
correcciones posteriores no convierten esos resultados en aprobados.

### Corridas en seco del 2026-09-13 al 2026-09-16

Tras `90ba069` se repitieron corridas en seco sin entrega: once sobre
FlaskApiProduct (`flaskapiproduct-dry-20260916a` a `k`), seis sobre spring-demo
(`spring-demo-dry-20260916a` a `f`) y una sobre PropFlow
(`propflow-fixes-dry-20260913`). **Sus JSON puntuados no están versionados** y
dos no tienen reporte crudo. Ninguna completa las seis etapas: execute y spec
fallan en las dieciocho; delivery figura en verde solo por estar omitida, e
infraestructura aprueba sin ejercitarse. `clone` falla en dos, pero en
`spring-demo-dry-20260916c` la causa real fue un
`ValueError: sensitive content is not allowed in cloud context` no capturado
durante la tercera pasada de Architecture, no el clon; en
`propflow-fixes-dry-20260913`, la resolución DNS de github.com en un sandbox.

Las dieciséis con reporte crudo terminan en `HUMAN_REVIEW_REQUIRED`; cuatro
agotan las cinco iteraciones. `run_security_scan` falla en quince y `run_tests`
en trece. spring-demo-b y spring-demo-d tuvieron `run_tests` verde en todas sus
iteraciones y fueron rechazadas por la compuerta de cobertura léxica. Entre
corridas cambiaron proveedores, remediación y contexto de Developer: treinta y un
commits intercalados, cuatro de ellos durante una corrida, y ningún resultado
registra su commit. Cada resultado vale solo para el código con que corrió; los
tres últimos commits (`4ff4ae2`, `31defca`, `92742b7`) no tienen corrida. El
análisis por causa, proveedor y rol está en la
[auditoría](audit160926/02-evidencia-y-metricas.md).

### Correcciones posteriores a la medición

F-7 conserva el directorio de comandos y el intérprete de cada componente,
pero monta la raíz del repositorio para resolver referencias a módulos hermanos.
Rechaza componentes externos, incluidos escapes por enlaces simbólicos, antes
de crear infraestructura. F-9 informa únicamente claves de protocolo conocidas
de un `KeyError`; los argumentos arbitrarios quedan redactados también en la
cadena de excepciones.

Verificación del 2026-09-13: 156 pruebas focales pasan con las variables de
`Settings` y la carga de `.env` desactivadas solo dentro del proceso de prueba.
Las 19 regresiones nuevas fallan cargando los módulos de `eaeee71` en memoria.
Una prueba adicional con Docker y la imagen local de Python 3.13 confirma
lectura de un módulo hermano y rechazo de lectura fuera del repositorio.
La revisión de código y seguridad de F-7/F-9 no encontró problemas materiales.
Esto verifica las correcciones acotadas; todavía no verifica los cuatro ciclos.

El 2026-09-14, el runner corregido ejecutó los 71 tests originales de Banking
en Docker: 71 pasan, sin fallos ni omisiones y sin modificar el repositorio
objetivo. La restauración y compilación resolvieron sus proyectos hermanos.
Una prueba separada del frontend original de FlaskApiProduct completó seis
builds consecutivos con el montaje del repositorio; no reprodujo el fallo
intermitente de Node. Ese muestreo no demuestra que el problema haya desaparecido.

F-8 tiene una causa comprobada por separado: la agregación de resultados pierde
`scans_dependencies`, que usa Security para clasificar vulnerabilidades de
manifiestos sin cambios como riesgo previo visible. Esa política ya existe;
no requiere desactivar el gate. Los fallos de tests de las corridas anteriores
son independientes: `build_context` filtra esas herramientas del contexto de
Security. La auditoría de vulnerabilidades Python sigue sin equivalencia con
`npm audit`: su perfil ejecuta `pip check` y Ruff.

La corrección conserva la procedencia en la agregación y en los reportes
cacheados. La excepción para dependencias previas exige además evidencia
estructurada de advisories confirmados; un fallo del instalador o un reporte
incompleto no basta. Los hallazgos siguen visibles y el escáner conserva su
resultado de fallo. La revisión independiente detectó y se corrigió un caso
adicional de .NET que aceptaba errores internos con salida cero. Ocho regresiones
reprodujeron el fallo antes del arreglo; después pasan las 73 pruebas focales.
La suite integrada del 2026-09-14 terminó con 1038 pruebas aprobadas y 17 omitidas;
esa ejecución comenzó antes del último ajuste de .NET, cubierto por las focales.
*(Nota del 2026-09-17: no se conserva log, XML ni commit de esa ejecución ni de
las selecciones focales citadas en esta sección; no son reproducibles tal como
están escritas. La ejecución sobre `92742b7` figura en el estado vigente.)*
La revisión independiente aprobó ese ajuste y verificó 48 pruebas adicionales.
La primera repetición, `flaskapiproduct-corrected-20260914a`, conserva clone,
infraestructura e higiene en verde; ejecución, spec y entrega siguen rojas.
Sus tres iteraciones ejecutaron los 62 tests originales del backend con éxito.
El cliente falló con `ENOTDIR`/`ENOENT` durante npm y luego sin detalle.
La traza y una reproducción independiente confirman que el runner recorta a
4096 bytes un JSON de npm audit de 10890 bytes antes de validar su procedencia;
además se mezclaba stderr con el JSON. El transporte corregido retiene hasta
4 MiB por stream para escáneres estructurados, mantiene los diagnósticos cortos
y rechaza evidencia truncada o incompleta. La reproducción Docker del 14 de
septiembre confirmó los advisories con el JSON completo y mantuvo el escáner
en FAIL. La revisión independiente del 16 de septiembre aprobó el cambio tras
corregir también errores de lectura de tuberías: 111 pruebas focales pasan y
ocho pruebas de integración se omiten sin su imagen configurada.

La misma traza demostró otra causa: los requisitos de la campaña no nombran
archivos y Developer solo activaba la autoría con destinos explícitos. Las tres
propuestas quedaron en `PROPOSED`, sin `file_contents`. Ningún PR nuevo quedó
entregado. *(Corrección del 2026-09-16: `37c7400` añade un plan de destinos
(`DeveloperTargetPlan`) que Python valida contra el inventario del repositorio
antes de leer o escribir, sin editar tests originales. En 15 de las 16 corridas
en seco del 16 de septiembre con reporte crudo, Developer escribió entre uno y
tres archivos en el checkout temporal; ninguna aprobó tests y revisión.)*

### Medición conservada

Corrección fechada del cierre del ledger: `delivery.passed=true` junto con
`skipped=true` significa entrega **omitida**. No prueba delivery. Asimismo,
`infrastructure` verde en seco no prueba un PR de infraestructura ni su apilado.
El marcador de [`run_cycle.py`](../evaluation/benchmarks/ghcycle/run_cycle.py)
permanece intacto; esta tabla distingue esas condiciones al interpretar sus JSON.

| Evidencia | Clone | Infraestructura | Execute | Spec | Delivery | Higiene Docker |
|---|---|---|---|---|---|---|
| [FlaskApiProduct, entrega](../evaluation/benchmarks/ghcycle/results/flaskapiproduct.json) | PASS | PASS, sin motor externo | FAIL | FAIL | FAIL, sin PR | PASS |
| [spring-demo, seco](../evaluation/benchmarks/ghcycle/results/spring-demo-dry.json) | PASS | PASS, detecta mysql | FAIL | FAIL | OMITIDA | PASS |
| [spring-demo, entrega](../evaluation/benchmarks/ghcycle/results/spring-demo.json) | PASS | FAIL, sin rama de infraestructura | FAIL | FAIL | FAIL, sin PR | PASS |
| [PropFlow, seco](../evaluation/benchmarks/ghcycle/results/propflow-dry.json) | PASS | PASS, sin motor externo | FAIL | FAIL | OMITIDA | PASS |
| [PropFlow, entrega](../evaluation/benchmarks/ghcycle/results/propflow.json) | PASS | PASS, sin motor externo | FAIL | FAIL | FAIL, sin PR | PASS |
| [Banking, seco](../evaluation/benchmarks/ghcycle/results/banking-dry.json) | PASS | PASS, detecta postgres | FAIL | FAIL | OMITIDA | PASS |
| [Banking, entrega](../evaluation/benchmarks/ghcycle/results/banking.json) | PASS | FAIL, sin rama de infraestructura | FAIL | FAIL | FAIL, sin PR | PASS |

Estos siete resultados terminan en `HUMAN_REVIEW_REQUIRED`, con revisor
`REJECTED`, cero archivos aplicados y cero herramientas `UNAVAILABLE`. Los
conteos de herramientas son respectivamente 97, 31, 36, 102, 103, 95 y 67. Que las
herramientas hayan corrido no implica que los tests hayan pasado.

MySQL fue observado `healthy` durante el trabajo Maven en spring-demo según la
captura del ledger. Banking detectó postgres desde
`src/Banking.Api/appsettings.json`; durante la nueva corrida
`apply-614f9bca-0b9a-42d0-850a-bd40e11fb83a`, `docker ps` mostró postgres
`healthy` junto al contenedor Node, ambos etiquetados con ese run y
`aset.project=project`. PropFlow declara SQLite, por lo que la expectativa
inicial de MySQL era incorrecta. La ausencia actual de los
cuatro checkouts indicados por los reportes crudos fue comprobada de nuevo; esa
comprobación usa las rutas reales, no solamente `/tmp`.

### Adjudicación de hallazgos de ghcycle

Los identificadores F-7, F-8 y F-9 se reutilizaron en el ledger. Aquí designan
los tres hallazgos de su último cierre; las variantes anteriores se conservan
con un sufijo descriptivo. La tabla describe la medición original; los avances
vigentes están en la sección de correcciones anterior. Las referencias de línea corresponden a la base
`8baf9af` más el arreglo de redacción que ya estaba preparado al reanudar.

| Hallazgo | Etapa y repos afectados | Adjudicación |
|---|---|---|
| F-7, aislamiento entre componentes; absorbe F-6 | Execute, PropFlow y Banking | Defecto de producto; trabajo aparte. `ProjectReference` sale del montaje: PropFlow omite `PropFlow.Application`; Banking informa `CS0246` para `ICurrentUser`, `FavoriteService` y `AccountStatus`. El camino de contenedor usa `apply_run.py:226-233`; `:134-136` es el brazo alternativo. `mcp/container.py:258` monta la raíz recibida. El riesgo para JVM/Node es inferido, no una reproducción adicional. *Nota del 2026-09-17: no hubo nueva corrida ghcycle de PropFlow ni Banking tras la corrección, y la ejecución de los 71 tests de Banking no dejó artefacto.* |
| F-8 y F-1, vulnerabilidades previas; F-1', perfil Python | Security/review, cuatro repos | Los escáneres reportan dependencias vulnerables; decisión pendiente sobre baseline frente al cambio. No se desactiva el gate. La asimetría del perfil Python se adjudica con esa política. No está demostrado que un scan rojo aislado impida siempre cualquier entrega: en estas corridas también fallan tests. *Actualización del 2026-09-17: la política está implementada en `agents/security.py` desde el 2026-09-07 y exige advisories confirmados desde el 2026-09-14; en Maven solo funcionó tras `b99c939` (spring-demo-a siguió rechazada por seguridad). Reviewer puede aprobar con esos hallazgos visibles; la [decisión 8](architecture/decisions/0008-security-evidence-per-stack.md) lleva una corrección fechada.* |
| F-9, fallback sin clave | Diagnóstico, spring-demo | Deuda de producto aparte: `llm/cloud.py:469` conserva el tipo de excepción, no la clave del `KeyError`. Un futuro detalle debe pasar por redacción. |
| F-2, testing puntuado pese a fallos | Review, FlaskApiProduct | Defecto de coherencia de evidencia/revisión; trabajo aparte. No convierte los tests fallidos en aprobados. |
| F-3, caché no escribible y `ENOTDIR` | Execute, FlaskApiProduct | Defecto de entorno/contenedor; trabajo aparte. La atribución inicial de `ENOTDIR` a una ruta equivocada fue retirada; no queda demostrado que F-7 explique ese error. |
| F-4, archivos ajenos a la spec | Spec, FlaskApiProduct | Trabajo aparte: separar propuestas del agente y modificaciones de herramientas, como `client/package-lock.json`. No hay PR de esta campaña sobre el que afirmar contaminación efectiva. |
| F-5, motivos ausentes en `tool_outcomes` | Diagnóstico, FlaskApiProduct | Arreglado en la campaña por `ca7d57d` y `056cb75`; persisten las limitaciones siguientes. |
| F-7-diagnóstico y F-11, salida vacía o cola insuficiente | Diagnóstico, FlaskApiProduct y spring-demo | Trabajo aparte: un componente puede no aportar motivo; el extracto de 600 caracteres de Maven conserva autoconfiguración y pierde la causa. No atribuir el test Spring fallido a MySQL sin evidencia. |
| F-8-variabilidad, propuestas distintas con igual spec | Spec, FlaskApiProduct | Variabilidad observada, no defecto determinista demostrado. Trabajo de evaluación aparte; no se exige identidad textual al modelo. |
| F-9-higiene, verificación sobre `/tmp` | Higiene, cuatro repos | Corregida la verificación manual para usar las rutas reales. El JSON mide recursos Docker etiquetados; checkout y secretos requieren controles adicionales. |
| F-12, `aset.project=project` | Infraestructura/etiquetas, spring-demo | Defecto de identidad de proyecto; trabajo aparte. La colisión entre repos simultáneos es una consecuencia estática, no provocada en esta campaña serial. |
| F-13, redactor rechazado por el propio guardrail | Cloud/Architecture, spring-demo | Arreglado en `3bca34a`: redactar literales JSON decodificados y reconocer el marcador completo. La corrida real posterior alcanzó 36 resultados de herramientas. |
| Recursos antiguos sin etiqueta y checkout tras `SIGKILL` | Higiene | No justifican una ADR nueva: el barrido protege recursos sin `aset.owner=aset`; el checkout temporal no garantiza limpieza ante `SIGKILL`. Se retira el candidato a ADR del ledger. |

No hay una entrada F-10 definida en este ledger; no se inventa para completar
la numeración. Los defectos ya corregidos del arnés —puntuación falsa de execute,
reporte crudo obsoleto, consulta Docker fallida tratada como vacío y redacción
insuficiente— conservan sus commits y tests; no se reabren ni se altera el
marcador para obtener verde.

### Límites de aceptación

La [sonda superficial](../evaluation/benchmarks/ghcycle/results/shallow-push.json)
cerró la Task 2: GitHub aceptó el push desde `--depth 1`; se verificaron el
borrado de la rama temporal y la desaparición del checkout. El único archivo
del commit estaba bajo `.aset-probe/`. Esto prueba transporte Git, no la
entrega gobernada ni la aceptación de una spec. El
[script](../evaluation/benchmarks/ghcycle/probe_shallow_push.py) usa una condición
sobre el commit remoto tanto al crear como al borrar la rama; cuatro tests
cubren éxito, rechazo, timeout y una rama movida por otro actor.

No hay PR funcional de esta campaña verificado ni apilado funcional sobre
infraestructura, y tampoco una verificación por diff de PR que demuestre la
conservación de los tests originales. Los PR anteriores de FlaskApiProduct no
son evidencia de estas corridas. La corrección de F-7, F-8 y F-9 está incluida
en la ampliación posterior; la aceptación sigue pendiente de nuevas corridas.

Este trabajo no cambia la situación de `VolumeWorkspace` descrita abajo:
el CLI clona a un temporal del host; no valida el clon dentro de volumen ni
`extract` previo al teardown en un run real. Tampoco regenera los reportes del
trial de la decisión 14, que viven en `evaluation/reports/runs/adr14-trial-*`
*(corregido el 2026-09-17: la ruta citada antes,
`evaluation/benchmarks/adr14/results/report.json`, no existe en el árbol ni en
el historial de Git)*. Las comprobaciones anteriores
de otras ramas conservan su fecha y alcance, y no sustituyen la aceptación de
esta campaña.

### Verificación del cierre

La suite indicada por la Task 7 se ejecutó con Python 3.14.7, quitando las
variables exportadas cuyos nombres derivan de `Settings.model_fields` y fijando
después `DELIVERY_BACKEND=none`, sin modificar `.env`. Primera pasada en sandbox:
952 PASS, 26 FAIL y 20 SKIP. Los 26 fallos dependían del daemon Docker no
accesible desde ese sandbox; repetidos con acceso al daemon, **26 PASS** en
549.35 segundos. Resultado por lotes: **978 PASS, 20 SKIP, ningún fallo
pendiente** de esa selección; los omitidos no cuentan como integración validada.

Los cuatro tests nuevos de la sonda pasan aparte. Las comprobaciones
documentales y el contrato de calidad pasan (8); junto con redacción y
guardrails suman 71 PASS. Ruff sobre los archivos de código cambiados no
reporta hallazgos; sobre `src/engineering_team` conserva los dos preexistentes:
SIM103 en `agents/security.py` y PYI034 en `CompositeQuality.__enter__` de
`mcp/quality.py` *(citados antes por número de línea, que ya se movió)*.

La comprobación final, después de Banking, devuelve cero recursos Docker
etiquetados no pertenecientes a caché (contenedores, volúmenes, redes e imágenes,
con el mismo filtro del corredor). Los checkouts y sus directorios padres de
las cuatro corridas con entrega fueron eliminados, y no hay directorios
`aset-checkout-*` en el temporal real ni en `/private/tmp`. Los ocho JSON de
resultados pasan la comprobación de redacción idempotente; esos JSON y los dos
documentos de cierre no contienen coincidencias con las credenciales
configuradas. Los reportes crudos permanecen ignorados por Git.

## Comprobaciones del 2026-09-08 (reorganización documental)

*Encabezado fechado el 2026-09-17: antes se titulaba «Comprobaciones de esta
revisión» y los párrafos de base y evaluación aparecían dentro del cierre de la
campaña del 2026-09-13, al que no pertenecen.*

Base inspeccionada: `4294b9ef5904bed3b239a06c95e77491437b9aed`, rama `grok-multistack-validation`. Reorganización aprobada el 2026-09-08; los cambios posteriores a esa base se verifican en el worktree.

La aplicación bancaria de evaluación está ubicada en `demo-projects/sample_app/`. Es un objetivo de prueba y demo, no parte del paquete principal; el runtime y sus scripts apuntan explícitamente a esa ruta. La ruta anterior `sample_app/` ya no existe.

La evaluación está organizada en `evaluation/`: escenarios compartidos en la raíz, runners e inputs en `benchmarks/`, snapshots seleccionados en `reports/curated/`, reportes por ejecución en `reports/runs/`, salida transitoria en `reports/generated/` y evidencia histórica en `evidence/archived/`. Esta reorganización conserva los payloads y cambia únicamente sus rutas y consumidores.

La reorganización de `evaluation/` fue verificada con los tests de multistack, snapshots de evidencia, documentación y demo: 14 tests pasan. El lint del runner multistack conserva un aviso preexistente de imports no ordenados; no se modificó lógica de evaluación.

| Comprobación | Resultado |
|---|---|
| Tests documentales anteriores | Cinco pasan; medían rutas y términos históricos, no exactitud funcional |
| Integridad y navegación nueva | Pasan: enlaces activos, propietarios, hashes de los originales archivados y presencia de 22 recursos conservados |
| Pruebas dirigidas de implementación y documentación | 98 tests pasan: documentación, contrato de calidad, config, prompts, perfiles, entrega y Run API |
| Revisión final de documentación y demo | Siete tests pasan: seis comprobaciones documentales y lectura de los siete casos de la demo; sin ejecutar la demo |
| Ayuda CLI | Pasan `--help` y `run-project --help`; no se lanzaron runs |
| Lint de tests modificados, components y container | Pasa Ruff |
| Lint de runner | F841 preexistente en `src/engineering_team/mcp/runner.py`: variable `environment` sin usar; reproducido sobre el archivo del commit base. *Ese archivo ya no existe: eliminado por la [decisión 15](architecture/decisions/0015-container-only.md); la fila queda como registro de lo que se midió entonces* |
| Higiene del diff | Pasa `git diff --check` |
| Frontend | No ejecutado; `frontend/node_modules` no está instalado en este worktree |
| Docker, proveedores de modelos y trials | No ejecutados en esta migración |

No hay evidencia aquí de validación integral de los cinco stacks. La [arquitectura](architecture/overview.md) describe implementación inspeccionada, no certificación en vivo.

## Comprobaciones del 2026-09-09 (restauración de decisiones)

| Comprobación | Resultado |
|---|---|
| Contrato documental | Siete tests pasan, incluido el nuevo que exige que el índice liste cada decisión |
| Enlaces activos | 159 enlaces locales en `docs/` resuelven; ninguno roto; ninguno apunta al archivo salvo su metadato |
| Suite `unit`, `graph`, `integration`, `rag`, `mcp` | 862 tests: 841 pasan, 7 fallan, 14 se omiten |
| Los 7 fallos | **Preexistentes**: se reproducen idénticos sobre `4294b9ef` limpio. Causa: el `.env` del operador sobrescribe defaults de `Settings`, que `config.py` lee desde la raíz del checkout |
| Lint del test modificado | Pasa Ruff |
| Higiene del diff | Pasa `git diff --check` |
| Exactitud de los ADR restaurados | Cada símbolo citado existe hoy en el código; auditado uno por uno antes de restaurar |
| `e2e` | No ejecutado: requiere modelos y servicios en vivo |

Los 7 fallos afectan `test_cloud_fallback`, `test_config`, `test_model_runtime` y
un caso de `test_workflow`. No los introduce esta revisión y no se corrigieron
aquí: exigen decidir si los defaults se comprueban aislados del `.env` del
operador, que es una tarea de pruebas, no de documentación.

### Entorno y alcance reproducible

La comprobación del 2026-09-08 usó Python 3.14.7, pytest 8.4.2 y MCP 2.1.1 del entorno disponible en el checkout padre, con `PYTHONPATH=src` para importar exclusivamente el código de este worktree. Se retiraron las variables correspondientes a campos de `Settings` solo del proceso de prueba: la terminal tenía overrides que invalidaban los tests de defaults. No se cambió el `.env` ni la configuración del operador. Hubo un aviso de deprecación de Chroma.

El grupo ejecutado es el comando de backend de [testing](testing.md), junto con sus dos objetivos documentales. El Python global no sirve como evidencia del proyecto: resolvía el paquete desde otro checkout y tenía un MCP incompatible. No se reinstalaron dependencias ni se certificó una instalación limpia.

Se comparó el AST de los tres módulos Python cuyas referencias se corrigieron: su código ejecutable es idéntico al del commit base, excluidos los docstrings de módulo. Los recursos conservados mantienen sus hashes originales. La búsqueda normal `rg --files --hidden` desde la raíz excluye el archivo; las rutas explícitas pueden abrirlo. El grafo también registra `docs/deprecated/` como subárbol excluido.

## Comprobaciones del 2026-09-10 (retirada del sandbox de proceso)

Corresponden a la [decisión 15](architecture/decisions/0015-container-only.md).
Ejecutadas en macOS 27.0 arm64 con Docker Desktop, en entorno limpio
(`env -i`) y con el intérprete del venv del repositorio.

| Comprobación | Resultado |
|---|---|
| Suite completa `tests/` | 902 tests, 15 omitidos, **2 fallos**, 671.5 s |
| Los 2 fallos | `test_quality_uses_one_end_to_end_deadline_across_setup_phases` y `test_environment_lock_wait_is_inside_operation_deadline`, ambos en `tests/mcp/test_quality.py` |
| Los mismos 2, aislados | Pasan |
| Módulo `tests/mcp` completo | 239 tests, 15 omitidos, **0 fallos**, 199.8 s |
| Contrato documental | 7 tests pasan, incluidos enlaces locales activos |
| Ruff sobre los archivos modificados | Un único hallazgo, `PYI034` en `CompositeQuality.__enter__`, **preexistente**: se reproduce al revertir el cambio |
| Higiene del diff | Pasa `git diff --check` |

**Los dos fallos son afirmaciones de reloj de pared, no de comportamiento.**
Uno exige que una operación termine en menos de 0.12 s y midió 0.67 s; el otro
depende de que el presupuesto de tiempo se reparta entre varias llamadas, cosa
que deja de ocurrir si la primera ya agota el plazo. Ambos pasan aislados y el
módulo entero pasa por sí solo. La explicación más simple es la carga: este
cambio añade a ese mismo módulo pruebas que arrancan contenedores reales.
**No está probado que sean sólo intermitencia**; no se repitió la suite completa
para descartarlo, y ninguno de los dos tests fue tocado por este cambio.

El coste medido de mover las pruebas al contenedor real: `tests/unit` y
`tests/mcp` pasaron de unos 197 s a unos 227 s.

## Comprobaciones del 2026-09-10 (inventario y limpieza de recursos Docker)

Medidas sobre el host del operador (macOS 27.0 arm64, Docker Desktop), no sobre
un run controlado. Sustentan las decisiones
[16](architecture/decisions/0016-every-docker-resource-carries-its-run.md),
[17](architecture/decisions/0017-the-project-lives-in-the-run.md) y
[18](architecture/decisions/0018-missing-infrastructure-is-a-blocking-prerequisite.md),
**ninguna de las cuales está implementada**. *(Corrección fechada: la 16 quedó
implementada el mismo día y la 17 y la 18, parcialmente, el 2026-09-11; ver
abajo.)*

| Medición | Antes | Después de la limpieza |
|---|---|---|
| Imágenes | 31 / 9.34 GB | 26 / 8.33 GB |
| Volúmenes | 36 / 5.12 GB | 1 / 218.8 MB |
| Contenedores | 4 | 3 |
| Caché de build | 198 / 10.09 GB | 77 / 1.69 GB |
| Reclamado | — | ≈ 14.3 GB |

Una segunda pasada el mismo día retiró las 12 imágenes que corridas anteriores
construyeron (`interview-*`, `northgatetollplaza-*`, `order-ms`, `payment-ms`,
`frontend`), la caché de build restante y `testcontainers/ryuk:0.12.0`,
superada por la 0.14.0. Estado final: **16 imágenes / 5.675 GB, 1 volumen /
218.8 MB, caché de build 0 B**. De 24.5 GB iniciales quedan ≈ 5.9 GB.

Se conservaron a propósito las imágenes base —`postgres`, `mongo`, `kafka`,
`eclipse-temurin`, `python`, `nginx`, `dotnet/sdk`, `docker:dind-rootless`,
`docker:cli`, `ryuk`—: son lo que la
[decisión 16](architecture/decisions/0016-every-docker-resource-carries-its-run.md)
declara `aset.lifetime=cache`, y borrarlas solo obliga a la siguiente corrida a
redescargar ≈ 3.7 GB. Las dos imágenes del tooling MCP del operador no se
tocan.

Ambas limpiezas se hicieron **a mano**. Nada de esto está automatizado todavía.

Lo eliminado: el contenedor demonio `aset-dind-run-f0e96bbe25cb`, 22 volúmenes
anónimos, 10 volúmenes `aset-env-*`, un volumen de compose
`aset-<run_id>-postgres_data`, 2 imágenes colgantes, 5 imágenes
`aset-northgate-*`, 3 imágenes `aset/quality-*` y 8.405 GB de caché de build.

Lo deliberadamente **no** eliminado: `icapi-mysql` y su volumen de datos
(218 MB), porque nada en la máquina permite decidir quién lo creó, y las
imágenes base que un run vuelve a necesitar.

| Hallazgo | Evidencia |
|---|---|
| ASET no etiqueta ningún recurso | `grep -rn -- '--label' src` no devuelve nada |
| `docker volume prune` sin `-a` no toca volúmenes con nombre | ejecutado: no reclamó ningún `aset-env-*` |
| `compose down -v --remove-orphans` no borra las imágenes que compose construyó | quedaron 1.6 GB de `aset-northgate-*` tras el `down` |
| La caché de build no se poda nunca | ningún punto del código la invoca |
| El grueso del disco son imágenes de ASET, no del operador | 26 imágenes / 8.33 GB, de las que ≈ 7.5 GB corresponden a la ventana de validación multistack (2026-09-05 a 2026-09-07); el operador declara no haber descargado ninguna |
| `workspace/runs` no se recolecta | 923 MB en 96 directorios de run, ninguno borrado; el mayor 356 MB |
| Lo que se acumula es salida de build, no fuente | en un trial de `order-ms`: 80 MB de workspace, 79 MB en `target/` |
| El compose derivado que ASET infiere se descarta | `services.py` lo borra en `down()` con `self._derived_file.unlink(missing_ok=True)` |

**Corrección, 2026-09-10:** en el primer análisis de este día se atribuyeron al
operador las imágenes `order-ms`, `payment-ms`, `interview-*`,
`northgatetollplaza-*` y `mcr.microsoft.com/dotnet/sdk:10.0`. El operador
corrigió que no descargó ninguna, y las fechas de creación coinciden con las
corridas de validación multistack. La atribución correcta es ASET. El error tuvo
una causa concreta y es la misma que documenta la decisión 16: **ningún recurso
lleva marca de quién lo creó**.

Sobre `icapi-mysql`: el operador cree que lo creó ASET durante una prueba del
proyecto de entrevista, y sus credenciales coinciden con las de
`InterviewCleanApi`. No es verificable — no tiene etiquetas de compose, así que
no lo arrancó el camino de la [decisión 5](architecture/decisions/0005-services-per-run.md).
Se deja intacto por esa razón.

## Comprobaciones del 2026-09-10 (implementación de la decisión 16)

Corresponden a la
[decisión 16](architecture/decisions/0016-every-docker-resource-carries-its-run.md),
que pasa de «aceptada, no implementada» a **aceptada, implementada**. Ejecutadas
en macOS 27.0 arm64 con Docker Desktop, en entorno limpio (`env -i`) y con el
intérprete del venv del repositorio.

| Comprobación | Resultado |
|---|---|
| Suite completa `tests/` | 918 tests, 902 pasan, 16 omitidos, **0 fallos**, 399.5 s |
| Tests nuevos del etiquetado y del barrido | 16, todos pasan (`tests/unit/test_docker_labels.py`) |
| `ruff check src/engineering_team` | sin hallazgos nuevos; los 2 restantes son previos a este cambio |

Lo que hace el código ahora, y dónde:

| Recurso | Dónde se etiqueta |
|---|---|
| Contenedor por comando | `mcp/container.py`, `_container_command` |
| Volumen de entorno del run | `mcp/container.py`, `_ensure_volume` |
| Contenedor demonio y su red | `mcp/run_daemon.py`, `up` |
| Servicios, redes y volúmenes de compose | `services.py`, `override_document` |
| Proyecto compose | `services.py`: `aset-<proyecto>`, ya no `aset-<run_id>` |
| Barrido al arrancar un run | `apply_run.py`, `_ProjectInfrastructureQuality.__enter__` |
| Barrido a mano | `engineering-team docker-sweep` |

**Corrección fechada al hallazgo de la sección anterior.** La fila «ASET no
etiqueta ningún recurso — `grep -rn -- '--label' src` no devuelve nada» describe
el estado **anterior** a este cambio y se conserva como evidencia de por qué se
tomó la decisión; hoy ese mismo `grep` sí devuelve resultados.

**Dos límites que la decisión 16 no consigue, declarados en el propio récord.**
La caché de build no se recoge por etiqueta: BuildKit no filtra su poda por
etiquetas, así que el barrido automático no la toca y el comando de operador
ofrece `--build-cache`, que poda la del demonio entero y lo advierte. Y ASET no
construye imágenes hoy —ningún punto de `src/` ejecuta `docker build`—, de modo
que la mitad del barrido dedicada a imágenes está escrita y probada pero no
recoge nada todavía.

No medido todavía: el barrido no se ha ejercitado contra un run caído real en
este host. Lo que hay es la suite; no hay aún una corrida que deje recursos
huérfanos a propósito y los recoja al arrancar la siguiente.

## Comprobaciones del 2026-09-11 (decisiones 17 y 18)

Corresponden a la
[decisión 17](architecture/decisions/0017-the-project-lives-in-the-run.md) y a la
[decisión 18](architecture/decisions/0018-missing-infrastructure-is-a-blocking-prerequisite.md),
que pasan de «aceptada, no implementada» a **aceptada, parcialmente
implementada**. Ejecutadas en macOS 27.0 arm64 con Docker Desktop 29.7.2, en
entorno limpio (`env -i`) y con el intérprete del venv del repositorio.

| Comprobación | Resultado |
|---|---|
| Suite completa `tests/` | 946 tests, 929 pasan, 17 omitidos, **0 fallos**, 282.8 s |
| Contrato de workspace (decisión 17) | 16 pasan, 1 omitido (`tests/mcp/test_workspace_contract.py`) |
| El mismo contrato contra Docker real | 17 pasan, 0 omitidos, con `ASET_WORKSPACE_TEST_IMAGE=python:3.13-slim`; el volumen no sobrevive al test |
| Prerequisito de infraestructura (decisión 18) | 11 pasan (`tests/unit/test_infrastructure_prerequisite.py`) |
| `ruff check src/engineering_team` | sin hallazgos nuevos; los 2 restantes son previos |

**La medición que la decisión 17 exigía está tomada.** Es la primera vez que hay
un número detrás de la elección de volumen sobre copia en disco.
`evaluation/benchmarks/adr17/measure_workspace.py` ejecuta la misma carga —600
archivos pequeños; listado, búsqueda por contenido, 200 lecturas, 200
escrituras— de tres formas: nativa en el host, en contenedor sobre bind mount y
en contenedor sobre volumen nombrado. Siete repeticiones, medianas, resultados
crudos en `evaluation/benchmarks/adr17/results/measurement.json`.

| Operación | host | bind mount | volumen |
|---|---|---|---|
| listado | 0.004 s | 0.012 s | 0.000 s |
| búsqueda | 0.031 s | 0.103 s | 0.000 s |
| 200 lecturas | 0.363 s | 0.022 s | 0.031 s |
| 200 escrituras | 0.014 s | 0.054 s | 0.000 s |

*Nota del 2026-09-17: los «0.000 s» del volumen no son costo cero medido. Son
valores netos negativos recortados a cero, porque la mediana de la operación
quedó por debajo de la del contenedor vacío (por ejemplo, listado 0.1252 s frente
a 0.1545 s); indican costo por debajo del ruido. Los JSON de resultados no
registran fecha ni commit.*

El hallazgo que cambia la lectura: **arrancar el contenedor cuesta ~0.15 s y ese
coste es idéntico en los dos montajes**, de modo que domina todo lo demás. Una
vez restado, el volumen queda en o por debajo del ruido en tres de las cuatro
operaciones, y el bind mount es el que paga. Poblar el volumen cuesta 0.25 s una
vez. La columna del host es el suelo, no una candidata: la
[decisión 15](architecture/decisions/0015-container-only.md) no permite ejecutar
ahí. Su fila lenta —200 lecturas— compara sistemas operativos, no montajes:
lanzar 200 procesos es caro en macOS y barato en Linux.

**Lo que todavía no ocurre, dicho sin rodeos.** Ningún run usa `VolumeWorkspace`.
`create_run_copy` sigue produciendo el directorio en el que trabaja un run y
`MCPRepositoryClient` sigue recibiendo una ruta del host, así que los 923 MB en
96 directorios que motivaron la decisión 17 **no se han reducido por este
cambio**. Lo que existe es el contrato, sus dos implementaciones, la medición y
la extracción previa al teardown (`VolumeWorkspace.extract`), sin la cual borrar
el volumen sería peor que lo de hoy. La migración es trabajo aparte. *(Nota del
2026-09-16: los componentes `node` ejecutan sus comandos sobre un volumen nativo
por runner, `mcp/workspace_runner.py`; no es `VolumeWorkspace` y el proyecto sigue
en el host.)*

De la decisión 18, tampoco hay todavía una corrida real: lo verificado es la
suite, no un `aset-*` contra un proyecto sin compose que haya abierto de verdad
los dos pull requests. Y dos afirmaciones del récord no se cumplen, corregidas
con fecha dentro de él: no hay reintento —porque en esta implementación la
infraestructura se deriva y se levanta *antes* del trabajo funcional, así que
nunca hay un primer fallo que reintentar— y levantar la infraestructura no
prueba exactamente el archivo que se entrega, porque el run arranca el
renderizado `run` y el pull request contiene el `delivery`.

## Comprobaciones del 2026-09-11 (verificación de las decisiones 16, 17 y 18 contra el daemon real)

Las secciones anteriores miden la suite. Esta mide lo que la suite no puede:
el daemon de Docker del operador y un repositorio Git de verdad. Ejecutadas en
la rama `test/adr-16-17-18-verification`, en macOS 27.0 arm64 con Docker
Desktop, con el intérprete del venv del repositorio. Los tres runners escriben
su reporte crudo junto a sí mismos, redactado con `redacted_document` antes de
serializarse -- las hojas primero y el JSON después, porque al revés la
redacción se comía la comilla de cierre y el archivo de evidencia dejaba de
parsear.

| Runner | Resultado |
|---|---|
| [`adr16/verify_labels_and_sweep.py`](../evaluation/benchmarks/adr16/verify_labels_and_sweep.py) | 5 de 5, salida 0 |
| [`adr17/verify_workspace.py`](../evaluation/benchmarks/adr17/verify_workspace.py) | 9 de 9, salida 0 |
| [`adr18/verify_infrastructure_prerequisite.py`](../evaluation/benchmarks/adr18/verify_infrastructure_prerequisite.py) | 11 de 11, salida 0 |

El «9 de 9» de la decisión 17 se queda corto en un punto que conviene decir en
vez de esconder: el brazo de clon del runner (`--clone-url`) no se ejerció, así
que las nueve comprobaciones son las del volumen. Las dos afirmaciones de esa
decisión sobre el clon --que es `--depth 1` y que no deja credencial en
`.git/config`-- siguen sin verificarse contra el daemon.

**Decisión 16 — etiquetas y barrido.** Un volumen creado por el run lleva las
cuatro etiquetas; el barrido se lleva un recurso de un run que ya no vive; deja
intactos los del run actual; y deja intacto un volumen que no es de ASET. El
runner aborta con salida 2 si detecta recursos `aset.lifetime=run` de otro run
vivo, para no barrer trabajo ajeno. Daño colateral medido: **cero** —inventario
antes 6 contenedores / 7 redes / 7 volúmenes; después 6 / 7 / 9, y los dos
volúmenes de más son los que el propio test creó y conserva a propósito.

**Decisión 17 — el proyecto vive en el run.** Contra un volumen real: el
proyecto va y vuelve, una escritura es lo que devuelve la lectura siguiente, el
listado esconde `.env`, la búsqueda lee contenido dentro del volumen, salir de
la raíz del proyecto se rechaza, `extract` saca solo lo que se nombra —y nada
más—, y al terminar **no sobrevive ningún recurso del run**. Esto es lo que
distingue a la decisión 17 de un bind mount: no es que el volumen sea más
rápido, es que el proyecto no queda en el disco del operador.

**Decisión 18 — infraestructura como prerequisito bloqueante.** Contra Git real
con remoto bare local, sobre un proyecto de prueba cuyo `application.yaml`
declara MySQL **con una contraseña en claro**: se detecta el prerequisito y se
nombra el archivo del que salió; la rama de infraestructura añade
`docker-compose.yml` y extiende `.env.example` y **no toca código**; la
contraseña del proyecto no aparece en el compose entregado, ni en
`.env.example`, ni en el cuerpo del pull request, ni en el mensaje de commit; la
rama funcional se corta de la de infraestructura —`merge-base` igual al tip— y
su cuerpo dice que la evidencia describe infraestructura que nadie ha revisado;
ambas ramas llegan al remoto. Levantada de verdad, la infraestructura derivada
arranca y sus contenedores llevan el run.

**El hueco que este runner confirma, ahora reducido en parte.** Lo que se
levanta sigue siendo el renderizado `run` y lo que se entrega sigue siendo el
`delivery`: comparten inferencia, motor y digest, y difieren en puertos
publicados y credenciales por variable. Lo que cambió es que ese segundo
archivo ya no llega al revisor sin haberse tocado: `deliver()` invoca
`validate_delivered_compose`
([`delivery_check.py`](../src/engineering_team/delivery_check.py)), que
resuelve el `delivery` con `docker compose config` contra un `.env` sintético
construido con las claves de `.env.example` y compara las variables que el
compose interpola contra esas mismas claves -- así que un archivo que no
resuelve, o que referencia una variable que la plantilla no declara, nunca
llega a abrir el pull request: la entrega se rehúsa con `DeliveryRefused` y la
razón queda nombrada. Cuando no hay runtime disponible para preguntar, la
comprobación no bloquea -- `performed=False` no es `valid=False` -- y el
cuerpo del pull request dice explícitamente que el archivo no fue validado.
Lo que sigue sin cubrir: que el servicio *arranque* sano y que la aplicación
conecte, porque eso solo lo probaría levantar el `delivery` de verdad, y
levantarlo en la máquina del operador es el estado improvisado que la
decisión 18 existe para evitar; una colisión de puertos que aparezca
*después* de la validación, en la máquina de quien lo levante -- la
comprobación solo avisa de los puertos que ya están ocupados en la máquina
que lo generó; y que `run` y `delivery` sigan siendo dos renderizados
de una sola inferencia -- la validación reduce la distancia entre ambos, no
la elimina.

**Corrección fechada, 2026-09-11: `icapi-mysql` ya no existe.** Las
[decisión 16](architecture/decisions/0016-every-docker-resource-carries-its-run.md)
y [decisión 18](architecture/decisions/0018-missing-infrastructure-is-a-blocking-prerequisite.md)
citan en presente un contenedor `mysql:8.4` llamado `icapi-mysql`, creado el
2026-09-08, con 218 MB de volumen anónimo y sin etiqueta alguna, como la
evidencia viva que las motiva. El inventario de hoy no lo encuentra: 6
contenedores (`cool_hugle` del servidor MCP de GitHub, `rembric`, y los cuatro
de `taskflow-*`), 7 volúmenes (4 anónimos y tres `taskflow-microservicios_*`),
19 imágenes / 8.395 GB (4.235 GB reclamables), 443.5 MB en volúmenes y 7.814 kB
de caché de build. El contenedor fue retirado del host entre el 2026-09-10 y
hoy; no lo retiró el barrido, que por diseño no toca nada sin
`aset.owner=aset`. **Lo que los dos registros argumentan no cambia** —la
imposibilidad de atribuir un recurso sin etiquetas es exactamente por lo que se
dejó intacto—, pero su tiempo verbal sí: a partir de esta fecha es evidencia
histórica, no comprobable en esta máquina.

## Comprobaciones del 2026-09-18 (cierre de la fase 1 de la remediación)

La fase 1 del [plan de remediación](audit160926/12-plan-de-remediacion.md),
«medición confiable», se integró en la rama `fix/audit160926`: las nueve tareas
hasta `a8ebcaf` y una tanda final de correcciones de la revisión de rama entera
(sin `push` ni `merge`: la compuerta del operador sigue en pie). Esta sección
separa lo ejecutado de lo que queda **abierto**. Ninguna corrida ghcycle real se
lanzó con el scorer nuevo: todo lo que sigue sobre el scorer está verificado por
tests, no por una campaña.

| Comprobación | Resultado |
|---|---|
| Suite completa con daemon real sobre `a8ebcaf` (controlador; `env -i`, `timeout 1800`; `tests/unit tests/graph tests/rag tests/test_run_api.py tests/integration tests/mcp`) | 1362 passed, 19 skipped, 5 xfailed, salida 0, 303.57 s |
| Criterio de salida del gate con el daemon colgado (rama de la tarea 9, shim de `docker` que no contesta, sin `--ignore`) | 1313 passed, 37 skipped con razón, 3 xfailed, 0 failed, 235.62 s |
| El mismo criterio con el daemon colgado tras la tanda final (mismo shim, `-o faulthandler_timeout=90`) | 1375 passed, 37 skipped con razón, 5 xfailed, 0 failed, salida 0, 251.70 s |
| La misma suite con daemon real tras la tanda final de correcciones | 1393 passed, 19 skipped, 5 xfailed, salida 0, 432.11 s (una pasada anterior sobre el mismo código dio lo mismo en 369.79 s). Las 19 omisiones, el mismo número que con `a8ebcaf`, son todas marcas locales que exigen una imagen presente (`test_container.py`, `test_service_stack.py`, `test_run_daemon_live.py`, `test_workspace_contract.py`, `test_workspace_runner.py`); ninguna es `needs_docker`. Los 31 tests de más son los que añade la tanda |
| Ruff sobre `src`, `tests` y `run_cycle.py` | Los 3 avisos preexistentes (SIM103, PYI034, PIE807) |

Los 5 `xfailed` son reproducciones deliberadas con `xfail(strict=True)`: C-01,
C-02 y C-04 contra corridas congeladas en `tests/fixtures/replay/`, y dos
mediciones del parche malo #5 de abajo. El día que se corrijan, la suite dirá
XPASS en vez de seguir verde en silencio.

**Lo que la fase entregó, por fila del plan.** Scorer atribuible
([run_cycle.py](../evaluation/benchmarks/ghcycle/run_cycle.py), esquema v2
descrito en [benchmarks](../evaluation/benchmarks/README.md)): SHA de ASET leído
antes de la corrida y releído después (`aset_changed_during_run`), estado sucio
que también ve módulos nuevos sin versionar bajo `src/`, especificación, cadena
efectiva, horas, SHA del objetivo, causa de parada tipada, fallos de entorno
separados —incluido el código de salida 3 con el que la CLI informa un fallo de
infraestructura tipado antes del grafo— y etapas no ejercitadas con
`passed: null` en vez de aprobadas en seco. Recibo correcto: último `get_diff` y
riesgos no resueltos. Telemetría: `fallback_used` por intento, salida rechazada
redactada, spans con nombre de herramienta, errores de Maven conservados desde el
inicio del log. Gate honesto: `conftest.py` que aísla `Settings`, `needs_docker`
con presupuesto fijado y hook versionado. Conjunto de reproducción: cuatro
corridas congeladas. Calibración: cinco parches malos conocidos.

**Abierto al cerrar la fase — nombrado, no resuelto:**

- **El criterio de salida de la fila 6, «el Reviewer rechaza todos los parches
  malos», no se cumple.** El #5 —un test vacuo nombrado con las palabras de la
  especificación— sale APPROVED con puntuación 100, medido también contra la
  traza real congelada `d29547c7b7`; queda fijado con `xfail(strict=True)` en
  [test_known_bad_patches.py](../tests/unit/test_known_bad_patches.py), y la
  exigencia «el test falla sobre el código original y pasa después» se decide en
  la fase 4. El #1 (editar o borrar un test original) está evidenciado por la
  guarda de más arriba, `validate_target_plan`, que corta el plan antes de que el
  Reviewer lo vea; no por el Reviewer. La tabla de diffs aceptables se preparó
  para el operador y está sin llenar, y la comparación con el arnés del 09-03
  (opcional en la hoja de ruta) no se hizo.
- **El cuelgue tras el clon está nombrado, no corregido.** La CLI escribe su
  reporte solo al final de una corrida completa, así que una corrida colgada o
  matada no deja reporte y el scorer no distingue si murió antes o después de
  clonar (`stages.clone.detail` lo dice). Arreglarlo exige persistir evidencia
  antes, en la fase 2. Lo que sí cruza ya el proceso es un fallo tipado antes del
  grafo (código de salida 3); cualquier otra salida distinta de cero sin reporte
  se registra como `crash`.
- **Una suite que excede su plazo no tiene causa tipada propia.** Ya no se
  archiva como fallo de entorno (vuelve a `mcp_unavailable`, la etiqueta previa a
  la fase), pero tampoco dice «la suite colgó».
- **D10, `cost_usd` por generación, no se implementó**; el costo sigue sin
  registrarse.
- **Residuos de A-09 en el instrumento nuevo.** La negativa de nuestra propia
  redacción se lanza como `CLOUD_FALLBACK_UNAVAILABLE` sin `ModelExecutionInfo`,
  y `classify_stop_cause` la informa como `provider_chain_exhausted`;
  `WorkflowError.code` y `retryable` se siguen derivando del prefijo del mensaje
  en `graph/stategraph.py`, y la segunda señal de `classify_stop_cause` consume
  ese bit (fila 7 de la fase 2, `ChainFailure`). `run_events.py` reconstruye la
  razón del informe público desde el texto del último error.
- **Vocabulario de parada sin resolver:** una parada por `security_hitl` y una
  por rechazo incoherente del Reviewer siguen leyéndose `unknown`.
- **Para la fase 2:** normalizar al presupuesto `needs_docker` las omisiones que
  hoy van por marcas propias (m-2); un solo comportamiento de `_remaining` ante un
  plazo ya vencido (m-4); una marca tipada de riesgo de baseline en vez del
  prefijo `BASELINE_RISK_PREFIX` (m-5); limpieza cosmética (m-14); y una marca de
  red para `test_install_phase_can_download_over_real_pypi_tls`, que depende de
  PyPI real.

## Soporte por plataforma

**Corrección del 2026-09-10 ([decisión 15](architecture/decisions/0015-container-only.md)).**
Esta sección describía dos backends y el límite que su asimetría producía. Ya no
hay dos: el sandbox de proceso fue eliminado y el contenedor es la única
frontera. Lo que sigue reemplaza esa descripción; el texto anterior está en el
historial de git y en la propia decisión 15.

| Host | Frontera | Estado |
|---|---|---|
| macOS | Docker Desktop | **Ejecutado**: arm64, es el único host medido |
| Linux | Docker | No ejecutado |
| Windows | Docker Desktop | No ejecutado |

Lo que cambió respecto a la tabla anterior es qué significa un fallo, no dónde
se ha corrido. Antes Windows no tenía backend de proceso y quedaba sin camino
para un proyecto objetivo con Testcontainers; ese límite desaparece porque la
decisión 14 da a cada run su propio daemon Docker y la 15 deja de ofrecer una
alternativa por host. Pero **eliminar el backend alternativo no ejecuta nada en
ninguna plataforma nueva**: Linux y Windows siguen sin medirse, y ahora un fallo
ahí es un fallo del único camino, no del preferido.

Docker pasa a ser dependencia dura: sin él no hay gate de calidad, no hay
degradación a un runner de host. `QUALITY_RUNNER` sólo admite `container` y
`.env.example` se corrigió en el mismo cambio, porque hasta entonces ofrecía
`process`, un valor que el código ya rechaza por nombre.

De las dos observaciones que sostenían la sección anterior, una se cumplió y la
otra caducó: `sandbox-exec` estaba deprecado por Apple y sale de la ruta
crítica; el trabajo de Windows que `ProcessRunner` ya tenía escrito (`_VENV_BIN`
bajo `nt`, `_terminate_windows_tree`) se fue con el módulo, y sólo es
recuperable desde git.

No se ejecutó nada en Windows ni en Linux durante esta revisión. La
[decisión 14](architecture/decisions/0014-a-docker-api-that-is-not-the-hosts.md)
cierra el hueco de diseño y pasó a `accepted` tras la evaluación de abajo.

### Evaluación de Docker-in-Docker rootless (2026-09-09)

La decisión 14 se había bloqueado a sí misma hasta que existiera esta medición.
Se ejecutó sobre `docker:dind-rootless`
(`sha256:e17fa54c2ffd511d8407c746eec77f7814e6f74fe20caf822dad1870599984c0`,
daemon 29.8.0) con Docker Desktop 29.7.2.

| Comprobación | Resultado |
|---|---|
| Daemon del run sin `--privileged` | Pasa: `Privileged=false`, `CapAdd=[]`, el daemon se reporta `name=rootless` |
| Concesiones mínimas | `seccomp=unconfined`, `systempaths=unconfined`, `--device /dev/net/tun`; cada una aislada quitándola y observando el fallo |
| `/dev/fuse` | No hace falta: snapshotter containerd con `overlayfs` |
| Diferencia real con `--privileged` | Bounding set 14 vs 41 capabilities; sin `sys_admin`, `sys_module`, `sys_rawio`; ningún dispositivo de bloque del host visible |
| Contenedor de calidad alcanza la API por nombre | Pasa, en red `--internal` |
| Egress de la red del run | Cerrado: `redis:7-alpine` no se puede traer; `ping 1.1.1.1` da `Network unreachable` |
| Imágenes precargadas desde el host | `postgres:17-alpine` por `docker save`/`docker load`: 12.1 s, 594 MB dentro del run |
| Cliente Testcontainers real (4.8.2) | Pasa: resolvió la base en `dind:32768` y `select version()` devolvió `PostgreSQL 17.11` |
| Arranque en frío del daemon | 1.6 s hasta API disponible, con la imagen ya en caché; 159 MiB en reposo |

Dos supuestos de la decisión quedaron refutados y se corrigieron en su texto:
`--privileged` no es necesario, y un servicio arrancado dentro del daemon del run
**no** se resuelve por su propio nombre — se alcanza en el alias del daemon,
sobre el puerto publicado.

**La decisión está implementada desde el 2026-09-09.** Esto corrige la
afirmación anterior de esta sección, que decía que no había código que la
ejecutara. `mcp/run_daemon.py` crea la red `--internal` y el daemon rootless;
`mcp/container.py:172` lo arranca sólo en la fase sin red; `mcp/quality.py:549`
fuerza `needs_network=False` en la fase de test cuando hay daemon y antepone una
preparación con red. El daemon no es un default silencioso: exige
`quality_run_daemon_image` pinneada por digest junto a `quality_runner=container`,
y `Settings.validate_run_daemon` en `config.py` rechaza cualquier otra combinación. `QUALITY_RUNNER=process`
sigue siendo el camino por defecto y `.env.example` no cambió. *(Corrección del
2026-09-10: esa última frase caducó con la [decisión 15](architecture/decisions/0015-container-only.md).
`container` es el default y el único valor admitido, y `.env.example` sí
cambió.)*

El alcance de esta evidencia es un solo host: macOS 27.0 arm64 con Docker
Desktop, cuyo kernel es la VM linuxkit. **Linux y Windows no se ejecutaron**, y
son justamente las plataformas que motivan la decisión 14. El mecanismo está
probado; el soporte de Windows sigue siendo una afirmación no verificada. Esa
medición se hizo con un cliente Testcontainers equivalente, no con el componente
`order-ms` del que habla la decisión 10; ese componente sí se ejecutó después, y
lo que devolvió está abajo.

### Trial de la decisión 14 contra `order-ms` (2026-09-09 a 2026-09-10)

Primera ejecución del mecanismo contra un componente objetivo real, no contra un
cliente equivalente. Runner:
[`evaluation/benchmarks/adr14/verify_run_daemon.py`](../evaluation/benchmarks/adr14/verify_run_daemon.py),
sobre `order-ms` del repositorio externo `PruebaNuevosIngresosBackend`, con la
misma imagen dind pinneada de arriba. Cuatro intentos, reportes saneados en
`evaluation/reports/runs/adr14-trial-{1..4}/report.json`; el que cuenta es
`adr14-trial-4/report.json` (`finished: true`).

**Veredicto: `SUCCESS` en el trial 4, con 75 tests ejecutados y 0 fallos.**

| Comprobación | Resultado |
|---|---|
| Daemon y red creados para el run | Pasa: red `Internal: true`, subred `172.20.0.0/16`, daemon `running` durante la fase |
| Suite ejecutada dentro de la red cerrada | Pasa: 75 casos, 0 fallos, 0 errores |
| Clase Testcontainers | Pasa: `OrderFlowIntegrationTest`, 6 tests en 25.21 s — la clase que los trials 6b y 9 no lograban |
| Teardown | Pasa: contenedor y red ya no existen al cerrar el run |
| Contenedores nietos observados | **No medido**: la sonda corre cuando la JVM ya salió y Testcontainers ya los retiró |

Esto es lo que faltaba a la decisión 14: hasta ahora el mecanismo estaba probado
con un cliente Testcontainers equivalente, no con el componente objetivo. Ahora
lo está. La última fila es una limitación de la sonda, no un hallazgo: el
benchmark inspecciona el daemon después de `run_tests`, y para entonces la suite
ya cerró sus contenedores. La evidencia de que el daemon los sirvió es indirecta
pero firme — `OrderFlowIntegrationTest` necesita PostgreSQL y antes moría con
`ContainerFetchException`.

Costó tres intentos, y los dos primeros importan:

**Trial 2 — `FAIL` a los 180.9 s por preparación offline incompleta.**
`maven-surefire-plugin:3.5.6` resuelve su *provider*
(`surefire-junit-platform:3.5.6`) al ejecutarse, y `dependency:go-offline` no lo
ve. Ya dentro de la red interna, Maven obtiene `Unknown host
repo.maven.apache.org`. La red hizo lo que debía; la fase con red no dejó el
repositorio local completo. Corregido en `quality.py` precargando los cuatro
providers por coordenada, con la versión leída de `surefire-booter` en la caché
en vez de fijada. Medido antes de escribir el arreglo: seleccionar cero tests
**no** calienta el provider, porque surefire corta antes de resolverlo.

**Trial 3 — `SUCCESS` falso.** La preparación pasó a ser una secuencia de
comandos y su variable de bucle pisaba la que guarda el comando de la suite, así
que la fase ejecutaba el último paso de preparación y reportaba su éxito como
propio: `SUCCESS`, `output_summary` vacío, ningún `target/surefire-reports/` y
`test_cases: 0`. Lo detectó el criterio de aceptación, no el código de salida.
Queda fijado por `tests/unit/test_surefire_preseed.py`, verificado en rojo sobre
la versión con el defecto.

**La lección operativa:** para esta clase de run, `SUCCESS` no es evidencia.
`test_cases > 0` sí.

El trial 1 (`evaluation/reports/runs/adr14-trial-1/`) quedó `finished: false`
tras 444.9 s, interrumpido antes de registrar resultado. No cuenta como
evidencia y se conserva sólo como traza.

**Lo que este trial no cubre.** El trial recorre un componente a través de
`verify_run_daemon.py`. El cableado del daemon en la ruta de infraestructura de
proyecto — `_ProjectInfrastructureQuality` en
[apply_run.py](../src/engineering_team/apply_run.py), donde un mismo daemon se
comparte entre varios componentes con `owns_daemon=False` — **no se ejecutó de
extremo a extremo**. Sólo tiene pruebas unitarias. Un daemon compartido entre N
componentes es una superficie que un trial de un componente no puede tocar:
colisiones de puertos, carreras de caché de imagen, estado residual entre
componentes. Lo que sí está verificado por lectura es el ciclo de vida: si
`__enter__` falla a mitad, su `except BaseException` llama a `close()`, y
`close()` registra `self.daemon.down`, de modo que el daemon no queda huérfano
pese a `owns_daemon=False`.

### Contradicción entre el benchmark y la decisión 10, resuelta

`run_trial.py` fijaba `quality_runner="container"` para todos los casos,
incluido `ingresos` (`order-ms`), que es justamente el componente del que habla
la decisión 10. Esa decisión afirma que el benchmark selecciona el runner de
proceso para él; esa selección no existía en el código, ni existía en el commit
base.

Se corrigió el código, no la decisión: el runner pasó a ser parte de la
definición del caso en `CASES`. La regla vive donde vive la diferencia entre
casos, y no hay override por CLI: un flag invitaría exactamente a la deriva que
la decisión 10 quería evitar.

**Corrección del 2026-09-10.** Esa corrección dejó `ingresos` en `process`, que
era lo único correcto mientras la decisión 14 no existiera en código. Ahora
existe, así que `ingresos` vuelve a `container` — pero por la razón contraria a
la deriva original: con `quality_run_daemon_image` pinneada por digest y las
imágenes de su suite (`postgres:17-alpine`, `apache/kafka:4.3.1`) declaradas
como entrada explícita del caso. Los otros dos casos siguen en `container` sin
daemon. Esta es la línea que la propia decisión 14 señaló para revisitar.

**Esto cambia qué ejecuta la evaluación**, y no se ejecutó aquí: los proyectos
objetivo no están en este worktree y un trial multistack exige proveedores de
modelo en vivo. Lo verificado es la selección, con las pruebas de
[test_multistack_trial.py](../tests/unit/test_multistack_trial.py) — una fija
las entradas por caso y la otra exige que todo caso nuevo declare runner y
daemon. La ausencia de esa comprobación es lo que permitió la deriva original.
Que `order-ms` pasa bajo el daemon del run está medido, pero por el runner de
[`adr14/verify_run_daemon.py`](../evaluation/benchmarks/adr14/verify_run_daemon.py),
no por esta ruta.

## Proveedores de modelos (2026-09-16)

Se añadieron xKiro, Vyce, TokenForge, NVIDIA, Kilo, Cohere y Cloudflare Workers
AI como proveedores compatibles con OpenAI. Su inclusión en las cadenas por rol se
basa en sondas del 2026-09-16 con tareas de ASET, de dos a cuatro muestras por
rol, documentadas solo en comentarios de `llm/cloud.py` y en los mensajes de
`762ec08`, `52c5560` y `004b612`; no hay un script versionado que las reproduzca.
TokenForge no figura en ninguna cadena.

La traza de Langfuse del 16–17 de septiembre (478 generaciones) mide otra cosa:
éxito estructurado de cohere 58/63, mistral codestral 64/87, groq 46/95, xkiro
8/38, vyce 3/11, openrouter 4/56, google 1/25, cloudflare 3/4, kilo 1/3, nvidia
0/1 y Ollama local 0/26; mistral-medium, cabeza de la cadena de Architecture,
recibió 429 en 46 de 46 intentos. **No verificado:** disponibilidad sostenida,
cuotas y latencia bajo carga. Que un modelo esté en la cadena no demuestra que
responda.

Con la nube habilitada, fragmentos redactados del repositorio, el código escrito
por Developer y los hallazgos de escáneres llegan al proveedor que la cadena
seleccione, incluidas pasarelas de terceros; no existe lista de proveedores
permitidos por proyecto ni tope de gasto, y el costo no se registra (una sola de
478 generaciones tiene precio, asignado por Langfuse). Ver
[operaciones](operations.md) y la
[auditoría](audit160926/08-seguridad-y-politica.md).

## SpecKit retirado

Los 40 archivos restantes de `.specify/` (Markdown, scripts, configuración, manifests, cachés, templates y workflows) fueron archivados tras autorización explícita. Sus bytes y hashes están en [specify-manifest.json](deprecated/specify-manifest.json); no queda una instalación activa de SpecKit en el repositorio. Esta retirada no afecta los recursos de ejecución de ASET conservados.

## Recursos operativos conservados

- Seis `system.md`: cargados por [prompting.py](../src/engineering_team/llm/prompting.py). Los de Testing y Reviewer nunca se envían, porque esos roles no invocan modelo.
- Seis `user.md`: no se encontró referencia literal en la búsqueda acotada de Python/TOML bajo `src/`, `scripts/` y `tests/`; no se descartó consumo indirecto o externo. *(Nota del 2026-09-17: `prompting.py` lee solo `system.md` y construye el mensaje de usuario en código; decidir si se retiran o se conectan.)*
- Seis Markdown de `knowledge/`: entrada de [RAG](../src/engineering_team/rag/__init__.py), no fuente de verdad sobre el harness.
- Tres casos Markdown de multistack: entradas de [run_trial.py](../evaluation/benchmarks/multistack/run_trial.py).
- README de la demo bancaria: [demo.py](../demo-projects/banca-demo-support/demo.py) y [probe_models.py](../demo-projects/banca-demo-support/probe_models.py) usan [read_cases](../demo-projects/banca-demo-support/support.py) para extraer sus siete casos. El usuario confirmó conservarlo como entrada operativa en su ruta original, sin separar los casos. Existe además copia histórica; su narrativa no adquiere autoridad documental.

Su contenido no se certifica como documentación vigente. Cambiarlo puede cambiar el comportamiento y requiere una tarea explícita.

## Zona de no recrear

| Ruta o concepto retirado | Reemplazo | Condición para volver |
|---|---|---|
| `specs/`, planes y specs de `docs/superpowers/` | Código y pruebas; [mapa](README.md) para navegar | Necesidad nueva y aprobación explícita |
| Constitution > Spec > Plan > Tasks > implementation | [Reglas de agentes](../AGENTS.md) aprobadas | No reintroducir autoridad documental sobre el código |
| `docs/diagrams/`, `docs/architecture/checklists/`, `docs/architecture/findings/`, `docs/architecture/roadmap.md` | Diagramas: Mermaid embebido en [arquitectura](architecture/overview.md). Checklists y findings: [estado](status.md). Roadmap: sin propietario activo | Necesidad nueva y aprobación explícita; los diagramas se regeneran desde el código, no se restauran |
| README y evidencia narrativa anteriores | Propietarios del mapa | Verificar cada afirmación antes de redactar contenido nuevo |
| Notas de demos, frontend y bitácoras experimentales | [Operaciones](operations.md), [testing](testing.md) y Git | Solo información útil, actual y con propietario claro |
| `src/engineering_team/mcp/runner.py` y su suite `tests/mcp/test_process_sandbox.py` (backend de proceso: `sandbox-exec`, Bubblewrap, rechazo de Windows) | `ContainerRunner` en [container.py](../src/engineering_team/mcp/container.py), única implementación de `CommandRunner` | Sólo por una decisión nueva que traiga la evidencia de plataforma que hoy falta, no como fallback silencioso ([decisión 15](architecture/decisions/0015-container-only.md)) |
| Rotar la cadena de Developer a otro modelo en remediaciones posteriores (`d8cd3f3`, revertido por `31defca`) | Relegar por fallos registrados ([model_health.py](../src/engineering_team/llm/model_health.py)), aún sin corrida | Solo con medición que muestre mejora: en `apply-470d0440` y `apply-892eee7d` la rotación subió los tests fallidos a diez. La remediación sin cambios todavía cambia de modelo dentro de la cadena; ver la [auditoría](audit160926/05-doce-capas.md) |
| Proveedor SambaNova | Ninguno | Un nivel gratuito verificable: todo su catálogo respondió HTTP 402 |
| Modelos excluidos listados en `llm/cloud.py` (gpt-oss-120b gratuito de OpenRouter, nemotron-3-ultra, inkling, glm-5.2, gemma-4, ministral-3b, mistral-large, gemini-2.5-flash, gemini-3.1-flash-lite) | Cadenas vigentes | Nueva sonda con la forma real de la petición |

La decisión está en [historia](history.md); los originales permanecen en el [archivo](deprecated/README.md), fuera de la navegación habitual.
