# Historia documental

## 2026-09-11 — El compose entregado se valida antes de llegar al revisor

`delivery_check.validate_delivered_compose` resuelve el archivo `delivery`
con `docker compose config` contra un `.env` sintético construido con las
claves de `.env.example`, y compara las variables que el compose interpola
contra esas mismas claves -- lo que el runtime no hace, porque una variable
sin definir es cadena vacía para él, no un error. `deliver()`, en
`infrastructure_prerequisite.py`, la invoca antes de abrir el pull request y
rehúsa la entrega -- `DeliveryRefused` -- cuando la comprobación se hizo y
falló; sin runtime disponible no bloquea, y el cuerpo dice que el archivo no
fue validado. El runner de la decisión 18 pasa 11 de 11 con esto ejercitado
contra el daemon real, dos comprobaciones más que la vez anterior.

La decisión 18 lleva una corrección fechada con lo que esto cierra y lo que
sigue sin cerrar: la validación es estática, así que un servicio que resuelve
bien y aun así no arranca, o una colisión de puertos que aparece después, en
la máquina de quien lo levanta, siguen sin poder probarse aquí. El párrafo del
hueco `run` contra `delivery` en [estado](status.md) queda dicho en esos
mismos términos.

## 2026-09-11 — Las decisiones 16, 17 y 18, verificadas contra el daemon real

Las suites de las tres decisiones pasan con dobles. Esta rama
—`test/adr-16-17-18-verification`, cortada de `main` tras el merge del PR #7—
añade tres runners que las ejercen contra el Docker del operador y, en el caso
de la decisión 18, contra un repositorio Git real con remoto bare: 5 de 5, 9 de
9 y 9 de 9, todos con salida 0. Viven junto a las mediciones, en
`evaluation/benchmarks/adrNN/`, porque son evidencia ejecutable, no pruebas de
la suite: exigen un daemon y no deben correr en CI sin él.

Lo que se buscaba comprobar no era que el código funciona —eso ya lo dicen los
tests— sino las tres afirmaciones que solo un daemon puede respaldar: que el
barrido **no toca nada ajeno** (daño colateral medido: cero), que el proyecto
**no queda en el disco del operador** cuando vive en un volumen, y que la
contraseña en claro de un proyecto **no llega** al compose entregado, al
`.env.example`, al cuerpo del pull request ni al mensaje de commit.

También confirma un hueco en lugar de taparlo: el compose que el run levanta es
el renderizado `run` y el que el pull request entrega es el `delivery`. Nada de
esto ejecuta el segundo, así que una colisión de puertos o una variable sin
definir en el archivo entregado llegaría al revisor sin haberse ejercido nunca.

**Corrección fechada: `icapi-mysql` ya no existe.** Las decisiones 16 y 18 lo
citan en presente como su evidencia viva; el inventario de hoy no lo encuentra.
Se retiró del host a mano, no por el barrido, que por diseño no toca nada sin
`aset.owner=aset`. Ambos registros llevan la corrección dentro, y el argumento
de los dos sigue en pie: lo que probaba el problema es haberlo dejado vivir dos
días de más sin poder decir quién lo creó, y eso no depende de que siga
corriendo.

## 2026-09-11 — Las decisiones 17 y 18, a medias y dicho así

**Decisión 17.** Existe el contrato que el récord pedía: `workspace/contract.py`
define `Workspace` y sus dos implementaciones, `HostWorkspace` —lo que ASET hace
hoy— y `VolumeWorkspace` —el proyecto dentro de un volumen del run, alcanzado un
contenedor por operación—. `RepositoryMCP` lee y escribe a través del contrato en
lugar de contra el sistema de archivos del host, y ninguna decisión de política
se duplicó: qué roles pueden escribir y qué es un diff siguen viviendo en él.

Y está tomada **la medición que el récord exigía antes de poder llamarse
validado**. El resultado apoya la dirección, pero el hallazgo interesante es
otro: arrancar el contenedor cuesta ~0.15 s y ese coste es el mismo con bind
mount que con volumen, de modo que domina cualquier diferencia entre montajes.
Restado eso, el volumen queda en o por debajo del ruido donde el bind mount paga
0.103 s por buscar y 0.054 s por escribir. El detalle está en
[el estado](status.md) y los datos crudos en
`evaluation/benchmarks/adr17/results/measurement.json`.

Lo que **no** ocurrió: ningún run usa todavía el volumen. `create_run_copy` sigue
produciendo el directorio en el que se trabaja, y los 923 MB que motivaron la
decisión siguen ahí. El récord decía que una dirección no es una migración; el
estado dice cuál de las dos se ha hecho. Sí se añadió lo que el propio récord
ponía como condición para poder borrar el volumen algún día:
`VolumeWorkspace.extract`, que saca archivos nombrados al host antes del
teardown —por nombre y nunca implícitamente—, porque un run fallido que no deja
nada legible sería peor que lo de hoy.

**Decisión 18.** La inferencia de topología dejó de tirarse a la basura. Cuando
un proyecto no declara su infraestructura, `ServicesMCP` ya la derivaba, la
escribía en un archivo temporal y la borraba al terminar; ahora
`infrastructure_prerequisite.py` la convierte en un pull request de
infraestructura y nada más —`docker-compose.yml` añadido, `.env.example`
extendido, ningún código de aplicación tocado—, que se abre **antes** que
cualquier entrega funcional. El trabajo funcional se apila encima: rama cortada
de la rama de infraestructura, pull request abierto contra ella, y un párrafo en
el cuerpo que dice lo que vale su evidencia —la suite pasó contra infraestructura
que nadie ha revisado, y si el revisor la cambia hay que volver a ejecutar—.

Eso obligó a tocar una invariante de la [decisión 6](architecture/decisions/0006-github-origin-pull-request-delivery.md):
una propuesta no elige contra qué se mergea. Sigue sin elegirlo. La base es un
argumento que pasa quien llama, no un campo de `Proposal`, y se rechaza si no
nombra una rama bajo el espacio `aset/` del propio sistema.

Dos afirmaciones del récord **no** se cumplen y se corrigieron con fecha dentro
de él en lugar de reescribirlo. No hay reintento: el código deriva y levanta la
infraestructura antes del trabajo funcional, así que no existe el primer fallo
que el récord describía reintentando, y el tope de «un reintento, no un bucle»
no tiene nada que acotar. Y levantar la infraestructura no prueba el archivo que
se entrega: el run arranca el renderizado `run` —red cerrada, sin puertos— y el
pull request lleva el `delivery` —puertos en localhost, credenciales como
variables—, de modo que una colisión de puertos en el archivo entregado no la
detectaría la corrida que lo propuso.

## 2026-09-10 — La decisión 16, implementada, y la promesa que no se pudo cumplir

Todo recurso Docker que un run crea lleva ya, en el momento de crearse,
`aset.owner`, `aset.run`, `aset.lifetime` y —cuando se conoce el proyecto—
`aset.project`. Las etiquetas viven en un módulo nuevo,
`src/engineering_team/docker_labels.py`, y las escriben los tres sitios que
crean recursos: el contenedor por comando y el volumen de entorno
(`mcp/container.py`), el demonio del run y su red (`mcp/run_daemon.py`) y el
documento de override que ASET añade sobre el compose del proyecto
(`services.py`). El proyecto compose pasa a llamarse `aset-<proyecto>` en lugar
de `aset-<run_id>`, con su coste aceptado: una segunda corrida simultánea sobre
el mismo proyecto se **rechaza por nombre**, con un mensaje que lo dice.

El barrido se ejecuta al arrancar la infraestructura de un run y también a mano
(`engineering-team docker-sweep`). Nunca consulta un recurso sin filtrar primero
por `aset.owner=aset`, de modo que lo que nadie etiquetó no llega siquiera a ser
candidato: `icapi-mysql` sobrevive por construcción, no por una excepción.

**Dos cosas que la decisión 16 afirmaba y el código no cumple**, corregidas con
fecha dentro del propio récord en lugar de reescribirlo: la caché de build no se
recoge por etiqueta, porque BuildKit no filtra su poda por etiquetas —el comando
de operador ofrece `--build-cache`, que poda la del demonio entero y lo advierte
en su ayuda—, y ASET no construye imágenes hoy, así que la mitad del barrido que
se ocupa de imágenes está escrita y probada pero no recoge nada todavía.

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
