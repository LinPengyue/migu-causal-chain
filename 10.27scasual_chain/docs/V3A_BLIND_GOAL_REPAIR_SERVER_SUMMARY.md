# Blind goal-repair challenge — server results (NOT success)

- code: `147b8aec03211e4a8be69782d82d6f430764fe54`
- paid HTTP: 0

| case | status | DETECTED | EDL_REPAIRED | failure stage |
|---|---|---|---|---|
| A controlled | `NOT_REPAIRED` | False | False | CRITIC_NO_EXPLICIT_GOAL_OMISSION → PLANNER_UNRESOLVED → EDL_UNCHANGED |
| B historical | `NOT_REPAIRED` | False | False | CRITIC_NO_EXPLICIT_GOAL_OMISSION → PLANNER_UNRESOLVED → EDL_UNCHANGED (raw-only upstream hole preserved) |
| C clean | `NO_UNNECESSARY_EDL_EDIT` | False | False | n/a (control) |

Key finding: Agent did **not** detect missing equalizer goal-action; diagnosed generic source-time jumps instead. No mutating revision. Control C avoided unnecessary EDL edits.

