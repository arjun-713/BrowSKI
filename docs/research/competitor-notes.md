# Competitor / ecosystem notes

Deeper research is pending (scaffold phase). No findings below are claimed
as verified — each entry lists what to investigate and where. Do not
fabricate benchmark comparisons; see `../benchmarks/evaluation-plan.md`.

## Browser Use (Python, open-source)

- What to study: agent loop structure, DOM-serialization approach, action
  history handling, benchmark numbers (WebArena-family, BU Bench).
- Links: https://github.com/browser-use/browser-use · docs at
  https://docs.browser-use.com
- Relevance: closest product analogue; primary benchmark rival.

## BrowserCode

- What to study: positioning vs Browser Use/Stagehand, API/SDK design,
  provider support, self-hosting story.
- Status: details to be filled in during Milestone 0 research — do not cite
  specifics until verified.

## Stagehand (Browserbase)

- What to study: `act/observe/extract` API design, caching (`cacheActions`),
  evals, Zod-schema structured extraction, Playwright/CDP layering.
- Links: https://github.com/browserbase/stagehand
- Relevance: best-in-class developer API to learn from (not copy internals).

## BrowserGym / AgentLab

- What to study: `browsergym` OpenAI-Gym-style harness, AgentLab experiment
  workflows; candidate primary external eval harness (Milestone 9).
- Links: https://github.com/ServiceNow/BrowserGym ·
  https://github.com/ServiceNow/AgentLab

## WebArena family (WebArena, VisualWebArena, WorkArena, AssistantBench)

- What to study: task sets, hosting requirements, scoring; candidates for
  Milestone 9 integration after BrowserGym.
- Note: Mind2Web-style grounding data useful for observation-model design
  (Milestone 2) where licensing permits.

## Research log

| Date | Area | Finding | Source |
|---|---|---|---|
| 2026-09-10 | Rust CDP libs | chromiumoxide 0.9.x leading; headless_chrome 1.0.x alternate; playwright-cdp 0.3 immature | crates.io (`cargo info`) |
| 2026-09-10 | PyO3 | 0.26 line supports current Python (3.12–3.14); workspace uses it | crates.io, local build |
| 2026-09-10 | M1 transport verdict | Custom transport kept: measured parity with chromiumoxide 0.9.1, +0 vs +28 transitive crates, no duplicate WS/HTTP stacks | local spike (`--features transport-chromiumoxide`), see ADR-002 |
