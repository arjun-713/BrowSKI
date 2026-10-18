# docs

Read the root [architecture plan](../ARCHITECTURE_PLAN.md),
[code quality standard](../CODE_QUALITY.md), and [working rules](../AGENTS.md)
before major implementation work. The plan in this repository is authoritative.

- [`architecture/`](architecture/) — system design: overview, language
  boundaries, agent loop, [decision routing](architecture/decision-routing.md),
  observation model, verification & recovery, privacy & vision, and the
  [controlled browser-code boundary](architecture/browser-code.md).
- [`benchmarks/`](benchmarks/) — evaluation plan and tracked metrics.
- [`development/`](development/) — roadmap with measurable gates, failure taxonomy.
- [`decisions/`](decisions/) — Architecture Decision Records (ADRs).
- [`protocols/`](protocols/) — versioning and compatibility rules.
- [`security/`](security/) — threat model and security boundaries.
- [`research/`](research/) — competitor and ecosystem notes.
- [`user/`](user/) — installation, extension, configuration, privacy, and
  troubleshooting guidance, including current product limits.

For product review, start with the [local demo](user/demo.md), the
[productization validation record](development/productization-validation.md)
and the [release checklist](development/release-checklist.md).

The [initial live smoke diagnosis](development/live-agent-smoke-2026-10-09.md)
records failures observed with real Luna responses. The
[repair and re-evaluation report](development/live-agent-repair-2026-10-12.md)
records subsequent fixes, successful controlled tasks, failed intermediate
runs, and the remaining public-site reliability limits.

The [frozen mixed-task evaluation](development/task-mix-evaluation-2026-10-14.md)
reports development and held-out outcomes separately, including long-task and
confirmation failures. The [prompt caching note](architecture/prompt-caching.md)
records the cache boundary, usage semantics and a controlled live cache probe.

The [final V8 long-task evaluation](development/long-task-diagnostics-2026-10-15.md)
records the frozen development rerun, independently authored holdout and blind
packet review. V8 passed 16/18 development checks and 0/6 holdout checks; the
development score did not generalize.

For the installed-extension failures, start with the
[incident record](debugging/extension-step-zero-incident.md) and
[extension validation ledger](debugging/extension-e2e-validation-report.md).
They distinguish the repaired transport/context failures, real packaged
extension and live Luna smoke results, measured latency, and remaining
attached-browser and test-gate limitations.
