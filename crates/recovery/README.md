# recovery

Low-level recoverable browser failures: stale nodes, detached frames,
intercepted actions, navigation races. Bounded mechanical retries only.

## May

- Classify transport/CDP errors into `FailureKind`.
- Decide `Retry | ReacquireAndRetry | Escalate` with explicit attempt bounds
  (`MAX_MECHANICAL_RETRIES = 3`).

## May NOT

- Change task strategy or replan — escalation goes to the Python agent
  runtime (`python/src/browser_agent/recovery`).
- Retry without a bound.
