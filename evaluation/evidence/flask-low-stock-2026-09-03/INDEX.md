# Flask low-stock apply evidence (2026-09-03)

Archive of ASET debugger apply runs (failed + successful). Kept for future remediations.

| file | run_id | final | iters | review | score | delivery |
|---|---|---|---|---|---|---|
| `apply-debugger-flask-writes-v2.json` | `apply-474c7045-738d-4cae-9d32-c8f67e056c90` | HUMAN_REVIEW_REQUIRED | 4 | REJECTED | 40.0 | — |
| `apply-debugger-flask-writes-v3.json` | `apply-30fc75c0-c245-4d76-8235-c99bda5413cf` | HUMAN_REVIEW_REQUIRED | 5 | REJECTED | 45.0 | — |
| `apply-debugger-flask-writes-v4.json` | `apply-5d1c2020-a7cd-4349-8675-b7c2507acf0e` | APPROVED | 0 | APPROVED | 100.0 | — |
| `apply-debugger-flask-writes-v5.json` | `apply-399a301c-fe29-459d-b565-8a37f108b2a2` | HUMAN_REVIEW_REQUIRED | 3 | REJECTED | 45.0 | — |
| `apply-debugger-flask-writes-v6.json` | `apply-569d0793-ac09-424e-894d-6d9c8455d00b` | HUMAN_REVIEW_REQUIRED | 5 | REJECTED | 45.0 | — |
| `apply-debugger-flask-writes-v7.json` | `apply-54541042-b076-447f-9a4f-b952b77097e2` | APPROVED | 3 | APPROVED | 100.0 | https://github.com/full-stack-dev-johncastrosanabria/FlaskApiProduct/pull/2 |
| `apply-debugger-flask-writes.json` | `apply-59c97440-7984-4311-a8a5-8c798e50dcd8` | HUMAN_REVIEW_REQUIRED | 4 | REJECTED | 45.0 | — |

## Lessons
- v1 HITL: invented Product.get_low_stock; wrong restock formula
- v2 HITL: trailing whitespace only (tests mostly green)
- v3 HITL: create without cost; bad count assert
- v4 false APPROVED: wrote products.py at repo root
- v5 HITL: coverage dimension security missing
- v6 HITL: assert count 1==2 (bad seed counts)
- v7 APPROVED + delivery PR https://github.com/full-stack-dev-johncastrosanabria/FlaskApiProduct/pull/2
