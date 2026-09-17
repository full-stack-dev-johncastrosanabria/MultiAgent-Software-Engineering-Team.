# Consejo: qué hacer después de 0 cambios aceptados

Deliberación del 2026-09-17 con el método «council»: cuatro voces, tres de ellas
subagentes independientes que recibieron solo la pregunta y los hechos
verificados, sin la conversación de la auditoría.

## Pregunta

ASET produjo 0 cambios aceptados en 26 corridas sobre repositorios reales
(2026-09-12 a 16). ¿Qué debe hacer el equipo?

- **(A)** Mantener el ciclo actual: correr el benchmark, parchear el fallo visto y
  volver a correr (lo ocurrido el 09-16: 31 commits intercalados con 17 corridas).
- **(B)** Congelar el benchmark y aplicar una remediación estructural acotada del
  workflow existente, validada contra un conjunto congelado de fallos grabados
  antes de otra campaña.
- **(C)** Rediseñar hacia un único agente de código con herramientas dentro del
  sandbox existente, conservando solo compuertas de entrega, sandbox y redacción.

## Posiciones

**Arquitecto (auditor principal, fijada antes de leer a las demás voces).**
Elegir B. Las causas dominantes son defectos deterministas ya verificados en
código; seguir corriendo reproduce el mismo fallo; el andamiaje de compuertas y
sandbox está ganado. Riesgo: que B se convierta en otra ronda de parches sin
métrica.

**Escéptico.** Ninguna opción tal como está planteada. Antes, un experimento de
dos días que las distinga: un modelo de pago fiable, código congelado y dos
sistemas bajo las mismas compuertas deterministas, ASET sin sus tres defectos
bloqueantes y un agente de código sin cabeza como control. Además, que una
persona lea los diffs finales de las 26 corridas: si alguno era aceptable, el
problema son las compuertas y no la generación.

**Pragmático.** B, pero solo su parte de borrado (llamadas eco, diagnósticos a
Developer, compuertas léxica y de razón), con un control de modelo de pago de
unos 20 USD y una campaña corta con criterio de éxito fijado de antemano (por
ejemplo, al menos 2 aprobaciones en 8 corridas sobre Flask). Límite de tres días.
Posponer checkpoint y paneles de costo hasta que algo se apruebe.

**Crítico.** B reducido a la mitad y, antes, dos cosas: enviar código solo a una
lista aprobada de proveedores de pago con tope de gasto, y corregir el scorer para
que sus resultados sean atribuibles. C es prematuro. Un conjunto de reproducción
solo contiene fallos: puede probar que el enrutado cambió, no que Developer ahora
escriba código que pase.

## Veredicto

- **Consenso.** Las cuatro voces rechazan A: sin commit registrado por corrida y
  con cambios en mitad de corridas, el ciclo no distingue mejora de ruido. Las
  cuatro consideran C prematuro. Las tres voces externas coinciden en que **la
  disponibilidad de proveedores es la primera causa de parada (13 de 26) y ni B ni
  C la resuelven**; C la empeora, porque un agente en bucle hace más llamadas.
- **Disidencia más fuerte.** El escéptico: decidir entre B y C solo después de un
  experimento con control (agente de código estándar bajo las mismas compuertas).
  Si el control aprueba y ASET no, hay que aceptar ese resultado en lugar de
  parchear alrededor.
- **Revisión de la premisa.** El escéptico y el crítico señalan que **la señal de
  aceptación nunca fue confiable**: las 3 aprobaciones del 09-03 tienen todos los
  subpuntajes en 100 (posible sello automático) y hoy la compuerta léxica rechaza
  suites verdes. Sin una aceptación calibrada, cualquier opción se juzga con una
  métrica rota.
- **Cambio en la recomendación del arquitecto.** Sí. La posición inicial ponía la
  lista de proveedores y el costo al final de B; tres voces independientes lo
  pusieron primero y aportaron dos piezas ausentes: calibrar Reviewer contra
  parches malos conocidos y comparar el arnés del 09-03 con el actual (posible
  regresión).

## Recomendación sintetizada

1. **Ahora:** no correr sobre repositorios privados con las cadenas actuales.
   Restringir cada rol a proveedores aprobados, preferentemente de pago, con tope
   de gasto por corrida.
2. **Medición atribuible:** el scorer registra commit, especificación, cadena de
   modelos y hora; sin aprobados vacíos en infraestructura y entrega; código
   congelado durante una campaña.
3. **Borrados mínimos** (un día): quitar las llamadas eco de Architecture y
   Security; diagnósticos de tests siempre a Developer; compuerta léxica y razón de
   cobertura de Architecture como consultivas; huella por clase de fallo.
4. **Calibrar la aceptación:** Reviewer contra parches malos conocidos; lectura
   humana de los diffs finales de las 26 corridas; comparación del arnés del 09-03
   con el actual.
5. **Experimento discriminante** con criterio fijado antes de correr: ASET
   recortado frente a un agente de código de control, mismas compuertas, mismo
   modelo y mismo commit congelado.
6. **Decidir** el resto de B o el paso a C según ese resultado.

El detalle ejecutable de esta secuencia está en el
[plan de remediación](12-plan-de-remediacion.md).
