> Papel de trabajo de la auditoría del 2026-09-16 (docs/audit160926), conservado tal como lo entregó su auditor, salvo rutas locales sustituidas por `~` y `<scratchpad>`. No es documentación vigente: las conclusiones adjudicadas están en las páginas de la auditoría y en el registro de hallazgos.

# A3 — 12-layer agent-architecture audit (ECC method), ASET @ 92742b7

Auditor A3. Read-only. Evidence: source (`path:line`), the Langfuse export
(`~/Downloads/1789609787428-lf-events-export-…json`, 2839 observations, 17 traces,
2026-09-16 16:49Z → 2026-09-17 00:11Z), analysed with Python; only aggregates and
short excerpts are quoted. No secrets printed (the export's metadata carries a
Langfuse *public* key; not reproduced).

**Code-version caveat.** The export predates commit 4ff4ae2 (model-health ledger,
18:15 local = 00:15Z; export ends 00:11Z) and spans several same-day chain edits.
Runtime claims about the ledger are therefore code-only. Chain order in the older
traces differs from today's `_ROLE_CHAINS`.

**Not redone (confirmed by lead/others, only referenced):** L1 echo validator
(`runtime.py:293-302`), remediation detail only to `return_to`
(`context.py:149-209`), unreachable Architecture evidence sufficiency, volatile
fingerprints (`routers.py`), docker sweep swallowing, silent ledger I/O errors.

---

## 1. Severity-ranked findings

No finding is rated critical: I found no path where the system confidently ships
wrong code without a gate. The main failure is that wrapper layers **end runs**
and **misdirect remediation**. They do not approve bad changes.

### H1 — Hidden model-chain loop ends runs at stages whose LLM output cannot change the artifact (L11)
- **Mechanism.** `invoke_candidate` sends every role except Testing and Reviewer
  through the primary runtime. The cloud primary walks a chain of up to 10–11
  models. If the whole chain fails, it tries the local secondary. If that also
  fails, a stage retry runs everything again. If that fails, the run goes to
  HUMAN_REVIEW_REQUIRED (`graph/stategraph.py:599-685`). Architecture and
  Security models must return the deterministic candidate unchanged
  (`llm/runtime.py:293-297`, `:336-374`; user prompt says "Copy every candidate
  key and value exactly", `llm/prompting.py:361`).
- **Runtime evidence.**
  - Accepted outputs that differ from the candidate: 0/39 for Architecture and
    0/42 for Security. The only Security difference is a trace-redaction
    artifact (see M3).
  - 10/17 traces ended because a whole chain was used up. 4 of those were echo
    stages: Architecture in `6f8b73c6b1` and `93970a62e2`, Security in
    `15dcd59512` and `ed7dbfd1e6`. In `93970a62e2`, Nemotron spent 129 s
    producing an Architecture "governed contradiction".
  - 290/478 generations failed (61%). Failed generations took 58.9 min against
    41.2 min for successful ones. Architecture plus Security took 53.1 min of
    generation time.
- **Root cause.** The graph treats "has a system prompt" as "needs a model". The
  governance layer turned those calls into exact-copy tests, but the transport
  and retry machinery still treats a failed copy as a stage failure.
- **Fix (code).** Treat Architecture, Security and PROPOSED Developer like
  Testing and Reviewer: no model call. Otherwise make the call advisory: if it
  fails, keep the candidate and record a degradation, without HITL.
- **Confidence.** 0.9.

### H2 — A stage failure keeps only the last model's transport error, reclassifies quality failures as availability, and replays the same chain (L11/L8)
- **Mechanism.**
  - The cloud runtime recurses through the chain and raises only the final
    model's error (`llm/cloud.py:622-628`, `:679-693`).
  - The graph maps any message not prefixed `LLM_QUALITY_ERROR` to
    `LLM_AVAILABILITY_ERROR`, which is retryable (`graph/stategraph.py:614-632`).
  - The stage retry then re-sends identical prompts at temperature 0
    (`:660-667`).
  - HTTP 400/413 are never cooled down: only 401/402/403/429/503 are
    (`llm/cloud.py:585-602`). Groq therefore gets the same oversized Developer
    payload again: `request_rejected` 18/21.
  - When every model is cooling down, the message is "disabled, missing
    credential, or budget", which misstates the cause (`llm/cloud.py:473-474`).
  - The public `review.reason` falls back to `errors[-1]`, the last transport
    string (`run_events.py:390`).
- **Runtime evidence.**
  - Of 26 stage-level `LLM_AVAILABILITY_ERROR` spans, 12 hid quality failures
    earlier in the chain (governed_contradiction, ineffective_remediation,
    incomplete_output, schema).
  - Of 16 `model stage retry` spans, 10 failed again. Examples: `5980c6dbfa`
    and `1fb8c0d488`, where the same 429/400/503 sequence repeats seconds later.
- **Root cause.** The error is an untyped string, and the retry rule does not
  check whether anything changed.
- **Fix.** Return a typed `ChainFailure(attempts=[…categories…])`. Classify the
  stage from the set of attempt categories. Retry only if some attempt failed
  for availability and its cooldown has passed. Cool down 400/413 per
  (provider, model, prompt-size bucket). Surface the dominant category.
- **Confidence.** 0.9.

### H3 — Baseline CVE text reaches the Developer as "failed assertion" diagnostics, with its baseline label cut off (L4 distillation)
- **Mechanism.**
  1. Security builds a *baseline* finding: "Residual baseline dependency risk
     … do not route to Developer". Its description embeds the last 2000 chars
     of scanner output (`agents/security.py:101-127`). Upstream, that output
     was already reduced to the last 4000 chars plus "Confirmed dependency
     advisories", `mcp/quality.py:713`, `:740`.
  2. The Reviewer puts `baseline_visible_problems` *first* in `problems` on the
     failed-tests path (`agents/reviewer.py:210-220`, `:263-289`).
  3. `build_context` keeps only the last 2000 bytes of each problem
     (`models/context.py:199-201`), which removes the label. The rest lands
     under "FAILED ASSERTIONS AND OTHER REQUIRED DIAGNOSTICS"
     (`:177-184`).
  4. The prompt adds "Resolve every listed regression and new failure"
     (`llm/prompting.py:196-214`), while obligation 4 forbids adding
     dependencies (`context.py:100-103`).
- **Runtime evidence.** The export has 33 Developer remediation prompts, all
  spring-demo. 29/33 contain the CVE list (jackson-databind, spring-core,
  spring-boot-data-jpa …) inside that section. The section starts mid-word
  ("n about the errors and possible solutions…[Help 1]"). 17/33 do not contain
  the compile root cause ("does not exist" / "cannot find symbol") in the
  section at all.
- **Root cause.** Diagnostics are free text concatenated by position. The
  "baseline" type lives only in the prose prefix, and tail truncation cuts it
  off.
- **Fix.** Use a typed remediation envelope, e.g.
  `{regressions, new_failures, compile_errors, baseline_risk}`. Never send
  `baseline_risk` to the Developer. For Maven, extract `[ERROR]` lines around
  `COMPILATION ERROR` / `Tests run:` instead of taking the tail.
- **Confidence.** 0.85.

### H4 — The model-health ledger is a cross-run memory that can poison every later run and never shows its effect (L3/L12)
Code-only; not exercised in the export. No `model-health.json` found under the
repo, `~/Developer` or `/private/tmp`.
- **Key is too coarse.** Entries are keyed `role|provider|model` only
  (`llm/model_health.py:86-87`). There is no project, stack, prompt size or
  time. The module's own motivation — Spring Boot 3 tests written for a Boot 4
  project — is a stack-specific failure that would demote the model for Flask
  too.
- **Misattributed outcomes.**
  - Authoring outcome = whole-suite `SUCCESS`/`FAIL` after the write
    (`graph/stategraph.py:529-547`). It ignores `baseline_tests`, so pre-existing
    failures and failures left by earlier iterations' files count against the
    current author.
  - `request_rejected` (413 payload too large) counts as a model *quality*
    failure (`model_health.py:26-29`).
- **No recovery.** Demoted models go to the end of the chain
  (`model_health.py:58-62`). They are rarely called again, so they rarely get
  new outcomes. There is no decay, only a 20-outcome window (`:101-106`). The
  docstring's "recent good outcomes bring it back" is unlikely in practice.
- **Lost updates.** Each run loads the ledger at start (`apply_run.py:347`) and
  rewrites the whole dict on every append (`model_health.py:127-135`). The Run
  API runs work in threads (`run_api.py:164`), so the last writer wins.
- **Shared file.** The path is relative to the working directory
  (`config.py:93`). Benchmark dry runs, launched from the repo root via
  `run_cycle.py:218-229`, share the ledger with operator runs. Unit tests use
  `tmp_path` and do not pollute it.
- **Invisible.** The reordered chain (`cloud.py:439-440`) is never traced or
  reported.
- **Fix.**
  - Key entries by stack profile.
  - Record authoring only for *new* failures attributable to the author (use
    the baseline and exclude infrastructure/compile-of-foreign-files).
  - Exclude 4xx payload errors.
  - Add time decay plus one exploration slot.
  - Take a file lock and merge on save.
  - Anchor the path the way `_ENV_FILE` is anchored, and give benchmarks a
    separate ledger.
  - Trace the effective chain order.
- **Confidence.** 0.75 on the mechanism; 0.3 on realized harm.

### M1 — The Architecture prompt asks for design judgment that the validator forbids (L1 vs L11)
- **Mechanism.** The system prompt says "Define a bounded technical design". The
  evidence-budget text says "If the omitted evidence could change the design,
  say so rather than designing around the gap" (`llm/prompting.py:334-340`). Yet
  the output must equal the candidate (`runtime.py:293-297`). The candidate's
  `evidence_sufficient`/`evidence_gap` are only filled in *after* the call
  (`stategraph.py:861-865`), so a model that "says so" by setting them is
  rejected.
- **Runtime evidence.** 9/9 Architecture governed-contradiction messages include
  `evidence_gap` or `evidence_sufficient`.
- **Fix.** Removed by H1's fix. Otherwise delete the design-inviting text from
  echo roles.
- **Confidence.** 0.8.

### M2 — Cloud redaction corrupts the source files the Developer must rewrite, and nothing stops a placeholder from being written (L9/L10)
- **Mechanism.**
  - `prompting.py:221-222` says previous attempts are "Deliberately not
    redacted … a redaction placeholder would be written into real source". But
    `cloud.py:496-497` redacts the whole user prompt anyway, including the
    "Untrusted repository files" blocks.
  - `secret_key=[REDACTED]` is valid Python (a list literal), so the AST gate
    passes it (`runtime.py:319-324`).
  - The write loop has no placeholder check (`stategraph.py:826-835`). A grep
    for `REDACTED` outside `guardrails/` and the observability modules finds no
    write-path guard.
- **Runtime evidence.** 18/90 accepted Developer prompts contained
  `[REDACTED]` inside file blocks (e.g. `def SECRET_KEY(self): secret_key=[REDACTED] if not secret_key=[REDACTED]`,
  `password=[REDACTED]`). 0 accepted outputs contained the placeholder.
- **Fix.**
  - Make edit targets that contain a secret non-writable, or refuse them.
  - Reject any `file_contents` containing `[REDACTED]` before the write.
  - Do not send redacted bodies of files the author must rewrite.
- **Confidence.** 0.8.

### M3 — Observability and Run-API redaction by key name hides the Security `authorization` verdict (L10)
- **Mechanism.** `langfuse.py:14-24` and `run_events.py:21-25`, `:71`, `:98`
  replace any value whose *key* is `authorization` with `[REDACTED]`. The
  OWASP checklist item `authorization: PASS|FAIL` is such a key. There are also
  three divergent sensitive-key sets: `secrets.py` has the new provider keys,
  the other two do not.
- **Runtime evidence.** In 42/42 Security generations, `safe_context.checklist.authorization`
  is `[REDACTED]`, while the prompt sent the real value.
- **Fix.** Detect secrets by value, not by field name, for trace and event
  payloads. Use one shared key set applied only to credential containers.
- **Confidence.** 0.85 for Langfuse; 0.7 for the Run API stream.

### M4 — Rejected LLM outputs are never kept, and contradiction messages list diffs instead of the rule broken (L11 observability)
- **Mechanism.**
  - Error paths trace metadata only (`cloud.py:615-621`, `:672-678`). Only
    success records input and output (`:711-721`).
  - `_GovernedContradiction.fields` lists *every* key that differs, including
    keys the model may legitimately change (`cloud.py:180-193`).
- **Runtime evidence.** 264/264 failed cloud generations have no input or
  output. "governed fields differ: findings" (26×) cannot be diagnosed. One
  hypothesis, confidence 0.5: the Security candidate carries a 2130-char raw
  scanner tail in `findings[].description` that must be copied verbatim. The
  OpenRouter Nemotron model had 25 contradictions and 12 `incomplete_output` in
  47 Security calls, with `max_tokens` 4096 and reasoning on
  (`cloud.py:538-541`).
- **Fix.** Persist a redacted, bounded rejected output plus the id of the
  violated rule, returned by `_preserves_governed_facts`.
- **Confidence.** 0.9.

### M5 — A failing JVM suite loses its structured evidence, and failure parsing only understands pytest (L7/L8; upstream cause of F-11)
- **Mechanism.**
  - `run_tests` keeps Surefire test cases only when the run is SUCCESS
    (`mcp/quality.py:1163-1168`).
  - The failure parser reads pytest `FAILED ` lines only
    (`testing_evidence.py:42-56`), so the Reviewer falls back to raw text
    (`reviewer.py:263-289`).
  - What survives is the last 4000 chars of Maven output (`quality.py:713`),
    then the last 2000 bytes per problem (`context.py:199-201`), then the last
    600 chars in the report (`apply_run.py:565-597`).
- **Fix.** On FAIL, keep the parsed Surefire failures (class, method, message,
  first stack frame). Extract Maven `[ERROR]` blocks instead of taking the tail.
- **Confidence.** 0.7.

### M6 — Duplicated and oversized context (L2/L5)
- **Evidence** (accepted prompts in the export):

| Call type | User prompt median | Max | What fills it |
|---|---|---|---|
| Architecture echo | 22.4 KB | — | 66% repository evidence, 6% RAG, for a call that must copy its input |
| Developer planner | 51 KB | 84 KB | 82% file blocks |
| Security echo | 6.2 KB | — | 77% schema + candidate |

- **Mechanism.** Governed values appear four times: system prompt
  (`prompting.py:96-98`), schema `const` (`:41-48`), the candidate, and the
  closing instruction (`:347-349`).
- **Consequence.** Groq HTTP 413/400 rejections on Developer: 18/21 calls.
- **Fix.** Send the governed fields once, as a schema `const`. Drop repository
  evidence from echo roles. Enforce a byte budget per provider before sending.
- **Confidence.** 0.8.

### M7 — The local repair loop is blind and cannot succeed; the local fallback is dead (L11)
- **Mechanism.**
  - Repairs append generic text without the invalid output or the validation
    error (`runtime.py:150-153`, `:211-218`).
  - A governed-contradiction repair *replaces the whole prompt* with "return
    this candidate exactly" (`:178-183`). For APPLIED `ImplementationResult`
    the candidate's `file_contents` is empty (44/44 author candidates in the
    export), so the echo fails the `file_contents` gate (`:314-318`).
  - The Ollama secondary failed 26/26 times in the export
    (`LLM_AVAILABILITY_ERROR: HTTPStatusError`, retry=0). There is no preflight
    check.
- **Fix.** Preflight the secondary runtime or disable it. Include the parse or
  validation error in repair prompts. Never "repair" an authoring call into an
  echo.
- **Confidence.** 0.85.

### M8 — The author (and the planner) is silently swapped mid-remediation (L11)
- **Mechanism.** A byte-identical remediation raises `_IneffectiveRemediation`
  and moves on to the next chain model (`cloud.py:577-581`, `:679-685`). The
  planner and the author are separate walks of the chain. This contradicts the
  intent of revert 31defca ("stop rotating the model chain").
- **Runtime evidence** (trace `1885fc593d`, run `apply-5f7b9e7e…`):
  - Iteration 0: Cohere plans, Codestral authors.
  - Iteration 1: Codestral plans, Codestral's authoring is rejected as
    "unchanged developer remediation", and Cohere authors instead.
  - Iteration 3: Cloudflare gpt-oss plans, Cohere authors.
  - The swaps appear only as rows in `model_usage`.
- **Fix.** Pin one author per remediation. Return the ineffective-remediation
  error to the same model with feedback, or escalate explicitly with a trace
  event.
- **Confidence.** 0.85.

### L1 — Dead and brittle prompt text (L1)
- Testing and Reviewer `system.md` are never sent: those roles are
  deterministic (`stategraph.py:600-603`), yet their prompts describe "Score
  validated artifacts".
- The Developer OUTPUT CONTRACT is swapped by exact string replacement
  (`prompting.py:66-69`). It silently does nothing if `system.md` wording
  changes.
- **Confidence.** 0.9.

### L2 — The shared RAG collection is rebuilt on every run (L12)
- **Mechanism.** `build_retriever(..., reindex=True)` (`apply_run.py:357`,
  `rag/__init__.py:20-27`) deletes and re-adds every chunk in a shared,
  persistent Chroma collection. Concurrent Run API runs can retrieve from an
  empty index, which produces `RAG_ERROR`, and the Reviewer then routes to
  Architecture (`reviewer.py:178-187`).
- **Evidence.** Not observed in the export.
- **Fix.** Reindex only when the knowledge hash changes.
- **Confidence.** 0.5.

### L3 — Cached tool getters carry no staleness marker; the run store fails hard on one bad record (L12)
- `_get_last` returns the previous result with `duration_ms=0` and no stale
  flag (`quality.py:1100-1119`). It is reachable only via the MCP server
  (`mcp/server.py:98`, `:106`, `:122`). The graph never uses it, so reports
  that reuse cached results are not a live-path problem.
- `RunStore._load_existing` raises on a duplicate or invalid record, which
  aborts API startup (`runs/store.py:194-200`).
- **Confidence.** 0.7.

### L4 — The model can freely rewrite `diff` and `validation_result`, and both are reported (L9)
- **Mechanism.** In APPLIED mode these two fields are not governed
  (`runtime.py:298-325`). They surface as `diff_summary` (`apply_run.py:656`)
  and as `FinalReport.implementation` (`stategraph.py:137`).
- **Runtime evidence.** 11 accepted outputs rewrote `diff`. No false validation
  claim was seen.
- **Confidence.** 0.7.

**Not a finding.**
- Accepting one fenced JSON block (`cloud.py:161-177`): exactly one block is
  required, and schema plus governance run afterwards.
- Tool invocation: models have no tool API. `run_tests`, scans and repo reads
  are called by the orchestrator (`stategraph.py:287-559`), and the Reviewer
  requires a real `run_tests` result (`reviewer.py:~311-317`).

---

## 2. Hidden second-pass inventory (L11)

Every place where another LLM call can replace, validate or repair an output:

| # | Where | What it does | Visible? | Contract |
|---|---|---|---|---|
| 1 | `cloud.py:622-628, 679-693` chain recursion | Next model replaces the failed one (up to 10–11 per role), on any HTTP, schema, governance or ineffective-remediation failure | ERROR generation (metadata only) and a `model_usage` row; the stage error keeps only the last one | Implicit; retries after quality failures change the model, not the input |
| 2 | `cloud.py:466-475` cooldown wait | Sleeps until a cooled model is available, within the role deadline | Not traced; failure message says "budget" | Deadline only |
| 3 | `stategraph.py:633-658` secondary runtime | Local Ollama (cloud-first) or cloud (local-first) replaces primary | "cloud fallback error" span | `fallback_reason` recorded; no preflight |
| 4 | `stategraph.py:660-667` model stage retry | Replays #1 and #3 with identical input | WARNING span | Retryable if the string does not start with LLM_QUALITY_ERROR |
| 5 | `runtime.py:123-125` local availability retry | Same request again | `retry` metadata | `max_local_retries` |
| 6 | `runtime.py:150-153, 169-183, 211-218` local repair | Appended repair text or full echo-prompt replacement | `repair` metadata | `max_local_repairs`; blind |
| 7 | `stategraph.py:687-779` Developer target plan | Separate LLM call chooses the write scope; author must match (`:783-796`) | "Developer target plan" span | `validate_target_plan` (strong) |
| 8 | `cloud.py:577-581` / `runtime.py:259-279` ineffective remediation | Byte-identical author output rejected, next model authors | ERROR generation | Byte equality only |
| 9 | `cloud.py:439-440` model-health reorder | Changes which model answers first, across runs | Not visible | Ledger heuristics (H4) |
| 10 | Remediation loop (Reviewer→Developer/Architecture) | Full stage re-execution up to 5 iterations | Route spans | Iteration cap plus fingerprint breaker (lead finding 4) |

---

## 3. Quick diagnostic questions

1. **Can the model skip a required tool and still answer?** No. Models get no
   tool API. Tools are invoked in code (`stategraph.py:287-559`), and the
   Reviewer blocks when there is no real `run_tests` (`reviewer.py:~311-317`).
   Residual gap: the unguarded `validation_result` text (L4).
2. **Does old content appear in new turns?** Yes, within a run and across runs.
   - Within a run: the Developer's rejected files come back with the instruction
     "Repair it; do not start over" (`prompting.py:223-242`).
     `remediation_request` goes to every role in later iterations
     (`context.py:144-148`). Baseline CVE text re-enters as diagnostics (H3).
   - Across runs: only the model-health ledger, which changes ordering, not
     content (H4).
3. **Same information in prompt, memory and history?** Yes. Governed values
   appear four times, and echo roles receive 15+ KB of repository evidence
   (M6).
4. **A second LLM pass before delivery?** Yes: ten mechanisms (§2). The
   chain/fallback/stage-retry combination is the dominant cost: 61% of
   generations failed.
5. **Does output differ between generation and delivery?** Yes.
   - The trace and event streams redact the `authorization` verdict (M3).
   - `review.reason` shows the last transport error instead of the cause (H2).
   - Rejected outputs are never delivered or kept (M4).
   - Prompts are redacted in ways the trace's `safe_context` does not show
     (M2/M3).
6. **Are "must use tool X" rules prompt-only?** Not for tools. Several
   invariants are prompt-only:
   - "mentally execute every new test", "end with one newline"
     (`prompting.py:109-115`);
   - "never add a dependency" (`context.py:100-103`), which is only partly
     enforced by the planner's manifest rules (`developer_plan.py:128-198`);
   - "Do not add prose" for echo roles, which code enforces as an exact match
     with consequence H1.
7. **Can the agent's own output become persistent memory?** Within a run, yes:
   rejected `file_contents` are re-injected, and the model-authored `diff`
   persists into the report. Across runs, only outcome labels are kept, in the
   ledger. No text is stored.

---

## 4. Architecture diagnosis

- **L11 is where runs die.** The transport and retry machinery was built for
  "the model is the author", but for three of the five model-invoking call types
  (Architecture, Security, PROPOSED Developer) governance reduced the model to
  an exact copier. Any provider noise or harmless paraphrase therefore becomes
  a stage failure. The failure is then flattened into a string, relabelled as
  availability (H2) and replayed unchanged. 10/17 runs ended there rather than
  on an engineering verdict.
- **L4 is where remediation goes wrong.** Free-text concatenation with tail
  truncation turns "baseline risk, not yours" into "failed assertion, resolve
  it" (H3). It also drops the Maven root cause (M5), so the Developer loops
  against goals it cannot meet. This adds to the lead's findings on
  `return_to` gating and fingerprint volatility.
- **L1 contradicts L11 in Architecture.** The prompt asks for judgment and the
  validator punishes any (M1).
- **L9/L10 mutate in two directions.** Outbound redaction corrupts the source
  handed to an author (M2). Inbound key-name redaction hides a security verdict
  from operators (M3).
- **L3/L12.** The new ledger adds silent cross-run state without stack scoping,
  attribution or visibility (H4). Other persistence is mostly sound: atomic run
  store, interrupted-run reconciliation, cached getters off the graph path. The
  exceptions are the per-run RAG rebuild (L2) and one bad record aborting the
  store (L3).

---

## 5. Ordered fix plan (code-first)

1. **Remove the model from echo stages** (Architecture, Security, PROPOSED
   Developer), or make the call non-blocking. Removes H1 and M1, most of M6's
   token waste, and 4/17 run terminations of that class.
2. **Type the chain failure** and make retries condition-changing (H2). Retry
   only after an availability failure whose cooldown has elapsed. Cool down
   400/413. Fix the "budget" message. Report the dominant category.
3. **Persist rejected outputs** (redacted, bounded) plus the violated rule id
   (M4). Needed to diagnose anything else in L11.
4. **Typed remediation envelope** (H3, M5): separate baseline risk; keep
   Surefire failures on FAIL; extract Maven errors instead of taking tails.
5. **Model-health ledger hardening** (H4): key by stack; attribute only new
   failures; exclude 4xx payload errors; decay plus exploration; lock and merge;
   anchored path; separate benchmark ledger; trace the effective order. Freeze
   the ledger (empty `MODEL_HEALTH_PATH`) until this is done.
6. **Pin the author per remediation** and make any swap an explicit, traced
   escalation (M8). Preflight or disable the dead local secondary; stop blind
   and echo repairs (M7).
7. **Redaction correctness** (M2, M3): no redacted bodies for write targets;
   reject `[REDACTED]` in `file_contents`; value-based trace redaction; one
   shared key set.
8. **Prompt hygiene** (M6, L1): send governed fields once; drop repository
   evidence from echo roles; delete dead prompts; replace string-replace
   contracts with per-phase files.
9. **Persistence cleanup** (L2, L3, L4): reindex RAG by knowledge hash;
   staleness flag on cached getters; tolerate one bad run record; govern or drop
   model-authored `diff`/`validation_result`.

---

## 6. Report (schema `ecc.agent-architecture-audit.report.v1`)

```json
{
  "schema_version": "ecc.agent-architecture-audit.report.v1",
  "executive_verdict": {
    "overall_health": "high_risk",
    "primary_failure_mode": "Hidden L11 model-chain/fallback/stage-retry loop around stages whose governed output must equal a deterministic candidate; quality failures are flattened into the last transport error, relabelled as availability and replayed unchanged, ending 10/17 traced runs (4 at echo stages) before any engineering verdict, while L4 free-text distillation sends baseline CVE text to the Developer as failed-assertion diagnostics.",
    "most_urgent_fix": "Stop invoking models for Architecture/Security/PROPOSED-Developer (or make them non-blocking) and replace string errors with a typed chain-failure that only retries when an availability condition has changed."
  },
  "scope": {
    "target_name": "ASET (MultiAgent-Software-Engineering-Team) @ 92742b7, branch gh-run-testing; Langfuse export 2026-09-16 16:49Z–2026-09-17 00:11Z (17 traces)",
    "model_stack": ["mistral codestral-latest / mistral-medium-latest / mistral-small-latest", "groq openai/gpt-oss-120b", "cohere command-a-03-2025", "xkiro deepseek-v4-pro / deepseek-v4.1-flash / qwen3-coder-plus", "openrouter + kilo + nvidia nemotron-3-super-120b", "cloudflare @cf models", "vyce agnes-3.0-flash / deepseek-v4-flash", "google gemini-3.5/3.6-flash", "ollama qwen3.5:9b / qwen3.5:4b (secondary)"],
    "layers_to_audit": ["L1 system prompt", "L2 session history", "L3 long-term memory", "L4 distillation", "L5 active recall", "L6 tool selection", "L7 tool execution", "L8 tool interpretation", "L9 answer shaping", "L10 platform rendering/transport", "L11 hidden repair loops", "L12 persistence"]
  },
  "findings": [
    {
      "severity": "high",
      "title": "Model-chain loop terminates runs at echo-only stages",
      "mechanism": "invoke_candidate sends Architecture/Security through a 10-11 model cloud chain, local secondary and stage retry; governance requires the output to equal the deterministic candidate, so any paraphrase or provider error becomes a stage failure and HUMAN_REVIEW_REQUIRED.",
      "source_layer": "L11 hidden repair loops",
      "root_cause": "Graph treats every prompted role as model-authored although governance reduced three call types to exact-copy validation.",
      "evidence_refs": ["src/engineering_team/graph/stategraph.py:599-685", "src/engineering_team/llm/runtime.py:293-297", "src/engineering_team/llm/prompting.py:361", "langfuse: 0/39 Architecture and 0/42 Security accepted outputs differ from candidate", "langfuse traces 6f8b73c6b1, 93970a62e2 (Architecture), 15dcd59512, ed7dbfd1e6 (Security) ended by chain exhaustion", "langfuse: 290/478 generations failed; 58.9 min failed vs 41.2 min ok generation latency"],
      "confidence": 0.9,
      "recommended_fix": "Treat Architecture, Security and PROPOSED Developer like Testing/Reviewer (no model call) or make the call advisory: on failure keep the candidate and record a degradation, never HITL."
    },
    {
      "severity": "high",
      "title": "Stage failure keeps only the last transport error, reclassifies quality failures as availability and replays identical input",
      "mechanism": "Cloud recursion raises only the final model's error; the graph maps any non-LLM_QUALITY_ERROR string to retryable LLM_AVAILABILITY_ERROR; stage retry re-sends the same prompts; 400/413 get no cooldown; cooldown exhaustion is reported as 'disabled, missing credential, or budget'; review.reason falls back to errors[-1].",
      "source_layer": "L11 hidden repair loops / L8 tool interpretation",
      "root_cause": "Untyped string errors and a retry rule that does not require any condition to change.",
      "evidence_refs": ["src/engineering_team/llm/cloud.py:622-628", "src/engineering_team/llm/cloud.py:679-693", "src/engineering_team/llm/cloud.py:473-474", "src/engineering_team/llm/cloud.py:585-602", "src/engineering_team/graph/stategraph.py:614-632", "src/engineering_team/graph/stategraph.py:660-667", "src/engineering_team/run_events.py:390", "langfuse: 12/26 stage-level LLM_AVAILABILITY_ERROR hid earlier quality failures; 10/16 model stage retries failed again; groq Developer request_rejected 18/21"],
      "confidence": 0.9,
      "recommended_fix": "Return a typed ChainFailure with per-attempt categories; classify from the set; retry only when an availability failure's cooldown elapsed; cool down 400/413 per provider/model/prompt-size bucket; correct the budget message; surface the dominant category."
    },
    {
      "severity": "high",
      "title": "Baseline CVE text re-enters Developer remediation as failed-assertion diagnostics with its baseline label truncated away",
      "mechanism": "Security embeds a 2000-char scanner tail in a 'baseline dependencies' finding; Reviewer prepends it to problems; build_context tail-truncates each problem to 2000 bytes (dropping the label) and groups it under FAILED ASSERTIONS AND OTHER REQUIRED DIAGNOSTICS; prompt says resolve every listed failure while forbidding dependency changes.",
      "source_layer": "L4 distillation",
      "root_cause": "Diagnostics are positional free text; the baseline type lives only in a prose prefix removed by tail truncation.",
      "evidence_refs": ["src/engineering_team/agents/security.py:101-127", "src/engineering_team/mcp/quality.py:713", "src/engineering_team/mcp/quality.py:740", "src/engineering_team/agents/reviewer.py:210-220", "src/engineering_team/agents/reviewer.py:263-289", "src/engineering_team/models/context.py:177-206", "src/engineering_team/llm/prompting.py:196-214", "langfuse: 29/33 Developer remediation prompts contain CVE list in diagnostics; 17/33 lack compile root cause there"],
      "confidence": 0.85,
      "recommended_fix": "Typed remediation envelope {regressions,new_failures,compile_errors,baseline_risk}; never send baseline_risk to Developer; extract Maven [ERROR] blocks instead of tails."
    },
    {
      "severity": "high",
      "title": "Model-health ledger is unscoped, misattributed, starving, racy and invisible cross-run memory",
      "mechanism": "Keyed role|provider|model only; authoring outcome is whole-suite status ignoring baseline; 413 counted as quality; demoted models tried last so they rarely get new outcomes, no decay; whole-dict rewrite per append with per-run in-memory copies loses concurrent updates; CWD-relative path shared by benchmark and operator runs; reordered chain not traced.",
      "source_layer": "L3 long-term memory / L12 persistence",
      "root_cause": "Cross-run outcome memory added without scope, attribution, expiry, concurrency control or observability.",
      "evidence_refs": ["src/engineering_team/llm/model_health.py:26-29", "src/engineering_team/llm/model_health.py:58-75", "src/engineering_team/llm/model_health.py:86-87", "src/engineering_team/llm/model_health.py:101-106", "src/engineering_team/llm/model_health.py:127-135", "src/engineering_team/graph/stategraph.py:529-547", "src/engineering_team/apply_run.py:345-355", "src/engineering_team/config.py:93", "src/engineering_team/run_api.py:164", "src/engineering_team/llm/cloud.py:439-440", "evaluation/benchmarks/ghcycle/run_cycle.py:218-229"],
      "confidence": 0.75,
      "recommended_fix": "Key by stack profile; record only author-attributable new failures; exclude 4xx payload errors; time decay plus exploration slot; file lock and merge-on-save; anchored path and separate benchmark ledger; trace effective chain order. Until then set MODEL_HEALTH_PATH empty."
    },
    {
      "severity": "medium",
      "title": "Architecture prompt invites design judgment the exact-equality validator forbids",
      "mechanism": "System prompt 'Define a bounded technical design' and evidence-budget text 'say so' vs actual == candidate; evidence_sufficient/evidence_gap are set after the call, so models that flag gaps are rejected.",
      "source_layer": "L1 system prompt",
      "root_cause": "Prompt text and validator contract evolved separately.",
      "evidence_refs": ["src/engineering_team/prompts/architecture/system.md:2", "src/engineering_team/llm/prompting.py:334-340", "src/engineering_team/llm/runtime.py:293-297", "src/engineering_team/graph/stategraph.py:861-865", "langfuse: 9/9 Architecture governed contradictions include evidence_gap or evidence_sufficient"],
      "confidence": 0.8,
      "recommended_fix": "Remove model call per first finding, or strip design-inviting text from echo roles."
    },
    {
      "severity": "medium",
      "title": "Cloud prompt redaction corrupts source the Developer rewrites; no gate rejects placeholders",
      "mechanism": "Whole user prompt is redacted including repository file blocks despite the 'deliberately not redacted' intent; 'x=[REDACTED]' parses as valid Python so the AST gate passes; write loop has no placeholder check.",
      "source_layer": "L10 transport / L9 answer shaping",
      "root_cause": "String-level redaction applied after prompt assembly without distinguishing author-writable evidence.",
      "evidence_refs": ["src/engineering_team/llm/cloud.py:496-497", "src/engineering_team/llm/prompting.py:221-222", "src/engineering_team/llm/runtime.py:319-324", "src/engineering_team/graph/stategraph.py:826-835", "langfuse: 18/90 accepted Developer prompts contain [REDACTED] inside file blocks (e.g. secret_key=[REDACTED])"],
      "confidence": 0.8,
      "recommended_fix": "Make secret-bearing edit targets non-writable or refused; reject file_contents containing [REDACTED] before write; do not send redacted bodies of write targets."
    },
    {
      "severity": "medium",
      "title": "Key-name redaction hides the Security checklist 'authorization' verdict in traces and run events",
      "mechanism": "Langfuse and run-event sanitizers replace any value under key 'authorization' with [REDACTED], including the OWASP checklist item; three divergent sensitive-key sets.",
      "source_layer": "L10 platform rendering/transport",
      "root_cause": "Field-name-based redaction applied to domain payloads.",
      "evidence_refs": ["src/engineering_team/observability/langfuse.py:14-24", "src/engineering_team/run_events.py:21-25", "src/engineering_team/run_events.py:71", "src/engineering_team/run_events.py:98", "src/engineering_team/guardrails/secrets.py:9-16", "langfuse: 42/42 Security generations show checklist.authorization=[REDACTED] in safe_context while the prompt carried the value"],
      "confidence": 0.85,
      "recommended_fix": "Value-based secret detection for trace/event payloads; single shared key set applied only to credential containers."
    },
    {
      "severity": "medium",
      "title": "Rejected LLM outputs are never recorded and contradiction messages list diffs, not violated rules",
      "mechanism": "Error trace records carry metadata only; _GovernedContradiction.fields lists every differing key including allowed changes.",
      "source_layer": "L11 hidden repair loops (observability)",
      "root_cause": "Only successful generations trace input/output; validator returns bool without rule id.",
      "evidence_refs": ["src/engineering_team/llm/cloud.py:180-193", "src/engineering_team/llm/cloud.py:615-621", "src/engineering_team/llm/cloud.py:672-678", "src/engineering_team/llm/cloud.py:711-721", "langfuse: 264/264 failed cloud generations have no input/output; 26x 'governed fields differ: findings' undiagnosable"],
      "confidence": 0.9,
      "recommended_fix": "Persist redacted, bounded rejected output and a rule id returned by _preserves_governed_facts."
    },
    {
      "severity": "medium",
      "title": "Failing JVM suites drop structured Surefire evidence; failure parser is pytest-only",
      "mechanism": "test_cases are collected only on SUCCESS; FAILED-line parser yields nothing for Maven, so Reviewer falls back to raw text tail-truncated at 4000 then 2000 then 600 chars.",
      "source_layer": "L8 tool interpretation / L4 distillation",
      "root_cause": "Evidence extraction specialized for pytest and success paths.",
      "evidence_refs": ["src/engineering_team/mcp/quality.py:1163-1168", "src/engineering_team/mcp/quality.py:713", "src/engineering_team/testing_evidence.py:42-56", "src/engineering_team/agents/reviewer.py:263-289", "src/engineering_team/models/context.py:199-201", "src/engineering_team/apply_run.py:565-597"],
      "confidence": 0.7,
      "recommended_fix": "Keep parsed Surefire failures on FAIL; extract Maven [ERROR] blocks around COMPILATION ERROR/Tests run."
    },
    {
      "severity": "medium",
      "title": "Context duplication and oversized prompts",
      "mechanism": "Governed values repeated in system prompt, schema const, candidate and closing instruction; echo roles get repository and RAG evidence; Developer planner prompts reach 84 KB.",
      "source_layer": "L2 session history / L5 active recall",
      "root_cause": "Prompt builder appends every available source without a per-call purpose or byte budget per provider.",
      "evidence_refs": ["src/engineering_team/llm/prompting.py:41-48", "src/engineering_team/llm/prompting.py:94-98", "src/engineering_team/llm/prompting.py:249-340", "src/engineering_team/llm/prompting.py:346-361", "langfuse: Architecture echo prompt median 22.4 KB (66% repo evidence); Developer plan median 51 KB, max 84 KB; groq Developer request_rejected 18/21"],
      "confidence": 0.8,
      "recommended_fix": "State governed fields once (schema const); no repository evidence for echo roles; enforce per-provider byte budget before transport."
    },
    {
      "severity": "medium",
      "title": "Local repair loop is blind and self-defeating; local secondary is dead",
      "mechanism": "Repair prompts omit the invalid output and error; contradiction repair replaces the prompt with 'return candidate exactly', which cannot pass the APPLIED file_contents gate because author candidates have empty file_contents; Ollama secondary failed 26/26 with no preflight.",
      "source_layer": "L11 hidden repair loops",
      "root_cause": "Generic repair strategy reused across echo and authoring contracts; no availability preflight.",
      "evidence_refs": ["src/engineering_team/llm/runtime.py:150-153", "src/engineering_team/llm/runtime.py:169-183", "src/engineering_team/llm/runtime.py:211-218", "src/engineering_team/llm/runtime.py:314-318", "langfuse: 44/44 author candidates have empty file_contents; 26/26 ollama generations LLM_AVAILABILITY_ERROR HTTPStatusError"],
      "confidence": 0.85,
      "recommended_fix": "Preflight or disable the secondary; include validation error in repair prompts; never convert an authoring call into an echo repair."
    },
    {
      "severity": "medium",
      "title": "Planner and author silently swapped mid-remediation",
      "mechanism": "Byte-identical remediation raises _IneffectiveRemediation and the chain advances to another model; planner and author are independent chain walks.",
      "source_layer": "L11 hidden repair loops",
      "root_cause": "Quality rejection handled by model rotation, contradicting the intent of revert 31defca.",
      "evidence_refs": ["src/engineering_team/llm/cloud.py:577-581", "src/engineering_team/llm/cloud.py:679-685", "src/engineering_team/llm/runtime.py:259-279", "langfuse trace 1885fc593d (apply-5f7b9e7e): iter0 cohere plan/codestral author; iter1 codestral 'unchanged developer remediation' then cohere authors; iter3 cloudflare plan/cohere author"],
      "confidence": 0.85,
      "recommended_fix": "Pin one author per remediation; return ineffective-remediation feedback to the same model or escalate with an explicit traced event."
    },
    {
      "severity": "low",
      "title": "Dead and brittle prompt text",
      "mechanism": "Testing/Reviewer system.md never sent; Developer contract swapped by exact string replace.",
      "source_layer": "L1 system prompt",
      "root_cause": "Prompts not tied to executed call types.",
      "evidence_refs": ["src/engineering_team/graph/stategraph.py:600-603", "src/engineering_team/prompts/reviewer/system.md:1-6", "src/engineering_team/llm/prompting.py:66-69"],
      "confidence": 0.9,
      "recommended_fix": "Delete unused prompts; use per-phase prompt files instead of string replacement."
    },
    {
      "severity": "low",
      "title": "Shared persistent RAG collection fully replaced every run",
      "mechanism": "reindex=True deletes and re-adds all chunks in a shared Chroma collection; concurrent runs may retrieve from an empty index, producing RAG_ERROR and an Architecture route.",
      "source_layer": "L12 persistence",
      "root_cause": "Index rebuild tied to run start rather than knowledge change.",
      "evidence_refs": ["src/engineering_team/apply_run.py:357", "src/engineering_team/rag/__init__.py:20-27", "src/engineering_team/agents/reviewer.py:178-187"],
      "confidence": 0.5,
      "recommended_fix": "Reindex only when the knowledge hash changes; build into a new collection and swap atomically."
    },
    {
      "severity": "low",
      "title": "Cached tool getters unmarked as stale; run store aborts on one bad record",
      "mechanism": "_get_last returns previous results with duration_ms=0 and no staleness flag (MCP server only); RunStore._load_existing raises on duplicate/invalid records.",
      "source_layer": "L12 persistence",
      "root_cause": "Cache and store lack staleness/tolerance semantics.",
      "evidence_refs": ["src/engineering_team/mcp/quality.py:1100-1119", "src/engineering_team/mcp/server.py:98", "src/engineering_team/runs/store.py:194-200"],
      "confidence": 0.7,
      "recommended_fix": "Add cached/as_of fields to getter results; quarantine unreadable run records instead of failing startup."
    },
    {
      "severity": "low",
      "title": "Model-writable diff and validation_result surface in reports",
      "mechanism": "APPLIED governance does not guard diff/validation_result; report shows diff_summary and FinalReport.implementation from them.",
      "source_layer": "L9 answer shaping",
      "root_cause": "Descriptive fields left outside governed set.",
      "evidence_refs": ["src/engineering_team/llm/runtime.py:298-325", "src/engineering_team/apply_run.py:656", "src/engineering_team/graph/stategraph.py:137", "langfuse: 11 accepted Developer outputs rewrote diff"],
      "confidence": 0.7,
      "recommended_fix": "Derive diff/validation text deterministically from get_diff and tool results, or mark them model-authored in the report."
    }
  ],
  "ordered_fix_plan": [
    {"order": 1, "goal": "Remove model calls from Architecture/Security/PROPOSED Developer or make them non-blocking", "why_now": "Echo stages add no information (0/81 accepted outputs differ) yet end runs and consume about half of generation time", "expected_effect": "Eliminates the echo-stage termination class (4/17 traced runs), M1, and most prompt bloat"},
    {"order": 2, "goal": "Typed chain failure with condition-changing retries and 400/413 cooldown", "why_now": "12/26 stage failures mislabelled as availability; 10/16 retries repeated identical failures", "expected_effect": "Fewer wasted calls, truthful stage errors and report reasons"},
    {"order": 3, "goal": "Persist rejected outputs and violated rule ids", "why_now": "264 failed cloud generations are currently undiagnosable", "expected_effect": "Every governed contradiction becomes attributable to model, prompt or validator"},
    {"order": 4, "goal": "Typed remediation envelope; keep Surefire failures on FAIL; extract Maven errors", "why_now": "29/33 Developer remediation prompts carry baseline CVE text as failing diagnostics; 17/33 lack the compile root cause", "expected_effect": "Developer receives actionable, correctly typed obligations; fewer non-converging iterations"},
    {"order": 5, "goal": "Harden or freeze the model-health ledger", "why_now": "Merged the same day, not yet exercised; will silently reorder all future chains", "expected_effect": "Cross-run memory scoped, attributable, recoverable and visible"},
    {"order": 6, "goal": "Pin author per remediation; preflight/disable dead local secondary; stop blind and echo repairs", "why_now": "Authorship rotates despite revert 31defca; 26/26 local fallbacks failed", "expected_effect": "Stable authorship, fewer hidden passes"},
    {"order": 7, "goal": "Redaction correctness: no redacted write targets, placeholder write gate, value-based trace redaction", "why_now": "18/90 author prompts had redacted source; authorization verdict hidden in 42/42 Security traces", "expected_effect": "No placeholder written to source; operators see security verdicts"},
    {"order": 8, "goal": "Prompt hygiene: single statement of governed fields, per-phase prompt files, delete dead prompts", "why_now": "Prompts up to 84 KB; groq 413s", "expected_effect": "Smaller prompts, fewer provider rejections"},
    {"order": 9, "goal": "Persistence cleanup: RAG reindex by hash, stale flags on cached getters, tolerant run store, governed diff text", "why_now": "Low-probability but silent failure modes under concurrency", "expected_effect": "No cross-run interference from shared indexes or caches"}
  ]
}
```
