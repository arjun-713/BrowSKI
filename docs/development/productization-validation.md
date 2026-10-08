# Productization validation record

This record covers the local BROWSKI 0.1.0 productization candidate. It is a
software and packaging acceptance record, not a model-performance benchmark.
GPT-6 Luna remains the active decision provider; Laya is shadow-only and Jev
is disabled. No OpenAI or Jev API calls, Laya tuning, large task-success
benchmarks, publication or cloud deployment were performed in this pass.

## Environment

Validation used Linux x86_64, Rust 1.98.1, Python 3.12.13 in the project venv,
uv 0.11.32, Node 22.23.1 and npm 10.9.8. Extension acceptance used Playwright
1.63 with its Chromium 153.0.8010.12 build. The installed system browser was
also available for managed-browser tests. Other operating systems and browser
versions have not been validated by this record.

## Quality gates

| Gate | Local result |
| --- | --- |
| Rust formatting and Clippy, all targets with warnings denied | Passed |
| Rust workspace tests | 129 passed; one manual latency test intentionally ignored |
| Python Ruff formatting/check and strict Pyright | Passed; zero type errors |
| Python tests excluding opt-in extension E2E | 329 passed, three live-provider tests skipped |
| TypeScript formatting, lint and typecheck | Passed |
| Extension unit/component tests | 49 passed |
| Production extension build | Passed |
| npm dependency audit | Zero vulnerabilities reported |
| Real packaged-extension E2E | 13 passed in 158.45 seconds after the startup/lifecycle fixes |
| Release-tooling unit tests and shell syntax checks | Passed; three unit tests |

The skipped Python tests require explicit live Laya, Jev or OpenAI opt-in.
They are not counted as validated model behavior. GitHub CI definitions were
updated; remote CI results have not been observed. Local Markdown validation
checked 101 relative paths with none missing; `git diff --check` passed before
committing the candidate. There is no separate repository-wide Markdown linter
configured.

## Real-browser acceptance boundary

The E2E suite loads the production Manifest V3 extension into a real Chromium
profile, installs the Native Messaging host in that temporary profile, starts
the authenticated local runtime, and uses the shared Rust engine and actual
LangGraph workflow. Only the reasoning provider and credential store are
deterministic test fixtures. Webpage interactions and verification are real.

Covered flows include:

- Native side-panel context creation, explicit tab attachment and detachment.
- Verified form typing and a bounded transient viewport PNG.
- Settings round trips, private configuration permissions and synthetic-key
  exclusion from webpage state, extension storage and visible traces.
- Owned-tab create/activate/close, refusal to adopt another tab and refusal to
  close the original user tab.
- A multi-step local form, supporting tab, source-bound text transfer into
  working memory, return to the form and completion before submission.
- Pause/resume, stop during a provider decision, tab loss and host disconnect.
- Explicit approval, denial and denial while paused for a consequential action.
- Narrow panel layout without overflow at 320 and 440 pixels.

The full demo completes eight verified browser actions. Its deterministic
provider reads the transferred value from runtime memory rather than a private
answer cache. This demonstrates product plumbing; it does not demonstrate that
Luna will choose the same actions. Side-panel creation uses a browser-reported
user gesture in the harness, not an automated physical toolbar click.
See [the demo instructions](../user/demo.md) for reproduction.

## Release artifacts

Local release preparation built the locked Rust workspace in release mode,
the mixed Python/PyO3 CPython 3.12 Linux x86_64 wheel and the production Chrome
extension. Artifacts are staged under the ignored `dist/release-0.1.0/`
directory with a manifest, deterministic extension ZIP, dependency metadata
and SHA256 checksums. Nothing was published.

The wheel was installed with its runtime dependencies into a separate temporary
venv without system-site packages, and its Python package and native binding
imported successfully. Dependency resolution for that installation was not
lockfile-based; the release build itself used locked project tooling. Its contents exclude tests,
bytecode caches, databases and secret-looking paths. The dependency inventory
contains 220 Rust, 112 Python and 410 npm entries with no missing declarations;
reciprocal/copyleft declarations remain recorded for human review. This is
metadata inspection, not legal certification. See the
[release checklist](release-checklist.md) and
[license review](../security/dependency-license-review.md).

## Doctor and installation

The Linux installer preflight and local build were exercised. Native host
registration remains an explicit user step bound to the installed extension
ID; the harness registers only temporary browser profiles.

The actual `browski serve` CLI was also started with explicit temporary
`--socket-path` and `--database` paths. Its Unix socket had owner-only 0600
permissions; SIGINT produced a clean zero exit and removed the socket. That
smoke test did not attach a browser or invoke a provider.

The current `browski doctor` reports Python, Rust binding, Chromium, persistence
and the built extension as available. It warns that no OpenAI key is configured,
the local service is not currently running, the host is not registered in the
default user profile and Laya is unavailable. These are real environment
findings, not passing runtime-connectivity or live-provider results.

## Security review and limitations

An internal source-and-test threat review fixed consequential-action label
classification gaps, sensitive browser-code result labels and a stale-result
capability bypass. Regression tests also cover page prompt injection, strict
finite action binding, bridge validation, isolated code limits, encrypted
checkpoint writes, missing-key failure and source-bound cross-tab evidence.

A concurrent acceptance run exposed an extension startup-restoration race:
late restoration could overwrite a newly consented tab attachment. Explicit
tab operations now wait for bounded startup restoration. Failed restoration
reports an error and refuses attachment; backend cleanup clears ownership
even when its Rust connection has already reset. Stop was also corrected to
persist and emit its terminal result before detaching owned debuggers while
leaving the user's Chrome tabs open. These are software regressions, not
model-performance findings.

The [threat model](../security/threat-model.md) records residual risks:

- Privacy and consequential-action classification are heuristic and incomplete.
- Standard-mode screenshots may contain sensitive content. Vision is disabled
  by default and blocked in privacy-first/offline modes pending sanitation.
- Local keyring storage protects API keys; an environment override is supported.
  Checkpoint encryption can use a private local key file. A compromised process
  running as the same user remains a threat.
- Retention is logical deletion, not guaranteed secure erasure of SQLite pages
  or backups. Screenshots are not retained by the runtime by default.
- Browser ownership is bounded and explicit. Cross-origin ownership changes
  fail closed; arbitrary existing tabs/popups and all OOPIF arrangements are
  not supported automatically.
- Observation before execution reduces stale decisions but cannot eliminate
  a user/page mutation in the final dispatch race.
- The browser-code tool transforms bounded semantic data in isolated QuickJS.
  Live page code, shell, filesystem and network capabilities remain unavailable.

This was not an independent penetration test or security certification.
Fresh observation and encryption add work; no product performance regression
benchmark was run. Earlier M0–M7 measurements remain historical evidence rather
than current latency guarantees.

## Readiness

| Area | Assessment |
| --- | --- |
| Product implementation | Implemented within the documented Linux/Chrome and capability limits; local review candidate |
| Software tests | Local quality gates and actual-browser fixture acceptance passed |
| Security | Internal review and regressions completed; residual risks and independent review remain |
| Agent reliability | Pending live Luna acceptance and subsequent task-success evaluation |
| Benchmark readiness | Existing harnesses retained; large-scale model evaluation and tuning deferred |

Review this candidate before further feature or benchmark work. Build and
fixture success alone do not establish production readiness.
