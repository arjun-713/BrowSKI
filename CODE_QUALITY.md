# CODE_QUALITY.md

# Code Quality Standard

This file defines the minimum code-quality standard for all changes made in this repository.

Every coding agent must follow these rules unless a repository-specific formatter or style guide explicitly overrides them.

The objective is simple:

> Code must be easy for another engineer to read, review, debug, extend, and delete.

Code that merely works is not sufficient.

---

## 1. Non-Negotiable Readability Rule

Never write production source code in compressed, minified, or "one feature per giant line" form.

Bad:

```ts
if(user){setUser(user);navigate("/home");track("login");toast.success("Done");}
```

Good:

```ts
if (user) {
  setUser(user);
  navigate("/home");
  track("login");
  toast.success("Done");
}
```

Bad:

```tsx
return <div className="card"><h2>{title}</h2><p>{description}</p><button onClick={onClick}>Open</button></div>;
```

Good:

```tsx
return (
  <div className="card">
    <h2>{title}</h2>
    <p>{description}</p>

    <button onClick={onClick}>
      Open
    </button>
  </div>
);
```

Bad:

```css
.card{display:flex;align-items:center;justify-content:space-between;padding:16px;border:1px solid var(--border);border-radius:12px;background:var(--surface);}
```

Good:

```css
.card {
  display: flex;
  align-items: center;
  justify-content: space-between;

  padding: 16px;

  border: 1px solid var(--border);
  border-radius: 12px;

  background: var(--surface);
}
```

If a formatter produces compact output, configure or replace the formatter rather than accepting unreadable source.

Do not commit minified source files unless they are generated artifacts and clearly excluded from normal editing.

---

# 2. Formatting

Always run the repository formatter before finishing.

Preferred tools:

```text
TypeScript / JavaScript / JSX / TSX
→ Prettier

Python
→ Ruff format

Rust
→ rustfmt

Go
→ gofmt

JSON / YAML / Markdown
→ Prettier or repository formatter
```

If the repository already defines another formatter, follow the repository.

Recommended maximum line length:

```text
80–100 characters preferred
120 characters maximum unless unavoidable
```

Long expressions should be split semantically.

Bad:

```ts
const result = await fetchAndTransformUserProfile(profileId, includePrivateFields, includeMetadata, organizationId, requestContext);
```

Good:

```ts
const result = await fetchAndTransformUserProfile(
  profileId,
  includePrivateFields,
  includeMetadata,
  organizationId,
  requestContext,
);
```

Do not manually fight the formatter.

---

# 3. One Logical Operation Per Line

Do not combine unrelated operations simply to reduce line count.

Bad:

```ts
const user = await loadUser(id); setUser(user); setLoading(false);
```

Good:

```ts
const user = await loadUser(id);

setUser(user);
setLoading(false);
```

Line count is not a quality metric.

Readable code is preferred over artificially short files.

---

# 4. Prefer Clear Blocks Over Dense Expressions

Avoid deeply nested ternaries, giant inline callbacks, and chained logic that requires rereading.

Bad:

```ts
const label = loading ? "Loading" : error ? error.message : user ? user.name : "Unknown";
```

Better:

```ts
let label = "Unknown";

if (loading) {
  label = "Loading";
} else if (error) {
  label = error.message;
} else if (user) {
  label = user.name;
}
```

Use compact expressions only when they remain immediately readable.

---

# 5. Functions Must Have One Clear Responsibility

A function should do one meaningful job.

Avoid functions that:

```text
fetch data
parse data
mutate state
render UI
log analytics
handle retries
show notifications
persist storage
```

all at once.

Split responsibilities when doing so makes the behavior easier to understand or test.

Bad:

```ts
async function handleSubmit() {
  // validate
  // mutate input
  // call API
  // retry
  // transform response
  // update five stores
  // navigate
  // show toast
  // log analytics
}
```

Prefer:

```ts
async function handleSubmit() {
  const input = validateForm(formState);
  const response = await submitApplication(input);

  updateApplicationState(response);
  showSuccessFeedback();
}
```

Do not over-fragment trivial logic into dozens of one-line helpers.

The goal is understandable boundaries, not maximum abstraction.

---

# 6. File Size and Responsibility

Files should represent a coherent unit.

Guideline:

```text
< 300 lines  → usually healthy
300–500      → review whether responsibilities should be split
> 500        → requires justification
> 800        → almost always split
```

These are guidelines, not blind limits.

A 550-line parser can be better than six fragmented parser files.

A 900-line React component is almost never acceptable.

---

# 7. Frontend Component Quality

React/Svelte/Vue components must remain readable.

Separate:

```text
presentation
state
data fetching
domain logic
browser APIs
formatting helpers
```

when complexity grows.

Avoid:

```tsx
function Dashboard() {
  // 400 lines of state
  // fetch calls
  // websocket setup
  // transforms
  // handlers
  // giant JSX tree
}
```

Prefer:

```text
Dashboard.tsx
components/
  MetricsPanel.tsx
  RunTable.tsx
  TraceTimeline.tsx

hooks/
  useRuns.ts
  useTraceStream.ts

lib/
  formatMetrics.ts
```

Do not create components solely to reduce line count.

Create them when they represent a meaningful reusable or understandable UI unit.

---

# 8. JSX / TSX Formatting

Never place a large component tree on one line.

Bad:

```tsx
<section><header><h1>{title}</h1><Button onClick={run}>Run</Button></header><Results data={results}/></section>
```

Good:

```tsx
<section>
  <header>
    <h1>{title}</h1>

    <Button onClick={run}>
      Run
    </Button>
  </header>

  <Results data={results} />
</section>
```

For components with several props:

```tsx
<TraceRow
  action={step.action}
  duration={step.duration}
  result={step.result}
  verification={step.verification}
/>
```

not:

```tsx
<TraceRow action={step.action} duration={step.duration} result={step.result} verification={step.verification} />
```

---

# 9. CSS Quality

CSS must be formatted and grouped logically.

Recommended property grouping:

```text
layout
positioning
dimensions
spacing
typography
appearance
effects
animation
```

Example:

```css
.agent-card {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;

  width: 100%;
  min-height: 96px;

  padding: 20px;
  gap: 16px;

  font-size: 14px;

  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);

  box-shadow: var(--shadow-sm);
}
```

Avoid:

- giant inline `style={{ ... }}` objects for normal styling
- repeated magic colors
- repeated pixel values with no design token
- deeply specific selectors
- `!important` unless required and documented
- one-line CSS blocks
- copying the same declaration into many files

Use variables/tokens for shared design values.

---

# 10. HTML Quality

HTML must preserve semantic structure.

Prefer:

```html
<nav>
<main>
<section>
<article>
<header>
<footer>
<button>
<form>
<label>
```

over meaningless nested `<div>` elements where semantic elements exist.

Accessibility is part of code quality.

Interactive elements must support:

```text
keyboard use
focus state
accessible names
proper roles
labels
disabled state
```

Do not replace native controls with custom div-based controls without a real reason.

---

# 11. TypeScript Quality

Use TypeScript as a type system, not JavaScript with annotations.

Avoid:

```ts
any
as any
unknown as Something
// @ts-ignore
```

unless absolutely required at an external boundary.

If unavoidable, contain it in the smallest possible adapter.

Prefer:

```ts
type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed";
```

over:

```ts
status: string;
```

Prefer explicit domain types.

Bad:

```ts
function execute(action: any): any
```

Good:

```ts
function execute(
  action: BrowserAction,
): Promise<ActionResult>
```

Do not create huge generic utility types that make code harder to understand than the underlying data.

---

# 12. TypeScript Imports

Keep imports organized.

Preferred order:

```text
external libraries

internal absolute imports

relative imports

types
```

Remove unused imports.

Do not create circular dependencies.

Avoid importing from deeply nested implementation files across module boundaries.

Prefer public module exports.

---

# 13. Python Quality

Python must be typed for non-trivial production code.

Prefer:

```python
async def execute(
    action: BrowserAction,
) -> ActionOutcome:
    ...
```

over:

```python
async def execute(action):
    ...
```

Use:

```text
dataclasses
Pydantic models
Enums
Protocols
TypedDict
```

where they make contracts clearer.

Avoid enormous dictionaries with undocumented string keys.

Do not hide important control flow in clever comprehensions.

Bad:

```python
results = [await run(x) for x in xs if x.active and await valid(x)]
```

Prefer explicit logic when async/control flow becomes non-trivial.

---

# 14. Rust Quality

Follow idiomatic Rust.

Use:

```text
strong newtypes
enums
Result
thiserror
ownership boundaries
small public APIs
```

Do not use `unwrap()` or `expect()` in production paths unless the invariant is truly impossible to violate and documented.

Prefer:

```rust
let tab = tabs
    .get(&tab_id)
    .ok_or(BrowserError::TabNotFound(tab_id))?;
```

over:

```rust
let tab = tabs.get(&tab_id).unwrap();
```

Do not hold async locks across network calls or `.await` unless explicitly required.

Never perform hidden blocking work on Tokio executor threads.

---

# 15. Naming

Names should explain intent.

Bad:

```text
x
tmp
obj
data2
thing
stuff
doIt
handleThing
processData
```

Good:

```text
active_tab
pending_commands
verification_result
semantic_snapshot
resolve_element
build_action_candidates
```

Short names are acceptable for established local concepts:

```text
i
x
id
url
ctx
```

Do not shorten domain concepts just to type less.

---

# 16. Comments

Comments should explain:

```text
WHY
invariants
workarounds
non-obvious constraints
external protocol behavior
tradeoffs
```

Do not explain obvious syntax.

Bad:

```ts
// Increment count
count += 1;
```

Good:

```ts
// Keep this counter monotonic because trace IDs are used to
// correlate events emitted by separate runtime tasks.
stepId += 1;
```

If the code requires a paragraph explaining what it does, first check whether the code can be simplified.

---

# 17. No Dead or Placeholder Code

Do not commit:

```text
unused helpers
commented-out old implementations
fake interfaces
TODO implementations that silently succeed
unused dependencies
placeholder abstractions "for later"
```

A TODO is acceptable only when:

- the current behavior is correct,
- the deferred work is explicit,
- and the TODO identifies the missing capability clearly.

---

# 18. Error Handling

Do not swallow errors.

Bad:

```ts
try {
  await run();
} catch {
  // ignore
}
```

Errors should be:

```text
handled
translated
retried with a bounded policy
reported
or propagated
```

Use domain-specific errors where useful.

Messages must contain enough context to debug the failure.

Bad:

```text
"failed"
```

Good:

```text
"Failed to resolve element @submit in snapshot generation 42"
```

Never leak secrets into error messages.

---

# 19. Avoid Magic Values

Bad:

```ts
await sleep(1375);
if (score > 0.73) { ... }
```

Prefer:

```ts
const NAVIGATION_SETTLE_TIMEOUT_MS = 1_500;
const MIN_DECISION_CONFIDENCE = 0.73;
```

If a threshold is empirical, document where it came from.

---

# 20. Avoid Premature Abstraction

Do not create:

```text
BaseAbstractGenericManagerFactory
UniversalServiceProvider
GenericProcessor<TInput, TOutput, TContext>
```

for a feature used once.

Prefer concrete code until a repeated pattern is proven.

A little duplication is often better than the wrong abstraction.

---

# 21. Dependency Discipline

Before adding a dependency, ask:

1. Can the standard library already do this cleanly?
2. Is the dependency actively maintained?
3. What transitive dependencies does it add?
4. Is the capability important enough to justify it?
5. Does the repository already contain a solution?

Do not add libraries for trivial helpers.

---

# 22. Public Interfaces Must Stay Small

Expose the minimum API required by other modules.

Prefer:

```text
observe()
resolve()
execute()
verify()
```

over exposing internal state structures and helpers.

Implementation details should stay private.

Cross-language APIs require especially careful discipline.

---

# 23. Separate Domain Logic from Framework Logic

Business/domain behavior should not be inseparable from:

```text
React
FastAPI
LangGraph
OpenAI SDK
TypeSafe SDK
database client
CDP library
```

Wrap external systems behind small adapters.

Example:

```text
DecisionProvider
├── LayaProvider
└── JevProvider
```

The rest of the code should depend on `DecisionProvider`, not vendor SDK internals.

---

# 24. Tests Are Part of Code Quality

Every meaningful behavior change should have an appropriate test.

Use:

```text
unit tests
integration tests
contract tests
regression tests
E2E tests
```

according to the boundary being changed.

Bug fixes should normally include a regression test reproducing the bug.

Do not weaken assertions merely to make a test pass.

Do not mock the behavior you are actually trying to verify.

---

# 25. Test Readability

Tests should clearly show:

```text
Arrange
Act
Assert
```

Example:

```python
async def test_stale_reference_is_rejected() -> None:
    session = await create_session()
    reference = await session.find("@submit")

    await mutate_page(session)

    result = await session.execute(
        Click(target=reference),
    )

    assert result.failure.kind == FailureKind.STALE_TARGET
```

A test should make the contract obvious to a reader.

---

# 26. Generated Code

Generated files must be clearly marked and isolated.

Do not manually edit generated code unless the generation workflow requires it.

Do not apply normal readability requirements to machine-generated protocol bindings if they are not intended for human maintenance.

Human-authored wrappers around generated code must still meet this guide.

---

# 27. Logging

Use structured logging for production systems.

Bad:

```python
print("here")
print("something failed")
```

Good:

```python
logger.warning(
    "element_resolution_failed",
    element_ref=element_ref,
    generation=generation,
)
```

Do not leave debug prints in committed code.

Do not log:

```text
passwords
API keys
tokens
cookies
private form values
secret environment variables
```

---

# 28. Async and Concurrency

Concurrency must be explicit and bounded.

Avoid:

```text
unbounded task spawning
unbounded queues
silent background tasks
locks held over I/O
fire-and-forget work with no shutdown behavior
```

Every long-lived task should have:

```text
ownership
shutdown path
error path
observability
```

---

# 29. Performance Code Still Must Be Readable

Do not sacrifice readability for theoretical micro-optimizations.

If an optimization genuinely requires less readable code:

1. benchmark it,
2. isolate it,
3. comment the reason,
4. keep a clear API around it.

No "performance optimization" is accepted without measurement.

---

# 30. Security Quality

Never commit:

```text
API keys
tokens
passwords
cookies
private certificates
secret URLs
credentials
```

Use environment variables or the repository's secret-management mechanism.

Validate untrusted input at boundaries.

Escape/render user content safely.

Avoid arbitrary shell execution and dynamic code execution unless explicitly required and sandboxed.

---

# 31. Frontend Visual Quality

For UI work, functionality and visual quality both matter.

Avoid:

```text
random spacing
inconsistent radii
unrelated colors
duplicate controls
misaligned grids
giant empty areas
unstructured visual hierarchy
```

Reuse design tokens and established component patterns.

Before finishing a page:

```text
check desktop layout
check narrow viewport
check overflow
check long text
check empty state
check loading state
check error state
check keyboard focus
```

---

# 32. Do Not Rewrite Healthy Code Without Reason

When implementing a feature:

- inspect the existing architecture,
- preserve working boundaries,
- make the smallest coherent change.

Do not rewrite entire modules because another style is personally preferred.

Refactors should solve a concrete problem.

---

# 33. Diff Quality

A good change should produce a reviewable diff.

Avoid mixing:

```text
feature implementation
mass formatting
unrelated renames
dependency upgrades
folder restructuring
```

into one change unless they are required together.

Keep diffs focused.

---

# 34. Agent-Specific Instruction

Coding agents must behave like maintainers, not code generators.

Before editing:

1. read repository instructions,
2. inspect nearby code,
3. identify existing patterns,
4. understand ownership boundaries,
5. plan the smallest coherent change.

While editing:

1. preserve formatting,
2. use readable multiline code,
3. avoid giant files,
4. do not duplicate logic,
5. do not bypass established interfaces,
6. add/update tests.

After editing:

1. run formatter,
2. run lint,
3. run type checker,
4. run relevant tests,
5. inspect the diff manually,
6. inspect changed files for readability,
7. remove temporary/debug code.

---

# 35. Mandatory Self-Review

Before declaring work complete, inspect every changed source file and ask:

```text
Would another engineer understand this in one pass?

Did I compress code unnecessarily?

Are any JSX/HTML/CSS blocks written as giant single lines?

Are functions doing too many unrelated things?

Are names specific enough?

Did I create duplicate logic?

Did I introduce an unnecessary abstraction?

Are errors useful?

Are edge cases tested?

Did I leave debug code?

Did I follow the existing architecture?

Did I run the formatter/linter/type checker/tests?
```

If any answer is unsatisfactory, fix it before reporting completion.

---

# 36. Required Quality Gates

Unless the repository defines stricter commands, run the relevant gates.

## TypeScript / frontend

```bash
prettier --check .
eslint .
tsc --noEmit
```

or the repository-equivalent commands.

## Python

```bash
ruff format --check .
ruff check .
pyright
pytest
```

## Rust

```bash
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```

## Go

```bash
gofmt
go vet ./...
go test ./...
```

Never report "all green" without actually running the checks.

If a check cannot run, report exactly why.

---

# 37. Definition of Done

A code change is done only when:

- behavior is implemented,
- code is formatted,
- code is readable,
- relevant types are explicit,
- errors are handled,
- tests exist where appropriate,
- existing tests pass,
- lint passes,
- type checking passes,
- dead/debug code is removed,
- architecture boundaries are preserved,
- the diff has been manually reviewed.

---

# 38. Final Principle

Prefer:

```text
boring
explicit
typed
formatted
testable
small
predictable
```

over:

```text
clever
compressed
magical
dense
over-abstracted
hard to review
```

The repository should look like it was written for humans who will maintain it for years, not generated for a one-time demo.
