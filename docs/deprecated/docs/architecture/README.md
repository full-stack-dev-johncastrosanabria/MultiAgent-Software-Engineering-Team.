# Architecture

Four documents, each answering a different question. A fact belongs to exactly
one of them; when two disagree, the one whose question it answers is right.

| | Question | Changes when |
|---|---|---|
| [overview.md](overview.md) | What the system **is** today | The code changes |
| [roadmap.md](roadmap.md) | Where it is **going** | A capability lands, or the destination moves |
| [decisions/](decisions/) | **Why** it is this way | Never — a decision is superseded by a new one, not edited |
| [checklists/](checklists/) | What must be **true** to call something done | We learn a way it can be done badly |
| [findings/](findings/) | What is **wrong** with it | An audit finds something, or a fix lands |

This directory is tracked in git on purpose. `PROJECT_STATE.md`, `AGENTS.md`
and `CLAUDE.md` are working state and are not: anything recorded only there is
lost when a session rotates it out.
