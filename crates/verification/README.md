# verification

Action-specific postconditions, before/after comparison, verification
evidence. Core principle: a tool call completing without exception does NOT
mean the intended action succeeded.

## May

- Compare `expected` vs `observed`, emit `SUCCESS | FAILURE | UNCERTAIN`
  with evidence and state deltas.

## May NOT

- Execute actions or replan tasks (execution → `executor`/`browser-core`,
  replanning → Python agent runtime).
