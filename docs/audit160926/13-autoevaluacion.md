# Autoevaluación del entregable

Método «agent-self-evaluation»: cinco ejes puntuados por separado de 1 a 5, con
evidencia para toda nota menor que 5. Se contrasta con una evaluación
independiente hecha por un agente evaluador que no participó en la auditoría.

**Resumen.** Auditoría verificable y trazable cuyas conclusiones centrales están
comprobadas en código y datos; pierde puntos por repetición de cifras entre
documentos y por lo que no se pudo validar en vivo.

## Puntuación del auditor principal

| Eje | Nota | Evidencia |
|---|---|---|
| Exactitud | **4** | Los cuatro hallazgos críticos y los catorce altos tienen verificación en código o datos. Durante la redacción aparecieron y se corrigieron cuatro errores propios: atribuir a spring-demo-c las tres decisiones de Security sin baseline (eran de spring-demo-a), afirmar que una ruta de adr14 «nunca existió» (solo consta que no está en el árbol ni en Git), contar «21» bloques del artículo (eran 25) y sumar 37 verificados (eran 36). Que existieran sugiere riesgo residual en los **17 hallazgos sin verificación cruzada** (niveles S o E) |
| Completitud | **4** | Ambos marcos se contrastaron sección por sección, incluidos los bloques del artículo recuperados al final; se revisaron el export de Langfuse, los 26 resultados y 27 reportes crudos, todo `evaluation/`, la suite completa y la documentación activa. Quedan fuera: los 26 tests que requieren Docker (daemon apagado), el frontend, la lectura humana de los diffs finales, los tres últimos commits sin corrida, las 12 imágenes del artículo y varios arreglos documentales que requieren decisión |
| Claridad | **4** | Estructura uniforme, identificadores únicos, claves de severidad y verificación, índice. Pero 53 hallazgos, 13 secciones y unos 250 KB de anexos en inglés dentro de una documentación en español exigen esfuerzo de lectura |
| Accionabilidad | **4** | Cada hallazgo crítico y alto tiene arreglo mínimo con `ruta:línea`; el plan tiene fases, criterios de salida y métricas. No se aplicó ningún arreglo de código, por alcance; el criterio del experimento (2 de 8) es una propuesta sin calibrar y las duraciones son estimaciones |
| Concisión | **3** | Las cifras de cabecera (0/26, 290/478, 13/24, 33 %) se repiten en el README de la auditoría, en evidencia, en Harness Engineering, en el registro y en el estado; los hallazgos aparecen resumidos en cada sección y de nuevo en el registro; los anexos duplican contenido ya sintetizado |
| **Global** | **3,8** | Promedio simple |

## Evaluación independiente

Un agente evaluador verificó más de 20 afirmaciones contra el código, recalculó
sobre el export de Langfuse las 16 trazas raíz en revisión humana, las 290
generaciones con error de 478 y las 42 decisiones de Reviewer rechazadas,
confirmó el 3/8 APPROVED del 2026-09-03 y recontó el registro. **No encontró
errores factuales.** Puntuó exactitud 5, completitud 4, claridad 5,
accionabilidad 5 y concisión 4: **4,8**.

**Conciliación.** La diferencia (3,8 frente a 4,8) se explica por tres cosas que
el evaluador no vio o ponderó menos: los errores propios corregidos durante la
redacción, que indican riesgo en lo no verificado; el texto incompleto del
artículo con que trabajaron los auditores, que se detectó y subsanó después de
su evaluación; y la repetición de cifras, que el evaluador también señaló como
mejora principal de concisión. Se mantiene la nota más baja.

## Mejoras, por impacto

1. **Validar en vivo lo que hoy es lectura estática.** Correr la suite con el
   daemon Docker activo y leer como humano los diffs finales de las 26 corridas.
   «Resuelto» significa que los 26 tests dependientes de Docker tienen resultado
   registrado en el [estado](../status.md) y que existe una tabla de diffs
   aceptables o no aceptables por corrida.
2. **Ejecutar la fase 3 del plan** (experimento discriminante con criterio fijado
   antes). «Resuelto» significa un par de resultados fechados, ASET recortado
   frente al control, con commit registrado y citado desde el estado.
3. **Un único propietario para las cifras.** Dejar las cifras en
   [evidencia y métricas](02-evidencia-y-metricas.md) y sustituir sus copias por
   enlaces. «Resuelto» significa que ninguna cifra de cabecera aparece con valor
   literal en más de un documento de la auditoría.

## Autocomprobación

¿Estaría de acuerdo el usuario con esta evaluación? Probablemente con la
exactitud y la accionabilidad, que puede comprobar con `git diff` y las
referencias `ruta:línea`. Lo más probable es que le moleste el volumen: la
respuesta a «qué está mal y qué hago» cabe en el [README](README.md) y en el
[plan](12-plan-de-remediacion.md), y el resto es respaldo.
