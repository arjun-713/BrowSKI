# ADR-009: On-demand vision fallback

Date: 2026-10-06 · Status: accepted

## Context

Semantic DOM, accessibility, and layout observation are BROWSKI's primary
browser representation. Some tasks depend on information that those sources do
not expose, such as chart content, canvas output, icon appearance, or color.
Screenshots may also contain sensitive visible page content.

## Decision

- Keep screenshots out of the default observation and action loop.
- Invoke vision only when an explicit visual task cue is present and semantic
  observation does not contain the needed information.
- Capture one bounded visible-viewport PNG for that tab and snapshot
  generation. Do not retain it by default or include its bytes in agent state.
- Send task, semantic observation, viewport geometry, and at most 64
  viewport-bounded semantic targets through GPT-6 Luna's structured vision
  adapter. Tab identity and snapshot generation stay local.
- Treat the screenshot and returned visual summary as untrusted page evidence.
  Carry it in a distinct `visual_observation` field. It cannot create actions,
  selectors, or coordinates.
- Use the visual result only as advisory evidence. Luna must still select a
  runtime-generated semantic action, and Rust verifies its result.
- Keep vision disabled by default. Until screenshot redaction is implemented,
  block remote vision requests in `privacy_first` and `offline` modes.
- If visual interpretation is required but unavailable or abstains, ask the
  user rather than continuing with a guess.

## Consequences

Managed-browser tasks can opt into a multimodal fallback without changing the
semantic-first architecture. Tasks that require visual evidence stop for user
guidance when the feature is disabled, privacy policy blocks it, the capture
fails, or Luna abstains. Attached-browser screenshot routing and screenshot
redaction remain incomplete.

## Validation

Fake-provider tests cover explicit visual routing, no screenshot capture for
ordinary semantic tasks, semantic-ref bounds, transient screenshot handling,
privacy-mode blocking, and instruction-like page/visual text. No live provider
request is required for these contract tests.
