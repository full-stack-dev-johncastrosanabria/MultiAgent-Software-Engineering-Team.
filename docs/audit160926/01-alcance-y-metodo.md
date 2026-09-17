# Alcance y método

## Alcance

| Dimensión | Valor |
|---|---|
| Sistema | ASET, equipo autónomo de ingeniería de software (`src/engineering_team/`, unas 18 400 líneas de Python) |
| Base | Rama `gh-run-testing` @ `92742b7` |
| Entradas | CLI `run-project` sobre repositorios reales, Run API y frontend |
| Pila de modelos | Cadenas por rol sobre Groq, Mistral, OpenRouter, xKiro, Vyce, TokenForge, NVIDIA, Kilo, Cohere, Cloudflare Workers AI y Google; fallback local Ollama |
| Síntoma | Ningún cambio aceptado en la campaña contra GitHub; toda corrida termina en revisión humana |
| Ventana | Corridas del 2026-09-12 al 16; traza de Langfuse del 2026-09-16 16:49Z al 2026-09-17 00:11Z |
| Fuera de alcance | Interfaz React (no se ejecutó `npm`), corridas nuevas contra proveedores o GitHub, cambios de código del producto |

## Marcos de referencia

1. **Anthropic, [«Building effective agents»](https://www.anthropic.com/engineering/building-effective-agents)**
   (diciembre de 2024): workflows frente a agentes, patrones de composición,
   tres principios (simplicidad, transparencia, interfaz agente-computador) y
   condiciones para agentes de código.
2. **LunarResearcher, [«Harness Engineering: The Complete Guide to Building AI Agents That Don't Fall Apart»](https://x.com/LunarResearcher/status/2096570562625655088)**
   (artículo en X, 2026-09-06): 19 secciones sobre el arnés que convierte
   inteligencia del modelo en trabajo confiable, niveles de arnés mínimo viable
   L1–L6 y métricas de trabajo aceptado. El texto se obtuvo mediante la API
   pública de fxtwitter, porque X exige sesión.
3. **Método «agent-architecture-audit»**: doce capas donde un envoltorio puede
   corromper al modelo, modelo de severidad y orden de arreglo con código antes
   que prompt.
4. **Métodos de gobernanza documental** «living-docs-governance» y «update-docs».
5. **Método «council»** para la decisión de qué hacer después, y
   **«agent-self-evaluation»** para evaluar este mismo entregable.

## Base de evidencia

| Fuente | Uso |
|---|---|
| Código en `92742b7` | Lectura directa con referencias `ruta:línea` |
| Export de Langfuse (2839 observaciones, 17 trazas) | Análisis por script; solo agregados en los documentos |
| `evaluation/benchmarks/ghcycle/results/` (26 puntuados) y `results/raw/` (27 crudos) | Resultados por etapa, causas de fallo y de parada |
| Todo `evaluation/` | Inventario de evidencia y contraste con el estado |
| Suite de tests | Ejecución completa en entorno aislado el 2026-09-17 |
| Historial de Git desde el 2026-09-10 | Intercalado de commits y corridas; tratamiento de fallos |
| Documentación activa y `PROJECT_STATE.md` | Deriva frente a código y roles documentales |

## Organización del trabajo

| Auditor | Tipo de agente | Alcance | Papel de trabajo |
|---|---|---|---|
| A1 | general | Patrones de Anthropic, flujo de control e interfaz de herramientas y prompts | [A1](anexos/A1-anthropic-patterns.md) |
| A2 | general | Las 19 secciones de Harness Engineering y madurez L1–L6 | [A2](anexos/A2-harness-engineering.md) |
| A3 | general | Doce capas y bucles ocultos | [A3](anexos/A3-12-layer.md) |
| A4 | general | Evidencia, corridas, trazas y métricas | [A4](anexos/A4-evidence-metrics.md) |
| A5 | general | Ejecución de la suite y calidad de tests | [A5](anexos/A5-tests.md) |
| A6 | general | Gobernanza documental y deriva | [A6](anexos/A6-docs-drift.md) |
| A7 | revisor de seguridad | Política, sandbox y salida de datos | [A7](anexos/A7-security.md) |
| A8 | cazador de fallos silenciosos | Errores tragados y retrocesos con forma de éxito | [A8](anexos/A8-silent-failures.md) |
| Consejo | tres voces independientes | Escéptico, pragmático y crítico sobre la decisión siguiente | [Consejo](10-consejo.md) |

Todos los auditores recibieron el mismo [brief](anexos/00-brief-de-auditores.md):
solo lectura sobre el repositorio, sin secretos, evidencia con `ruta:línea` o
comando, confianza de 0 a 1, lectura de reportes crudos antes de concluir y
cautela ante fallos conocidos del bind mount de Docker.

## Protocolo de verificación

1. El auditor principal analizó de forma independiente el export de Langfuse y
   la cadena causal del bucle de remediación **antes** de recibir los informes.
2. Cada hallazgo crítico y la mayoría de los altos se verificaron leyendo el
   código o recalculando la cifra. Los niveles de verificación están en el
   [registro](11-registro-de-hallazgos.md).
3. Las cifras en conflicto entre auditores se reconciliaron explícitamente (por
   ejemplo, 41/44 frente a 44/44 escaneos).
4. Se ajustaron severidades cuando la verificación no sostenía la original
   (barrido Docker de crítica a alta; suite omitida de alta a media) y se
   corrigieron inferencias propias que resultaron falsas.
5. Los hallazgos repetidos entre secciones se fusionaron con un único
   identificador.
6. Cada corrección documental se verificó contra el código antes de escribirla.

## Limitaciones

- **Sin daemon Docker durante la ejecución de tests.** Los 26 tests que lo
  requieren fallaron y no quedaron validados; tampoco se pudo inventariar recursos
  Docker sobrantes.
- **No se lanzaron corridas nuevas.** Los tres últimos commits (`4ff4ae2`,
  `31defca`, `92742b7`) no tienen evidencia de ejecución y sus efectos se juzgan
  solo por código.
- **Nadie leyó como humano los diffs finales** de las 26 corridas; la calidad del
  código producido no está calificada.
- **Independencia limitada.** Todos los auditores son instancias del mismo modelo;
  el consejo mitiga el anclaje con contexto mínimo, pero no sustituye una revisión
  humana.
- **Interrupción.** Cinco auditores se detuvieron por el límite de sesión y se
  reanudaron con su contexto; A2 había completado su informe antes de detenerse.
- **Texto inicial incompleto del artículo de LunarResearcher.** El brief común
  se redactó con el texto del artículo sin sus 25 bloques de código y diagramas
  (clases de riesgo, tabla de clase de fallo y acción, campos del recibo,
  especificación del arnés, fórmula de la métrica). Se recuperaron al cierre y se
  contrastaron en [Harness Engineering](04-harness-engineering.md); no cambiaron
  ningún veredicto, pero precisaron A-06 y la métrica del §18. Las 12 imágenes
  del artículo no se recuperaron.
- **Export de Langfuse incompleto** para flask-k (faltan 33 observaciones de
  herramienta y el span de revisión humana).
- **Frontend no auditado.**
