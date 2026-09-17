> Papel de trabajo de la auditoría del 2026-09-16 (docs/audit160926), conservado tal como lo entregó su auditor, salvo rutas locales sustituidas por `~` y `<scratchpad>`. No es documentación vigente: las conclusiones adjudicadas están en las páginas de la auditoría y en el registro de hallazgos.

# A7 — Security, policy & data egress (ecc:security-reviewer) — with lead adjudication

Lead verification at 92742b7: provider endpoints `llm/cloud.py:32-45` (groq, openrouter, xkiro, vyce, tokenforge, nvidia, kilo, cohere, cloudflare) VERIFIED; `_require_loopback` exists only in `project_api.py:35,91,112`, not in `run_api.py` VERIFIED; `mcp/container.py:303-314` bridge network when `allow_network` VERIFIED. Other line refs accepted as reported (not all re-read).

## Findings
1. HIGH (0.85) — No per-provider trust tier for cloud data egress. `_ROLE_CHAINS` (`llm/cloud.py:67-158`) mixes first-party vendors with small third-party gateways (xkiro.com, vyceai.com, tokenforge.ai.studio, kilo.ai, Cloudflare Workers AI, NVIDIA free, OpenRouter free) as equal fallbacks for every role. Only a global `cloud_enabled` (`config.py:25`); no allowlist, private-repo flag, or ADR. Redacted repository fragments, authored code and scanner findings go to whichever provider is next. Fix: `provider_trust_tier` in Settings, unvetted gateways behind explicit opt-in, per-provider data policy documented next to `_OPENAI_COMPATIBLE`.
2. HIGH (0.7) — Dependency installs with network egress. `mcp/quality.py:975-1047,1152,1242` run pip/npm/Maven installs with `allow_network=True` → Docker `bridge` (`mcp/container.py:303-314`); postinstall/build scripts of target-repo dependencies run with internet access and the repo mounted. Mitigated by cap-drop ALL, no-new-privileges, non-root, digest-pinned images, resource limits, no host socket. Fix: registry-only egress proxy/allowlist; `--ignore-scripts` where compatible; audit before install.
3. MEDIUM (0.75) — Redaction is pattern/allowlist-bounded. `guardrails/secrets.py:140-142` key-name alternation + fixed vendor shapes (ghp_/github_pat_, sk-ant-, gateway sk-/tf_/nvapi-/JWT, AKIA/ASIA, URL userinfo) + path exclusion (`repository_evidence.py:41-61,197-211`). Misses e.g. `STRIPE_KEY=sk_live_…`, Slack `xoxb-…` under non-matching names. Commits 41463de, 78b487e (2026-09-16) closed bypasses found on four repos → coverage bounded by observed corpus. Fail-closed is correct: `llm/cloud.py:489-505` aborts the chain on unredactable content. Fix: entropy pass near key-like identifiers; adversarial fuzz corpus.
4. MEDIUM (0.6) — `run_api.py:279-360` (`/api/runs`, `/apply`, `/restore`) has no auth/loopback guard, unlike `project_api.py`. Safe only while bound to 127.0.0.1 (`docs/operations.md:49`). Fix: same guard or bearer token.
5. LOW (0.5) — rootless dind with `seccomp=unconfined`, `systempaths=unconfined`, `/dev/net/tun` (`mcp/run_daemon.py:78-90`); not privileged, internal network, no host socket (ADR 14 mitigation of ADR 10 risk).
6. LOW (0.5) — `delivery.py:26-29,213-247` `_check_no_secret` only matches key=value; doesn't reuse shape detectors from `guardrails/secrets.py` for PR title/body/files.

## Not found / lower than expected
No host docker.sock mount; path traversal contained (`workspace/contract.py:47-52,109-113`); `reset_project` CLI-only; Langfuse export: no AKIA/ghp_/sk-/xox/PEM matches; `password=` hits are placeholders or `[REDACTED]`; `pk-lf-…` is a public key.

## Rule enforcement table
| Rule | Enforced in code? (where) | Prompt-only? |
|---|---|---|
| Role read/write file allowlist | Yes — `mcp/repository.py` `_READ_ROLES`/`_WRITE_ROLES` | No |
| Path traversal / symlink containment | Yes — `workspace/contract.py:47-52,109-113` | No |
| Credential-file read exclusion | Yes — `repository_evidence.py:41-61,197-211` | No |
| Secret redaction before cloud calls | Yes, partial — `guardrails/secrets.py`, `llm/cloud.py:364-386` | No |
| Fail-closed on unredactable content | Yes — `llm/cloud.py:489-505` | No |
| Container network isolation (default none) | Yes — `mcp/container.py:303-314` | No |
| Digest-pinned images | Yes — `mcp/container.py:87-91` | No |
| No host Docker socket | Yes — ADR 10/14, `mcp/run_daemon.py` | No |
| Delivery requires explicit confirmation | Yes — `delivery.py:113-116,313-316` | No |
| Only `aset/*` branches | Yes — `delivery.py:191-200` | No |
| PR only after Reviewer APPROVED | Yes — `apply_run.py:691-696`, deterministic reviewer gate | No |
| No secrets in PR | Yes, narrow — `delivery.py:213-247` | No |
| "Never invent files/evidence/authorization" | Cross-checked by reviewer evidence gate | Prompt `prompts/developer/system.md:3`, not solely relied on |
| run_api access control | No | Neither — deployment convention only |
| Provider trust tier / private-repo opt-in | No | Neither |
