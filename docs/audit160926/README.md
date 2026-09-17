# Auditoría del 2026-09-16

Auditoría de ASET sobre `gh-run-testing` @ `92742b7`, realizada entre el 16 y el
17 de septiembre de 2026 con ocho auditores independientes, un consejo de
decisión y verificación del auditor principal. Marcos: «Building effective
agents» de Anthropic, «Harness Engineering» de LunarResearcher y el método de
auditoría de las doce capas de un agente.

Es evidencia de una revisión fechada, no propietaria de hechos vigentes. Lo que
sigue siendo cierto se trasladó al [estado](../status.md), a la
[arquitectura](../architecture/overview.md) y a [operaciones](../operations.md).

## Veredicto

**ASET no produce trabajo aceptado con su arnés actual.** Ninguna de las 26
corridas contra repositorios reales completó sus etapas, ninguna de las 42
decisiones de Reviewer aprobó y no se abrió ningún PR. La causa no es el
razonamiento del modelo: son **defectos deterministas del arnés**, verificados en
código, sumados a **cadenas de modelos gratuitos que se agotan**.

| Medida | Valor |
|---|---|
| Corridas aceptadas | **0 / 26** |
| Paradas por cadena de modelos agotada | 13 / 24 |
| Generaciones LLM fallidas | 290 / 478 (61 %) |
| Reloj gastado en intentos que fallan | 33 % |
| Transiciones de remediación que repiten la clase de fallo | 22 / 27, detectadas 7 |
| Fallos de herramienta por CVEs previos que el cambio no puede arreglar | 70 / 138 (51 %) |
| Tests en `92742b7` | 1270: 1221 pasan, 26 fallan (sin daemon Docker), 23 omitidos |
| Hallazgos | 4 críticos, 14 altos, 24 medios, 11 bajos |

**Clasificación.** En términos de Anthropic, ASET es un *workflow*, no un sistema
de agentes: el código decide cada transición y cada llamada a herramienta. Es una
cadena de prompts con compuertas y un único generador (Developer) en un bucle
evaluador-optimizador cuyo evaluador es código. Esa forma es defendible; el
problema es que el bucle **no entrega la verdad del entorno al generador** y **no
sabe detenerse cuando no progresa**.

## Los cuatro bloqueos críticos

1. **C-01 — Developer no ve por qué fallaron los tests.** Cuando Reviewer enruta
   por Architecture (26 de 42 veces), el diagnóstico solo llega a Architecture,
   cuyo modelo no puede cambiar nada.
2. **C-02 — La ruta por Architecture no puede converger.** Exige leer la mitad de
   19–67 archivos candidatos con una ventana de unos 7; la retroalimentación
   agranda el denominador.
3. **C-03 — El detector de estancamiento no ve repeticiones**, porque hashea texto
   de diagnóstico que cambia en cada ciclo.
4. **C-04 — La compuerta de aceptación es léxica** sobre reglas que redacta un LLM:
   rechazó suites verdes porque los nombres de tests Java no contenían palabras en
   español.

## Lo que está bien

El código, no el modelo, decide el flujo; Testing y Reviewer son deterministas;
hay validación de plan, autorización de escritura y entrega con dos llaves;
contenedores con capacidades eliminadas y contención de rutas; redacción que
falla cerrada antes de la nube; tests de baseline antes de escribir; y un estado
documental que se niega a declarar verde lo que no lo es.

## Qué hacer

Según el [consejo](10-consejo.md), por orden: **contener** (proveedores aprobados
con tope de gasto, código congelado por campaña), **medir de forma atribuible**
(scorer con commit, recibo correcto, gate de tests honesto, aceptación calibrada),
**borrar y desbloquear** (llamadas eco, diagnóstico a Developer, enrutado por
fronteras, contrato de aceptación, huella por clase, escaneo de baseline único) y
correr un **experimento discriminante** contra un agente de código de control
antes de decidir si se completa la remediación o se rediseña. Detalle en el
[plan](12-plan-de-remediacion.md).

## Documentación corregida

Treinta commits del 09-16 no habían tocado ningún Markdown. Esta auditoría
corrigió el límite de remediación, la lista de proveedores, la superficie de la
CLI, valores de configuración y conteos en README, arquitectura, operaciones,
pruebas, mapa y AGENTS.md; añadió al estado una tabla de estado vigente, la
campaña del 16 de septiembre, los proveedores y retiros; añadió una corrección
fechada a la decisión 8 y una nota a la 17; y registró las auditorías fechadas en
la comprobación documental. Ver [documentación](07-documentacion.md).

## Índice

| Sección | Contenido |
|---|---|
| [01 Alcance y método](01-alcance-y-metodo.md) | Marcos, evidencia, auditores, protocolo de verificación y limitaciones |
| [02 Evidencia y métricas](02-evidencia-y-metricas.md) | Corridas, causas de fallo y de parada, Langfuse por rol y proveedor, RAG, telemetría, scorer e inventario de `evaluation/` |
| [03 Patrones de Anthropic](03-patrones-anthropic.md) | Flujo real, mapa de patrones, principios y condiciones de agentes de código |
| [04 Harness Engineering](04-harness-engineering.md) | Las 19 secciones, madurez L1–L6, métricas de trabajo aceptado y lista de eliminación |
| [05 Doce capas](05-doce-capas.md) | Diagnóstico por capa, bucles ocultos y preguntas de diagnóstico |
| [06 Pruebas](06-pruebas.md) | Ejecución de la suite, invariantes cubiertos y afirmaciones previas |
| [07 Documentación](07-documentacion.md) | Roles, deriva corregida y pendiente |
| [08 Seguridad y política](08-seguridad-y-politica.md) | Salida de datos, sandbox, redacción y reglas código frente a prompt |
| [09 Fallos silenciosos](09-fallos-silenciosos.md) | Errores tragados y casos que fallan cerrados |
| [10 Consejo](10-consejo.md) | Decisión sobre el paso siguiente con disidencia visible |
| [11 Registro de hallazgos](11-registro-de-hallazgos.md) | Los 53 hallazgos con evidencia, verificación y confianza |
| [12 Plan de remediación](12-plan-de-remediacion.md) | Fases, criterios de salida y métricas |
| [13 Autoevaluación](13-autoevaluacion.md) | Evaluación de este entregable en cinco ejes |
| [report.json](report.json) | Informe estructurado `ecc.agent-architecture-audit.report.v1` |
| [Anexos](anexos/00-brief-de-auditores.md) | Brief común y papeles de trabajo A1–A8 tal como se entregaron |
