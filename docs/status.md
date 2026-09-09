# Estado y límites de evidencia

Base inspeccionada: `4294b9ef5904bed3b239a06c95e77491437b9aed`, rama `grok-multistack-validation`. Reorganización aprobada el 2026-09-08; los cambios posteriores a esa base se verifican en el worktree.

La aplicación bancaria de evaluación está ubicada en `demo-projects/sample_app/`. Es un objetivo de prueba y demo, no parte del paquete principal; el runtime y sus scripts apuntan explícitamente a esa ruta. La ruta anterior `sample_app/` ya no existe.

La evaluación está organizada en `evaluation/`: escenarios compartidos en la raíz, runners e inputs en `benchmarks/`, snapshots seleccionados en `reports/curated/`, reportes por ejecución en `reports/runs/`, salida transitoria en `reports/generated/` y evidencia histórica en `evidence/archived/`. Esta reorganización conserva los payloads y cambia únicamente sus rutas y consumidores.

La reorganización de `evaluation/` fue verificada con los tests de multistack, snapshots de evidencia, documentación y demo: 14 tests pasan. El lint del runner multistack conserva un aviso preexistente de imports no ordenados; no se modificó lógica de evaluación.

## Comprobaciones de esta revisión

| Comprobación | Resultado |
|---|---|
| Tests documentales anteriores | Cinco pasan; medían rutas y términos históricos, no exactitud funcional |
| Integridad y navegación nueva | Pasan: enlaces activos, propietarios, hashes de los originales archivados y presencia de 22 recursos conservados |
| Pruebas dirigidas de implementación y documentación | 98 tests pasan: documentación, contrato de calidad, config, prompts, perfiles, entrega y Run API |
| Revisión final de documentación y demo | Siete tests pasan: seis comprobaciones documentales y lectura de los siete casos de la demo; sin ejecutar la demo |
| Ayuda CLI | Pasan `--help` y `run-project --help`; no se lanzaron runs |
| Lint de tests modificados, components y container | Pasa Ruff |
| Lint de runner | F841 preexistente en `src/engineering_team/mcp/runner.py`: variable `environment` sin usar; reproducido sobre el archivo del commit base |
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

## Soporte por plataforma

El backend de proceso es específico por host y el de contenedor no lo es. Esto
sale de leer el código, no de haber ejecutado en las tres plataformas.

| Host | `process` | `container` |
|---|---|---|
| macOS | `sandbox-exec` | Docker Desktop |
| Linux | Bubblewrap | Docker |
| Windows | rechazado en `mcp/runner.py:447` | Docker Desktop |

Cruzado con la [decisión 10](architecture/decisions/0010-integration-tests-need-the-host-docker-api.md),
que exige `quality_runner=process` para componentes cuya suite arranca sus
propios contenedores, resulta un límite que hasta ahora no estaba enunciado:
**un proyecto objetivo con Testcontainers no tiene camino soportado en
Windows**. No es degradación, es ausencia de backend.

Dos observaciones asociadas, ambas verificadas sobre el código de este worktree:

- `sandbox-exec` está deprecado por Apple; su propio manual lo declara así. El
  camino `process` no es un piso estable en dos de los tres hosts.
- `ProcessRunner` ya está escrito para Windows salvo la frontera: `_VENV_BIN`
  elige `Scripts` bajo `nt`, el passthrough incluye las variables de Windows, y
  `_terminate_windows_tree` existe completo. Lo que falta es la primitiva de
  aislamiento, no la supervisión.

No se ejecutó nada en Windows ni en Linux durante esta revisión: la tabla
describe lo que el código admite o rechaza, no una ejecución observada. La
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

**La decisión está aceptada, no implementada.** No hay código que la ejecute:
`dind`, `docker-in-docker` y `DOCKER_HOST` no aparecen en `src/`. Lo medido es
que el mecanismo funciona, no que el sistema lo use; hoy `QUALITY_RUNNER=process`
sigue siendo el camino soportado para la clase Testcontainers y `.env.example` lo
documenta así con razón.

El alcance de esta evidencia es un solo host: macOS 27.0 arm64 con Docker
Desktop, cuyo kernel es la VM linuxkit. **Linux y Windows no se ejecutaron**, y
son justamente las plataformas que motivan la decisión 14. El mecanismo está
probado; el soporte de Windows sigue siendo una afirmación no verificada.
Tampoco se ejecutó el componente `order-ms` del que habla la decisión 10: no
existe en este worktree, es un proyecto objetivo externo del benchmark. La
prueba se hizo con un cliente Testcontainers equivalente, no con ese componente.

### Contradicción entre el benchmark y la decisión 10, resuelta

`run_trial.py` fijaba `quality_runner="container"` para todos los casos,
incluido `ingresos` (`order-ms`), que es justamente el componente del que habla
la decisión 10. Esa decisión afirma que el benchmark selecciona el runner de
proceso para él; esa selección no existía en el código, ni existía en el commit
base.

Se corrigió el código, no la decisión: el runner pasó a ser parte de la
definición del caso en `CASES`, de modo que `ingresos` selecciona `process` y
los otros dos siguen en `container`. La regla vive donde vive la diferencia
entre casos, y no hay override por CLI: un flag invitaría exactamente a la
deriva que la decisión 10 quería evitar.

**Esto cambia qué ejecuta la evaluación.** El caso `ingresos` ahora corre bajo el
sandbox de proceso. Es el comportamiento que la decisión 10 siempre describió,
pero ningún trial se ejecutó para confirmarlo aquí: los proyectos objetivo no
están en este worktree y un trial exige proveedores de modelo en vivo. Lo
verificado es la selección, con dos pruebas nuevas en
[test_multistack_trial.py](../tests/unit/test_multistack_trial.py) — una fija la
selección por caso y la otra exige que todo caso nuevo declare su backend. La
primera se comprobó reintroduciendo el defecto: falla con
`assert 'container' == 'process'`. La ausencia de esa comprobación es lo que
permitió la deriva original.

## SpecKit retirado

Los 40 archivos restantes de `.specify/` (Markdown, scripts, configuración, manifests, cachés, templates y workflows) fueron archivados tras autorización explícita. Sus bytes y hashes están en [specify-manifest.json](deprecated/specify-manifest.json); no queda una instalación activa de SpecKit en el repositorio. Esta retirada no afecta los recursos de ejecución de ASET conservados.

## Recursos operativos conservados

- Seis `system.md`: cargados por [prompting.py](../src/engineering_team/llm/prompting.py).
- Seis `user.md`: no se encontró referencia literal en la búsqueda acotada de Python/TOML bajo `src/`, `scripts/` y `tests/`; no se descartó consumo indirecto o externo.
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

La decisión está en [historia](history.md); los originales permanecen en el [archivo](deprecated/README.md), fuera de la navegación habitual.
