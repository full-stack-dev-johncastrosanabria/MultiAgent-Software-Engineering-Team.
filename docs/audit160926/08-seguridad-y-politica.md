# Seguridad, política y salida de datos

Auditoría del 2026-09-16 sobre `gh-run-testing` @ `92742b7`. Fuente de
trabajo: auditor A7 ([papel de trabajo](anexos/A7-security.md)). Solo lectura;
no se mostraron valores secretos. Referencias relativas a
`src/engineering_team/`.

Marco aplicado: «el modelo propone, la política autoriza» (Harness Engineering
§4 y §9) y la guía de Anthropic sobre sandbox y guardarraíles.

Verificado por el auditor principal: endpoints de proveedores
(`llm/cloud.py:32-45`), ausencia de guardia de loopback en `run_api.py` (solo
existe en `project_api.py:35,91,112`) y red `bridge` cuando una orden pide red
(`mcp/container.py:303-314`). El resto de referencias se acepta tal como se
reportó.

## Hallazgos

| ID | Severidad | Hallazgo | Escenario | Arreglo | Confianza |
|---|---|---|---|---|---|
| A-06 | Alta | **Sin nivel de confianza por proveedor para la salida de código.** `_ROLE_CHAINS` (`llm/cloud.py:67-158`) mezcla proveedores de primera parte con pasarelas pequeñas o gratuitas (xkiro, vyce, tokenforge, kilo, Cloudflare Workers AI, NVIDIA y OpenRouter gratuitos) como fallbacks equivalentes para todos los roles. Solo existe `cloud_enabled` global (`config.py:25`); no hay lista permitida, bandera de repositorio privado ni decisión registrada | Un repositorio privado se clona y sus fragmentos (tras redacción), el código escrito y los hallazgos de escáneres llegan al siguiente proveedor disponible, cuya política de retención y entrenamiento no está documentada | `cloud_allowed_providers` obligatorio por proyecto y comprobado en `CloudRouter.enabled_for`; pasarelas no revisadas detrás de un opt-in explícito; política de datos documentada por proveedor | 0.85 |
| A-07 | Alta | **Instalación de dependencias con salida a internet.** `mcp/quality.py:975-1047,1152,1242` instala con pip, npm o Maven con `allow_network=True`, que se traduce a la red `bridge` de Docker | Un paquete comprometido o con typosquatting del repositorio objetivo ejecuta scripts de instalación con red y el repositorio montado. Mitigado por `--cap-drop ALL`, `no-new-privileges`, usuario no root, imágenes fijadas por digest, límites de recursos y ausencia del socket del host | Proxy o lista de salida limitada a registros; `--ignore-scripts` donde sea compatible; auditoría antes de instalar | 0.7 |
| M-10 | Media | **La redacción depende de patrones.** `guardrails/secrets.py:140-142` combina nombres de clave (`api_key`, `access_token`, `token`, `password`, `secret`), formas fijas de proveedor (`ghp_`, `github_pat_`, `sk-ant-`, `sk-`/`tf_`/`nvapi-`/JWT, `AKIA`/`ASIA`, userinfo en URL) y exclusión de rutas (`repository_evidence.py:41-61,197-211`). Los commits `41463de` y `78b487e` del 2026-09-16 cerraron omisiones halladas en cuatro repositorios | Un `STRIPE_KEY=sk_live_…` o un `xoxb-…` bajo un nombre que no coincide pasaría sin redactar. El rechazo es correcto y falla cerrado: `llm/cloud.py:489-505` aborta toda la cadena ante contenido no redactable | Pasada por entropía junto a identificadores con forma de clave; corpus adversarial de pruebas | 0.75 |
| M-11 | Media | **La Run API no tiene autenticación ni guardia de loopback.** `run_api.py:279-360` (`/api/runs`, `/apply`, `/restore`) no replica el `_require_loopback` de `project_api.py` | Seguro mientras uvicorn escuche en `127.0.0.1` ([operaciones](../operations.md)); si se enlaza a `0.0.0.0` en un contenedor de desarrollo, cualquiera que alcance el puerto enumera corridas y dispara apply o restore | Misma guardia o token portador | 0.6 |
| B-07 | Baja | El daemon Docker-in-Docker rootless usa `seccomp=unconfined`, `systempaths=unconfined` y `/dev/net/tun` (`mcp/run_daemon.py:78-90`) | Aumento acotado de superficie de kernel para código de tests escrito por el modelo. No es `--privileged`, usa red interna y no toca el socket del host ([decisión 14](../architecture/decisions/0014-a-docker-api-that-is-not-the-hosts.md)) | Ninguno urgente | 0.5 |
| B-08 | Baja | `_check_no_secret` (`delivery.py:26-29,213-247`) solo reconoce `clave=valor` y no reutiliza los detectores por forma de `guardrails/secrets.py` antes de publicar título, cuerpo o archivos de un PR | Última línea más débil que la redacción previa | Llamar a los detectores de forma | 0.5 |

## Lo que no se encontró o resultó menor de lo esperado

- Ningún montaje del socket Docker del host; la decisión 10 lo rechaza y la 14 lo
  reemplaza por un daemon aislado.
- Traversal de rutas contenido (`workspace/contract.py:47-52,109-113`).
- `reset_project` es solo CLI; no es alcanzable por HTTP.
- El export de Langfuse no contiene coincidencias `AKIA`, `ghp_`, `sk-`, `xox` ni
  bloques PEM; los 39–43 casos con forma `password=` son marcadores de posición o
  `[REDACTED]`. El valor `pk-lf-…` presente en cada observación es la clave
  **pública** de Langfuse, no un secreto.

## Reglas: código frente a prompt

| Regla | ¿Aplicada en código? | ¿Solo prompt? |
|---|---|---|
| Lista de roles para leer y escribir archivos | Sí — `mcp/repository.py` `_READ_ROLES`/`_WRITE_ROLES` | No |
| Contención de traversal y enlaces simbólicos | Sí — `workspace/contract.py:47-52,109-113` | No |
| Exclusión de archivos de credenciales | Sí — `repository_evidence.py:41-61,197-211` | No |
| Redacción antes de la nube | Sí, cobertura parcial — `guardrails/secrets.py`, `llm/cloud.py:364-386` | No |
| Falla cerrada ante contenido no redactable | Sí — `llm/cloud.py:489-505` | No |
| Aislamiento de red de contenedores (`none` por defecto) | Sí — `mcp/container.py:303-314` | No |
| Imágenes fijadas por digest | Sí — `mcp/container.py:87-91` | No |
| Sin socket Docker del host | Sí — decisiones 10 y 14, `mcp/run_daemon.py` | No |
| La entrega exige confirmación explícita | Sí — `delivery.py:113-116,313-316` | No |
| Solo ramas `aset/*` | Sí — `delivery.py:191-200` | No |
| PR solo tras Reviewer APPROVED | Sí — `apply_run.py:691-696` y compuerta determinista | No |
| Sin secretos en el PR | Sí, patrón estrecho — `delivery.py:213-247` | No |
| «Nunca inventar archivos, evidencia o autorización» | Contrastada por la compuerta de evidencia de Reviewer | Prompt (`prompts/developer/system.md:3`), sin depender solo de él |
| Control de acceso de la Run API | **No** | Ninguno: convención de despliegue |
| Nivel de confianza por proveedor u opt-in para repos privados | **No** | Ninguno |
